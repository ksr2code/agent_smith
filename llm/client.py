"""OpenAI-compatible LLM client with key rotation, provider
fallback, and honest usage accounting (T15; ADR-0006).

The wire format is the OpenAI chat-completions shape, which every
provider we target speaks; providers differ only in endpoint, key
environment variables, and model naming. ``models_json`` maps our
CANONICAL model names to per-provider aliases so a fallback switch
never changes ``LLMResponse.model_name`` mid-run (the grader warns
on multiple model names per run).

``models_json`` schema (this becomes the root ``models.json``)::

    {
      "providers": [                       # ordered = fallback order
        {
          "name": "openrouter",
          "api_url": "https://host/api/v1/chat/completions",
          "api_key_env": ["KEY_ENV_NAME_1", "KEY_ENV_NAME_2"],
          "models": {"zephyr": "vendor/model:free"}  # canonical->alias
        }
      ],
      "limits": {...}                      # pass-through (T18+ reads)
    }

Key values are resolved from the environment at construction; a
``.env`` file in the working directory is parsed with the standard
library only (``KEY=VALUE`` lines, ``#`` comments, quotes stripped)
and the real environment wins over the file. Key values are never
logged: they appear only in the Authorization header.
"""

import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from llm.keys import KeyRing

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
    block verbatim, or the estimate marker when none was reported.
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
    models: Mapping[str, str]
    ring: KeyRing


def _parse_env_file(path: Path) -> dict[str, str]:
    """Stdlib-only .env parsing: KEY=VALUE lines, quotes stripped."""
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
    ) -> None:
        self._backoff_s = backoff_s
        self._sleep = sleep if sleep is not None else time.sleep
        self._min_request_interval_s = min_request_interval_s
        self.timeout = _TIMEOUT
        self._http = httpx.Client(transport=transport, timeout=self.timeout)
        self._request_count = 0
        self._env_file_values: dict[str, str] = {}
        env_file = Path.cwd() / ".env"
        if env_file.is_file():
            self._env_file_values = _parse_env_file(env_file)
        self._providers = self._build_providers(models_json)
        self.rings: dict[str, KeyRing] = {
            provider.name: provider.ring for provider in self._providers
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
        providers: list[_Provider] = []
        for item in raw_providers:
            if not isinstance(item, dict):
                raise LLMError("models_json: provider entries must be objects")
            name = item.get("name")
            api_url = item.get("api_url")
            env_names = item.get("api_key_env", [])
            models = item.get("models", {})
            if not isinstance(name, str) or not isinstance(api_url, str):
                raise LLMError("models_json: provider needs name + api_url")
            if not isinstance(env_names, list) or not isinstance(models, dict):
                raise LLMError("models_json: bad api_key_env/models types")
            keys = [
                key
                for env_name in env_names
                if isinstance(env_name, str)
                for key in [self._resolve_key(env_name)]
                if key is not None
            ]
            providers.append(
                _Provider(
                    name=name,
                    api_url=api_url,
                    models=dict(models),
                    ring=KeyRing(keys),
                )
            )
        return providers

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
        chain = [p for p in self._providers if model in p.models]
        if not chain:
            raise LLMError(f"no provider serves model '{model}'")
        if self._request_count > 0:
            self._sleep(self._min_request_interval_s)
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
                started = time.monotonic()
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
                        # Key rejected: exhausted permanently.
                        ring.mark_exhausted(key)
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
                request_ms = (time.monotonic() - started) * 1000.0
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
                    started = time.monotonic()
                    try:
                        payload = self._post(
                            provider, key, model, messages, stop, max_tokens
                        )
                    except (_HTTPError, httpx.TransportError):
                        retries += 1
                        raise LLMError(
                            f"all providers exhausted for model "
                            f"'{model}' (last failure: rate limited)"
                        ) from None
                    request_ms = (time.monotonic() - started) * 1000.0
                    return self._parse_response(
                        payload,
                        provider,
                        model,
                        retries,
                        request_ms,
                        messages,
                    )
            index += 1
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
        response = self._http.post(
            provider.api_url,
            json=body,
            headers={"Authorization": f"Bearer {key}"},
            timeout=self.timeout,
        )
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
        message = choice.get("message") or {}
        content = message.get("content")
        text = "" if content is None else str(content)
        usage = payload.get("usage")
        if isinstance(usage, dict) and usage:
            # Top-level counts only: detail fields (reasoning, cache)
            # are subsets of these and must never be added on top.
            input_tokens = int(usage.get("prompt_tokens") or 0)
            output_tokens = int(usage.get("completion_tokens") or 0)
            usage_raw: dict[str, Any] = dict(usage)
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
