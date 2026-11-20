# Agent Smith — Worker Protocol & A/B Interface Contract

Status: **Ratified** (v1.1) — approved by both members in the PR #2 review, merged 2026-11-16.
Lineage: reconciles two drafts — the T04 worker-protocol draft (this
branch) and the A/B Working Agreement proposal (`docs/ab-interface-protocol`,
commit `7a7f8a7`). Naming conventions, the typed shared contracts and
the task-deadline model are adopted from the A/B proposal; wire
semantics core (status derivation, stdout replacement, stale discard,
tee streaming) comes from the T04 draft. Both drafts credited; the
deltas are labeled inline.

Consumers: A side (agent loop, MCP client, CLIs) and B side (sandbox
worker/process, tool servers). This file is the single interface
contract; changes after ratification require architect sign-off per
docs/planning/TEAM_WORKFLOW.md §2.

## 1. Shared typed contracts (neutral module)

Both halves import these from ONE neutral module (proposed:
`contracts.py` at the repository root — `models.py` is the frozen
grader contract and must not grow project types). Typed models and
validated JSON boundaries, not unchecked dictionaries:

```python
ToolInfo(name: str, python_name: str, description: str,
         input_schema: JsonObject, parameter_order: tuple[str, ...])
ToolArguments(values: JsonObject)
ToolReply(is_error: bool, text: str)
ToolDispatcher.call(name: str, arguments: ToolArguments,
                    *, deadline: float) -> ToolReply
```

`JsonObject` = string keys, recursively JSON-safe values.

- `python_name` is **derived, never trusted from the wire**: the
  neutral module provides `derive_python_name(name)` implementing the
  identifier rules (`-`/`.`→`_`, leading digit → `_`, degenerate →
  `tool_` prefix) and the collision rule (a tool literally named
  `final_answer` becomes `mcp_final_answer` — the sandbox owns that
  name). Both halves call the same function; see §4 for why the
  worker recomputes it rather than receiving it.
- Argument validation against `input_schema` happens at the
  **dispatch boundary** (parent side), not in the worker.
- `[TOOL ERROR]` is prefixed **exactly once** — by the parent when
  formatting a failed `ToolReply`; worker stubs surface that text via
  an exception; no layer adds a second prefix.

## 2. Sandbox public API — B provides, A calls

```python
class SandboxProcess:
    def __init__(self, cfg, tools, tool_dispatch): ...
    def start(self) -> None            # returns once the worker is ready
    def execute(self, code: str, *, task_deadline: float) -> ExecutionResult
    def shutdown(self) -> None         # bounded; safe to repeat

@dataclass
class ExecutionResult:
    status: str        # ok | error | final | timeout | killed
                       # | keyboard_interrupt | system_exit
    stdout: str        # actual output; partial output on failure
    error: str | None
    final_answer: str | None
```

Required behavior (both drafts agree unless noted):

- Variables persist across entries after normal execution and
  ordinary Python errors.
- Timeout or worker death terminates and reaps the worker (process
  group); the next entry runs on a fresh worker and the result
  reports "variables were reset". External effects (tool edits,
  container state) are NOT rolled back and interrupted code is never
  automatically replayed.
- `final_answer()` is a sandbox built-in, never an MCP tool. Its
  value is captured via a slot that survives user-side
  `except BaseException`. **First answer per entry wins** (A/B
  proposal; adopted over the T04 last-write-wins — simpler
  invariant). `final` is reported whenever it was called, even if
  user code caught the signal.
- `KeyboardInterrupt` / `SystemExit` propagate to the parent caller;
  `SystemExit` re-raises with its exit code (wire carries it, §4).
- Ordinary execution errors come back in `ExecutionResult`;
  lifecycle/protocol failures (worker won't start, channel corrupt)
  raise a typed `SandboxError` with partial output attached — A
  handles them and writes an honest failed solution.
- Output is capped (10 000 chars) with truncation disclosed inside
  the cap.

## 3. Deadline model

Single enforcement of the hard stop (A/B proposal; adopted):

- A passes `task_deadline` — an absolute `time.monotonic()` value,
  already minus A's output/cleanup reserve. B treats it as the outer
  bound: reject expired deadlines before executing; expiry mid-entry
  returns `timeout` with a task-deadline diagnostic, and **A ends the
  task** (no further iterations — unlike a sandbox timeout, which
  permits another iteration).
- Internally B still enforces the per-exec limit
  (`cfg.max_execution_time_seconds` + 5 s grace): the guard is
  suspended while a tool call is in flight and extended by the
  call's measured duration — tool time is not sandbox time
  (ADR-0002), but ALL elapsed time counts toward A's task budget.
- Tool calls have finite per-call timeouts; B stops processes it
  owns. Deferred restart is allowed (recreate the worker on the next
  `execute`).
- Discriminating test (binding): the slow-tool test must sleep
  LONGER than timeout + grace, so it fails if the deadline extension
  is ever broken (a shorter tool passes on defective code — known
  failure mode).

## 4. Wire protocol v1.1 (worker ↔ parent)

Framing: JSON Lines on the worker's stdin/stdout — one UTF-8 JSON
object per line, `"v": 1`. The protocol channel carries protocol
only (worker's own logs → stderr). `exec_id` never repeats during a
`SandboxProcess` lifetime, including across restarts; `call_id` is
unique within an execution. The parent rejects mismatched tool
replies and discards stale events; missing/invalid fields fail
explicitly; only validated current messages change state.

### Messages

| type | Direction | Fields |
|---|---|---|
| `init` | P→W | `config` (SandboxConfig dict; `{}` = defaults), `tools` (see below) |
| `ready` | W→P | — |
| `exec` | P→W | `exec_id`, `code` |
| `tool_call` | W→P | `exec_id`, `call_id`, `name`, `arguments` |
| `tool_result` | P→W | `exec_id`, `call_id`, `is_error`, `text` |
| `stdout` | W→P | `exec_id`, `text` (streamed user output) |
| `result` | W→P | `exec_id`, `status`, `stdout`, `error`, `final_answer`, `exit_code` (system_exit only) |
| `shutdown` | P→W | — |

### init.tools — minimal wire projection (T04 position; retained)

The wire carries only what the worker needs to build stubs:

```json
{"name": "run_tests", "description": "…", "parameter_order": ["code", "test_list", "test_imports"]}
```

`python_name` is NOT sent: the worker derives stub names itself via
`derive_python_name` (§1). If stub names were parent-supplied, a
discovery bug or a hostile/unknown MCP server could name a stub
`final_answer` and shadow the sandbox's own construct — stub naming
is worker-side policy in exactly one place. The full `ToolInfo`
(including `input_schema`) lives in the neutral module and is used
in-process by the parent and dispatch boundary; it is not
serialized to the worker. *(Only deviation from the A/B proposal;
its own §3 "B installs worker stubs from ToolInfo" is satisfied —
the projection is pinned to a layer.)*

### Result semantics (T04 core; retained)

- Wire statuses are ONLY `ok | error | final | keyboard_interrupt |
  system_exit`. The parent derives `timeout` (deadline expired) and
  `killed` (worker died) — a dead worker sends nothing.
- `result.stdout` REPLACES the streamed accumulation — never
  concatenate both copies. On timeout/death without a result, the
  parent retains accumulated streamed output up to the cap.
- `final` is set whenever `final_answer()` was called (slot; first
  answer wins), even if user code caught the signal.
- `system_exit` carries `exit_code`; `keyboard_interrupt` uses the
  same fields without it. The parent re-raises both.
- After a kill the worker is assumed dead; the parent restarts it
  (possibly deferred to the next `execute`).
- EOF or malformed lines during execution → `SandboxError` with
  partial output attached. Unexpected death without corruption →
  `killed`.

### Example — init and one tool call

```json
{"v":1,"type":"init","config":{},"tools":[{"name":"run_tests","description":"Run candidate code against tests","parameter_order":["code","test_list","test_imports"]}]}
{"v":1,"type":"ready"}
{"v":1,"type":"exec","exec_id":1,"code":"print(run_tests(code='def f(): return 1', test_list=['assert f() == 1']))"}
{"v":1,"type":"tool_call","exec_id":1,"call_id":1,"name":"run_tests","arguments":{"code":"def f(): return 1","test_list":["assert f() == 1"]}}
{"v":1,"type":"tool_result","exec_id":1,"call_id":1,"is_error":false,"text":"{\"success\":true,\"output\":\"\"}"}
{"v":1,"type":"stdout","exec_id":1,"text":"{\"success\":true,\"output\":\"\"}\n"}
{"v":1,"type":"result","exec_id":1,"status":"ok","stdout":"{\"success\":true,\"output\":\"\"}\n","error":null,"final_answer":null}
```

### Example — terminal results

```json
{"v":1,"type":"result","exec_id":2,"status":"error","stdout":"","error":"NameError: name 'x' is not defined","final_answer":null}
{"v":1,"type":"result","exec_id":3,"status":"final","stdout":"","error":null,"final_answer":"def f(): return 1"}
{"v":1,"type":"result","exec_id":4,"status":"system_exit","stdout":"","error":null,"final_answer":null,"exit_code":0}
{"v":1,"type":"shutdown"}
```

## 5. Boundary policies

- **MCP boundary:** A is the client (discovery, manual generation,
  alias mapping, dispatcher); B provides `mcp_tools_mbpp.py` and
  `mcp_tools_swebench.py`, independently testable without the agent
  loop, stdio + streamable HTTP, unknown-server compatible.
  `run_tests` (MBPP) returns MCP text containing
  `{"success": bool, "output": str}` — a failing candidate is a
  successful tool call with `success:false`; only service/configuration
  failures are tool errors.
- **SWE-bench tools:** the nine tools with the plan's pinned output
  formats, identical across local/Docker modes; B owns TESTBED_PATH
  confinement, AGENT_CONTAINER selection, EVAL_SCRIPT_PATH.
- **get_patch:** returns a COMPLETE patch or an explicit error —
  never a truncated success value (A/B proposal; adopted. A silently
  truncated patch is an unappliable submission). Threshold number:
  open question §6.
- **Guest feeding:** tool values delivered into guest scope are
  uncapped on the dispatch path (tools bound their own payload caps;
  the worker caps what the guest prints). Observation caps apply
  when formatting for the LLM.
- **Credentials:** provider keys stay with the LLM client; child
  environments are filtered (no `*API_KEY*` forwarding to workers,
  tools or containers); never logged.
- **Cleanup:** A's CLI coordinates; B provides bounded worker and
  container cleanup. Reserve time for `solution.json`, preserve the
  original error, and never rely on `finally` or signal handlers
  after SIGKILL.

## 6. Open questions for the joint review

- [ ] Names → roles confirmation and the T10/T11 → B transfer
      (with ADR; separate from this document).
- [ ] T27 split: B leads unknown-server testing, A fixes client
      findings.
- [ ] Wave re-sequencing: B's serial chain grows with T10/T11 —
      revisit the parallel plan.
- [ ] `get_patch` oversize threshold; confirm the 10 000-char
      output cap.
- [ ] Startup/shutdown timeout values (proposal: ready ≤ 30 s,
      shutdown ≤ 3 s + kill).
- [ ] Docker lifecycle API (needed before T24; not for the first
      MBPP integration).
- [ ] First joint gate: one real MBPP task end to end
      (CLI → LLM → sandbox → MCP tool), trace and metrics checked,
      `solution.json` passing the moulinette.
