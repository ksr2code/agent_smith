# Task tracker

Source of truth for task and gate status. GitHub Issues are not used;
if a remote/PR workflow starts later, gates may be mirrored to a
GitHub milestone board — until then this file is authoritative.

Update rules: the row is updated in the same commit (or the merge
commit) that changes the task's state. Statuses: todo | in-progress |
blocked | waiting | done. Evidence points at commits and commands,
never at summaries. Owners: A, B, S (shared) per the implementation
plan. This file records state only — how work is produced is not
tracked here.

## Gates

| Gate | Target | Status | Open items |
|---|---|---|---|
| M0 | 2026-11-13 | waiting | docs/protocol.md review by BOTH members; then one retro line in docs/log.md |
| M1 | 2026-11-20 | todo | — |
| M2 | 2026-11-27 | todo | — |
| M3 | 2026-12-04 | todo | — |
| M4 | 2026-12-16 | todo | — |
| M5 | 2026-12-29 | todo | — |

(Target dates and cut-line live in docs/planning/IMPLEMENTATION_PLAN.md
under "Milestones and gates" — that section stays authoritative.)

## Tasks

| ID | Task | Owner | Status | Evidence / notes |
|---|---|---|---|---|
| T01 | Repo, tooling, skeleton | S | done | merged to main (95d0dfb..e30f2db); pytest 5/5, lint/types clean; ADR-0010; docker Linux path proven |
| T02 | Study the example moulinette + runbook | A | done | merged (5430572..5103f0b); docs/grader-notes.md; models.py byte-provenance test; pydantic 2.12.5 correction |
| T03 | Models + solution IO | A | done | merged (9550a84); totals formula source-verified vs example grader |
| T04 | Worker protocol spec + ADR-0001/0002 | A | done | merged (e9d1646, c95ea5c); docs/protocol.md v1 — both-member review pending (see M0) |
| T05 | MCP SDK pin on 3.10 | A | done | merged (ac4e610, 8a9d9c7); mcp 1.30.0, both transports as committed tests |
| T06 | Security battery, written first (red) | B | todo | unblocked (T03 merged); lives on a branch, never on main, until T07 greens it |
| T07 | Worker core + attribute policy | B | todo | — |
| T08 | SandboxProcess (parent side) | B | todo | — |
| T09 | Sandbox REPL CLI | B | todo | — |
| T10 | SWE-bench tools, local mode | A | todo | — |
| T11 | MBPP run_tests tool | A | todo | — |
| T12 | MCP client manager + stubs | A | todo | needs T08 + one server |
| T13 | Tool result formatting | A | todo | — |
| T14 | Dynamic sandbox manual | A | todo | — |
| T15 | LLM client, keys, usage | A | todo | — |
| T16 | Code extractor | A | todo | no dependencies |
| T17 | System prompts | A | todo | after T14 |
| T18 | Agent loop + budget | A | todo | critical path |
| T19 | MBPP CLI | A | todo | critical path |
| T20 | MBPP harness + tuning ≥80% | A | todo | critical path |
| T21 | SWE-bench layout ADR-0003 | A | todo | — |
| T22 | Docker lifecycle + cleanup | B | todo | may be pulled forward after T02 study |
| T23 | SWE-bench tools, Docker mode | B | todo | — |
| T24 | SWE-bench CLI + hard gate | A | todo | critical path |
| T25 | SWE-bench harness + tuning ≥4/6 | A+B | todo | critical path |
| T26 | Red-team pass + allowlist audit | B+A | todo | never cut |
| T27 | Unknown-server compatibility | A | todo | — |
| T28 | Quality pass + Linux + FREEZE | A | todo | critical path |
| T29 | Benchmark matrix + ablation | A+S | todo | critical path |
| T30 | BENCHMARK_REPORT.md | S | todo | — |
| T31 | README.md | S | todo | — |
| T32 | Final checks + defense rehearsal | A | todo | never cut |
