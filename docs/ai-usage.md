# AI usage

Meaningful AI assistance recorded per docs/planning/TEAM_WORKFLOW.md §9.
Dates, tasks, what AI helped with, and what we changed.
Entries record the significant contributions (review findings, plan
issues, design decisions) rather than routine implementation detail.

| Date | Task | What AI helped with | What we changed |
|---|---|---|---|
| 2026-11-11 | T01 repo skeleton, tooling, ADR-0010 | AI implemented the skeleton per the implementation plan; an independent AI review pass caught a non-discriminating template test (pinned entry count, not membership) — fixed before merge. | _(to be completed by A)_ |
| 2026-11-11 | T02 moulinette study, models.py, grader notes | AI ran the grader study: models.py provenance copy, grader notes + exam-day runbook. Findings: the hidden first MBPP test, MBPP solutions graded under Python 3.11 (we develop on 3.10), two moulinette environment quirks. An independent AI review source-verified every contract string against the moulinette source and caught a pydantic version misattribution. | _(to be completed by A)_ |
| 2026-11-11 | T03–T05 solution IO, MCP pin, worker protocol | AI implemented solution_io (source-verifying en route that the example grader trusts reported totals and never recomputes them), pinned mcp 1.30 with both transports verified on 3.10, and drafted the worker protocol + ADR-0001/0002. An independent AI review of the protocol seam caught two blockers before any implementation existed: a stale final-answer slot that would wedge the loop after a rejected final, and an unspecified stub-naming side that would let a server tool shadow final_answer. | _(to be completed by A)_ |
