"""Provenance and contract-anchor tests for the root models.py.

models.py must stay a byte-identical copy of the example moulinette's
models_public.py behind a two-line header comment. The provenance
test only runs when moulinette/ is present (a fresh grader clone has
no gitignored reference material and must not fail); it discriminates
any accidental field drift or edit of the grader contract. The import
test always runs and pins the field names both our code and the
grader rely on.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_PATH = REPO_ROOT / "models.py"
MOULINETTE_SOURCE = REPO_ROOT / "moulinette" / "models_public.py"
HEADER_LINE_COUNT = 2


def test_models_is_verbatim_grader_contract() -> None:
    """Fail on ANY change to the copied contract body."""
    if not MOULINETTE_SOURCE.is_file():
        pytest.skip("moulinette/ reference material not present")
    lines = MODELS_PATH.read_bytes().splitlines(keepends=True)
    assert len(lines) > HEADER_LINE_COUNT
    assert lines[0].startswith(b"# Copied verbatim from ")
    body = b"".join(lines[HEADER_LINE_COUNT:])
    assert body == MOULINETTE_SOURCE.read_bytes()


def test_models_contract_anchors() -> None:
    """The exact field names our solution IO and the grader share.

    The sets below are EXHAUSTIVE (taken from models.py's
    model_fields, which is byte-pinned to the grader's file by the
    provenance test): a rename or deletion of any contract field —
    e.g. the totals the harnesses write — must fail here even on a
    clone without moulinette/, where the provenance test skips.
    """
    import models

    assert set(models.SolutionOutput.model_fields) == {
        "task_id",
        "benchmark",
        "success",
        "solution",
        "iterations",
        "total_requests",
        "total_input_tokens",
        "total_output_tokens",
        "total_time_seconds",
        "steps",
        "system_prompt",
        "error",
        "timestamp",
    }
    assert set(models.StepMetrics.model_fields) == {
        "step",
        "input_tokens",
        "output_tokens",
        "request_time_ms",
        "timestamp",
        "api_url",
        "model_name",
        "llm_output",
        "sandbox_input",
        "sandbox_output",
        "retries",
    }
    # SandboxConfig has exactly these four fields in the contract.
    assert set(models.SandboxConfig.model_fields) == {
        "authorized_imports",
        "allowed_directories",
        "max_execution_time_seconds",
        "max_memory_mb",
    }
