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
