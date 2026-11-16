# Sandbox worker protocol

Status: working draft (T04) — pending joint review alongside the
A/B interface proposal.

## 1. Transport and framing

The worker is launched as [sys.executable, "-m", "sandbox.worker"] in
its own process group (start_new_session=True); the parent talks to
it over the worker's stdin/stdout with ONE JSON object per line
(UTF-8, no pretty-printing, no embedded newlines — JSON escapes
them). The worker's stderr is DEVNULL on the parent side: the
protocol channel must stay pure (the worker's own diagnostics go to
ITS stderr and are deliberately discarded by the parent).

## 2. Messages

### Parent → Worker

- init: {"type": "init", "config": <SandboxConfig as dict>,
  "tools": [{"name": str, "description": str, "params": [str, ...]}]}
  — exactly one per worker process, first line after spawn. tools is
  the ToolInfo list (params in server order, from list_tools); empty
  when no server is connected (final_answer is always injected
  separately — it is never an MCP tool).

  The `name` in `tools[]` is the RAW server name, exactly as the MCP
  server reports it. The WORKER builds the namespace stubs from this
  list, applying the naming rules (invalid identifier characters
  `-`/`.` rewritten to `_`, leading digit prefixed `_`), and renames
  a server tool literally named `final_answer` to `mcp_final_answer`
  — the sandbox owns that name; the injected `final_answer` always
  wins. `tool_call.name` on the wire ALWAYS carries the raw server
  name, so the parent dispatches to the server unchanged and no
  back-map exists.

- exec: {"type": "exec", "id": <int, monotonic from 1>, "code": str}
- tool_result: {"type": "tool_result", "call": <int, matching the
  tool_call>, "text": str} — text is the ALREADY-FORMATTED
  observation (the parent applies format_tool_result, including any
  "[TOOL ERROR]" prefix); the worker-side stub returns it verbatim to
  user code. A failed tool call is a normal string return carrying
  the error text — it never aborts the exec.
- shutdown: {"type": "shutdown"} — after this the worker exits 0.

### Worker → Parent

- ready: {"type": "ready"} — sent once per worker process, after
  limits are set, the import gate installed, stubs built and the
  restrictions in place. The parent waits for `ready` after every
  (re)start before sending any exec; no exec is processed before
  it.
- stdout: {"type": "stdout", "id": <exec id>, "chunk": str} — user
  code's print() output, streamed in chunks by the tee (§4).
- tool_call: {"type": "tool_call", "call": <int, monotonic from 1
  per worker process>, "id": <exec id>, "name": str, "args":
  {str: Any}} — emitted by the stub when user code invokes an MCP
  tool. If the stub cannot JSON-serialize an argument, that is a
  LOCAL TypeError raised into user code (naming the argument) — no
  tool_call message is sent; the exec continues under normal
  exception semantics.
- result: {"type": "result", "id": <exec id>, "status": <one of
  "ok" | "error" | "final" | "keyboard_interrupt" |
  "system_exit">, "stdout": <str: full accumulated user output for
  this exec>, "error": <str | null: the standard Python traceback
  text, as formatted by traceback.format_exception, when status is
  "error">, "final_answer": <str | null>}

## 3. Statuses and their derivation

ok / error / final / keyboard_interrupt / system_exit travel on the
wire; the PARENT derives two more, never sent by the worker:

- timeout — the parent's deadline expired (§5) and the worker was
  killed; result carries the partial accumulated stdout received so
  far.
- killed — the worker died without a result (crash, os._exit, OOM at
  the OS level); partial stdout likewise.

The parent accumulates stdout events per exec ONLY to recover
partial output after timeout/killed; on a normal `result` message
the parent uses `result.stdout` and DISCARDS its own accumulation
(the two would double-count).

After a timeout or killed result the worker process is assumed DEAD
(the parent never reuses it): a fresh worker is started (fresh exec
ids continue the parent's own monotonic counter; variable state is
lost — the loop's "variables were reset" feedback exists for this).
Messages arriving with an exec id that is not the current one are
STALE (e.g. queued output from a replaced worker): the parent drops
them silently.

## 4. Output tee

Inside an exec the worker replaces sys.stdout with a tee that
(a) accumulates the full text for the result message and (b) emits a
stdout event per chunk — so partial output survives a kill. The
worker caps what it reports at 10,000 chars per exec, appending a
"[truncated N chars]" note; the cap counts the note itself (the
note fits inside the cap, mirroring the tool-result cap rule), and
the note appears in `result.stdout` — and in the final stdout
event, which the tee emits capped the same way. THE PROTOCOL
CHANNEL ITSELF never carries user output except inside stdout
events and result fields.

## 5. Time and the tool-time exemption

Tool-call time is NOT sandbox time. Per exec the parent computes
base_deadline = now + config.max_execution_time_seconds + grace
(5 s). While a tool_call is in flight (sent, no tool_result yet) the
parent waits with NO timeout — the deadline is suspended; when the
tool_result arrives the parent ADDS the call's measured wall
duration to the deadline. On expiry: SIGTERM to the worker's process
group, 2 s grace, then SIGKILL; report timeout with partial stdout;
restart the worker. A consequence, stated as a test requirement
(T08): a tool that sleeps longer than timeout + grace must still
return its result with status ok, while pure `while True: pass`
code must still time out.

Measurement endpoints: the call's duration is measured from receipt
of `tool_call` to send of `tool_result` — the only interval the
parent can observe. The worker is single-threaded: at most one
tool_call is in flight at any moment. INVARIANT: every `tool_call`
receives exactly one `tool_result`, always — during flight the
parent waits with NO timeout, so a lost reply would hang the agent
forever; the parent's dispatch callback never raises and always
answers (its errors become `[TOOL ERROR]`-prefixed text).

## 6. final_answer semantics

final_answer(answer) is injected by the worker into the execution
namespace (never an MCP tool). It writes a module-level slot FIRST,
then raises FinalAnswerSignal(BaseException). After user code
finishes — regardless of how: normal return, caught exception,
uncaught exception — the worker checks the slot: if set, the result
status is "final" and final_answer carries the slot's value, EVEN IF
user code caught the signal or another exception followed it.

The slot is RESET at the start of every exec: a `final` status and
its answer belong to exactly one exec and can never leak into the
next one. (Consequence for the agent loop: after a final-check
rejection the next exec starts with a clean slot — a stale answer
cannot be re-reported.) Within one exec a second `final_answer`
call overwrites the slot (last write wins).

`final` outranks `error` AND `keyboard_interrupt`/`system_exit` for
the exec's status: if the slot is set, the worker reports `final`
and does NOT re-raise the flow-control exception to the parent — a
called final_answer means the task is done; the parent re-raises
KeyboardInterrupt/SystemExit only when NO final answer was recorded.

## 7. Flow control

User code raising KeyboardInterrupt or SystemExit produces the
respective wire statuses; the PARENT re-raises them into the agent
loop when no final answer was recorded (§6 — a recorded final wins
and is not interrupted). They control shutdown; when re-raised they
are never swallowed. The exit code of SystemExit is not carried on
the wire (the status is what matters; the parent re-raises a bare
SystemExit). The worker never sends anything on stdout that is not
a valid protocol message; the parent treats an unparsable line as
worker death (kill + restart, status killed) — fail-closed, no
guesswork parsing.

## 8. In-process helper (tests and REPL)

sandbox/worker.py additionally exposes run_code(code, cfg, tools) as
a plain in-process function running the SAME pipeline as the
protocol path — parse → scan → rewrite → fix_missing_locations →
compile → exec under the same restrictions (fix_missing_locations
is load-bearing: the rewrite creates nodes without location info
and compile() rejects them without it). run_code is the IN-PROCESS
helper for TESTS only: same restriction pipeline, no timeout/kill
semantics (a test that needs kill semantics uses the protocol path
via SandboxProcess). The REPL (T09) does NOT use run_code — it
drives a real SandboxProcess so per-entry timeout, memory limits
and restart semantics apply to human-typed code exactly as to agent
code. Anything protocol-specific (tee streaming, message ids) lives
only in the protocol main loop.

## 9. Message sequence (example)

One exec with a tool call, annotated. `P` lines go parent → worker
stdin, `W` lines worker → parent stdout.

    P: {"type": "init", "config": {...}, "tools":
        [{"name": "run_tests", "description": "...",
          "params": ["code", "test_list"]}]}     exactly once, per
                                                 process
    W: {"type": "ready"}                         worker is armed
    P: {"type": "exec", "id": 7, "code": "...user code..."}
    W: {"type": "stdout", "id": 7, "chunk": "running tests\n"}
                                                 tee streams early
    W: {"type": "tool_call", "call": 1, "id": 7,
        "name": "run_tests", "args": {"code": "...",
        "test_list": ["assert f(1) == 2"]}}      stub forwards
    P: {"type": "tool_result", "call": 1,
        "text": "{'success': True, ...}"}        pre-formatted;
        [deadline suspended during this call, then extended by the
         call's measured duration — §5]
    W: {"type": "stdout", "id": 7, "chunk": "tests passed\n"}
    W: {"type": "result", "id": 7, "status": "ok",
        "stdout": "running tests\ntests passed\n", "error": null,
        "final_answer": null}                    end of the exec

A later exec reuses the same worker with the next exec id (8, 9, …);
after a timeout/killed the next exec id still advances, but it runs
on a fresh worker with empty variable state (§3).

Caught-final case (§6): the slot wins even when user code swallows
the signal, and the next exec starts with a clean slot.

    P: {"type": "exec", "id": 12, "code":
        "try:\n    final_answer(\"v1\")\nexcept BaseException:\n    pass"}
        (user code catches the FinalAnswerSignal — no traceback)
    W: {"type": "result", "id": 12, "status": "final",
        "stdout": "", "error": null, "final_answer": "v1"}
        [the next exec (id 13) starts with a CLEAN slot — a stale
         answer cannot be re-reported]
