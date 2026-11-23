# ADR index

| Number | Title | Status |
|---|---|---|
| 0001 | Restricted worker subprocess as the sandbox isolation unit | Accepted |
| 0002 | MCP client in the parent, tool stubs in the worker | Accepted |
| 0007 | Async MCP SDK on a dedicated thread with a synchronous bridge | Accepted |
| 0010 | Keep code packages at the repository root (no nested student/ directory) | Accepted |
| 0013 | Role assignments and task-ownership moves | Accepted |
| 0014 | Typed interface contracts and the task-deadline model | Accepted |

0001–0009 and 0011–0012 are pre-aligned in
docs/planning/PROJECT_PLAN.md §2 and become ADR files in the tasks
noted in docs/planning/IMPLEMENTATION_PLAN.md.

sandbox_template.json is the subject's default allowlist plus one
documented addition (`_strptime` — CPython's datetime.strptime
imports it through the caller's import hook; full rationale recorded
with ADR-0005).
