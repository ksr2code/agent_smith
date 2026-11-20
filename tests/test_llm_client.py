"""Tests for the T15 LLM client: KeyRing rotation, provider
fallback with the canonical-name invariant, pacing, and honest
usage parsing (reasoning subsets never added; estimate fallback).

All HTTP is scripted with httpx.MockTransport; sleeps are recorded,
never performed; key values are dummies injected via monkeypatch.
"""

import json
from pathlib import Path

import httpx
import pytest

from llm import KeyRing, LLMClient, LLMError, sanity_check_usage

_A_URL = "https://a.example/v1/chat/completions"
_B_URL = "https://b.example/v1/chat/completions"


def _models_ab() -> dict:
    """Two providers x two keys each; canonical 'zephyr' on both."""
    return {
        "providers": [
            {
                "name": "prov_a",
                "api_url": _A_URL,
                "api_key_env": ["T15_KEY_A1", "T15_KEY_A2"],
                "models": {"zephyr": "a/zephyr-free"},
            },
            {
                "name": "prov_b",
                "api_url": _B_URL,
                "api_key_env": ["T15_KEY_B1", "T15_KEY_B2"],
                "models": {"zephyr": "b/zephyr-free"},
            },
        ],
        "limits": {"mbpp": {"max_iterations": 10}},
    }


def _models_a() -> dict:
    """Single provider — the 'last provider' for reset semantics."""
    return {
        "providers": [
            {
                "name": "prov_a",
                "api_url": _A_URL,
                "api_key_env": ["T15_KEY_A1", "T15_KEY_A2"],
                "models": {"zephyr": "a/zephyr-free"},
            }
        ],
        "limits": {},
    }


class _Scripted:
    """MockTransport backend scripting one outcome per request.

    Outcomes: ("json", code, body) or ("error", exception). Records
    the Authorization header and parsed body of every request, and
    every sleep call.
    """

    def __init__(self) -> None:
        self.script: list[tuple] = []
        self.auths: list[str | None] = []
        self.bodies: list[dict] = []
        self.sleeps: list[float] = []

    def add(self, code: int, body: dict) -> None:
        self.script.append(("json", code, body))

    def add_error(self, exc: Exception) -> None:
        self.script.append(("error", exc))

    def __call__(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.auths.append(request.headers.get("authorization"))
        self.bodies.append(json.loads(request.content))
        kind, *rest = self.script.pop(0)
        if kind == "error":
            raise rest[0]
        code, body = rest
        return httpx.Response(code, json=body)


def _reply(
    content: str | None = "hi",
    usage: dict | None = None,
    finish: str | None = "stop",
) -> dict:
    message = {"role": "assistant", "content": content}
    body: dict = {"choices": [{"message": message, "finish_reason": finish}]}
    if usage is not None:
        body["usage"] = usage
    return body


def _client(
    scripted: _Scripted,
    models: dict,
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    **kwargs: object,
) -> LLMClient:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return LLMClient(
        models,
        transport=httpx.MockTransport(scripted.handler),
        sleep=scripted,
        **kwargs,  # type: ignore[arg-type]
    )


_MESSAGES = [{"role": "user", "content": "hello"}]


def test_success_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    # Discriminates: a parser that drops finish_reason, invents
    # retries, loses the raw usage block, or reports the provider
    # alias instead of the canonical model name.
    usage = {"prompt_tokens": 100, "completion_tokens": 50}
    scripted = _Scripted()
    scripted.add(200, _reply(usage=usage))
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert resp.text == "hi"
    assert resp.input_tokens == 100
    assert resp.output_tokens == 50
    assert resp.finish_reason == "stop"
    assert resp.retries == 0
    assert resp.api_url == _A_URL
    assert resp.model_name == "zephyr"
    assert resp.request_time_ms >= 0.0
    assert resp.usage_raw == usage


def test_429_rotates_to_next_key_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: retrying the same throttled key (must rotate) or
    # sleeping on rotation (rotation IS the backoff — immediate).
    scripted = _Scripted()
    scripted.add(429, {"error": {"message": "rate limited"}})
    scripted.add(200, _reply())
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert resp.retries == 1
    assert scripted.auths == ["Bearer sk-a1", "Bearer sk-a2"]
    assert scripted.sleeps == []


def test_all_keys_429_falls_through_to_next_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: a client that stays on the exhausted provider or
    # leaks the provider alias into model_name (the grader warns on
    # multiple model names per run). api_url must record the actual
    # endpoint used.
    scripted = _Scripted()
    scripted.add(429, {"error": {"message": "rate limited"}})
    scripted.add(429, {"error": {"message": "rate limited"}})
    scripted.add(200, _reply())
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {
            "T15_KEY_A1": "sk-a1",
            "T15_KEY_A2": "sk-a2",
            "T15_KEY_B1": "sk-b1",
            "T15_KEY_B2": "sk-b2",
        },
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert resp.model_name == "zephyr"
    assert resp.api_url == _B_URL
    assert resp.text == "hi"
    assert resp.retries == 2
    assert scripted.bodies[-1]["model"] == "b/zephyr-free"
    assert scripted.sleeps == []


def test_last_provider_rate_limited_resets_and_retries_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: giving up when every key is exhausted although
    # per-minute windows reopen — reset + backoff + one more try.
    scripted = _Scripted()
    scripted.add(429, {"error": {"message": "rate limited"}})
    scripted.add(429, {"error": {"message": "rate limited"}})
    scripted.add(200, _reply())
    client = _client(
        scripted,
        _models_a(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert resp.text == "hi"
    assert resp.retries == 2
    assert scripted.sleeps == [1.0]  # backoff_s, not pacing
    assert client.rings["prov_a"].next_key() is not None


def test_reset_retry_exhausted_raises_llm_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = _Scripted()
    for _ in range(3):
        scripted.add(429, {"error": {"message": "rate limited"}})
    client = _client(
        scripted,
        _models_a(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    with pytest.raises(LLMError, match="rate limited"):
        client.generate(_MESSAGES, "zephyr")
    assert len(scripted.auths) == 3  # one reset round only


def test_auth_rejection_exhausts_key_permanently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: reusing a 401'd key on the next generate call —
    # auth failures must mark the key exhausted permanently.
    scripted = _Scripted()
    scripted.add(401, {"error": {"message": "bad key"}})
    scripted.add(200, _reply())
    scripted.add(200, _reply())
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {
            "T15_KEY_A1": "sk-a1",
            "T15_KEY_A2": "sk-a2",
            "T15_KEY_B1": "sk-b1",
            "T15_KEY_B2": "sk-b2",
        },
    )
    first = client.generate(_MESSAGES, "zephyr")
    second = client.generate(_MESSAGES, "zephyr")
    assert first.retries == 1
    assert scripted.auths[:2] == ["Bearer sk-a1", "Bearer sk-a2"]
    assert scripted.auths[2] == "Bearer sk-a2"  # sk-a1 never retried
    assert second.text == "hi"
    assert scripted.sleeps == [4.0]  # pacing between calls only


@pytest.mark.parametrize("code", [402, 403])
def test_other_auth_rejections_exhaust_key(
    code: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = _Scripted()
    scripted.add(code, {"error": {"message": "denied"}})
    scripted.add(200, _reply())
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {
            "T15_KEY_A1": "sk-a1",
            "T15_KEY_A2": "sk-a2",
            "T15_KEY_B1": "sk-b1",
            "T15_KEY_B2": "sk-b2",
        },
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert scripted.auths[0] == "Bearer sk-a1"
    assert scripted.auths[1] == "Bearer sk-a2"
    assert resp.text == "hi"


def test_server_error_backs_off_same_key_exponentially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: rotating keys on a 5xx (the key is innocent —
    # the server is down) or a flat retry interval (must be 1s, 2s).
    scripted = _Scripted()
    scripted.add(500, {"error": {"message": "overloaded"}})
    scripted.add(500, {"error": {"message": "overloaded"}})
    scripted.add(200, _reply())
    client = _client(
        scripted,
        _models_a(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert scripted.auths == ["Bearer sk-a1"] * 3
    assert scripted.sleeps == [1.0, 2.0]
    assert resp.retries == 2


def test_transport_error_backs_off_same_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = _Scripted()
    scripted.add_error(httpx.ConnectError("boom"))
    scripted.add(200, _reply())
    client = _client(
        scripted,
        _models_a(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert scripted.auths == ["Bearer sk-a1"] * 2
    assert scripted.sleeps == [1.0]
    assert resp.retries == 1


def test_persistent_server_errors_yield_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: an infinite 5xx retry loop — after the backoff
    # cap the key must be yielded and the chain move on.
    scripted = _Scripted()
    for _ in range(6):
        scripted.add(500, {"error": {"message": "down"}})
    scripted.add(200, _reply())
    client = _client(
        scripted,
        _models_a(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert scripted.auths == ["Bearer sk-a1"] * 6 + ["Bearer sk-a2"]
    assert scripted.sleeps == [1.0, 2.0, 4.0, 8.0, 16.0]
    assert resp.retries == 6


def test_other_4xx_raises_llm_error_with_provider_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = _Scripted()
    scripted.add(400, {"error": {"message": "bad request body"}})
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    with pytest.raises(LLMError, match="bad request body") as excinfo:
        client.generate(_MESSAGES, "zephyr")
    assert "sk-a1" not in str(excinfo.value)  # never leak key material
    assert len(scripted.auths) == 1  # not retryable — fail loudly


def test_stop_and_max_tokens_reach_the_request_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = _Scripted()
    scripted.add(200, _reply())
    scripted.add(200, _reply())
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    client.generate(_MESSAGES, "zephyr")
    client.generate(
        _MESSAGES,
        "zephyr",
        stop=["\nObservation:"],
        max_tokens=700,
    )
    assert scripted.bodies[0]["model"] == "a/zephyr-free"
    assert "stop" not in scripted.bodies[0]
    assert "max_tokens" not in scripted.bodies[0]
    assert scripted.bodies[1]["stop"] == ["\nObservation:"]
    assert scripted.bodies[1]["max_tokens"] == 700


def test_reasoning_tokens_are_never_added(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: summing reasoning-token detail fields into the
    # top-level counts — details are subsets of completion_tokens.
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "prompt_tokens_details": {"cached_tokens": 20},
        "completion_tokens_details": {"reasoning_tokens": 30},
    }
    scripted = _Scripted()
    scripted.add(200, _reply(usage=usage))
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert resp.input_tokens == 100
    assert resp.output_tokens == 50


def test_null_content_is_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = _Scripted()
    scripted.add(200, _reply(content=None, finish="length"))
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert resp.text == ""
    assert resp.finish_reason == "length"


def test_missing_usage_is_estimated_and_marked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: zeros silently swallowed as real usage — the
    # estimate must be chars/4 AND flagged in usage_raw.
    scripted = _Scripted()
    scripted.add(200, _reply(content="abcdefgh"))  # no usage block
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert resp.input_tokens == len(json.dumps(_MESSAGES)) // 4
    assert resp.output_tokens == len("abcdefgh") // 4
    assert resp.usage_raw["estimated"] is True


def test_pacing_between_generate_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: hammering the free tier — consecutive requests
    # must space at least min_request_interval_s apart (recorded,
    # never real-slept).
    scripted = _Scripted()
    scripted.add(200, _reply())
    scripted.add(200, _reply())
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    client.generate(_MESSAGES, "zephyr")
    assert scripted.sleeps == []  # first request: no pacing
    client.generate(_MESSAGES, "zephyr")
    assert scripted.sleeps == [4.0]
    assert scripted.sleeps[0] >= 4.0


def test_env_file_loaded_with_real_env_precedence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Discriminates: file values overriding the process environment
    # (real environment must win) and a missing env var silently
    # dropping a key.
    env_file = tmp_path / ".env"
    env_file.write_text(
        'T15_KEY_A1=file-a1\n# comment line\nT15_KEY_B1="file-b1"\n',
        encoding="utf-8",
    )
    scripted = _Scripted()
    scripted.add(429, {"error": {"message": "rate limited"}})
    scripted.add(200, _reply())
    monkeypatch.setenv("T15_KEY_A1", "env-a1")  # beats the file
    monkeypatch.chdir(tmp_path)  # .env discovered in the cwd
    client = LLMClient(
        _models_ab(),
        transport=httpx.MockTransport(scripted.handler),
        sleep=scripted,
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert scripted.auths == ["Bearer env-a1", "Bearer file-b1"]
    assert resp.api_url == _B_URL  # prov_a key2 unresolved → skipped


def test_timeout_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    # Discriminates: httpx's 5 s default read timeout, which starves
    # slow reasoning models.
    scripted = _Scripted()
    scripted.add(200, _reply())
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    assert client.timeout.connect == 10.0
    assert client.timeout.read == 110.0


def test_unknown_model_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    scripted = _Scripted()
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    with pytest.raises(LLMError, match="no provider serves"):
        client.generate(_MESSAGES, "gpt-5-turbo")
    assert scripted.auths == []


def test_keyring_round_robin_skips_and_resets() -> None:
    ring = KeyRing(["k1", "k2", "k3"])
    assert ring.next_key() == "k1"
    assert ring.next_key() == "k2"
    ring.mark_exhausted("k2")
    assert ring.next_key() == "k3"
    assert ring.next_key() == "k1"  # wraps, skips the exhausted key
    ring.reset()  # rate windows are per-minute, not permanent
    assert ring.next_key() == "k2"


def test_keyring_exhaustion_returns_none() -> None:
    ring = KeyRing(["k1"])
    ring.mark_exhausted("k1")
    assert ring.next_key() is None
    ring.reset()
    assert ring.next_key() == "k1"
    assert KeyRing([]).next_key() is None


def test_keyring_repr_never_contains_key_material() -> None:
    ring = KeyRing(["super-secret-value"])
    assert "super-secret-value" not in repr(ring)
    assert "super-secret-value" not in str(ring)


def test_sanity_check_usage_flags_divergence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Hidden reasoning: 5000 tokens reported, ~250 implied by the
    # visible text (>5x) — must produce a note.
    scripted = _Scripted()
    usage = {"prompt_tokens": 10, "completion_tokens": 5000}
    scripted.add(200, _reply(content="a" * 1000, usage=usage))
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    note = sanity_check_usage(resp.text, resp)
    assert note is not None
    assert "5000" in note


def test_sanity_check_usage_quiet_when_aligned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = _Scripted()
    usage = {"prompt_tokens": 10, "completion_tokens": 25}
    scripted.add(200, _reply(content="a" * 100, usage=usage))
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert sanity_check_usage(resp.text, resp) is None
