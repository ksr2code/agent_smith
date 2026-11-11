# Grader notes — the example moulinette, observed

Study date 2026-11-11. Machine: macOS, uv 0.13.1, Docker 29.8.2,
CPython 3.10.19 (uv-managed). Moulinette venv resolved: pydantic
2.12.5, multiprocess 0.70.18, swebench 4.1.0, colorama 0.4.x (the
project venv carries pydantic 2.14.3; do not conflate them). Every
claim below is OBSERVED by running the commands, except sentences
marked "(from source)". The example moulinette is gitignored
reference material; nothing in it was edited — the two environment
quirks were routed around by a driver under gitignored `cache/`.

## Environment quirks of the example moulinette

1. The `moulinette_eval` console script cannot import the package on
   this machine. Its editable install ships only a dist-info entry —
   no path hook, no package files in site-packages — so the script
   dies with `ModuleNotFoundError: No module named 'moulinette'`
   unless the cwd happens to be the moulinette root. `quickstart.sh`
   calls the same script, so it is equally affected here. (Observed
   both ways; `uv run python -c "import moulinette"` works from the
   moulinette cwd because `python -c` puts cwd on sys.path.)
2. Even when importable, the CLI crashes at import with
   `AttributeError: type object 'ResourceTracker' has no attribute
   '__del__'`. Cause (from source): the optional shutdown-silencer in
   `moulinette/__main__.py` wraps `ResourceTracker.__del__`, but
   multiprocess 0.70.18 no longer defines `__del__`; the guard only
   catches ImportError. Workaround: define a no-op `__del__` before
   import — exactly the behavior the guard intends.

Lesson: the exam moulinette will pin its own versions on the exam
machine — budget one minute of the runbook to confirm the CLI starts
before anything time-critical depends on it.

## JSON formats (observed)

MBPP task dump (`dump mbpp --task-id 11`), keys in file order:

    task_id            int (11)
    task_definition    str  ("Write a python function to remove first
                        and last occurrence of a given character from
                        the string.")
    function_definition str ("def remove_Occ(s,ch):")
    test_imports       list[str] (observed: [])
    test_list          list[str] (observed: 2 asserts)

Key observations:

- `task_id` is an **int** in the task but a **str** in
  `SolutionOutput` ("MBPP task_id as string"). The `str()` conversion
  is OURS to do when saving the solution.
- The dump withholds the FIRST dataset test. Task 11 has 3 asserts in
  the dataset; the dump carries the last 2. Validation runs ALL tests
  (`skip_first_k_tests=0` — from source), so the withheld first test
  is the hidden one: passing every dumped test proves nothing.
- `test_imports` can be empty.

SWE-bench task dump (`dump swebench --task-id sympy__sympy-14711`):

    instance_id        str  ("sympy__sympy-14711")
    problem_statement  str  (observed 1070 chars)
    docker_image       str  ("swebench/sweb.eval.x86_64.sympy_1776_\
                        sympy-14711:latest")
    eval_script        str  (observed 1165 chars of bash)
    hints_text         str  (observed EMPTY)
    repo               str  ("sympy/sympy")

- `hints_text` may be empty — the prompt must not assume hints.
- `docker_image` names an **x86_64** eval image; the platform pin in
  our Docker work exists because of this.
- `eval_script` is a complete bash script (activates
  `/opt/miniconda3`, conda env `testbed`) — it is meant to be copied
  into the container and executed there.
- The Hugging Face dataset downloads on first `dump swebench`
  (worked on this machine; several minutes, one-time).

## Validation semantics (observed verbatim)

`validate` = three separate gates, in order:

1. **FORMAT** — `SolutionOutput.model_validate` at load. A schema
   violation crashes with a raw pydantic traceback BEFORE any banner
   (observed tail: `total_output_tokens ... Field required
   [type=missing, ...]`), exit 1. There is no pretty "invalid format"
   message — a traceback is the format signal.
2. **CORRECTNESS** — MBPP runs `solution + test_imports + ALL tests`
   in Docker: image `python:3.11-slim`, network disabled, 128 MB mem,
   50% CPU, 30 s exec timeout; the container is removed after every
   run (from source + observed). Note the grader judges MBPP
   solutions under **Python 3.11**, not our 3.10. On failure it
   prints the child traceback as `Correctness check detail:`
   (observed: `NameError: name 'remove_Occ' is not defined` for an
   empty solution).
3. **METRICS** — limits table + error list (texts below).

A format-valid solution that honestly failed still "validates" as
format-correct: metrics print VALID and `Overall` fails only on
correctness. Exit 0 iff correctness AND metrics both pass. The
literal pass marker is `Overall: PASSED` — plain text when output is
piped (observed: colorama strips ANSI on non-TTY streams here; on a
real terminal the line may carry color codes — our harness must
capture via pipe or strip ANSI, and match fail-closed).

Observed full run for the honest failed dummy (exit 1):

    ============================================================
    VALIDATING SOLUTION
    ============================================================
    Task ID: 11
    Benchmark: mbpp
    Success claimed: False
    ============================================================
    STEP 1: CORRECTNESS VALIDATION
    ============================================================
    Correctness check detail: Traceback (most recent call last):
      File "<string>", line 2, in <module>
    NameError: name 'remove_Occ' is not defined
    Correctness: FAILED
    ============================================================
    STEP 2: METRICS VALIDATION
    ============================================================
    Iterations: 1 / 10 OK
    Input tokens: 120 / 6000 OK
    Output tokens: 15 / 1500 OK
    Time: 4.2s / 120.0s OK
    Metrics: VALID
    ============================================================
    FINAL RESULT
    ============================================================
    Correctness: FAILED
    Metrics: VALID
    Overall: FAILED

A correct dummy solution (same shape, real `remove_Occ`) printed
`Correctness: PASSED`, `Overall: PASSED`, **exit 0** — the marker and
exit code verified live, not just read from source.

`--skip-metrics` difference (observed): the metrics table is replaced
by `(Metrics validation skipped)`, the FINAL RESULT block drops the
`Metrics:` line, and `Overall` reflects correctness alone.

Limit violations — one per dummy, steps consistent with totals
(observed error lines, verbatim; table rows mark the metric
`EXCEEDED`, `Metrics: INVALID`, exit 1):

    - Iterations 11 exceeds limit 10
    - Input tokens 7000 exceeds limit 6000
    - Output tokens 1600 exceeds limit 1500
    - Time 130.0s exceeds limit 120.0s

These lines print with a two-space dash prefix (`  - <text>`) and the
WARN/NOTE lines with a two-space prefix (`  WARN: <text>`),
color-wrapped on a TTY — match on the text, never assume exact
leading whitespace. The `Multiple model_names` set repr has
non-deterministic ordering; match on the prefix, not the full line.

`display` exits 0 for a valid solution file (missing file or invalid
JSON raises → non-zero). Consistency warnings observed verbatim:

    NOTE: Step 2: 1 LLM retries
    WARN: system_prompt is empty
    WARN: Step 2: timestamp 2026-11-11T12:00:01.000000 < previous 2026-11-11T12:00:05.000000
    WARN: Multiple model_names across steps: {'study/other', 'study/dummy'}
    WARN: Steps 1 and 2: identical sandbox_input (copy-paste?)
    WARN: Step 1: llm_output is empty

A clean trace prints `All checks passed`. The timestamp/model-name/
identical-input checks match the plan's honesty rules exactly —
traces we generate must satisfy them.

## run-agent kill behavior (observed)

- Fast command: child stdout passes through (`1`), then
  `Agent finished in 0.0s`, exit 0.
- Sleeping command under a 5 s limit:
  `Agent exceeded time limit (5s) — killed`, wall ≈6.0 s, **exit
  124** (GNU timeout convention). Mechanism (from source): the child
  runs in its own process group; SIGTERM to the group, SIGKILL after
  a 10 s grace. Anything our agent forks dies with it.

## Observed vs guaranteed

Treat as CONTRACT (copied or subject-stated): the pydantic schema
(models.py is the verbatim copy), the limits table (10/6k/1.5k/120 s
MBPP, 30/300k/10k/900 s SWE-bench), pass thresholds (4/5 MBPP,
2/3 SWE-bench), `--student-path` invocation, patch format, honesty
rules.

Treat as OBSERVED-ONLY (the exam moulinette may differ): every
printed string (banners, `Correctness check detail:`, the four limit
error texts, display WARN/NOTE wording), the exit-code convention
(124), the hidden-first-test split, the Docker parameters of MBPP
correctness (image/version, 30 s), the colorama/ANSI behavior, and
both environment quirks. Re-verify all of these on exam day via the
runbook below — our tooling matches on `Overall: PASSED` fail-closed.

SWE-bench VALIDATION IS DEFERRED: `validate swebench` pulls
multi-GB eval images and was intentionally not run in this study.
It is first exercised by the real SWE-bench run (T24 hard gate,
before any M4 tuning) — NOT verified here. Docker itself is proven
on this machine (MBPP correctness container + sandbox-tests-linux).

## Exam-day runbook (≤10 minutes)

1. (1 min) `cd moulinette && uv sync`; confirm the CLI starts:
   `uv run python -c "from moulinette.__main__ import main"`. If the
   ResourceTracker AttributeError appears, define a no-op `__del__`
   on ResourceTracker before importing (the pattern documented in
   quirk 2 above). This runbook assumes the same working directory —
   with `moulinette/` present — is carried to the exam machine.
2. (2 min) Dump one MBPP and one SWE-bench task (specific IDs).
   Diff each file's keys against `MBPPTaskInput` /
   `SWEBenchTaskInput` in models.py. Re-check the hidden-test split
   (dumped test count < dataset count for the same task).
3. (2 min) Dummy-validate one MBPP solution; READ the enforced
   limits back from the STEP 2 table (trust the validator, not our
   docs) and re-verify a passing dummy prints `Overall: PASSED` and
   exits 0.
4. (1 min) Confirm the invocation: cwd and command shape from
   quickstart.sh — `uv run python -m agent_mbpp --task-file <abs>
   --output <abs> --model-name <m> --provider-url <u>` under
   `run-agent <limit>`; confirm `--student-path` points at our repo
   root (flat layout, ADR-0010).
5. (1 min) Container hygiene: after any validate/run, check
   `docker ps -a` — the grader removes its own containers; assert
   none of OURS remain (`agent-smith` label filter empty).
6. (1 min) `docker images | grep sweb.eval` — if exam-machine images
   are NOT pre-cached, assume the agent's own ~600 s pull budget
   inside the 900 s kill clock (T24 abort-gracefully path).
7. (2 min) Buffer: `display` the dummy and eyeball the STEP-BY-STEP
   TRACE — this is what the corrector sees; our StepMetrics must
   look complete and monotonic in this exact view.
