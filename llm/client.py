"""OpenAI-compatible LLM client with key rotation, provider
fallback, and honest usage accounting (T15; ADR-0006).

The wire format is the OpenAI chat-completions shape, which every
provider we target speaks; providers differ only in endpoint, key
environment variables, and model naming. ``models_json`` maps our
CANONICAL model names to per-provider aliases so a fallback switch
never changes ``LLMResponse.model_name`` mid-run (the grader warns
on multiple model names per run). ``api_url`` is the provider's
OpenAI-compatible BASE url; the chat endpoint is
``{api_url}/chat/completions``.

``models_json`` schema (this IS the root ``models.json``)::

    {
      "providers": [                        # declared endpoints
        {
          "name": "groq",
          "api_url": "https://api.groq.com/openai/v1",
          "keys_env": ["GROQ_API_KEY", "GROQ_API_KEY_2"]
        }
      ],
      "models": [                           # canonical -> alias per provider
        {
          "canonical": "gpt-oss-120b",
          "providers": {"groq": "openai/gpt-oss-120b"}
        }
      ],
      "limits": {...}                       # pass-through (T18+ reads)
    }

For each canonical model, providers are tried in the order listed in
that model's ``providers`` object: the first is primary, the rest
are fallbacks — a provider's position in the top-level
``providers`` list does not set per-model precedence.

Usage accounting is honest: counts come from the provider's
top-level ``prompt_tokens``/``completion_tokens`` verbatim (detail
fields are subsets and are never added on top). When the whole
usage block is absent, both counts are estimated at chars/4 and
flagged ``estimated``; when individual counts are missing (absent
or ``None``), only those are estimated and listed in
``usage_raw["estimated_fields"]`` — a present count (even a
literal 0) is reported unchanged, so genuine under-reporting stays
visible to ``sanity_check_usage``.

Key values are resolved from the environment at construction; a
``.env`` file in the working directory is parsed with the standard
library only (``KEY=VALUE`` lines, ``#`` comments, quotes stripped)
and the real environment wins over the file. Key values are never
logged: they appear only in the Authorization header.
"""

import json
import os
import time
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from llm.keys import KeyRing

# The 110 s read keeps slow reasoning models alive — httpx's 5 s
# default read timeout starves them (observed calls exceeding 90 s
# on free tiers); the connect stage stays tight at 10 s.
_TIMEOUT = httpx.Timeout(110.0, connect=10.0)
_RATE_LIMIT = 429
_AUTH_FAILURES = frozenset({401, 402, 403})
# A provider failing this many consecutive 5xx/transport attempts on
# one key yields the key back to the ring instead of looping forever.
_MAX_BACKOFF_RETRIES = 5


class LLMError(RuntimeError):
    """Non-retryable provider failure (or total exhaustion).

    The message carries the provider's own error text so failures are
    diagnosable; it never contains key material.
    """


class _HTTPError(Exception):
    """Internal: an HTTP status that the retry loop classifies."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class LLMResponse:
    """One successful completion plus honest accounting.

    ``model_name`` is always the CANONICAL name from the caller, even
    when the answer came from a fallback provider; ``api_url`` records
    the endpoint actually used. ``usage_raw`` is the provider's usage
    block verbatim; when the whole block is absent it carries the
    estimate marker, and when individual counts are missing (absent
    or ``None``) it gains ``estimated_fields`` listing which counts
    were estimated at chars/4 — present counts (even a literal 0)
    stay verbatim.
    """

    text: str
    input_tokens: int
    output_tokens: int
    request_time_ms: float
    retries: int
    api_url: str
    model_name: str
    finish_reason: str | None
    usage_raw: dict[str, Any]


@dataclass(frozen=True)
class _Provider:
    name: str
    api_url: str
    models: dict[str, str]
    ring: KeyRing


def _parse_env_file(path: Path) -> dict[str, str]:
    """Stdlib-only .env parsing: KEY=VALUE lines, quotes stripped.
    (Kept simple on purpose: the value is split on the FIRST '=' and
    only whole surrounding quotes are stripped.)"""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name:
            values[name] = value
    return values


def _provider_error_message(response: httpx.Response) -> str:
    """Best-effort provider error text (never includes our key)."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and "message" in error:
            return str(error["message"])
        if isinstance(error, str):
            return error
    return response.text[:200]


class LLMClient:
    """Rotation + fallback front end over one HTTP transport.

    ``transport`` accepts any httpx transport (tests use
    ``MockTransport``); ``sleep`` replaces ``time.sleep`` so tests
    record waits instead of performing them; pacing spaces consecutive
    requests by ``min_request_interval_s`` (free tiers throttle per
    minute — a 10-step task must not throttle itself).
    """

    def __init__(
        self,
        models_json: Mapping[str, Any] | str | Path,
        transport: httpx.BaseTransport | None = None,
        backoff_s: float = 1.0,
        sleep: Callable[[float], None] | None = None,
        min_request_interval_s: float = 4.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._backoff_s = backoff_s
        self._sleep = sleep if sleep is not None else time.sleep
        self._clock = clock if clock is not None else time.monotonic
        self._min_request_interval_s = min_request_interval_s
        self.timeout = _TIMEOUT
        self._http = httpx.Client(transport=transport, timeout=self.timeout)
        self._request_count = 0
        self._last_request_at: float | None = None
        self._env_file_values: dict[str, str] = {}
        self._unresolved_env: dict[str, list[str]] = {}
        self._model_providers: dict[str, list[str]] = {}
        env_file = Path.cwd() / ".env"
        if env_file.is_file():
            self._env_file_values = _parse_env_file(env_file)
        self._providers = self._build_providers(models_json)
        self.rings: dict[str, KeyRing] = {
            provider.name: provider.ring for provider in self._providers
        }
        self._providers_by_name: dict[str, _Provider] = {
            provider.name: provider for provider in self._providers
        }

    def _resolve_key(self, env_name: str) -> str | None:
        """Resolve one env-var name; the real environment wins."""
        value = os.environ.get(env_name)
        if not value:
            value = self._env_file_values.get(env_name)
        return value or None

    def _build_providers(
        self, models_json: Mapping[str, Any] | str | Path
    ) -> list[_Provider]:
        if isinstance(models_json, Mapping):
            data = dict(models_json)
        else:
            data = json.loads(Path(models_json).read_text(encoding="utf-8"))
        raw_providers = data.get("providers")
        if not isinstance(raw_providers, list):
            raise LLMError("models_json: 'providers' must be a list")
        by_name: dict[str, _Provider] = {}
        providers: list[_Provider] = []
        for item in raw_providers:
            if not isinstance(item, dict):
                raise LLMError("models_json: provider entries must be objects")
            name = item.get("name")
            api_url = item.get("api_url")
            env_names = item.get("keys_env", [])
            if not isinstance(name, str) or not isinstance(api_url, str):
                raise LLMError("models_json: provider needs name + api_url")
            if not isinstance(env_names, list):
                raise LLMError("models_json: bad keys_env type")
            keys = [
                key
                for env_name in env_names
                if isinstance(env_name, str)
                for key in [self._resolve_key(env_name)]
                if key is not None
            ]
            if not keys:
                # Names only, never values — a value must never reach
                # a message.
                unset = [
                    str(env_name)
                    for env_name in env_names
                    if not (
                        isinstance(env_name, str)
                        and self._resolve_key(env_name)
                    )
                ]
                self._unresolved_env[name] = unset
                warnings.warn(
                    f"provider '{name}': no API keys resolved — "
                    f"check env vars: {', '.join(unset)}",
                    stacklevel=2,
                )
            provider = _Provider(
                name=name, api_url=api_url, models={}, ring=KeyRing(keys)
            )
            by_name[name] = provider
            providers.append(provider)
        raw_models = data.get("models", [])
        if not isinstance(raw_models, list):
            raise LLMError("models_json: 'models' must be a list")
        for entry in raw_models:
            if not isinstance(entry, dict):
                raise LLMError("models_json: model entries must be objects")
            canonical = entry.get("canonical")
            mapping = entry.get("providers", {})
            if not isinstance(canonical, str) or not isinstance(mapping, dict):
                raise LLMError(
                    "models_json: model needs canonical + providers"
                )
            for provider_name, alias in mapping.items():
                target = by_name.get(provider_name)
                if target is None or not isinstance(alias, str):
                    raise LLMError(
                        f"models_json: model '{canonical}' names unknown "
                        f"provider '{provider_name}'"
                    )
                target.models[canonical] = alias
            # Per-model fallback order = the entry's own providers
            # insertion order (first = primary, rest = fallbacks).
            self._model_providers[canonical] = list(mapping.keys())
        return providers

    def _chain_for(self, model: str) -> list[_Provider]:
        """Providers serving ``model``, in the model entry's order."""
        by_name = self._providers_by_name
        return [
            by_name[name]
            for name in self._model_providers.get(model, [])
            if name in by_name
        ]

    def generate(
        self,
        messages: Sequence[Mapping[str, str]],
        model: str,
        stop: Sequence[str] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """One completion; rotation and fallback are internal.

        ``model`` is the canonical name; the provider-specific alias
        is chosen per endpoint and never surfaces in the response.
        """
        chain = self._chain_for(model)
        if not chain:
            raise LLMError(f"no provider serves model '{model}'")
        # Rate windows are per-minute: reopen rate-limited keys once
        # per call; permanently retired keys stay out (KeyRing.reset).
        for ring in self.rings.values():
            ring.reset()
        if self._request_count > 0:
            elapsed = self._clock() - (self._last_request_at or 0.0)
            wait = self._min_request_interval_s - elapsed
            if wait > 0.0:
                self._sleep(wait)
        return self._run_chain(chain, model, messages, stop, max_tokens)

    def _run_chain(
        self,
        chain: list[_Provider],
        model: str,
        messages: Sequence[Mapping[str, str]],
        stop: Sequence[str] | None,
        max_tokens: int | None,
    ) -> LLMResponse:
        retries = 0
        backoff_stage = 0
        last_rate_limited = False
        last_failure = "unknown"
        attempted = False
        reset_used = False
        index = 0
        while index < len(chain):
            provider = chain[index]
            ring = provider.ring
            key: str | None = None
            while True:
                if key is None:
                    key = ring.next_key()
                if key is None:
                    break
                started = self._clock()
                attempted = True
                try:
                    payload = self._post(
                        provider, key, model, messages, stop, max_tokens
                    )
                except _HTTPError as exc:
                    retries += 1
                    if exc.status == _RATE_LIMIT:
                        # Rotation IS the backoff: next key, no sleep.
                        ring.mark_exhausted(key)
                        key = None
                        last_rate_limited = True
                        last_failure = "rate limited"
                        backoff_stage = 0
                        continue
                    if exc.status in _AUTH_FAILURES:
                        # Key rejected: exhausted permanently — it must
                        # never rejoin, not even via a ring reset.
                        ring.mark_exhausted(key, permanent=True)
                        key = None
                        last_rate_limited = False
                        last_failure = f"key rejected (HTTP {exc.status})"
                        backoff_stage = 0
                        continue
                    if exc.status >= 500:
                        last_rate_limited = False
                        last_failure = f"server error (HTTP {exc.status})"
                        backoff_stage += 1
                        if backoff_stage > _MAX_BACKOFF_RETRIES:
                            ring.mark_exhausted(key)
                            key = None
                            backoff_stage = 0
                            continue
                        self._sleep(self._backoff_s * 2 ** (backoff_stage - 1))
                        continue
                    if exc.status == 400 and (
                        exc.message == "Provider returned error"
                    ):
                        # OpenRouter :free endpoints transiently return
                        # 400 "Provider returned error" for upstream
                        # failures; identical payloads succeed on
                        # retry — retry with backoff, capped like
                        # 5xx. Any other 400 is a real request error
                        # and fails fast.
                        last_rate_limited = False
                        last_failure = "transient provider error (HTTP 400)"
                        backoff_stage += 1
                        if backoff_stage > _MAX_BACKOFF_RETRIES:
                            ring.mark_exhausted(key)
                            key = None
                            backoff_stage = 0
                            continue
                        self._sleep(self._backoff_s * 2 ** (backoff_stage - 1))
                        continue
                    raise LLMError(
                        f"provider '{provider.name}' rejected the "
                        f"request: {exc.message}"
                    ) from None
                except httpx.TransportError as exc:
                    retries += 1
                    last_rate_limited = False
                    last_failure = f"transport error ({type(exc).__name__})"
                    backoff_stage += 1
                    if backoff_stage > _MAX_BACKOFF_RETRIES:
                        ring.mark_exhausted(key)
                        key = None
                        backoff_stage = 0
                        continue
                    self._sleep(self._backoff_s * 2 ** (backoff_stage - 1))
                    continue
                request_ms = (self._clock() - started) * 1000.0
                return self._parse_response(
                    payload, provider, model, retries, request_ms, messages
                )
            # Every key of this provider is exhausted.
            if (
                index == len(chain) - 1
                and last_rate_limited
                and not reset_used
            ):
                # Rate windows are per-minute: reopen the ring, wait
                # one backoff, and retry once more — a single request;
                # if that fails too, the exhaustion is final.
                reset_used = True
                backoff_stage = 0
                ring.reset()
                self._sleep(self._backoff_s)
                key = ring.next_key()
                if key is not None:
                    started = self._clock()
                    attempted = True
                    try:
                        payload = self._post(
                            provider, key, model, messages, stop, max_tokens
                        )
                    except _HTTPError as exc:
                        retries += 1
                        raise LLMError(
                            f"all providers exhausted for model "
                            f"'{model}' (last failure: HTTP "
                            f"{exc.status}: {exc.message})"
                        ) from None
                    except httpx.TransportError as exc:
                        retries += 1
                        raise LLMError(
                            f"all providers exhausted for model "
                            f"'{model}' (last failure: transport error "
                            f"({type(exc).__name__}))"
                        ) from None
                    request_ms = (self._clock() - started) * 1000.0
                    return self._parse_response(
                        payload,
                        provider,
                        model,
                        retries,
                        request_ms,
                        messages,
                    )
            index += 1
        if not attempted:
            zero_key = [
                name
                for name in self._unresolved_env
                if any(p.name == name for p in chain)
            ]
            if zero_key:
                detail = "; ".join(
                    f"provider '{name}' (unset env vars: "
                    f"{', '.join(self._unresolved_env[name])})"
                    for name in zero_key
                )
                raise LLMError(
                    f"no API keys resolved for model '{model}' — {detail}"
                )
            raise LLMError(
                f"all providers exhausted for model '{model}' — all "
                f"keys of provider(s) "
                f"{', '.join(repr(p.name) for p in chain)} are exhausted"
            )
        raise LLMError(
            f"all providers exhausted for model '{model}' "
            f"(last failure: {last_failure})"
        )

    def _post(
        self,
        provider: _Provider,
        key: str,
        model: str,
        messages: Sequence[Mapping[str, str]],
        stop: Sequence[str] | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": provider.models[model],
            "messages": [dict(message) for message in messages],
        }
        if stop is not None:
            body["stop"] = list(stop)
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        self._request_count += 1
        endpoint = provider.api_url.rstrip("/") + "/chat/completions"
        try:
            response = self._http.post(
                endpoint,
                json=body,
                headers={"Authorization": f"Bearer {key}"},
                timeout=self.timeout,
            )
        finally:
            # Wall-clock pacing counts every completed exchange —
            # failed ones included.
            self._last_request_at = self._clock()
        if response.status_code >= 400:
            raise _HTTPError(
                response.status_code, _provider_error_message(response)
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMError(
                f"provider '{provider.name}' returned a non-JSON body"
            ) from exc
        if not isinstance(payload, dict):
            raise LLMError(
                f"provider '{provider.name}' returned a non-object body"
            )
        return payload

    def _parse_response(
        self,
        payload: Mapping[str, Any],
        provider: _Provider,
        model: str,
        retries: int,
        request_ms: float,
        messages: Sequence[Mapping[str, str]],
    ) -> LLMResponse:
        choices = payload.get("choices") or []
        if not isinstance(choices, list) or not choices:
            raise LLMError(f"provider '{provider.name}' returned no choices")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise LLMError(
                f"provider '{provider.name}' returned a malformed "
                f"choice (expected an object)"
            )
        message = choice.get("message") or {}
        content = message.get("content")
        text = "" if content is None else str(content)
        usage = payload.get("usage")
        if isinstance(usage, dict) and usage:
            # Top-level counts only: detail fields (reasoning, cache)
            # are subsets of these and must never be added on top.
            # A MISSING count (key absent or None) is estimated at
            # chars/4 and named in estimated_fields; a PRESENT count
            # — including a literal 0 — is kept verbatim, so genuine
            # under-reporting stays visible to sanity_check_usage.
            usage_raw: dict[str, Any] = dict(usage)
            estimated: list[str] = []
            prompt = usage.get("prompt_tokens")
            completion = usage.get("completion_tokens")
            if prompt is None:
                estimated.append("prompt_tokens")
                input_tokens = len(json.dumps(messages)) // 4
            else:
                input_tokens = int(prompt)
            if completion is None:
                estimated.append("completion_tokens")
                output_tokens = len(text) // 4
            else:
                output_tokens = int(completion)
            if estimated:
                usage_raw["estimated_fields"] = estimated
        else:
            request_chars = len(json.dumps(messages))
            input_tokens = request_chars // 4
            output_tokens = len(text) // 4
            usage_raw = {
                "estimated": True,
                "input_chars": request_chars,
                "output_chars": len(text),
            }
        return LLMResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_time_ms=request_ms,
            retries=retries,
            api_url=provider.api_url,
            model_name=model,
            finish_reason=choice.get("finish_reason"),
            usage_raw=usage_raw,
        )

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._http.close()

    def __repr__(self) -> str:
        names = [provider.name for provider in self._providers]
        return f"LLMClient(providers={names})"
