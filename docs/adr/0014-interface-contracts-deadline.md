# ADR-0014: Typed interface contracts and the task-deadline model

- Status: Proposed (pending joint ratification via PR review)
- Date: 2026-11-16
- Deciders: A + B (pending joint ratification)

## Context

Two protocol drafts collided on docs/protocol.md: the T04
worker-protocol draft (written first, wire semantics complete) and
the A/B Working Agreement proposal (docs/ab-interface-protocol,
7a7f8a7 — naming, typed contracts, task-deadline model). Both must
become one contract both members own.

## Options considered

1. T04 draft as-is: minimal field names (`id`, `call`, `args`, `ok`,
   `value`), dict-based tool descriptors, per-exec deadline only.
2. A/B proposal as-is: explicit names (`v`, `exec_id`, `call_id`,
   `arguments`, `is_error`, `text`), typed shared contracts, full
   ToolInfo (incl. `python_name` and `input_schema`) serialized on
   the init wire, absolute task deadline passed into `execute`.
3. Reconciliation: option 2's naming, types and deadline model;
   option 1's wire semantics; init.tools as a MINIMAL wire
   projection with worker-side stub naming.

## Decision

Option 3, as canonicalized in docs/protocol.md v1.1. Rationale for
the one deviation from option 2: if `python_name` arrives on the
wire, a discovery bug or a hostile/unknown MCP server can name a
stub `final_answer` and shadow the sandbox's own construct — stub
naming is worker-side policy, derived via the shared
`derive_python_name`. The full ToolInfo type (with input_schema)
lives in a neutral module used in-process; only
(name, description, parameter_order) is serialized.

## Consequences

- A neutral contracts module (`contracts.py`) is shared by both
  halves; no duplicated models, no circular imports.
- `SandboxProcess.execute(code, *, task_deadline)` becomes the
  single enforcement point of the hard stop; the Budget's reserve
  flows down; per-exec timeout + grace remains the internal
  mechanism, suspended during tool calls and extended by their
  measured duration.
- The slow-tool discriminating test is binding (tool sleeps longer
  than timeout + grace).
- Policies adopted with this ADR: get_patch complete-or-explicit-
  error; first-wins final_answer; `[TOOL ERROR]` prefixed exactly
  once; exit_code carried on system_exit.

## Approval

Ratified when both members approve the reconciling pull request;
statuses in this ADR and docs/protocol.md flip to Accepted/ratified
afterwards.
