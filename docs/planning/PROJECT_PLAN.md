# Agent Smith — Project Plan

> Strategy layer: tasks live in docs/planning/IMPLEMENTATION_PLAN.md,
> daily routine in docs/planning/TEAM_WORKFLOW.md.

Team: 2 people. Tracking: GitHub Issues per milestone gate. Linting
and type checking run by hand (no hooks, per the subject). This plan
is the starting point; adjust it as you learn — and record *why* in
ADRs when a decision changes.

## Contents

1. Vision and principles
2. Key decisions (the ADR program)
3. Milestones and task catalog
4. Working with ADRs
5. Risks and checklists

## 1. Vision and principles

**Goal.** Build an agent framework where an LLM writes Python code, a
restricted sandbox runs it, tools reach the repository through MCP,
and the loop (Thought, Code, Observation) repeats until
`final_answer()` is called. Graded on MBPP (≥4 of 5), SWE-bench
(≥2 of 3), sandbox security tests (all), standalone tool correctness,
the benchmark report, code quality, and a live defense.

- Build vertical slices: MBPP end to end first, SWE-bench second.
- Prove it works with the strongest model and no limits, then add the
  limits.
- Build to the subject as the contract; the provided moulinette is an
  example — the exam one may differ. Verify the real one with the
  exam-day runbook before graded runs.
- Every component is testable on its own (the grader tests tools and
  the sandbox independently, without our Docker setup).
- Both members must be able to explain and modify any part — the
  defense includes live changes per person.
- Every test must discriminate: it fails on a wrong implementation,
  not only passes on the right one.
- Timeouts are kills, not checks: every budget stops early so the
  submission lands before the deadline.
- Honesty by construction: totals from the enforcing numbers,
  fail-closed validation, labeled repairs, artifact-backed results.
- Write decisions down when you make them (ADRs), not at the end.
- No automatic lint or type gates; write typed, documented code as
  you go and run ruff (79 columns) and mypy by hand at milestone
  gates.
- Never depend on our own process surviving: the grader kills it.

## 2. Key decisions (the ADR program)

These are pre-aligned proposals so ADR writing is ratification, not
debate from zero. Each becomes an ADR (numbering fixed) in the phase
noted in docs/planning/IMPLEMENTATION_PLAN.md.

| # | Topic | Decision | Core rationale |
|---|---|---|---|
| 0001 | Sandbox isolation | Restricted worker subprocess | Killable on timeout, own memory limit, crash isolation; in-process exec cannot be killed reliably; docker-per-run is slow and Python-level rules are required anyway |
| 0002 | MCP client location | In the parent; stubs in the worker | The worker must not open sockets; tool time is not sandbox time (deadline suspended and extended by call duration) |
| 0003 | SWE-bench layout | Host sandbox + tools bridging into Docker | Local-first tools already work standalone; the host keeps control; allowed_directories stay nominal |
| 0004 | Action format | Python code blocks primary; converters for XML/Hermes JSON/ReAct | Required breadth across models; repairs always labeled |
| 0005 | Imports policy | Gate (exact-name or explicit `root.*`, fromlist guard) + default-deny attribute policy + module proxies + format rewrite | Blacklists always have gaps; capability tables + a dynamic enumeration test make leaks caught by construction |
| 0006 | LLM access | OpenAI-compatible client behind our interface; canonical-name → per-provider alias map; multi-key rotation | Provider switching without changing the model name mid-run; honest usage accounting |
| 0007 | Async bridge | MCP SDK session on a dedicated thread; sync bridge via run_coroutine_threadsafe | The SDK is async; the sandbox world is synchronous |
| 0008 | Container cleanup | Self-destructing `--rm` containers (timeout N sleep infinity), labels, startup sweep, fast SIGTERM handler | SIGKILL is uncatchable — cleanup must never depend on the agent surviving |
| 0009 | SWE-bench tool environment | Tools run locally on TESTBED_PATH by default; Docker via AGENT_CONTAINER env | The grader tests tools standalone, before and without our Docker setup |
| 0010 | Repository layout | Code packages at the repo root, no nested student/ directory | `python -m agent_mbpp` and `uv run sandbox` must resolve from the repo root the grader runs in |
| 0011 | Allowlist changes | Only via ADR; never allowlist modules that open files or execute code | `io`, `codecs`, `tempfile`, `pickle`, `shelve` are permanently out |
| 0012 | Model selection | From benchmark evidence (T29) | Keep/drop with data |

## 3. Milestones and task catalog

Gates M0–M5 with their acceptance evidence are defined in
docs/planning/IMPLEMENTATION_PLAN.md. Compact catalog (owner: A = architect/agent
side, B = systems side, S = shared; sizes S ≈ hours, M ≈ a day,
L ≈ two days):

| ID | Title | Size | Owner | Depends on |
|---|---|---|---|---|
| T01 | Repo, tooling, skeleton | S | S | – |
| T02 | Study the example moulinette + runbook | S | A | T01 |
| T03 | Models + solution IO | S | A | T01 |
| T04 | Worker protocol spec + ADR-0001/0002 | S | A | T03 |
| T05 | MCP SDK pin on 3.10 (ADR-0007) | S | A | T01 |
| T06 | Security battery, written first (red) | M | B | T03 |
| T07 | Worker core + attribute policy (ADR-0005) | L | B | T06 |
| T08 | SandboxProcess (parent side) | M | B | T07 |
| T09 | Sandbox REPL CLI | S | B | T08 |
| T10 | SWE-bench tools, local mode (ADR-0009) | L | A | T05 |
| T11 | MBPP run_tests tool | S | A | T05 |
| T12 | MCP client manager + stubs | L | A | T08, T10 |
| T13 | Tool result formatting | S | A | T12 |
| T14 | Dynamic sandbox manual | S | A | T12 |
| T15 | LLM client, keys, usage (ADR-0006) | M | A | T01 |
| T16 | Code extractor (ADR-0004) | M | A | – |
| T17 | System prompts | M | A | T14 |
| T18 | Agent loop + budget | L | A | T15, T16, T17 |
| T19 | MBPP CLI — `validate mbpp` PASSED | S | A | T18 |
| T20 | MBPP harness + tuning to ≥80% | L | A | T19 |
| T21 | SWE-bench layout (ADR-0003) | S | A | T12 |
| T22 | Docker lifecycle + cleanup (ADR-0008) | M | B | T02 |
| T23 | SWE-bench tools, Docker mode | L | B | T10, T22 |
| T24 | SWE-bench CLI + real-run hard gate | M | A | T18, T23 |
| T25 | SWE-bench harness + tuning to ≥4/6 | L | A+B | T24 |
| T26 | Red-team pass + allowlist audit | M | B+A | T07, T20, T25 |
| T27 | Unknown-server compatibility | M | A | T13 |
| T28 | Quality pass + Linux + FREEZE | M | A | T25 |
| T29 | Benchmark matrix + ablation | L | A+S | T28 |
| T30 | BENCHMARK_REPORT.md | M | S | T29 |
| T31 | README.md | M | S | T29 |
| T32 | Final checks + defense rehearsal | M | A | all |

Parallel waves after T04: B runs T06→T07→T08→T09 while A runs
T10/T11/T15/T16, then T12→T13→T14→T17; B may pull T22 forward
right after T08 (Wave 2b) so Docker work overlaps A's client tasks.

## 4. Working with ADRs

An ADR records one important decision: context, options, the choice,
the consequences. Write one when the decision is hard to change, had
real alternatives, or a reviewer could ask "why not X?". Not for
choices code review already covers.

Process: `docs/adr/NNNN-short-title.md` (number in order, never reuse)
→ Status: Proposed, in a PR containing only the ADR → discuss and
challenge → both agree → Accepted (merge). Rejected ADRs stay on
disk. Never rewrite an accepted ADR: supersede it with a new number.
Keep `docs/adr/README.md` as the index.

Template:

```markdown
# ADR-NNNN: <title as a decision>
- Status: Proposed | Accepted | Rejected | Superseded by ADR-XXXX
- Date: YYYY-MM-DD
- Deciders: <both>
## Context
## Options considered
## Decision
## Consequences
```

## 5. Risks and checklists

| Risk | Mitigation |
|---|---|
| Free-tier quota windows stall tuning/benchmarks | ≥2 providers with multiple keys; request pacing; resume-safe batches; start benchmark runs early |
| Security gaps discovered late | Battery first (T06, red); iterated adversarial review rounds in T26 until a round finds nothing new; capability tables + enumeration test by construction |
| macOS ≠ Linux semantics (memory limits, kills) | `make sandbox-tests-linux` authoritative from T07; one bare-VM pass in T28 |
| Prompt overfits to tuned instances | Tune on train/pool; hold-out instances in T25/T29; tune the loop, not per-task |
| Exam moulinette differs from the example | Build to the subject; limits configurable; exam-day runbook rehearsed (T02/T32) |
| Wall-clock overruns (kills, not checks) | 90% token margins; time reserve; submit-before-deadline prompt rules |
| Review bottleneck with 2 people | Ownership map + cross-review; small PRs; gates, not per-task ceremonies |
| AI-assisted code nobody understands | Cross-half walkthroughs; nothing commits that either member cannot explain; every member reads what they merge |

**Pre-submission checklist**

- [ ] No keys in code or git history; `.env` ignored.
- [ ] README first line correct, in English, both logins.
- [ ] BENCHMARK_REPORT.md present, every number artifact-backed.
- [ ] `uv run sandbox` works with all CLI variants; no orphan processes.
- [ ] Both agents run with the moulinette and respect the limits.
- [ ] No labeled Docker containers after runs, SIGTERM, or SIGKILL.
- [ ] Exam-day runbook rehearsed ≤10 min; reasoning tokens in totals.
- [ ] MCP tools standalone with any TESTBED_PATH; unknown server works.
- [ ] Repo free of Docker images and large generated outputs.
- [ ] `make lint`, `make types`, `make test` clean; freeze respected.
- [ ] Both members can explain and live-modify any module.
