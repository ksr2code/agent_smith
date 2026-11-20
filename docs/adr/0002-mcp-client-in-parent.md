# ADR-0002: MCP client in the parent, tool stubs in the worker
- Status: Accepted — ratified via PR #2 review (both members), merged 2026-11-16
- Date: 2026-11-11
- Deciders: A + B (pre-aligned in PROJECT_PLAN §2, committed 95c6169)

## Context

Tools reach the world outside the sandbox — files via TESTBED_PATH,
Docker, test runs — while the worker is restricted to allowlisted
stdlib imports with no network. If the worker owned the MCP client
it would need sockets and asyncio threads inside the restricted
namespace: a standing escape hatch. Tool calls must also stay
observable and time-accounted from the parent (ADR-0007 already
places the MCP SDK session on a dedicated parent thread).

## Options considered

(a) MCP client inside the worker — requires network + asyncio inside
    the restricted process; every allowlist decision becomes a
    security decision.

(b) MCP client in the parent; tool stubs injected into the worker
    that forward over the protocol channel (docs/protocol.md §4).

## Decision

Option (b). The worker receives plain callable stubs built from the
ToolInfo list carried in the init message; a stub call crosses the
wire as tool_call, and the parent's tool_result carries the
ALREADY-FORMATTED observation text (format_tool_result) which the
stub returns verbatim to user code. A server tool literally named
final_answer is renamed on the stub side (mcp_final_answer) — the
sandbox owns that name.

## Consequences

- Tool time is not sandbox time (protocol §3): the deadline is
  suspended while a call is in flight and extended by the call's
  measured duration — otherwise a slow run_tests would murder
  innocent steps.
- The worker never opens a socket; no allowlist entry exists for
  networking.
- Tool errors surface as "[TOOL ERROR]"-prefixed observation
  strings, never as exec aborts; a failed tool call is ordinary
  data.
- The parent's tool dispatch callback never raises; its failures
  are formatted observations like any other result.

## Amendment (2026-11-20)

Protocol v1.1 (ADR-0014) refines two points of this decision; the
architecture (client in the parent, stubs in the worker) is
unchanged:

- The init message carries a MINIMAL projection per tool (name,
  description, parameter_order) — not the full ToolInfo. The worker
  derives stub names itself via `derive_python_name` (protocol §1,
  §4); `python_name` and `input_schema` are never serialized.
- The wire `tool_result` carries typed `is_error`/`text` fields;
  `[TOOL ERROR]` is prefixed exactly once by the parent when
  formatting a failed ToolReply, and the worker stub surfaces that
  text via an exception (protocol §1).
