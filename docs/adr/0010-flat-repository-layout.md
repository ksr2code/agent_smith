# ADR-0010: Keep code packages at the repository root (no nested
# student/ directory)
- Status: Proposed
- Date: 2026-11-11
- Deciders: A + B (pre-aligned in PROJECT_PLAN §2, committed 95c6169) (pending joint ratification)

## Context

The exam scripts invoke the student tree with
`--student-path ./student`, and the subject's examples run
`uv run python -m agent_mbpp ...` and `uv run sandbox ...` from
inside the student checkout. For grading, our repository root IS
that checkout: the grader runs the commands against our repo. uv and
hatchling resolve console scripts and `-m` modules from the project
root the grader runs in — so `pyproject.toml` must sit in exactly
the directory the grader points at.

## Options considered

(a) A nested `student/` directory inside the repo: packages one
    level down, plus a top-level `pyproject.toml` reaching into it,
    or symlinks/wrapper directories to stitch the two views
    together.

(b) Packages (`sandbox/`, `agent/`, `llm/`, `mcp_client/`) and the
    root-level entry modules (`agent_mbpp.py`, `agent_swebench.py`,
    `mcp_tools_*.py`) at the repository root, with `pyproject.toml`
    beside them.

## Decision

Option (b) — the flat layout. `python -m agent_mbpp`,
`python -m agent_swebench` and the `sandbox` console script all
resolve from the repository root, which is exactly the path the
grader passes as `--student-path`.

## Consequences

- The root `pyproject.toml` must keep the packages declared, and add
  the py-modules (`models.py`, `solution_io.py`) as their files
  land, so `uv sync` installs everything the exam commands invoke.
- The grader's `--student-path` is satisfied by pointing at the repo
  itself; this is verified in the exam-day runbook (grader-notes
  task, T02).
- No symlinks or wrapper directories are needed — nothing extra to
  break on the exam machine.
