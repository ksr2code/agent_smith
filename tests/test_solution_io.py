"""Tests for solution_io: save/reload round-trip, task dispatch,
contract strictness, and the single-source totals formula."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from models import (
    MBPPTaskInput,
    SolutionOutput,
    StepMetrics,
    SWEBenchTaskInput,
)
from solution_io import load_task, save_solution, totals_from_steps


def _two_step_solution() -> SolutionOutput:
    """A failed two-step run: step 1 clean, step 2 with 2 retries."""
    return SolutionOutput(
        task_id="11",
        benchmark="mbpp",
        success=False,
        solution="",
        iterations=2,
        total_input_tokens=300,
        total_output_tokens=45,
        total_time_seconds=8.0,
        total_requests=4,
        steps=[
            StepMetrics(
                step=1,
                input_tokens=120,
                output_tokens=15,
                request_time_ms=830.0,
                retries=0,
            ),
            StepMetrics(
                step=2,
                input_tokens=180,
                output_tokens=30,
                request_time_ms=910.0,
                retries=2,
            ),
        ],
        system_prompt="study",
        error="dummy",
    )


def test_round_trip_save_reload(tmp_path: Path) -> None:
    # Discriminates: a saver that drops fields (compact dump) or the
    # loader losing data on the way back — equality must hold.
    sol = _two_step_solution()
    target = tmp_path / "nested" / "solution.json"
    save_solution(sol, target)
    text = target.read_text(encoding="utf-8")
    # Discriminates: model_dump_json() without indent (single line).
    assert text.splitlines()[1].startswith('  "')
    # Discriminates: missing trailing newline (grader diff noise).
    assert text.endswith("\n")
    reloaded = SolutionOutput.model_validate_json(text)
    assert reloaded == sol


def test_load_task_dispatches_mbpp_by_task_id(tmp_path: Path) -> None:
    # Discriminates: a loader that str()-ifies the int task_id or
    # misroutes on the distinguishing keys (real task-11 shape).
    data = {
        "task_id": 11,
        "task_definition": (
            "Write a python function to remove first and last "
            "occurrence of a given character from the string."
        ),
        "function_definition": "def remove_Occ(s,ch):",
        "test_imports": [],
        "test_list": [
            'assert remove_Occ("abcda","a") == "bcd"',
            'assert remove_Occ("PHP","P") == "H"',
        ],
    }
    path = tmp_path / "task.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    task = load_task(path)
    assert isinstance(task, MBPPTaskInput)
    assert task.task_id == 11
    assert isinstance(task.task_id, int)
    assert len(task.test_list) == 2


def test_load_task_dispatches_swebench_by_instance_id(tmp_path: Path) -> None:
    # Discriminates: dispatch on the WRONG key (task_id present in a
    # SWE-bench dump would be an input bug we must see, not mask).
    data = {
        "instance_id": "sympy__sympy-14711",
        "problem_statement": "vector add 0 error\n```python\r\nimport sympy",
        "docker_image": "swebench/sweb.eval.x86_64.sympy_1776_sympy-14711:latest",
        "eval_script": "#!/bin/bash\nset -uxo pipefail\n",
        "hints_text": "",
        "repo": "sympy/sympy",
    }
    path = tmp_path / "task.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    task = load_task(path)
    assert isinstance(task, SWEBenchTaskInput)
    assert task.instance_id == "sympy__sympy-14711"


def test_load_task_rejects_undispatchable_shape(tmp_path: Path) -> None:
    # Discriminates: a loader that guesses a benchmark instead of
    # failing loudly on a file it cannot identify.
    path = tmp_path / "mystery.json"
    path.write_text(json.dumps({"foo": 1}), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_task(path)
    assert "mystery.json" in str(exc.value)


def test_load_task_rejects_both_keys(tmp_path: Path) -> None:
    # Discriminates: silent precedence when a file claims both
    # benchmarks — that is a malformed dump, never a valid task.
    path = tmp_path / "ambiguous.json"
    path.write_text(
        json.dumps({"task_id": 11, "instance_id": "sympy__sympy-14711"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_task(path)


def test_solution_rejects_int_task_id() -> None:
    # Discriminates: "helpful" str coercion — the grader field is str
    # (grader-notes); an int task_id must fail HERE, not at grading.
    with pytest.raises(ValidationError):
        SolutionOutput(
            task_id=282,
            benchmark="mbpp",
            success=False,
            solution="",
            iterations=1,
            total_requests=1,
            total_input_tokens=0,
            total_output_tokens=0,
            total_time_seconds=0.0,
        )


def test_totals_from_steps_matches_reported_totals() -> None:
    # Discriminates: totals math that forgets retries in
    # total_requests (2 steps + 2 retries = 4, not 2).
    sol = _two_step_solution()
    totals = totals_from_steps(sol.steps)
    assert totals == (300, 45, 4)
    assert totals == (
        sol.total_input_tokens,
        sol.total_output_tokens,
        sol.total_requests,
    )


def test_totals_from_empty_steps() -> None:
    # Discriminates: summing without a start value (sum([]) is 0, but
    # an implementation returning None or raising must fail here).
    assert totals_from_steps([]) == (0, 0, 0)
