# Sandbox worker protocol

Status: seam contract v1 (T04). Changes require architect sign-off
per docs/planning/TEAM_WORKFLOW.md §2. Both members review this file.

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
  — exactly one, first line after spawn. tools is the ToolInfo list
  (params in server order, from list_tools); empty when no server is
  connected (final_answer is always injected separately — it is
  never an MCP tool).
- exec: {"type": "exec", "id": <int, monotonic from 1>, "code": str}
- tool_result: {"type": "tool_result", "call": <int, matching the
  tool_call>, "text": str} — text is the ALREADY-FORMATTED
  observation (the parent applies format_tool_result, including any
  "[TOOL ERROR]" prefix); the worker-side stub returns it verbatim to
  user code. A failed tool call is a normal string return carrying
  the error text — it never aborts the exec.
- shutdown: {"type": "shutdown"} — after this the worker exits 0.

### Worker → Parent

- ready: {"type": "ready"} — once: limits set, import gate
  installed, stubs built, restrictions in place. No exec is
  processed before it.
- stdout: {"type": "stdout", "id": <exec id>, "chunk": str} — user
  code's print() output, streamed in chunks by the tee (§4).
- tool_call: {"type": "tool_call", "call": <int, monotonic from 1
  per worker process>, "id": <exec id>, "name": str, "args":
  {str: Any}} — emitted by the stub when user code invokes an MCP
  tool.
- result: {"type": "result", "id": <exec id>, "status": <one of
  "ok" | "error" | "final" | "keyboard_interrupt" |
  "system_exit">, "stdout": <str: full accumulated user output for
  this exec>, "error": <str | null: traceback/error text when
  status is "error">, "final_answer": <str | null>}

## 3. Statuses and their derivation

ok / error / final / keyboard_interrupt / system_exit travel on the
wire; the PARENT derives two more, never sent by the worker:

- timeout — the parent's deadline expired (§5) and the worker was
  killed; result carries the partial accumulated stdout received so
  far.
- killed — the worker died without a result (crash, os._exit, OOM at
  the OS level); partial stdout likewise.

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
"[truncated N chars]" note. THE PROTOCOL CHANNEL ITSELF never
carries user output except inside stdout events and result fields.

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

## 6. final_answer semantics

final_answer(answer) is injected by the worker into the execution
namespace (never an MCP tool). It writes a module-level slot FIRST,
then raises FinalAnswerSignal(BaseException). After user code
finishes — regardless of how: normal return, caught exception,
uncaught exception — the worker checks the slot: if set, the result
status is "final" and final_answer carries the slot's value, EVEN IF
user code caught the signal or another exception followed it. Status
"final" outranks "error" for the same exec.

## 7. Flow control

User code raising KeyboardInterrupt or SystemExit produces the
respective wire statuses; the PARENT re-raises them into the agent
loop (they control shutdown, they are never swallowed). The worker
never sends anything on stdout that is not a valid protocol message;
the parent treats an unparsable line as worker death (kill +
restart, status killed) — fail-closed, no guesswork parsing.

## 8. In-process helper (tests and REPL)

sandbox/worker.py additionally exposes run_code(code, cfg, tools) as
a plain in-process function running the SAME pipeline as the
protocol path — parse → scan → rewrite → compile → exec under the
same restrictions — used by tests and the REPL. It is NOT the
protocol path: anything protocol-specific (tee streaming, message
ids) lives only in the protocol main loop.

## 9. Message sequence (example)

One exec with a tool call, annotated. `P` lines go parent → worker
stdin, `W` lines worker → parent stdout.

    P: {"type": "init", "config": {...}, "tools":
        [{"name": "run_tests", "description": "...",
          "params": ["code", "test_list"]}]}     exactly once
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
