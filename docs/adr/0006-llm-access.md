# ADR-0006: LLM access via one OpenAI-compatible client
- Status: Accepted — ratified via PR #4 review comment (both members), 2026-11-23
- Date: 2026-11-20
- Deciders: A + B (pre-aligned in PROJECT_PLAN §2, committed 95c6169)

## Context

T15–T20 need chat completions from free-tier providers whose keys
throttle per minute and whose quotas burn fast. Providers differ in
endpoint, key environment variables, and model naming. The agent
loop (T18) must not know any of it, and the grader warns when one
run logs multiple model names — so a fallback switch may change
endpoints, never the reported model name.

## Options considered

(a) One provider SDK per provider — N dependencies and N failure
    modes; the free-tier providers we target have no synchronous
    Python 3.10 SDK.

(b) Orchestration libraries (LangChain and friends) — banned by the
    subject; the graded code must be ours.

(c) One OpenAI-compatible HTTP client behind our interface, with a
    canonical-name → per-provider alias map and multi-key rotation.

## Decision

Option (c), implemented in T15 as `llm/client.py`. Providers are
declared in `models_json` (endpoint, ordered API-key env-var names,
canonical→alias map); the client rotates keys within a provider,
falls through to the next provider serving the same canonical
model, and always reports `model_name` as the canonical name.

## Consequences

- Canonical-name invariant: fallback changes `api_url`, never
  `model_name`.
- Error ladder: 429 → rotate to the next key immediately (rotation
  is the backoff); 401/402/403 → the key is exhausted permanently;
  ≥500 and transport errors → exponential backoff (1 s base) on the
  same key, with a five-attempt cap that yields the key back to the
  ring; other 4xx → `LLMError` with the provider's message.
- When the last provider's keys exhaust by rate limiting, the ring
  resets once, waits one backoff, and retries once — per-minute
  windows reopen; after that, exhaustion is final.
- Pacing: ≥4 s between consecutive requests, so a 10-step task does
  not throttle itself; the read timeout is 110 s (connect 10 s) —
  the httpx 5 s default starves slow reasoning models.
- Honest usage: counters come from the top-level `prompt_tokens`/
  `completion_tokens` only (detail fields are subsets — never added
  on top); missing usage is estimated at chars/4 and flagged
  `estimated` in `usage_raw`.
- Keys exist in code only as env-var NAMES; values are resolved at
  construction (`.env` parsed with the stdlib, real environment
  wins) and are never logged or rendered in errors. A provider with
  zero resolved keys warns at construction (naming the env-var
  names) and the exhaustion error says so, instead of a generic
  request-failure message.

- Ring reopen semantics: rate windows are per-minute, so every
  `generate()` call reopens rate-limited keys first — a 429 (and a
  capped 5xx streak, which yields the key back as rate-limited)
  only benches a key for the current call. Auth rejections
  (401/402/403) retire the key permanently; no reset ever reopens
  it.

- Partial usage: a count that is absent (or `None`) while the
  block itself is non-empty is estimated at chars/4 and listed in
  `usage_raw["estimated_fields"]`; a present count — including a
  literal 0 — is reported verbatim, so genuine under-reporting
  stays visible to `sanity_check_usage`. An unparseable count
  value raises `LLMError` naming the provider and the field,
  matching the malformed-response handling.

- Deadline contract: `generate(..., deadline=...)` takes an
  absolute `time.monotonic()` timestamp (the caller computes the
  task deadline once per task and passes it to every call). While
  time remains, waits and each attempt's HTTP timeout are capped to
  the remainder; at expiry no new attempt starts and the call
  raises `LLMDeadlineExceeded` (an `LLMError`) — budget death is
  distinguishable from provider exhaustion. `None` keeps the
  unbounded default behavior.

- Pacing is wall-clock-aware: the client records when each request
  completed and at call entry sleeps only the remainder of the
  interval — a call long after the previous one sleeps nothing.
