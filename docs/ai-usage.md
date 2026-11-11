# AI usage

Meaningful AI assistance recorded per docs/planning/TEAM_WORKFLOW.md §9.
Entries record where AI helped detect and solve issues, suggested
solutions, or shaped planning — not implementation detail.

| Date | Task | What AI helped with | What we changed |
|---|---|---|---|
| 2026-11-11 | T01 repo skeleton | A review pass caught a non-discriminating test in the skeleton suite: the sandbox template test pinned the allowlist entry count rather than membership, so a wrong entry (e.g. an allowlisted `shutil`) would pass unnoticed. The test was strengthened to exact-membership + uniqueness + int-type checks and verified by mutation before merge. | Verified the fixed template test discriminates; accepted. |
| 2026-11-11 | T02 grader study | Analysis of the example grader surfaced facts that shaped the design: the MBPP dump withholds the first dataset test (passing all dumped tests proves nothing), MBPP solutions are graded under Python 3.11 while we develop on 3.10, and two moulinette environment quirks (broken console script on editable installs; a multiprocess 0.70.18 import crash) that the exam-day runbook now handles. A verification pass also caught a pydantic version misattribution in our notes (the grader venv is 2.12.5, not the project venv's 2.14.3). | Corrected the pydantic version attribution (2.12.5) after the review finding. |
| 2026-11-11 | T03–T05 design checks | Source verification settled a design assumption: the example grader trusts reported token totals and never recomputes them from steps — so totals are computed from step data by construction and would survive a stricter exam grader. A protocol design review caught two blockers in the worker protocol before any implementation existed: a final-answer slot that would leak across execs (wedging the loop after a rejected final) and an unspecified tool-stub naming side (an unknown server tool named `final_answer` would shadow the sandbox's own). | Designed the fixes (slot reset, stub-naming rules) into docs/protocol.md before implementation. |
