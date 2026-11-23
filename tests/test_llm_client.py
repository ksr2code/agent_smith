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

_A_URL = "https://a.example/v1"
_B_URL = "https://b.example/v1"


def _models_ab() -> dict:
    """Two providers x two keys each; canonical 'zephyr' on both."""
    return {
        "providers": [
            {
                "name": "prov_a",
                "api_url": _A_URL,
                "keys_env": ["T15_KEY_A1", "T15_KEY_A2"],
            },
            {
                "name": "prov_b",
                "api_url": _B_URL,
                "keys_env": ["T15_KEY_B1", "T15_KEY_B2"],
            },
        ],
        "models": [
            {
                "canonical": "zephyr",
                "providers": {
                    "prov_a": "a/zephyr-free",
                    "prov_b": "b/zephyr-free",
                },
            }
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
                "keys_env": ["T15_KEY_A1", "T15_KEY_A2"],
            }
        ],
        "models": [
            {"canonical": "zephyr", "providers": {"prov_a": "a/zephyr-free"}}
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
    env: dict[str, str | None],
    **kwargs: object,
) -> LLMClient:
    defaults = {
        "T15_KEY_A1": "sk-a1",
        "T15_KEY_A2": "sk-a2",
        "T15_KEY_B1": "sk-b1",
        "T15_KEY_B2": "sk-b2",
    }
    merged = {**defaults, **env}
    for name, value in merged.items():
        if value is None:  # explicit None = leave unset (zero-key case)
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    return LLMClient(
        models,
        transport=httpx.MockTransport(scripted.handler),
        sleep=scripted,
        **kwargs,  # type: ignore[arg-type]
    )


class _FakeClock:
    """Injectable monotonic clock: tests advance it manually, so
    wall-clock pacing is deterministic (a recorded sleep does NOT
    advance it — the test says how much time passed)."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


_MESSAGES = [{"role": "user", "content": "hello"}]


def test_chat_endpoint_is_base_plus_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: posting to the base url — provider api_url is
    # the OpenAI-compatible BASE; the chat endpoint must be
    # {base}/chat/completions (groq 404s with 'POST /openai/v1'
    # otherwise).
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json=_reply())

    scripted = _Scripted()
    scripted.handler = handler  # type: ignore[method-assign]
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    client.generate(_MESSAGES, "zephyr")
    assert seen == ["/v1/chat/completions"]


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
    with pytest.raises(LLMError, match="HTTP 429: rate limited"):
        client.generate(_MESSAGES, "zephyr")
    assert len(scripted.auths) == 3  # one reset round only


def test_auth_rejection_exhausts_key_permanently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: reusing a 401'd key on the next generate call —
    # auth failures must mark the key exhausted permanently.
    scripted = _Scripted()
    clock = _FakeClock()
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
        clock=clock,
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


def test_transient_openrouter_400_retries_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: failing fast on a transient upstream 400 — the
    # identical payload succeeds on retry, so it must back off on
    # the same key instead of raising.
    scripted = _Scripted()
    scripted.add(400, {"error": {"message": "Provider returned error"}})
    scripted.add(200, _reply())
    client = _client(
        scripted,
        _models_a(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert resp.text == "hi"
    assert resp.retries == 1
    assert scripted.auths == ["Bearer sk-a1"] * 2  # same key
    assert scripted.sleeps == [1.0]  # backoff_s, not pacing


def test_real_400_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    # Discriminates: retrying a GENUINE payload error — a real 400
    # must raise immediately with the provider's message, no sleeps,
    # no second attempt.
    scripted = _Scripted()
    scripted.add(400, {"error": {"message": "invalid model"}})
    client = _client(
        scripted,
        _models_a(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    with pytest.raises(LLMError, match="invalid model"):
        client.generate(_MESSAGES, "zephyr")
    assert scripted.sleeps == []
    assert len(scripted.auths) == 1


def test_transient_openrouter_400_ladder_yields_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: an endless transient-400 stream wedging one key
    # — the exponential ladder runs, the cap yields the key, and the
    # ring's second key serves the success.
    scripted = _Scripted()
    for _ in range(6):
        scripted.add(400, {"error": {"message": "Provider returned error"}})
    scripted.add(200, _reply())
    client = _client(
        scripted,
        _models_a(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert scripted.sleeps == [1.0, 2.0, 4.0, 8.0, 16.0]
    assert scripted.auths == ["Bearer sk-a1"] * 6 + ["Bearer sk-a2"]
    assert resp.text == "hi"
    assert resp.retries == 6


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


def test_malformed_choices_payload_raises_llm_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: a 200 whose choices[0] is not an object crashing
    # with AttributeError instead of a diagnosable LLMError.
    scripted = _Scripted()
    scripted.add(200, {"choices": ["garbage"]})
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    with pytest.raises(LLMError, match="malformed"):
        client.generate(_MESSAGES, "zephyr")


def test_root_models_json_schema_is_loadable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Discriminates: a malformed root models.json breaking startup —
    # the real config file must parse into providers and alias maps.
    # chdir away from any developer .env so keys are genuinely
    # unresolved (deterministic zero-key warnings + error path).
    monkeypatch.chdir(tmp_path)
    root_config = Path(__file__).resolve().parent.parent / "models.json"
    with pytest.warns(UserWarning):
        client = LLMClient(root_config, sleep=lambda _s: None)
    assert set(client.rings) == {
        "openrouter",
        "groq",
        "google",
        "nvidia",
    }
    groq = next(p for p in client._providers if p.name == "groq")
    assert groq.models["gpt-oss-120b"] == "openai/gpt-oss-120b"
    with pytest.raises(LLMError, match="no API keys resolved"):
        client.generate(_MESSAGES, "gpt-oss-120b")


def test_root_models_json_limits_are_subject_contract() -> None:
    # Discriminates: placeholder or tuning values drifting into the
    # limits block — these are the subject's contract numbers, read
    # verbatim by T18/T19, so the blocks are pinned field-exact
    # (an extra or missing key breaks the equality either way).
    config = json.loads(
        (Path(__file__).resolve().parent.parent / "models.json").read_text(
            encoding="utf-8"
        )
    )
    assert config["limits"]["mbpp"] == {
        "max_iterations": 10,
        "max_input_tokens": 6000,
        "max_output_tokens": 1500,
        "max_time_seconds": 120.0,
    }
    assert config["limits"]["swebench"] == {
        "max_iterations": 30,
        "max_input_tokens": 300000,
        "max_output_tokens": 10000,
        "max_time_seconds": 900.0,
    }


def test_models_json_loaded_from_file_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Discriminates: the str/Path loading branch of models_json —
    # only ever exercised dict fixtures before.
    models_file = tmp_path / "models.json"
    models_file.write_text(json.dumps(_models_ab()), encoding="utf-8")
    scripted = _Scripted()
    scripted.add(200, _reply())
    client = _client(
        scripted,
        str(models_file),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert resp.api_url == _A_URL
    scripted = _Scripted()  # also the Path form
    scripted.add(200, _reply())
    client = _client(
        scripted,
        models_file,
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    assert client.generate(_MESSAGES, "zephyr").text == "hi"


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


def test_empty_usage_dict_takes_whole_estimate_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: an empty usage dict slipping into the partial
    # path — no counts exist to keep, so it must behave exactly like
    # an absent block (full estimate + the `estimated` marker).
    scripted = _Scripted()
    scripted.add(200, _reply(content="abcdefgh", usage={}))
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert resp.input_tokens == len(json.dumps(_MESSAGES)) // 4
    assert resp.output_tokens == len("abcdefgh") // 4
    assert resp.usage_raw == {
        "estimated": True,
        "input_chars": len(json.dumps(_MESSAGES)),
        "output_chars": 8,
    }


def test_partial_usage_missing_prompt_tokens_is_estimated_and_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: a usage block present but missing prompt_tokens
    # silently yielding a 0 input count — the missing count must be
    # estimated at chars/4 and named in estimated_fields, while the
    # present completion count stays verbatim.
    usage = {"completion_tokens": 50}
    scripted = _Scripted()
    scripted.add(200, _reply(content="abcdefgh", usage=usage))
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert resp.input_tokens == len(json.dumps(_MESSAGES)) // 4
    assert resp.output_tokens == 50
    assert resp.usage_raw == {
        "completion_tokens": 50,
        "estimated_fields": ["prompt_tokens"],
    }


def test_partial_usage_missing_completion_tokens_is_estimated_and_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: the mirror case — missing completion_tokens
    # estimated from the visible text while the prompt count stays
    # verbatim.
    usage = {"prompt_tokens": 100}
    scripted = _Scripted()
    scripted.add(200, _reply(content="abcdefgh", usage=usage))
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert resp.input_tokens == 100
    assert resp.output_tokens == len("abcdefgh") // 4
    assert resp.usage_raw == {
        "prompt_tokens": 100,
        "estimated_fields": ["completion_tokens"],
    }


def test_partial_usage_present_values_stay_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: estimating over a PRESENT count — a literal 0
    # with visible text is genuine under-reporting that the sanity
    # check must keep catching, so present values (even a numeric
    # string) are int()'d and reported unchanged, with no flag.
    usage = {"prompt_tokens": 0, "completion_tokens": "12"}
    scripted = _Scripted()
    scripted.add(200, _reply(content="abcdefgh", usage=usage))
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert resp.input_tokens == 0
    assert resp.output_tokens == 12
    assert "estimated_fields" not in resp.usage_raw
    assert resp.usage_raw == {"prompt_tokens": 0, "completion_tokens": "12"}


def test_partial_usage_explicit_none_counts_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: treating an explicit null count as present —
    # some providers report null; None is MISSING, so both counts
    # get estimated and flagged in order.
    usage = {"prompt_tokens": None, "completion_tokens": None}
    scripted = _Scripted()
    scripted.add(200, _reply(content="abcdefgh", usage=usage))
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    assert resp.input_tokens == len(json.dumps(_MESSAGES)) // 4
    assert resp.output_tokens == len("abcdefgh") // 4
    assert resp.usage_raw == {
        "prompt_tokens": None,
        "completion_tokens": None,
        "estimated_fields": ["prompt_tokens", "completion_tokens"],
    }


def test_pacing_between_generate_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: hammering the free tier — consecutive requests
    # must space at least min_request_interval_s apart (recorded,
    # never real-slept). First-ever call never sleeps.
    scripted = _Scripted()
    clock = _FakeClock()
    scripted.add(200, _reply())
    scripted.add(200, _reply())
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
        clock=clock,
    )
    client.generate(_MESSAGES, "zephyr")
    assert scripted.sleeps == []  # first request: no pacing
    client.generate(_MESSAGES, "zephyr")
    assert scripted.sleeps == [4.0]  # zero elapsed → full interval


def test_pacing_sleeps_only_the_remainder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: a full-interval sleep on top of elapsed wall
    # time — only interval minus elapsed may be slept, and a call
    # long after the last request must not sleep at all.
    scripted = _Scripted()
    clock = _FakeClock()
    scripted.add(200, _reply())
    scripted.add(200, _reply())
    scripted.add(200, _reply())
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
        clock=clock,
    )
    client.generate(_MESSAGES, "zephyr")
    clock.advance(1.0)  # 1 s of the 4 s window already elapsed
    client.generate(_MESSAGES, "zephyr")
    assert scripted.sleeps == [3.0]  # remainder only
    clock.advance(100.0)  # far apart — window fully elapsed
    client.generate(_MESSAGES, "zephyr")
    assert scripted.sleeps == [3.0]  # no further sleep


def test_model_entry_order_sets_primary_and_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: chain order taken from the top-level providers
    # list instead of the model entry's own providers mapping — the
    # owner declares per model which provider is primary (listed
    # first), even when the providers list names it later. The 429
    # exhausts the primary; the backup must serve the fallback.
    models = {
        "providers": [
            {
                "name": "backup_first",
                "api_url": _B_URL,
                "keys_env": ["T15_KEY_B1", "T15_KEY_B2"],
            },
            {
                "name": "primary_later",
                "api_url": _A_URL,
                "keys_env": ["T15_KEY_A1", "T15_KEY_A2"],
            },
        ],
        "models": [
            {
                "canonical": "zephyr",
                "providers": {
                    "primary_later": "a/zephyr-free",
                    "backup_first": "b/zephyr-free",
                },
            }
        ],
        "limits": {},
    }
    scripted = _Scripted()
    scripted.add(429, {"error": {"message": "rate limited"}})
    scripted.add(429, {"error": {"message": "rate limited"}})
    scripted.add(200, _reply())
    client = _client(
        scripted,
        models,
        monkeypatch,
        {
            "T15_KEY_A1": "sk-a1",
            "T15_KEY_A2": "sk-a2",
            "T15_KEY_B1": "sk-b1",
            "T15_KEY_B2": "sk-b2",
        },
    )
    resp = client.generate(_MESSAGES, "zephyr")
    # Both primary keys 429 (primary_later is exhausted) before the
    # backup provider serves the fallback.
    assert scripted.auths == [
        "Bearer sk-a1",
        "Bearer sk-a2",
        "Bearer sk-b1",
    ]
    assert resp.api_url == _B_URL
    assert resp.model_name == "zephyr"


def test_zero_key_provider_warns_and_error_names_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: a provider whose env vars are all unset failing
    # with a generic "last failure: unknown" — construction must warn
    # naming the env-var NAMES (never values), and the final error
    # must say no keys were resolved, not pretend a request failed.
    scripted = _Scripted()
    with pytest.warns(UserWarning) as caught:
        client = LLMClient(
            _models_ab(),
            transport=httpx.MockTransport(scripted.handler),
            sleep=scripted,
        )
    messages = [str(warning.message) for warning in caught]
    assert any("prov_a" in m and "T15_KEY_A1" in m for m in messages)
    assert any("prov_b" in m and "T15_KEY_B2" in m for m in messages)
    assert not any("sk-" in m for m in messages)  # names, never values
    with pytest.raises(LLMError, match="no API keys resolved") as excinfo:
        client.generate(_MESSAGES, "zephyr")
    message = str(excinfo.value)
    assert "prov_a" in message and "prov_b" in message
    assert "T15_KEY_B2" in message  # unresolved env names, no values
    assert scripted.auths == []  # no request was ever attempted


def test_rate_limited_keys_reopen_on_next_generate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: a 429-exhausted key staying benched forever —
    # per-minute windows reopen, so the next generate() call must
    # serve the same key again.
    scripted = _Scripted()
    scripted.add(429, {"error": {"message": "rate limited"}})
    scripted.add(429, {"error": {"message": "rate limited"}})
    scripted.add(429, {"error": {"message": "rate limited"}})
    scripted.add(200, _reply())
    client = _client(
        scripted,
        _models_a(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    with pytest.raises(LLMError):
        client.generate(_MESSAGES, "zephyr")  # reset retry 429s too
    resp = client.generate(_MESSAGES, "zephyr")  # window reopened
    assert resp.text == "hi"
    assert scripted.auths == [
        "Bearer sk-a1",
        "Bearer sk-a2",
        "Bearer sk-a1",  # reset retry
        "Bearer sk-a2",  # gen2: pointer resumes, both keys reopened
    ]


def test_auth_exhausted_keys_never_rejoin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: the reopen sweeping auth-rejected keys back in —
    # a 401'd key must stay out across generate() calls, and the
    # error must say the keys are exhausted (not "unknown").
    scripted = _Scripted()
    scripted.add(401, {"error": {"message": "bad key"}})
    client = _client(
        scripted,
        _models_a(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": None},  # one key only
    )
    with pytest.raises(LLMError, match="key rejected \\(HTTP 401\\)"):
        client.generate(_MESSAGES, "zephyr")
    with pytest.raises(
        LLMError,
        match=r"all keys of provider\(s\) 'prov_a' are exhausted",
    ):
        client.generate(_MESSAGES, "zephyr")
    assert scripted.auths == ["Bearer sk-a1"]  # no further requests


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


def test_keyring_reset_reopens_only_rate_limited() -> None:
    # Discriminates: reset() sweeping permanently retired keys back
    # in — rate windows reopen, auth rejections never do.
    ring = KeyRing(["k1", "k2"])
    ring.mark_exhausted("k1")  # rate-limited (default)
    ring.mark_exhausted("k2", permanent=True)  # auth-rejected
    assert ring.next_key() is None
    ring.reset()
    assert ring.next_key() == "k1"  # rate-limited reopened
    ring.mark_exhausted("k1")  # bench it again so only k2 remains
    assert ring.next_key() is None  # k2 was permanent — still out


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


def test_sanity_check_usage_empty_text_with_reported_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Discriminates: the empty-reply boundary — ANY reported output
    # tokens with zero visible text is the hidden-reasoning
    # signature, not just large counts.
    scripted = _Scripted()
    usage = {"prompt_tokens": 10, "completion_tokens": 3}
    scripted.add(200, _reply(content="", usage=usage))
    client = _client(
        scripted,
        _models_ab(),
        monkeypatch,
        {"T15_KEY_A1": "sk-a1", "T15_KEY_A2": "sk-a2"},
    )
    resp = client.generate(_MESSAGES, "zephyr")
    note = sanity_check_usage(resp.text, resp)
    assert note is not None
    assert "infinite" in note


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
