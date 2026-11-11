# Team Workflow Guide

For: the Agent Smith team — 2 people with defined roles. Read once
from top to bottom; then use §3 as the daily routine.

## 0. The big picture in one minute

- We build an agent: an LLM writes Python, a restricted sandbox runs
  it, tools reach the repository through MCP, and the loop repeats
  until `final_answer()` is called.
- **Roles are asymmetric by design** (see docs/planning/IMPLEMENTATION_PLAN.md
  "Roles and ownership"): one architect + agent-side implementer, one
  systems-side implementer. The authority ladder: both of us together
  → architect (technical direction) → each owner inside their half.
- Work is organized into **milestones with acceptance gates**
  (M0–M5). Inside a milestone, each person works their own half.
- Code reaches `main` only through pull requests, and **the author
  never reviews their own code** — every PR is reviewed by the other
  member.
- Design decisions are ADRs in `docs/adr/`, accepted after PR
  discussion.
- Linting and type checking run by hand (ruff at 79 columns,
  flake8-conformant, mypy) — no hooks (a team choice; the subject
  requires readable, structured, documented code, nothing more); the
  config is correct from day one so "clean" is the default.
- The provided moulinette is an example; the exam one may differ. We
  build to the subject and verify with the exam-day runbook before
  any graded run.

## 1. One-time setup (each person)

1. Clone the repo; install Python 3.10 and `uv`; run `uv sync`.
2. `cp .env.example .env` and fill your API keys. Never commit
   `.env` (it is gitignored). Never paste keys into code, issues,
   chats or logs.
3. `make test` → green.
4. `git config user.name/user.email` with your real identity.
5. Read, in order: `docs/planning/IMPLEMENTATION_PLAN.md` (roles, design
   principles, your half's tasks), this file, `docs/planning/PROJECT_PLAN.md`
   (strategy and the decisions you will ratify as ADRs).

## 2. Ownership map

| Area | Owner | Reviewer |
|---|---|---|
| `sandbox/*`, `docker_env.py`, security battery, docker tool mode | Systems owner | Architect |
| `llm/`, `agent/`, `mcp_client/`, both CLIs, `mcp_tools_mbpp.py`, `models.py`/`solution_io.py` | Architect (agent side) | Systems owner |
| `mcp_tools_swebench.py` | Shared (formats: agent side; docker mode: systems) | The other owner |
| `docs/protocol.md` and the five interface contracts | Architect | Systems owner |
| ADRs, milestone specs, acceptance gates, runbook, freeze | Architect | Both discuss in the PR |
| `benchmarks/` + devlogs, README | Shared | Architect accepts |

Rules:
- One milestone task in flight per person on their own half.
- **Interfaces are the architecture.** Anything touching
  `docs/protocol.md`, `SandboxProcess`/`ExecutionResult`, `ToolInfo`,
  `LLMClient`/`LLMResponse`, or `ExtractionResult` needs the
  architect's sign-off before implementation — that is how direction
  stays controlled without controlling every task.
- Questions inside a half belong to that half's owner. Disagreements
  cross-cutting both halves go to the architect; grading/scope
  decisions go to both.

## 3. Daily routine (one task)

1. Pick the next task **in your area** from the current milestone.
2. Branch from `main`: `git switch -c feat/sys-security-battery` (or
   `feat/agt-llm-client`, `docs/…`, `test/…`).
3. Work in small steps. Where the plan gives TDD steps, write the
   failing test first and watch it fail. Commit after every green
   cycle (`type: description` — `feat`, `fix`, `test`, `docs`,
   `refactor`, `chore`). Never leave the tree red overnight; **the
   one sanctioned exception** is T06's red security battery, which
   lives on its feature branch (never on `main`) until T07 turns it
   green.
4. Before pushing: `make test` (plus `make sandbox-tests` for
   sandbox-adjacent work). Run `ruff format <file>` on what you
   wrote.
5. Push and open a PR early (draft is fine). Description: what
   changed, why, how to test, `Closes #<issue>` if one exists.
6. Ask the other member to review. Move the issue to review.
7. Fix every comment (answer each, even with "done"), re-run tests,
   wait for approval, merge (squash default), delete the branch.

## 4. Reviews

As the reviewer, check in this order:
1. **Correctness:** does it do what the task says, in the subject's
   exact pinned formats?
2. **Security** (sandbox half especially): could this let code escape
   the sandbox, reach files outside the allowed roots, or leak keys?
3. **Tests:** normal, edge and failure cases — and does each test
   **discriminate** (would it fail on a wrong implementation)? The
   plan states which wrong implementation each critical test
   discriminates; verify that claim.
4. **Readability:** type hints, docstrings, names, no dead code.
   Nothing checks style automatically — the review is where it is
   caught.
5. **Understanding:** can you explain this code without the author?
   If not, ask for a walkthrough. This matters most: the defense
   includes live changes to the code **per person**.

Approve only when comfortable. Leave specific comments ("this check
misses `..`"), not vague ones.

## 5. Milestone gates (the weekly rhythm anchors here)

- Each milestone ends with a **gate**: the owners present evidence
  (test output, validation verdicts, devlog rows, artifact paths);
  the architect verifies against the plan's gate table and accepts or
  bounces it. Evidence is checked against the repo (diffs, artifacts,
  command output), not against the summary. **Countersign rule:**
  a gate covering the architect's own implementation work (M2–M4
  contain it) is co-accepted by the systems owner — the
  author-never-reviews rule applies to gate acceptance too.
- After each gate: `make lint && make types` on the milestone's diff;
  a 20-minute retro (what slowed us down → one line in
  `docs/log.md`).
- **At every gate exit: one cross-half walkthrough** (alternate who
  explains) — the explainer presents a module from the *other*
  half, unaided. If it is unclear, review it together. This is
  defense training on a schedule, not an optional ritual: both
  members must be able to explain and modify any module live.
- **Freeze rule** (after the quality pass, before benchmarks): source
  changes need architect sign-off and restart affected benchmark
  data. The benchmark report must describe the exact code the repo
  ships.

## 6. Checks (manual, no hooks)

Before every push: `make test` (+ `make sandbox-tests` for
sandbox-adjacent work). At milestone ends: `make lint`, `make types`.
Sandbox/memory/kill results are authoritative only from
`make sandbox-tests-linux` (macOS does not enforce `RLIMIT_AS`) plus
one bare-VM pass before delivery. Benchmarks are never run
automatically (this project has no CI) and never on unfrozen code.

## 7. ADRs

`docs/adr/NNNN-short-title.md`. Write one when the decision is hard
to reverse, had real alternatives, or a reviewer could ask "why not
X?". Process: draft with Status: Proposed → PR containing only the
ADR → discuss and challenge → Accepted (both agree; the architect
finalizes) → link from related issues. Never rewrite an accepted ADR:
supersede it. Keep `docs/adr/README.md` as the index. First ADRs:
0001 subprocess sandbox, 0002 MCP client in the parent, 0003
SWE-bench layout, 0004 action formats, 0005 imports policy (with the
security tables), 0006 LLM access, 0007 async bridge, 0008 container
cleanup, 0009 tools local-first, 0010 flat layout.

## 8. Project rules that come from the subject

Breaking any of these can fail the project:
- Python 3.10 and `uv` only. No agent-orchestration libraries. No
  RestrictedPython — the sandbox is standard library only.
- Our two MCP servers at the repository root; the system must also
  work with an unknown MCP server (stdio AND streamable HTTP).
- API keys only from environment variables or `.env`. A hardcoded
  key is a security failure.
- Limits: MBPP 10 iterations / 6,000 input / 1,500 output / 120 s;
  SWE-bench 30 / 300,000 / 10,000 / 900 s — cumulative, reasoning
  tokens count, enforced by kill.
- The agent must never fetch solutions from PRs, issues or the web;
  never feed it reference solutions or gold patches — graded tests
  include tests the agent never saw.
- Patch: `git add -A -N` then `git -c core.fileMode=false diff`; clean
  up Docker containers after SWE-bench runs.
- README in English, first line the italic 42 sentence with **both
  logins**. Code readable, structured, documented and typed.

## 9. Using AI responsibly

- AI assistance is allowed and useful; we make the decisions. Read
  and understand everything before committing — if you cannot explain
  it, rewrite it or ask your partner.
- Record meaningful uses in `docs/ai-usage.md`: date, task, what AI
  helped with, what we changed.
- Do not commit code that either of us cannot explain — the defense
  includes live modification per person, and the ownership map exists
  so "can explain any part" is trainable (§5 walkthroughs).

## 10. Quick reference

| I want to… | Do this |
|---|---|
| Start work | Next task in my area from the current milestone; branch `feat/<area>-<name>` |
| Get reviewed | PR → other member reviews → merge (author never reviews own code) |
| Report a bug | Issue: what happened, expected, reproduce command |
| Record a decision | ADR PR (Proposed → discuss → Accepted) |
| Change an interface contract | Architect sign-off BEFORE implementation |
| End a milestone | Gate evidence to the architect; retro line in `docs/log.md` |
| Run checks | `make test` always; `make lint && make types` at gates; `make sandbox-tests-linux` authoritative |
| See what is left | The plan's milestone table + gate evidence |

## 11. Troubleshooting

- **`uv sync` fails on `mcp`:** Python must be 3.10; `mcp` is pinned
  `<2` (ADR-0007).
- **Provider rate limits:** rotate keys, respect the request pacing,
  resume the batch in the next window — never silently shrink the
  sample.
- **Leftover containers:** `docker ps -a --filter label=agent-smith=1`;
  `make clean-containers`.
- **mypy/ruff pile-up:** fix at the milestone gate, not "later".
- **Merge conflict:** preserve both sides' intent, re-run
  `make test`, mention it in the PR.
- **Unsure who owns a piece of work:** §2 map; else the architect
  decides.

## 12. Glossary

- **Agent loop:** the repeated cycle Thought → Code → Observation.
- **Sandbox / worker:** the restricted subprocess executing the
  LLM's Python.
- **MCP:** Model Context Protocol — the connection between the agent
  and its tools; our servers expose the nine SWE-bench tools (one of
  which is SWE-bench's own `run_tests`) plus the MBPP server's
  separate `run_tests`.
- **MBPP / SWE-bench:** the two graded benchmarks.
- **ADR:** architecture decision record. **Gate:** milestone
  acceptance with evidence. **Freeze:** no source changes without
  architect sign-off once benchmarking starts.
