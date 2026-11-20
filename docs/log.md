# log

## 2026-11-20 — T15 real-call verification

One real tiny call per canonical model through `LLMClient`
(`messages=[{"role": "user", "content": "Reply with exactly: ok"})`,
`max_tokens=8`, no retries needed anywhere). Provider = first entry
of the canonical's provider chain (fallback never triggered — no
request failed). Prompt "Reply with exactly: ok" plus
`max_tokens=8` makes `finish_reason: length` on reasoning-style
models expected: they spend the whole budget on hidden thinking.

| canonical | provider (alias) | in/out tokens | est. | finish | latency | sanity |
|---|---|---|---|---|---|---|
| qwen3-235b | openrouter (qwen/qwen3-235b-a22b-2507) | 13/2 | no | stop | 0.84 s | ok |
| deepseek-v3 | openrouter (deepseek/deepseek-chat) | 8/2 | no | stop | 0.85 s | ok |
| nemotron-3.5-lightning | openrouter (nvidia/nemotron-3.5-lightning:free) | 21/8 | no | length | 0.57 s | DIVERGENCE: 8 tokens reported, empty visible text (hidden reasoning) |
| qwen3.8-27b | groq (qwen/qwen3.8-27b) | 17/2 | no | stop | 0.10 s | ok |
| gemini-3.5-flash-lite | google (gemini-3.5-flash-lite) | 6/1 | no | stop | 7.05 s | ok |
| gemini-3.5-flash | google (gemini-3.5-flash) | 6/0 | no | length | 8.03 s | ok — 0 reported, 0 visible; budget consumed server-side, watch at real budgets |
| gemma-4-31b-it | nvidia (google/gemma-4-31b-it) | 18/2 | no | stop | 71.4 s | ok |

Notes:

- Every response's `model_name` stayed CANONICAL; no key material
  appeared anywhere (keys travel in Authorization headers only).
- No usage estimate was needed: all seven providers reported
  top-level token counts.
- `nemotron-3.5-lightning` tripped `sanity_check_usage` exactly as
  designed (8 output tokens, empty reply — hidden reasoning); the
  note is recorded here per the T15 contract.
- gemma on nvidia was slow (71 s, well under the 110 s read
  timeout — keep an eye on it for T18 budgeting).
- Cohere `north-mini-code:free` and `mistral-small` are absent from
  this run: the planned OpenRouter id is not in the live catalog
  (nearest: cohere/command-a family) and no usable MISTRAL key is
  set. No substitutions invented; revisit when the owner updates
  the catalog or adds the key.

### 2026-11-20 — gemma free backup + per-model ordering

Owner decisions: per-model provider order in `models.json` is now
the contract (first listed = primary, rest = fallbacks; pinned by
`test_model_entry_order_sets_primary_and_backup`), and
`gemma-4-31b-it` gained `openrouter (google/gemma-4-31b-it:free)`
as its SECOND provider — nvidia stays primary. Verification of the
two new `:free` aliases (tiny calls, same recipe) hit the shared
quota pool:

| canonical | provider (alias) | in/out tokens | est. | finish | latency | sanity |
|---|---|---|---|---|---|---|
| particle-1 | openrouter (particle-ai/particle-1:free) | — | — | — | — | FAILED: HTTP 429 "Provider returned error" (free pool) — NOT added to models.json pending owner re-verification |
| gemma-4-31b-it | openrouter (google/gemma-4-31b-it:free) | — | — | — | — | FAILED: HTTP 429 "Provider returned error" (free pool) — backup added anyway per owner decision |

Caveat: OpenRouter's `:free` models share one daily quota pool per
key, so `gemma-4-31b-it:free` is backup-only and `nemotron-3.5-lightning:free`
(and a future `particle-1:free`) draw from that same daily quota —
a dry pool takes all of them down together, which is exactly why
the free variant must never be the primary path. The gemma `:free`
id itself is live-catalog-verified (it appears in OpenRouter's
`:free` listing); the earlier nvidia primary call succeeded (71 s).
Re-run the two tiny calls when the pool reopens to complete the
verification rows.
