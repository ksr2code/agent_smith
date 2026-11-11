"""Task loading and solution saving for the grader's JSON contract.

Helpers live here; the model classes live in models.py (the verbatim
grader copy — never edit it). This module is the single source of the
totals formula and of the task-dump dispatch rules.
"""

import json
from collections.abc import Sequence
from pathlib import Path

from models import (
    MBPPTaskInput,
    SolutionOutput,
    StepMetrics,
    SWEBenchTaskInput,
)

Task = MBPPTaskInput | SWEBenchTaskInput


def load_task(path: Path | str) -> Task:
    """Load a task JSON and dispatch on its distinguishing keys.

    MBPP dumps carry an int ``task_id``; SWE-bench dumps carry a
    string ``instance_id`` (docs/grader-notes.md). A file with
    neither key — or with both — is malformed and raises ValueError
    naming the file; we never guess a benchmark.
    """
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError(
            f"{path}: task JSON must be an object, got {type(data).__name__}"
        )
    has_instance = "instance_id" in data
    has_task_id = "task_id" in data
    if has_instance and has_task_id:
        raise ValueError(
            f"{path}: has both 'task_id' and 'instance_id'; cannot dispatch"
        )
    if has_instance:
        return SWEBenchTaskInput.model_validate(data)
    if has_task_id:
        return MBPPTaskInput.model_validate(data)
    raise ValueError(
        f"{path}: has neither 'task_id' (MBPP) nor 'instance_id' (SWE-bench)"
    )


def save_solution(sol: SolutionOutput, path: Path | str) -> None:
    """Write the solution as indent=2 JSON with a trailing newline.

    Creates missing parent directories; the trailing newline keeps
    grader-side diffs and terminal reads clean.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(sol.model_dump_json(indent=2) + "\n", encoding="utf-8")


def totals_from_steps(steps: Sequence[StepMetrics]) -> tuple[int, int, int]:
    """Return ``(total_input, total_output, total_requests)``.

    SINGLE SOURCE OF TRUTH: ``total_requests = len(steps) +
    sum(retries)`` — one request per step plus one per retry. Verified
    from the example moulinette source (2026-11-11): validate_metrics
    (moulinette/moulinette/__main__.py) delegates to
    MetricsValidationResult.validate_solution
    (moulinette/moulinette/models.py), which compares only the
    REPORTED top-level fields against the limits and never recomputes
    totals from steps; the example grader does not check
    ``total_requests`` at all. We keep the formula exact and here so
    reported totals are honest by construction and can never drift
    from a duplicated copy — never recompute totals elsewhere.
    """
    total_input = sum(step.input_tokens for step in steps)
    total_output = sum(step.output_tokens for step in steps)
    total_requests = len(steps) + sum(step.retries for step in steps)
    return total_input, total_output, total_requests
