# Agent Smith — A/B Working Agreement

**Draft for joint review.** Based on the planning documents at
[`ac8bbb5`](https://github.com/ksr2code/agent_smith/tree/ac8bbb5cb849b9f1626130e79fd55bd9b12b6781).
The project subject and evaluation contract take precedence. These interfaces
are proposed, not implemented or accepted yet.

## 1. Ownership and workload

| A — Agent side | B — Systems side | Shared |
|---|---|---|
| LLM client, extraction, prompts, agent loop, budgets, MCP client/manual, task CLIs, solution output | Sandbox/REPL, security, tool servers, Docker lifecycle and Linux verification | Interface decisions, cross-review, benchmark runs, documentation and final checks |

**Main proposal:** move T10 (local SWE-bench tools) and T11 (MBPP test
server) from A to B. B would then own both local and Docker tool implementations.
A still owns client integration and fixes.

**Optional further adjustment:** B leads T27 compatibility testing; A fixes
client issues. Agree this separately from the T10/T11 transfer.

Rough workload comparison from the plan's task sizes:

| Split | A | B |
|---|---:|---:|
| Original plan | 23.25 person-days | 11.25 person-days |
| Move T10/T11 to B | 20.75 | 13.75 |
| Also move T27 testing to B | 19.75 | 14.75 |

Method: S = 0.5 day, M = 1 day, L = 2 days; shared tasks split equally,
including A+S. These are relative estimates, not delivery promises. They exclude
extra coordination/review and may substantially underestimate security rework.
Linux work within T28 and shared delivery work are not separately re-estimated.

## 2. Sandbox API — B provides, A calls

| Interface | Contract |
|---|---|
| `SandboxProcess(cfg, tools, tool_dispatch)` | Receives typed config, discovered tool descriptors and A's dispatcher |
| `start() -> None` | Returns once the worker is ready |
| `execute(code: str, *, deadline: float) -> ExecutionResult` | Runs one entry; deadline is an absolute `time.monotonic()` task deadline |
| `shutdown() -> None` | Bounded cleanup; safe to repeat |

`ExecutionResult` is an immutable typed model:

| Field | Type / meaning |
|---|---|
| `status` | `ok`, `error`, `final`, `timeout`, or `killed` |
| `stdout` | Actual output, including partial output on failure |
| `error` | Diagnostic string or None |
| `final_answer` | Submitted string, only for final; otherwise None |

Required behavior:

- Variables persist after normal entries and ordinary Python errors.
- Timeout/crash terminates and reaps the worker; restart before the next entry.
  Report that variables were reset. Never automatically replay interrupted code;
  external edits and tool effects are not rolled back.
- `final_answer()` belongs to the sandbox, not MCP. Capture its value even if
  guest code catches its internal signal. Proposed rule: first answer per entry wins.
- KeyboardInterrupt/SystemExit propagate to the parent caller for shutdown.
- Ordinary execution errors return results; lifecycle/protocol failures raise
  a typed SandboxError. A handles them and writes an honest failed solution.
- Output is bounded (planned cap: 10,000 characters), with truncation disclosed.

B owns SandboxConfig/ExecutionResult; A owns task/solution models and ToolInfo.
Use shared typed contracts and validated JSON boundaries, not duplicated models.

**Proposed deadline addition:** A passes the task deadline minus its output/cleanup
reserve. B must return or raise within that allowance, including tool waits and
termination. Reject expired deadlines before executing. If it expires during an
entry, return timeout with a task-deadline diagnostic; A ends the task. Sandbox
timeouts can allow further iterations; task-deadline expiry cannot. Restart may
be deferred to the next execute call. If graceful termination cannot finish in
time, escalate and report cleanup failure explicitly.

## 3. MCP boundary — A is client, B is server

A discovers tool names, descriptions and complete input schemas, builds valid
Python aliases/wrappers, and generates the manual. Calls use original MCP names.
Tools cannot override the built-in final_answer. Support stdio and streamable
HTTP, plus resource/prompt discovery and documented access where available.

B provides root-level `mcp_tools_mbpp.py` and `mcp_tools_swebench.py`, independently
testable without AgentLoop. The injected dispatcher accepts a tool name and typed
arguments, returning a typed reply with `is_error` and `text`.

Shared contract shapes (typed models, not unchecked dictionaries):

```text
ToolInfo(name: str, python_name: str, description: str,
         input_schema: JsonObject, parameter_order: tuple[str, ...])
ToolArguments(values: JsonObject)
ToolReply(is_error: bool, text: str)
ToolDispatcher.call(name: str, arguments: ToolArguments,
                    *, deadline: float) -> ToolReply
```

JsonObject means a validated JSON object: string keys and recursively JSON-safe
values. Validate arguments against input_schema; preserve required fields and
defaults. Alias collisions must be resolved uniquely, including final_answer.
B installs worker stubs from ToolInfo; A owns discovery, alias mapping and the
dispatcher. Keep these contract types in a neutral module to avoid circular imports.

A normalizes MCP results before returning ToolReply: join text blocks; represent
non-text blocks as `[type]`; use serialized structuredContent when text is absent.
Preserve isError. Stubs return reply.text on success and a `[TOOL ERROR]`-prefixed
string on failure (prefix once). Arguments/schema errors produce an explicit tool
error. KeyboardInterrupt/SystemExit propagate rather than becoming ToolReply.
Keep full tool values in guest scope; apply observation caps when printing.

**MBPP:**

```text
run_tests(code: str, test_list: list[str],
          test_imports: list[str] | None = None) -> str
```

MCP text contains JSON: `{"success": bool, "output": str}`. Wrong code or a
candidate timeout returns success=false; service/configuration failures are
MCP errors. Confirm schema and execution behavior against the moulinette.
For example, a completed failing test yields
`ToolReply(is_error=False, text='{"success":false,"output":"AssertionError"}')`;
a disconnected server yields `ToolReply(is_error=True, text="MCP connection lost")`.

**SWE-bench:** use T10's names/defaults for read_file, edit_file, list_files,
search_code, search_function_or_class_definition_in_code, find_references,
run_tests, get_patch and run_command. Read output is `<line>: <content>`;
search output is `/absolute/path:<line> <content>`; commands report stdout,
stderr and exit code. Keep formats consistent across local/Docker modes.

B handles TESTBED_PATH confinement, AGENT_CONTAINER mode selection and
EVAL_SCRIPT_PATH. A formats tool errors as `[TOOL ERROR]`. Truncated observations
must say so. **Proposed correction: get_patch returns a complete patch or an
explicit error; never a truncated success value.** Agree the oversize policy.

## 4. Timing, communication and cleanup

- B owns the worker's JSON Lines protocol: init/ready, exec, stdout,
  tool_call/tool_result, result and shutdown. Use execution/call IDs; stdout
  carries protocol only; stale messages cannot complete a new execution.
- A calls the public API rather than parsing worker messages. B finalizes wire
  field definitions with A before worker/client integration.
- Sandbox execution time excludes measured tool-call waits. Tool calls still
  have finite timeouts, and **all elapsed time counts toward A's task budget**.
- Verify the plan's proposed five-second sandbox grace against the subject.
  A bounds waits by remaining task time; B stops owned command processes.
- A's CLI coordinates cleanup; B provides bounded worker/container cleanup.
  Reserve time for solution.json, preserve the original error, and do not rely
  on finally or signal handlers running after SIGKILL.
- Provider keys stay with the LLM client. Filter child environments and never
  forward credentials to workers, tools, containers or logs.

### Proposed worker messages (v1)

Every line is one UTF-8 JSON object with `v` and `type`. IDs are positive integers;
exec_id never repeats during a SandboxProcess lifetime, including restarts.
call_id is unique within an execution. The parent rejects mismatched tool replies
and discards stale events. Missing/invalid fields fail explicitly. Only validated
current messages may change state.

Initialization and one tool call (arrows describe direction, not wire content):

```json
{"v":1,"type":"init","config":{},"tools":[]}
{"v":1,"type":"ready"}
```

Here config={} requests SandboxConfig defaults. Actual tool descriptors use the
ToolInfo fields above; the following execution assumes run_tests was discovered
and included in init.tools. Init → ready completes before exec is accepted.

```json
{"v":1,"type":"exec","exec_id":1,"code":"print(run_tests(code='def f(): return 1', test_list=['assert f() == 1']))"}
{"v":1,"type":"tool_call","exec_id":1,"call_id":1,"name":"run_tests","arguments":{"code":"def f(): return 1","test_list":["assert f() == 1"]}}
{"v":1,"type":"tool_result","exec_id":1,"call_id":1,"is_error":false,"text":"{\"success\":true,\"output\":\"\"}"}
{"v":1,"type":"stdout","exec_id":1,"text":"{\"success\":true,\"output\":\"\"}\n"}
{"v":1,"type":"result","exec_id":1,"status":"ok","stdout":"{\"success\":true,\"output\":\"\"}\n","error":null,"final_answer":null}
```

These are internal worker messages, not MCP protocol envelopes. The parent owns
the monotonic deadline and passes it into dispatch; the worker cannot extend it.
result.stdout replaces streamed accumulation; never concatenate both copies.
On timeout/death without result, retain accumulated output up to the cap.

Other terminal examples:

```json
{"v":1,"type":"result","exec_id":2,"status":"error","stdout":"","error":"NameError: name 'x' is not defined","final_answer":null}
{"v":1,"type":"result","exec_id":3,"status":"final","stdout":"","error":null,"final_answer":"def f(): return 1"}
{"v":1,"type":"result","exec_id":4,"status":"system_exit","stdout":"","error":null,"final_answer":null,"exit_code":0}
{"v":1,"type":"shutdown"}
```

keyboard_interrupt uses the same result fields without exit_code. The parent
re-raises control-flow exceptions; it derives timeout/killed locally rather than
expecting a result from a dead worker. EOF or malformed messages during execution
raise SandboxError with partial output attached. Unexpected process death without
protocol corruption returns killed. Shutdown closes streams and reaps the worker;
no acknowledgement is required. All lifecycle waits are bounded by configuration
and, during a task, the remaining deadline.

## 5. Confirm together before integration

- [ ] Assign teammate names to A/B; accept T10/T11 transfer; decide T27 separately.
- [ ] Accept sandbox API (including deadline), shared types, reset and exception behavior.
- [ ] Check MCP-client-in-parent design against the subject's sandbox boundary.
- [ ] Agree tool schemas, timeout/cancellation behavior and complete-patch policy.
- [ ] Accept v1 messages and normalization; define startup/shutdown timeout settings.
- [ ] Agree Docker lifecycle API before T24 (not needed for first MBPP integration).
- [ ] Update ownership in all three plans; record important decisions in ADRs.

A can build against a fake sandbox; B can test with fixed code and a fake
dispatcher. First joint gate: one real MBPP task through CLI → LLM → sandbox
→ MCP test tool, with trace/metrics checked and solution.json passing moulinette.
This proves the pipeline, not full security or the required overall pass rate.
