# Agent Smith — Pair Implementation Plan

**Goal:** Build Agent Smith as a two-person team: an agentic framework
(Thought → Code → Observation) with a hardened sandbox, MCP tool
servers, an MBPP agent (≥4/5), a SWE-bench agent (≥2/3), all sandbox
security tests, and a model benchmark report — with **both members
able to explain and modify any part at the defense**.

**Architecture:** A CLI loads a task, starts our MCP tool server over
stdio, builds a system prompt from a dynamic manual, and runs a loop:
call the LLM → extract one Python block → execute it in a restricted
worker subprocess (the sandbox) → feed the observation back → repeat
until `final_answer()` or a budget limit. Tools run on `TESTBED_PATH`
locally by default and bridge into a Docker container for SWE-bench.

**Tech stack:** Python 3.10, uv, pydantic v2, `mcp` SDK (pin `<2`;
stdio + streamable HTTP), httpx, pytest, ruff (line-length 79) +
flake8 conformance, mypy, Docker (SWE-bench only).

**Spec:** `en.subject_agent_smith.pdf` (the contract). Task catalog and ADR
program: `docs/planning/PROJECT_PLAN.md`. This plan is the binding task-by-task
specification; interfaces below are contracts — changing one requires
architect sign-off.

---

## Roles and ownership

| Member | Role | Implements | Reviews |
|---|---|---|---|
| **A — Architect + agent side** | Planning, ADRs, interface contracts, milestone acceptance | `llm/`, `agent/`, `mcp_client/`, `agent_mbpp.py`, `agent_swebench.py`, `mcp_tools_mbpp.py`, `models.py`/`solution_io.py`, `docs/protocol.md` | B's half |
| **B — Systems side** | Sandbox and infrastructure | `sandbox/*`, `docker_env.py`, `mcp_tools_swebench.py` (docker mode), the security battery, docker tests | A's half |
| Shared | Both | `mcp_tools_swebench.py` formats, `benchmarks/` + devlogs, cross-half tests, README | Cross-review |

Working rules:
- **The author never reviews their own code.** Every PR is reviewed by
  the other member; the architect additionally accepts every
  milestone gate.
- **Interfaces are the architecture.** The five seams —
  `docs/protocol.md`, `SandboxProcess`/`ExecutionResult`, `ToolInfo`,
  `LLMClient`/`LLMResponse`, `ExtractionResult` — are architect-owned.
  Task-level decisions inside a half belong to its owner.
- **Parallel waves** are marked per phase: after T04, the two halves
  proceed concurrently on separate branches.
- Branches `feat/<area>-<name>` (`sys-`, `agt-`, `docs-`, `test-`);
  commits `type: description`; commit after every green test cycle;
  never leave the tree red overnight.

## Global constraints (from the subject; every task implicitly includes them)

- Python 3.10; uv is the only package manager.
- No agent-orchestration libraries (llama-index, smolagents, langgraph,
  crewai, autogen). The loop is our own code.
- Sandbox restrictions: standard library only (no RestrictedPython).
- `mcp_tools_mbpp.py` and `mcp_tools_swebench.py` at the repository root.
- Tool output formats: `read_file` → `<n>: <line>` (cat -n style);
  search tools → `/abs/path.py:<line> <content>`.
- `final_answer` is injected by the sandbox, never an MCP tool.
  `KeyboardInterrupt`/`SystemExit` propagate to the loop.
- Limits (§6.1): MBPP 10 iterations / 6,000 input / 1,500 output
  tokens / 120 s; SWE-bench 30 / 300,000 / 10,000 / 900 s. Cumulative
  per task; reasoning tokens count. Timeouts are enforced by kill.
- Patch format: `git add -A -N` then `git -c core.fileMode=false diff`
  (untracked files included; build artifacts excluded).
- Free-tier LLM providers only; keys from env/`.env` only; multi-key
  rotation mandatory; a hardcoded key is a security failure.
- The agent must never fetch solutions from PRs/issues/web; traces
  must show legitimate exploration. Never feed reference solutions or
  gold patches to the agent.
- Both stdio and streamable-HTTP MCP transports; the system must work
  with an unknown MCP server.
- README in English, first line the italic 42 sentence with **both
  logins**; `BENCHMARK_REPORT.md` at root backed by `solution.json`
  files.
- Style: ruff at 79 columns + flake8-conformant + mypy, configured
  from day one, run by hand (no hooks, per the subject).

## Design principles (binding for every task)

1. **Default-deny, layered.** Every defense assumes the others failed:
   static scan AND runtime checks; import gate AND module proxies;
   process boundary (kill, restart, rlimits) behind everything.
2. **Discriminating tests.** A test for a mechanism must fail on the
   wrong implementation. State in a one-line comment which wrong
   implementation each test discriminates. Example (T08): a suspended
   deadline test whose tool sleeps *longer than timeout + grace* —
   a shorter tool passes even when the deadline extension is broken.
3. **Honesty by construction.** Token totals come from the same
   numbers that enforce budgets; validation is fail-closed (only the
   literal `Overall: PASSED` counts); repairs are labeled, never
   silent; estimates are marked; every benchmark row is backed by one
   artifact on disk.
4. **Kills, not checks.** Wall-clock limits are enforced by process
   death; therefore every budget stops early (90% of token budgets;
   a time reserve) so `final_answer` and `solution.json` land first.
5. **The system authors observations.** Stop sequences and feedback
   messages are machinery, not suggestions to the model.
6. **Freeze before measuring.** Benchmark data is collected on frozen
   code; afterwards, only data and docs change without architect
   approval.

## Target file map

```
repo/
├── docs/planning/  PROJECT_PLAN.md, IMPLEMENTATION_PLAN.md, TEAM_WORKFLOW.md
├── pyproject.toml, uv.lock, .env.example, .gitignore, .flake8, Makefile
├── mcp_tools_mbpp.py, mcp_tools_swebench.py
├── sandbox_template.json        # subject SandboxConfig defaults
├── models.json                  # providers, key env names, limits
├── models.py                    # verbatim moulinette copy (never edit)
├── solution_io.py               # task/solution IO + totals
├── sandbox/    config.py, security.py, worker.py, process.py, cli.py
├── mcp_client/ manager.py, stubs.py, formatting.py, manual.py
├── llm/        client.py, keys.py, usage.py
├── agent/      extractor.py, limits.py, feedback.py, prompts.py, loop.py
├── agent_mbpp.py, agent_swebench.py
├── docker_env.py
├── tests/      (mirrors packages; fixtures: hello_server, odd_server, testbed)
├── benchmarks/ mbpp_bench.py, swebench_bench.py, devlogs, notes, metrics
├── docs/       adr/, protocol.md, grader-notes.md, ai-usage.md, log.md
├── BENCHMARK_REPORT.md
└── README.md
```

## Milestones and gates

| Gate | After | Evidence required (architect accepts) |
|---|---|---|
| M0 | T01–T05 | skeleton green on `make test/lint/types`; protocol doc reviewed by both; Linux suite path proven |
| M1 | T06–T09 | security battery green on macOS AND `make sandbox-tests-linux`; REPL demo; no orphan processes |
| M2 | T10–T17 | tools standalone with two TESTBED_PATHs (no Docker); unknown-server green; mocked `validate mbpp`; docker cleanup incl. SIGKILL self-destruct |
| M3 | T18–T20 | real `validate mbpp` PASSED; honest test-split ≥80% on ≥2 seeds; p95 ≤100 s; devlog rows artifact-backed |
| M4 | T21–T25 | one pool task `validate swebench` PASSED **before** tuning; final-prompt pool ≥4/6; re-draw reproducible; ≥4 hold-outs recorded; metrics on 3 traces |
| M5 | T26–T32 | red-team closed; lint/types/test clean; Linux + bare-VM passes; **freeze declared**; matrix ≥5×≥2×3 + ablation; report; README; runbook ≤10 min; live-mod drill; `v1.0` |

---

# Phase 0 — Foundations [A leads, both pair] — T01–T05

### T01 [SHARED]: Repo, tooling, skeleton

Create `pyproject.toml` (hatchling; `[project.scripts]
sandbox = "sandbox.cli:main"`; packages + py-modules so the script
resolves after `uv sync`; `requires-python >=3.10,<3.11`;
`[tool.ruff] line-length = 79`; `[tool.mypy] disallow_untyped_defs =
true` + file list), `.flake8` (max-line-length 79, `extend-ignore =
E203` — Black-style formatter compatibility; excludes only for
documented provenance files), `.gitignore` (`.env`, `cache/`,
`evaluations/`), `.env.example` (names only), `Makefile`, empty
packages, `sandbox_template.json` (subject defaults verbatim: the 19
authorized-import entries incl. `math.*`, `collections.*`, `typing.*`,
`datetime.*`; `/testbed`, `/tmp/agent`; 30 s; 512 MB).

Makefile: `test`, `sandbox-tests`, `sandbox-tests-linux` (security
suite inside `ghcr.io/astral-sh/uv:python3.10-bookworm`, repo mounted
— authoritative for memory/kill semantics), `lint` (ruff check +
format --check), `types`, `clean-containers`, and placeholders for
`bench-mbpp`/`bench-swebench`.

- [ ] `uv sync`; `uv run pytest` runs (0 tests, exit 0); `make lint`
      and `make types` clean; `make sandbox-tests-linux` runs.
- [ ] `git status` shows no `.env`. Commit `chore: project skeleton`.
- [ ] Write ADR-0010 (flat repository layout: packages at the root so
      `python -m agent_mbpp` and `uv run sandbox` resolve from the
      repo the grader runs in). Commit with the skeleton.

### T02 [ARCH]: Study the example moulinette + exam-day runbook

- [ ] `cd moulinette && uv sync`; dump an MBPP task and a SWE-bench
      task; write a dummy `solution.json` by hand and validate it;
      then exceed each limit (11 iterations, 7000 input, 1600 output,
      130 s) and record the exact error texts. Verify `--skip-metrics`.
- [ ] Copy `models_public.py` → `models.py` verbatim (header comment:
      "copied verbatim; do not edit fields"). Helpers never go here.
- [ ] Write `docs/grader-notes.md`: JSON formats; observed-vs-
      guaranteed split (hidden first MBPP test; fresh-container patch
      validation; display warnings: empty system_prompt, non-monotonic
      timestamps, multiple model names, identical consecutive
      sandbox_input); the exam-day runbook (10-minute checklist: dump
      one task per benchmark and diff JSON shape against models.py;
      dummy-validate and read enforced limits; confirm the invocation
      cwd/command; re-check container cleanup).
- [ ] Commit. Both members run the commands once.

### T03 [ARCH]: Models + solution IO

`solution_io.py`: `load_task(path) -> MBPPTaskInput | SWEBenchTaskInput`
(dispatch on `instance_id`/`task_id` keys); `save_solution(sol, path)`
(`model_dump_json(indent=2)`); `totals_from_steps(steps) ->
(total_in, total_out, total_requests)` where requests =
`len(steps) + sum(retries)` — this single formula is what the grader
recomputes; keep it in one place so it can never drift.
- [ ] Failing test: round-trip a SolutionOutput; `task_id="282"`
      accepted, `task_id=282` (int) raises ValidationError; totals
      equal sums. Then implement; green; commit.

### T04 [ARCH]: Worker protocol spec + ADR-0001/0002

`docs/protocol.md` — JSON lines on worker stdin/stdout: init (config +
tools) / ready / exec / streamed stdout / tool_call ↔ tool_result
(correlated by `call` id) / result / shutdown. Wire statuses:
`ok | error | final | keyboard_interrupt | system_exit`; the parent
derives `timeout` (deadline expired) and `killed` (worker died).
Rules: the worker prints only protocol lines (its own logs → stderr);
user `print` streams via a tee (events + accumulation — partial output
survives kills); after a kill the worker is assumed dead (parent
restarts); `final` is set whenever `final_answer()` was called even if
user code caught the exception; **tool-call time is not sandbox time —
the deadline is suspended while a call is in flight and extended by
its measured duration**.
- [ ] ADR-0001 (subprocess sandbox; alternatives in-process /
      docker-per-run) and ADR-0002 (MCP client in the parent, stubs in
      the worker; tool time excluded). Status: Accepted, both deciders.
- [ ] Commit. **Both members review this document — it is the first
      seam.**

### T05 [AGT]: MCP SDK pin on 3.10

- [ ] Pin `mcp<2`; hello-world FastMCP server (`add(a,b)`); scratch
      client over stdio then streamable HTTP; assert 3. Record the
      pinned version in ADR-0007 (async bridge: SDK session on a
      dedicated thread; sync bridge via `run_coroutine_threadsafe`).

---

# Phase 1 — The Sandbox [B owns; A reviews] — T06–T09

### T06 [SYS]: Security battery, written first (red)

`tests/test_worker_security.py`, one comment per test naming the
attack. Groups mirroring the exam: imports, builtins, paths, timeout,
memory, flow control, `final_answer`, escape vectors. **Attack vectors
that MUST be covered** (analysis of CPython's object model — every one
is reachable from allowlisted modules):

- imports: `import os`/`from os import path` (cache-hit case — the
  gate must fire before `sys.modules`), `socket`, `subprocess`, `sys`;
  `import json.tool` and `from json import tool` (a bare `json` entry
  authorizes only `json`, never submodules); relative imports
  (`from . import x` — `__package__` is user-spoofable).
- builtins: `eval`, `exec`, `compile`, `__import__("os")`,
  `open("/etc/passwd")`, `input()` (no hang), `vars` (removed).
- attribute chains: `().__class__.__bases__[0].__subclasses__()`,
  `__mro__`/`__base__` walks, `print.__self__`, runtime-built names
  (`getattr(random, "_ur" + "andom")`), `getattr(list, "__cla"+"ss__")`,
  `object.__getattribute__(x, "__globals__")`, `delattr` of underscore
  names.
- slot leak on the module proxy: `proxy._mod` (slot lookup bypasses
  `__getattr__` — the denial must live in `__getattribute__`).
- capability attributes: `json.codecs.open("/etc/passwd")` (codecs
  binds the REAL `open`), `from json import codecs`; `typing.sys`;
  `re.enum.sys` (recursive chains).
- code constructors: `typing.types.CodeType`/`FunctionType` +
  hand-assembled bytecode → `object.__subclasses__()` → `FileIO` read.
- eval sinks: `typing.ForwardRef("open('/etc/passwd').read() or
  int")._evaluate({}, {}, frozenset())` (runs with typing's REAL
  builtins) and `get_type_hints(f, {}, {})` (same route).
- attribute-protocol bypasses: `operator.attrgetter`,
  `operator.methodcaller`, `string.Formatter().format("{0.__globals__}",
  f)` (walks attributes from a plain string).
- format strings: `s = "{0.__globals__}".format; s(f)` (non-call use),
  `str.format(...)` (unbound), runtime-built `"for" + "mat"`, nested
  specs `"{0:{1.__x__}}"`; positive controls: `"{} {}".format(1,2)`,
  f-strings, `print(__name__)`, `self._x`, `x.__class__.__name__`,
  decorator reading `f.__name__`.
- traceback/frame walks: `e.__traceback__.tb_next.tb_frame.f_globals` /
  `.f_builtins`; `gi_frame`/`cr_frame`.
- paths: `/etc/passwd`, `/testbed/../etc/passwd`, symlink outside →
  PermissionError; write+read under `/tmp/agent` → ok.
- timeout: `while True: pass` → status `timeout`, partial stdout
  kept, worker restarts. Memory: >limit allocation → clean
  MemoryError, restartable (authoritative on Linux only).
- flow control: `SystemExit(3)` / `KeyboardInterrupt()` → own statuses,
  re-raised in the parent. `final_answer("x")` inside
  `except BaseException: pass` → still final.
- **the dynamic enumeration test:** fresh-import every allowlisted
  root, walk every module-valued attribute, assert none (outside the
  three deny layers) exports `open`/`fdopen`/`open_code`/`system`/
  `popen`/exec/eval/code constructors. This makes the NEXT capability
  leak caught by construction.

- [ ] All tests fail for the right reason (ImportError until T07/T08).
      Commit `test: security battery (red)`.

### T07 [SYS]: Worker core + attribute policy

`sandbox/config.py`: `load_config(path|None)` (None → subject
defaults from the config module; the allowlist lives in DATA, mirrored
in `sandbox_template.json`; known CPython fact to encode now: the C
accelerator for `datetime.strptime` imports `_strptime` through the
caller's `__import__` — allowlist `_strptime` as data; it exports no
capabilities and re-denies `sys` at the proxy layer).

`sandbox/security.py` — the policy as DATA (define these tables
exactly; they are the heart of the defense):
- `REMOVED_BUILTINS`: eval, exec, compile, breakpoint, input, vars,
  exit, quit, help, license, credits, copyright.
- `DUNDER_ALLOWLIST` (the only dunder attribute names reachable):
  `__init__ __name__ __qualname__ __module__ __class__ __doc__
  __version__ __repr__ __str__ __eq__ __ne__ __lt__ __le__ __gt__
  __ge__ __hash__ __len__ __getitem__ __setitem__ __delitem__
  __contains__ __iter__ __next__ __call__ __enter__ __exit__ __bool__
  __int__ __float__ __index__`.
- `FRAME_PREFIXES`: `f_ tb_ gi_ cr_ ag_ co_`.
- `FORBIDDEN_ATTRS` (module identities never reachable as attributes,
  on proxies and real modules): `sys os subprocess socket builtins
  importlib ctypes pathlib shutil` + the capability set `codecs io
  _io tempfile pickle shelve marshal zipfile tarfile ssl http urllib
  inspect site sysconfig` + `types` + the alias binds `sre_compile
  stdlib_re contextlib`.
- `MODULE_DENIED_EXPORTS` (never handed through a proxy): `attrgetter
  methodcaller Formatter vformat get_field` + `open fdopen open_code`
  + `CodeType FunctionType LambdaType FrameType TracebackType
  BuiltinFunctionType MethodType ModuleType` + `eval exec` +
  `ForwardRef get_type_hints`. Deliberate exception: do NOT deny
  `compile` as an export — it would break the legitimate
  `re.compile` anchor; the dangerous `compile` binds are denied via
  the alias-module identities above.
- `FORMAT_NAMES = {"format", "format_map"}`.

Mechanisms:
- **Import gate** = replaced `__import__` in the restricted builtins
  (fires before any `sys.modules` lookup; both import forms route
  through it; exact-name or explicit `root.*` only; relative imports
  denied; fromlist guard: after the import, every newly-present
  `<name>.<item>` module must itself be authorized) + an
  `AllowlistFinder` at `sys.meta_path[0]` installed only in the
  subprocess worker, after the worker's own imports.
- **`SafeModuleProxy`** wraps every module handout (and every
  module-valued attribute, recursively): denials in
  `__getattribute__` (THE single lookup point — slot lookup bypasses
  plain `__getattr__`); underscore names denied outside the allowlist;
  `FORBIDDEN_ATTRS`/`MODULE_DENIED_EXPORTS` denied; `__setattr__`/
  `__delattr__` deny everything; controlled `__repr__`/`__dir__`.
- **Static AST scan + rewrite:** attribute LOAD of underscore names
  outside the allowlist → reject (single-underscore loads allowed
  statically; the module vector is closed by proxies — `self._x` and
  `other._x` idioms must work); frame prefixes always rejected;
  dunder-shaped NAME loads rejected except `__name__`; dunder STORES
  rejected (a class body's `def __init__` is a FunctionDef —
  unaffected). After the scan, a `NodeTransformer` rewrites every
  `obj.format`/`obj.format_map` LOAD into `_sbx_attr(obj, "format")`
  (also catches non-call uses, unbound `str.format`, `type(s).format`);
  compile from the REWRITTEN AST.
- **Runtime attribute policy:** `checked_getattr/setattr/hasattr/
  delattr` route through one `_sbx_attr(obj, name)` that enforces the
  tables FIRST (a policy violation raises even when getattr has a
  default; only genuine AttributeError falls back) and, for format
  methods on strings, returns a guarded wrapper that validates the
  REAL format string at call time (any attribute segment starting
  with `_`, recursing into nested specs).
- **Checked `open`:** realpath both sides; admit only
  `path == root or path.startswith(root + os.sep)`; `PermissionError`
  naming the allowed dirs; all modes guarded.
- **`final_answer`:** write a module-level slot, THEN raise
  `FinalAnswerSignal(BaseException)`; the worker checks the slot after
  execution regardless of exception handling.
- **Resource limits:** `RLIMIT_AS` (skip where unsupported); CPU
  limit only as a generous backstop (timeout + 60 s) — the parent owns
  timeouts; a tight CPU limit misreports timeouts as kills.

`sandbox/worker.py`: `run_code(code, cfg, tools)` in-process helper
(tests/REPL) and the protocol main loop (T04 doc exactly): init →
limits → meta_path finder → stubs → `install_restrictions` → ready;
exec → swap in a stdout `_Tee` (accumulate + stream events) → pipeline
(`ast.parse → scan → rewrite → fix_missing_locations → compile →
exec`) → cap stdout at 10 000 with a `[truncated N chars]` note →
slot check (slot set ⇒ status `final`) → result.
- [ ] Battery green on macOS and Linux. Regression: ~20 reference
      solutions from train/fewshot splits (local sandbox-regression
      use only — never shown to the agent) + dunder-idiom snippets.
- [ ] ADR-0005 (imports policy incl. the tables; standing rule: never
      allowlist modules that open files or execute code — `io`,
      `codecs`, `tempfile`, `pickle`, `shelve` are permanently out).
      Commit.

### T08 [SYS]: SandboxProcess — parent side

`sandbox/process.py`:
```python
@dataclass
class ExecutionResult:
    status: str   # ok|error|final|timeout|killed|keyboard_interrupt|system_exit
    stdout: str; error: str | None; final_answer: str | None

class SandboxProcess:
    def __init__(self, cfg, tools=None, tool_dispatch=None): ...
    def start(self) -> None      # Popen [sys.executable, -m sandbox.worker],
                                 # start_new_session=True (own process group),
                                 # stderr=DEVNULL (protocol channel purity)
    def execute(self, code: str) -> ExecutionResult
    def shutdown(self) -> None
```
`execute` semantics: reader-thread queue; `base_deadline = now +
timeout + grace(5 s)`; while a tool call is in flight, wait with NO
timeout (suspended) and **after the call add its measured duration to
the deadline**; on expiry kill the process group (SIGTERM → 2 s →
SIGKILL), restart, status `timeout` with the partial stdout and
"variables were reset"; worker death → `killed` + restart;
`keyboard_interrupt`/`system_exit` re-raise in the parent; transparent
restart if the worker died between execs; stale exec-id messages
dropped; tool dispatch through the injected callback (never raises —
errors become `[TOOL ERROR]` observations).

- [ ] Failing tests, each with its discrimination comment: timeout
      returns partial stdout + restart; KI/SystemExit re-raised;
      `os._exit` → killed + restart; 3 sequential execs share state;
      10 000-char stdout truncation; **slow tool sleeps 8 s under a
      1 s timeout (grace is 5 s — longer than the deadline): returns
      the tool result with status ok** (discriminates a broken
      deadline extension: without the measured-duration extension the
      remaining time goes negative and the test fails) while
      `while True: pass` still times out at timeout + grace.
- [ ] Green incl. `make sandbox-tests-linux`. Commit.

### T09 [SYS]: Sandbox CLI (REPL)

`uv run sandbox [config.json] [--mcp-stdio "python mcp_tools_mbpp.py"]
[--mcp-server URL]` — prompt `sandbox> `, persistent namespace, same
restrictions as agent code; `final` → `[final_answer] x`; errors as
`[status] error`; exit/EOF clean; MCP flags wired in T12; connect
failure must not kill the REPL (banner to stderr).
- [ ] Piped-stdin tests + manual: all four variants start;
      `pgrep -f sandbox.worker` empty after. Commit.

---

# Phase 2 — Tools + Client + LLM (parallel waves) — T10–T17

**Wave 2a [AGT]:** T10, T11, T15, T16. **Wave 2b [SYS]** (after T08):
T22. **Wave 3 [AGT]:** T12–T14 (needs T08 + one server). **T17**
after T14.

### T10 [AGT]: `mcp_tools_swebench.py` — the nine tools, local mode

FastMCP server `swebench-tools`. Every path resolves under
`TESTBED_PATH` (read from the environment on EVERY call — the grader
sets it before starting the server; never hardcode `/testbed`) and is
confined (local mode: `resolve()` then `resolved == root or root in
resolved.parents` — symlinks and `..` confined). Signatures (exact):

```python
read_file(filepath, start_line=1, end_line=None) -> str   # "<n>: <line>"
edit_file(filepath, old_str, new_str) -> str              # count + ast.parse check
list_files(directory=".", pattern="*") -> str             # relative, .git filtered, ≤500
search_code(pattern, file_pattern="*") -> str             # "/abs/path.py:<line> <content>"
search_function_or_class_definition_in_code(name) -> str  # ast.walk, same format
find_references(name, filepath, line) -> str              # \b-escaped regex, def site excluded
run_tests() -> str      # bash $EVAL_SCRIPT_PATH in the root, 600 s, exit_code + 2000-char tail
get_patch() -> str      # git add -N (untracked minus PATCH_IGNORE) + git -c core.fileMode=false diff
run_command(command, workdir=".") -> str                  # sh -c, 120 s, exit/stdout/stderr
```

Constants: `OUTPUT_CAP = 10_000`; `PATCH_CAP = 50_000`;
`PATCH_IGNORE = ("__pycache__/", "*.pyc", ".pytest_cache/",
"*.egg-info/", "build/", "dist/")` — build artifacts must never
pollute a patch. All output caps append `[truncated N chars]`.
`edit_file`: exact-match replace (count==0 → error quoting `old_str`);
replaces all occurrences and reports the count; then `ast.parse` →
"syntax OK" or "SYNTAX ERROR introduced: … — fix it". Errors raise a
`ToolError` (FastMCP marks isError).
- [ ] Failing tests (tools as plain functions): exact formats; `get_patch`
      includes a NEW untracked file and excludes artifacts created by
      `run_command`; path escapes denied; two different TESTBED_PATH
      values. Live smoke over stdio. ADR-0009 (local-first; Docker
      optional). Commit.

### T11 [AGT]: `mcp_tools_mbpp.py` — run_tests

`run_tests(code, test_list, test_imports=None) -> json.dumps(
{"success": bool, "output": str})`. Semantics mirror the grader:
concatenate code + imports + asserts IN THAT ORDER, run
`[sys.executable, "-c", full]`, timeout 10 s, success = exit code 0,
output = (stdout+stderr) tail 2000 chars; timeout → success false with
a "timed out" prefix. Candidate code never runs in the server process.
- [ ] Tests: correct/wrong/hanging/syntax-error + test_imports. Live
      stdio smoke. Commit.

### T12 [AGT]: MCP client manager + stubs

`MCPClientManager`: dedicated daemon thread owning an asyncio loop;
every public method = `run_coroutine_threadsafe(...).result(timeout)`.
`connect_stdio(command)`: shlex-split; **the child environment drops
every var matching `*API_KEY*`** (tools never see provider keys);
`python`/`python3` → `sys.executable`. `connect_http(url)`: on
failure, retry once with `/mcp` appended. `list_tools()` →
`ToolInfo(name, description, params)` where params = the JSON-schema
property keys IN SERVER ORDER; `list_resources`/`list_prompts`
best-effort (unknown servers may not implement them). `call_tool`:
timeout enforced twice (asyncio.wait_for inside, +5 s outside) — no
hang from either side. `close()` idempotent, never raises.
`stubs.build_stubs(tools, call_fn)`: valid identifiers (`-`/`.`→`_`;
leading digit → `_`); a server tool literally named `final_answer`
becomes `mcp_final_answer` (the sandbox owns the name); stub maps
positionals onto the declared params, dispatches with the ORIGINAL
wire name; `__name__`/`__doc__` set.
- [ ] Failing tests via `tests/fixtures/hello_server.py`: stdio + HTTP;
      sandbox exec calls the tool; slow tool → clear timeout; env
      filter verified. Wire REPL `--mcp-*` flags. Commit.

### T13 [AGT]: Result formatting

`format_tool_result(result, cap=8_000) -> str`; **never raises**.
`isError` → `[TOOL ERROR] ` prefix; text blocks joined; non-text
blocks → `[<type>]` placeholders; empty → `json.dumps(
structuredContent or {})`; the truncation note fits INSIDE the cap.
**The `cap=None` contract:** callers feeding values into GUEST CODE
(the SWE-bench dispatch) skip the cap — a truncated `get_patch()` is a
silently un-appliable submission; the tools bound their own payload
caps and the worker caps what the guest prints.
- [ ] Failing tests with hand-built results (error, multi-text, image,
      empty+structured, huge). Commit.

### T14 [AGT]: Dynamic sandbox manual

`generate_manual(tools, resources, prompts, cfg) -> str`: Tools
(`ident(params)`: description; renamed ones show "(MCP `raw`)"),
Limits (allowlist verbatim, dirs, per-step time, memory, "No direct
network access — use the tools"), Submitting Answers (MBPP:
`final_answer(code)`; SWE-bench: `final_answer(get_patch())`),
Resources/Prompts when present. The manual is the single source of
tool documentation — the prompt never duplicates it; a different
server must produce a different manual.
- [ ] Tests (hello vs odd server). Commit.

### T15 [AGT]: LLM client, keys, usage

`LLMResponse(text, input_tokens, output_tokens, request_time_ms,
retries, api_url, model_name, finish_reason, usage_raw)`.
`KeyRing(keys)`: round-robin `next_key` skipping exhausted;
`mark_exhausted`; `reset` (rate windows are per-minute, not
permanent). `LLMClient(models_json, transport=None, backoff_s=1.0,
sleep=None, min_request_interval_s=4.0)` — sleep injectable for tests.

`generate(messages, model, stop=None, max_tokens=None)` — required
behavior:
- `.env` loaded at construction (stdlib parsing; real environment
  wins over the file); keys resolved from env-var NAMES in
  `models.json`; never logged.
- **Pacing:** ≥4 s between consecutive requests (free tiers throttle
  per minute; a 10-step task must not throttle itself).
- httpx `Timeout(110.0, connect=10.0)` — the 5 s default starves
  slow models.
- Error classes: **429** → mark that key exhausted, retry immediately
  on the next key (rotation is the backoff); **401/402/403** → key
  exhausted permanently; **≥500 / transport errors** → exponential
  backoff, same key; other 4xx → raise `LLMError` with the provider's
  message. All keys of the last provider exhausted AND the failure was
  rate-limiting → `KeyRing.reset()` + backoff + retry (the window may
  have reopened); otherwise fall through to the next provider serving
  the SAME canonical model (per-provider alias map in models.json);
  `model_name` stays canonical across fallback (the grader warns on
  multiple model names per run) while `api_url` records the actual
  endpoint.
- Response parsing: `content: null` → `""`; usage from the top-level
  `prompt_tokens`/`completion_tokens` **only** (reasoning-token
  details are subsets — never add them); missing usage → chars/4
  estimate with `usage_raw["estimated"] = true`; `finish_reason`
  surfaced ("length" matters downstream).
- `usage.sanity_check_usage(text, usage)` → note when reported tokens
  diverge >5× from visible length (hidden reasoning / under-reporting)
  — run once per model, record in `docs/log.md`.
- [ ] Failing tests with `httpx.MockTransport`: success parse; 429 →
      key rotation; all-keys-429 → provider fallback (canonical name
      constant, api_url changes); stop + max_tokens in the body;
      reasoning counted ONCE; null content; estimated marking.
- [ ] One real tiny call per provider; verify usage by hand; record.
      ADR-0006. Commit.

### T16 [AGT]: Code extractor

`ExtractionResult(status: "ok"|"no_block"|"malformed", code,
explanation)`; `extract_code(text)` — priority ladder: ```python fence
→ **unclosed ```python fence (fires when max_tokens cut the reply
mid-block — take the partial code, REPORT it as malformed)** → plain
fence → Hermes `<tool_call>` JSON (trailing-comma repair, reported) →
Anthropic `<invoke>`/`<parameter>` XML (numeric coercion) → ReAct
`Action:/Action Input:`. Every tool-call dialect normalizes to
`result = name(**args)`. Repairs are never silent.
- [ ] Tests: one real-looking sample per format, unclosed fence,
      trailing comma, empty text, fences inside prose, dict Action
      Input. ADR-0004. Commit.

### T17 [AGT]: System prompts

`build_system_prompt(manual, benchmark) -> head + manual` (the manual
verbatim — instructions never duplicate it). MBPP head ≈ ≤1 200 chars
(the 6 000-token input budget covers the WHOLE run): slots (Thought /
ONE ```python block / "no text after the block — the Observation
comes from the system"), rules (variables persist; allowlist; ALWAYS
`run_tests` first; the budget with "aim for 1–3 steps"; **reuse the
SAME variable in `final_answer(code)` — never re-type source into a
new string literal** (escape corruption passes visible tests and
fails hidden ones)), and a two-step example ending in
`final_answer(code)`.
SWE-bench head, in this order: slots with "Thought ≤ 3 sentences, no
speculative prose"; ONE action per step; **PRINT every tool result**
(the sandbox only reports printed output); search discipline (empty
result ⇒ broaden the query, never rerun identical); reading
discipline (≤60-line ranges, never the same range twice — every
observation is billed); the 5-phase workflow (explore → reproduce →
one minimal exact-match edit, never test files → verify →
`final_answer(get_patch())`); **run_tests is a black box — never read
the eval script's source**; pristine-checkout rule (minimal,
cause-level edits); budget + pacing (first edit before ~15 steps; if
over half the budget is gone with no edit — apply the best-supported
fix hypothesis NOW); never prototype in the sandbox (it cannot see
the repo); the repo's tests run in its conda env
(`/opt/miniconda3/envs/testbed`); green → submit on the NEXT step.
The example must be **generic** (`src/config.py`-style paths, no real
repo names) — pin with a test.
- [ ] Tests: slots/example/final_answer/manual pointer present; MBPP
      variant under the size cap; generic-path test. Measure the real
      token count; record. Commit.

---

# Phase 3 — MBPP end-to-end [AGT owns] — T18–T20

### T18 [AGT]: Agent loop + budget

`Budget(max_iterations, max_input_tokens, max_output_tokens,
max_time_seconds, reserve_seconds=15.0)`: `consume(LLMResponse)`;
`verdict()` checked BEFORE every call — iterations ≥ max; tokens ≥ 90%
of max (the NEXT call must fit); time ≥ max − reserve (kills, not
checks). Reason strings prefixed `Budget exhausted: …` downstream.
`AgentLoop(llm, sbx, manual, limits, model, final_validator=None).run(
task_prompt, benchmark, task_id) -> SolutionOutput` — **never
raises**. Per step, in order: verdict; compute the step output cap
`min(700, max(100, 90%_cap − consumed))` (no single call can consume
the whole budget; the floor keeps the model able to answer); call with
`stop=["\nObservation:"]` (observations are authored by the system);
ANY LLM exception → `loop_error = "LLM generation failed: …"` +
clean break; consume; extract; no_block → feedback #1 (no sandbox
round-trip; tokens still recorded); else execute — `final`: capture
solution+success, then **the final-check gate**: if `final_validator`
rejects, revoke (solution="", success=False, final_rejected=True),
observation = the final-check-failed feedback, loop CONTINUES;
`timeout` → feedback with the partial output + "variables were
reset"; `error` with SyntaxError → the syntax feedback, else
`[ERROR]`, stdout-before-error prepended; `ok` → stdout, empty →
"(completed with no output)"; identical consecutive input → append
the change-strategy nudge; record `StepMetrics` (UTC ISO timestamps,
full trace triple, retries — monotonic, as the grader checks); on
success break, else append the assistant reply VERBATIM + the user
Observation message. Catch-all → `loop_error`. Totals via
`totals_from_steps`; `task_id=str(...)`; `system_prompt` recorded.

The five mandatory feedback messages + the nudge + the
final-check-failed message live in `agent/feedback.py` (runtime bytes
asserted by tests).

- [ ] Failing tests with a mock LLM + hello-server tools: 1-step happy
      path; no_block feedback; nudge; budget stop at 90% → valid
      failed SolutionOutput; timeout observation; final-check
      rejection then recovery; totals == sums; timestamps monotonic;
      never-raise on a raising fake.
- [ ] Commit.

### T19 [AGT]: MBPP CLI

`python -m agent_mbpp --task-file --output --model-name
--provider-url [--max-iterations] [--config] [--sandbox-config]`.
Flow: load + type-guard the task; limits from `models.json`
(subject defaults as fallback); load sandbox config; start
`mcp_tools_mbpp.py` over stdio via an ABSOLUTE script path (works
from any cwd); `_dispatch = call_tool → format_tool_result`;
generate manual; `SandboxProcess(tools, tool_dispatch)`; **wire the
final-check gate: re-run the task's public tests against the exact
submitted code inside the sandbox — status ok ⇔ submission accepted**;
task prompt = definition + signature + public tests + imports (plain,
nothing that leaks answers); run the loop; `finally: sbx.shutdown();
mgr.close()` (no orphans, ever); `task_id=str(task.task_id)`; save.
- [ ] Mocked test: solution.json validates against our models. Real
      run: dump → run → `moulinette_eval validate mbpp` → PASSED.
      Commit.

### T20 [AGT+ARCH]: MBPP bench harness + tuning to ≥80%

**Harness** (`benchmarks/mbpp_bench.py`, `make bench-mbpp`): reads
splits from the moulinette's own `sanitized_tasks.json`; seeded RNG
sample (`pick_ids(pool, n, seed)` — deterministic, reproducible task
sets); per task: dump (runs with `cwd=moulinette` — **always pass an
absolute --workdir** or dumps land in the wrong place) → run the CLI
(timeout 150 s: the exam's 120 + margin that PRESERVES the artifact
for categorization) → validate **fail-closed** (only the literal
`Overall: PASSED` counts; a zero exit from a format change must never
become a PASS); per-task layer errors never abort the batch; failure
taxonomy (timed out/`agent killed` → latency; nonzero exit (the CLI
exits 0 on handled failures) → crash; claimed success over limits →
budget/latency; **claimed success within limits → logic**
(over-claimed submission); `Budget exhausted` → budget; `LLM
generation failed` → provider); exam limits read from `models.json`,
never duplicated; every row appended to `benchmarks/mbpp_devlog.md`,
**every row backed by one artifact** under
`cache/mbpp_bench/<split>-<seed>/runs/<model>/<task>/solution.json`;
summary JSON; exit 1 on any failure.
**Tuning:** tune on TRAIN split only; measure honestly on TEST split:
≥20 tasks × ≥2 seeds, ≥80% within limits; p95 wall ≤100 s; categorize
every failure; iterate on prompt/stop/observation caps; commit each
iteration.
- [ ] Harness tests (sampler determinism, taxonomy incl. the
      logic-over-claim case, fail-closed validation, layer-error
      continuation). Devlog + honest tables. Commit.

---

# Phase 4 — SWE-bench [SYS docker + AGT agent; ARCH gates] — T21–T25

### T21 [ARCH]: Layout ADR-0003

Host sandbox + tools bridging into Docker (local-first tools already
work standalone; emulation stays out of the sandbox's way;
allowed_directories nominal `/testbed`, `/tmp/agent`). 1–2 h prototype
of the alternative if any doubt. Accepted by both.

### T22 [SYS]: Docker lifecycle + bulletproof cleanup

`docker_env.py`: `LABEL = "agent-smith=1"`.
- `pull_image`: `--platform linux/amd64` (SWE-bench eval images are
  x86_64-only; the pin is a no-op on amd64 hosts; emulation runs it
  elsewhere); 1800 s timeout (gigabyte images).
- `start_instance_container(task, run_id, selfdestruct_s=960)`:
  `-d --rm --name agent-smith-<run_id> --label … -e
  TESTBED_PATH=/testbed -w /testbed` and command
  `timeout 960 sleep infinity` — **PID 1 exits on its own, so the
  container disappears even if our process is SIGKILLed** (cleanup
  never depends on the agent surviving; 960 = the 900 s exam limit +
  margin).
- `sweep(older_than_minutes)`: labeled containers older than the
  threshold; **hygiene, not a precondition** — `docker ps` gets a 30 s
  fail-fast and a failed sweep logs to stderr and returns 0 (a cold
  daemon must never kill a run); per-`rm` isolation; unparsable
  timestamps handled conservatively; `sweep(0)` = remove all
  (`make clean-containers`).
- `install_sigterm_handler([containers])`: the handler does isolated
  `docker rm -f` under a hard cap then `os._exit(0)` — `finally` does
  NOT run on SIGTERM; the self-destruct timer is the net beneath.
- `atexit` registry cleanup; `python -m docker_env sweep` CLI.
- [ ] Failing tests: start+exec; cleanup after normal exit; SIGTERM
      leaves nothing; **SIGKILL self-destruct**: selfdestruct_s=5,
      kill the parent, container gone within ~10 s WITHOUT any sweep;
      stale sweep. ADR-0008. Commit.

### T23 [SYS]: Tools, Docker mode

Env `AGENT_CONTAINER` switches every tool to `docker exec` (argv
verbatim, no shell except the two documented `sh -c` cases; `-w`
workdir; input via stdin — quoting is never a bug vector). Paths are
in-container; `TESTBED_PATH` names the in-container root, existence
checked INSIDE the container (never against the host filesystem);
confinement is LEXICAL in this mode (`normpath` — the container is the
isolation boundary). **One exec enumerates all `.py` files** (a
stdlib-only script inside the container emitting one JSON
`[path, text]` record per file) — never a `cat` per file; matching
and formatting stay host-side so outputs are byte-identical to local
mode. Local default unchanged.
- [ ] Failing tests: same fixture testbed in a container; outputs
      identical to local mode; unset AGENT_CONTAINER → local tests
      still green. Commit.

### T24 [AGT]: SWE-bench CLI

Same args as MBPP + `--docker/--no-docker`. Flow: type-guard; limits
(30/300k/10k/900 defaults); eval script → host temp file; docker
path: `startup_sweep()` → `pull_image` → `start_instance_container`
→ **`install_sigterm_handler([container])` immediately** →
`copy_in(eval_tmp, "/eval.sh")` → child env `AGENT_CONTAINER`,
`TESTBED_PATH=/testbed`, `EVAL_SCRIPT_PATH=/eval.sh`. The env reaches
the server via a context manager exporting the vars around
`connect_stdio` (the manager passes a filtered env copy — that is the
only channel); local path UN-sets `AGENT_CONTAINER` explicitly.
`_dispatch` uses `format_tool_result(res, cap=None)` — the whole
`get_patch()` must reach guest scope (the tools cap their payloads;
the worker caps what the guest prints). **Budget-only rescue:** if
not success AND `error.startswith("Budget exhausted")` AND the
solution is empty → capture `get_patch()` (accept only if
`"diff --git"` present), success STAYS False — never rescue provider
failures/crashes (a half-explored tree would grade work the agent
never produced); the grader still grades correctness, and the devlog
labels every rescue. `finally`: shutdown sandbox, close session,
remove container, unlink temp. Task prompt = instance + repo +
problem_statement + hints (nothing else).
- [ ] Mocked happy path (patch markers present, container cleaned).
- [ ] **HARD GATE (M4 entry): one real pool task —
      `moulinette_eval validate swebench` → Overall: PASSED — before
      ANY tuning.** If it fails, debug the pipeline, not the prompt.
      Commit.

### T25 [AGT+SYS]: SWE-bench harness + tuning to ≥4/6

Harness (`benchmarks/swebench_bench.py`) = T20 semantics plus:
`submission provenance` computed from artifact fields (agent iff
`success`; rescue iff not-success + non-empty patch; else none) —
never from error-text matching; rows carry `wall (ext) | loop |
submission` columns; **honesty screen**: `/eval.sh` in agent-authored
code or patch = hit; in prose = hit only with a read-command verb
(word-boundary matched); the eval script's heredoc marker anywhere =
hit; **the screen failing = hit** (fail-closed; write `honesty.log`
beside the artifact); a validated PASS is overridden to FAIL on any
hit; crash handling NEVER clobbers an artifact the CLI already wrote
(stamp the crash reason only into artifacts carrying no error of
their own); keep the CLI's captured output in `agent.log` beside the
artifact; retry a 0-iteration nonzero-exit crash ONCE (completed work
is never re-run or double-charged); validation via the moulinette's
own Docker eval (fresh container, pristine checkout); hold-outs via
`list_instances --repo-pattern "django|requests|scikit-learn|astropy"`.
Tuning: the 6 example-pool instances; categorize failures (exploration
waste, no test rerun before submit, patch context drift, budget
overruns); iterate; **final-prompt pool acceptance ≥4/6 within
limits, reproducible on re-draw**; ≥4 hold-outs recorded honestly;
intermediary metrics by hand on 3 traces (first read/edit of the
patched file; iterations between first green run_tests and
final_answer, target 0–1).
- [ ] Harness tests (provenance incl. a forged trace, screen hits and
      the prose false-positive case, preserve-on-crash, fail-closed).
      Devlog tables. ADR-0011 only if blocked imports appear. Commit.

---

# Phase 5 — Hardening, freeze, benchmark, delivery [ARCH leads] — T26–T32

### T26 [SYS+ARCH]: Red-team pass + allowlist audit

Attack the sandbox as if you were the exam: every T06 vector via
every reachable path, runtime-built names, fresh combinations.
**Expect to find things** — a battery passing is not proof; run
iterated adversarial review rounds (each round: fresh eyes, mandate =
concrete reproducible exploits, not speculation) until a round finds
nothing new; fix at the policy/data level with an empirical fence
(exploit fails, positive controls pass) for every finding. Allowlist
audit: for every authorized entry, grep its CPython source for
`import os/sys`, `subprocess`, `open(` and confirm the proxy covers
each exposure (record in ADR-0005's appendix). Regression: ≥10 MBPP
test-split tasks + 1 SWE-bench pool task still pass under final
rules.
- [ ] Battery extended with anything found; audit appendix; commit.

### T27 [AGT]: Unknown-server test

`tests/fixtures/odd_server.py` (hyphenated tool name, optional
params, a slow tool, a raising tool, a huge-output tool, zero
resources) + tests: both transports; stubs are valid identifiers; the
manual lists the odd tools; timeout → clear error; raise →
`[TOOL ERROR]`; huge → truncated; optional params callable with a
subset. No code changes needed to switch servers.
- [ ] Green. Commit.

### T28 [ARCH]: Quality pass + Linux validation + FREEZE

`make lint`/`make types` fully clean (justified `# type: ignore[code]`
+ comment only where unavoidable); docstrings/type hints on all public
functions; dead code removed; `make sandbox-tests-linux` green; ONE
bare-VM (non-container) Linux pass — process-group kill semantics can
differ under nested containers; record it. **Declare the freeze**:
from here, source changes require architect sign-off and restart
affected benchmark data; benchmarks run only on frozen code.

### T29 [ARCH+SHARED]: Benchmark matrix + ablation

Provider probe gates first (per candidate model): catalog → tiny call
+ usage honesty → ONE-task loop-compat run (**budget/logic FAIL with
real iterations = compatible; API-layer rejection = rejected**).
Matrix: ≥5 models × ≥2 providers × 3 SWE-bench tasks (≥1 never-tuned
hold-out); column-major by task, resume-safe across provider windows;
every run saved + validating; retries and window events recorded
(provider reliability); ≥2 intermediary metrics from saved traces
(script or by-hand tables, ambiguous cells marked). Ablation on a
CONFIG/CLI axis — e.g. `--max-iterations 30 vs 15`, same model, same
tasks — never a code change.
- [ ] Data + tables committed. ADR-0012 (model selection).

### T30 [SHARED]: BENCHMARK_REPORT.md

Six sections: Setup; Results table (pass/iterations/tokens/wall per
model×task); Provider reliability (windows, retries); Intermediary
metrics; Ablation; Conclusions (keep/drop with data). Every number
links to its artifact.

### T31 [SHARED]: README.md

First line: `*This project has been created as part of the 42
curriculum by <login1>, <login2>.*` Sections: Description;
Instructions (fresh clone → uv sync → .env → both agents with exact
dump/run/validate commands → sandbox REPL variants → make targets);
Resources (incl. AI usage → `docs/ai-usage.md`); System architecture;
Agent loop; Sandbox design (cite the ADRs); Tool implementation;
Benchmark results summary. A stranger can install and run from it.

### T32 [ARCH]: Final checks + defense rehearsal

`make lint/types/test` clean; key scan (`grep -rE "(sk-|API_KEY=)"
--exclude-dir=.git` → zero); `.env` untracked; no images/large
outputs; no labeled containers. Run the three exam flows (mbpp,
swebench, sandbox REPL) + SIGKILL container drill. Rehearse the
exam-day runbook (docs/grader-notes.md) end-to-end, timed ≤10 min.
Live-modification drill per member: 3 small changes (config knob, a
prompt line, an observation template), each ≤5 min, run one task,
revert, clean tree. Tag `v1.0`.

---

## Where to cut if behind (in order)

1. Extra benchmark models (keep the 5-model/2-provider minimum).
2. Hold-out breadth in T25 (keep ≥3).
3. Ablation scope (one simple axis).
4. **Never cut:** the security battery and its review rounds, the T02
   runbook, the freeze, the Linux validation, T32.
