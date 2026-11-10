*This project has been created as part of the 42 curriculum by ksmailov, wehan.*

# Agent Smith

An autonomous coding agent: an LLM writes Python, a restricted sandbox
executes it, tools reach the repository through MCP, and a
Thought → Code → Observation loop repeats until `final_answer()` —
solving MBPP tasks and real SWE-bench bugs within strict resource
limits.

**Status:** work in progress — see the plan documents below.

## Documentation

- `docs/planning/PROJECT_PLAN.md` — vision, decisions (ADR program), milestones, risks
- `docs/planning/IMPLEMENTATION_PLAN.md` — task-by-task specification and acceptance gates
- `docs/planning/TEAM_WORKFLOW.md` — how we work: ownership, reviews, routine

## Setup (placeholder — expanded as the project grows)

uv sync
make test
