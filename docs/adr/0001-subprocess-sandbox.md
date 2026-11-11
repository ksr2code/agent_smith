# ADR-0001: Restricted worker subprocess as the sandbox isolation
# unit
- Status: Accepted
- Date: 2026-11-11
- Deciders: A + B (pre-aligned in PROJECT_PLAN §2, committed 95c6169)

## Context

LLM-generated code must run with import, filesystem, network and
builtin restrictions, a wall-clock timeout, and a memory cap — and
it must not take the agent down when it crashes or hangs. Python-
level rules are required regardless of the isolation unit (subject
constraint: stdlib-only enforcement, no RestrictedPython), so the
unit must accept in-process policy layers AND be killable from
outside.

## Options considered

(a) In-process exec with patched builtins — cannot be killed
    reliably on timeout (a runaway loop holds the GIL); RLIMIT_AS
    would hit the agent itself; a crash takes the loop down.

(b) Docker per run — heavy per-step latency (the loop execs many
    steps per task), and the Python-level rules are still required
    inside the container.

(c) A restricted worker subprocess in its own process group —
    killable via SIGTERM/SIGKILL, own rlimits, crash-isolated, cheap
    to restart; IPC is one JSON-lines channel (docs/protocol.md).

## Decision

Option (c). The worker is `[sys.executable, "-m",
"sandbox.worker"]`, started with `start_new_session=True`; the
parent owns timeouts by killing the process group (SIGTERM → 2 s →
SIGKILL) and replaces the worker after any timeout or death.

## Consequences

- The protocol channel (docs/protocol.md) is a seam owned by the
  architect; both sides are implemented against it (T07 worker, T08
  parent).
- After timeout/killed the worker is replaced and variable state is
  lost — by design; the loop's "variables were reset" feedback
  exists for exactly this.
- Memory and kill semantics are authoritative only on Linux
  (`make sandbox-tests-linux`); macOS does not enforce RLIMIT_AS.
- stdin/stdout purity rules follow from the single channel: user
  output only inside protocol messages; worker diagnostics go to the
  worker's stderr (DEVNULL on the parent side).
