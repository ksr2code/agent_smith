"""Smoke tests for the T01 repository skeleton (packages + template).

A real suite, not an empty one: pytest exits 5 when it collects
nothing, and the project baseline must be a green exit-0 run. Each
test discriminates: it fails if a package loses its docstring or the
sandbox template drifts from the subject's default shape.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "sandbox_template.json"


def test_sandbox_package_imports() -> None:
    import sandbox

    assert sandbox.__doc__


def test_agent_package_imports() -> None:
    import agent

    assert agent.__doc__


def test_llm_package_imports() -> None:
    import llm

    assert llm.__doc__


def test_mcp_client_package_imports() -> None:
    import mcp_client

    assert mcp_client.__doc__


def test_sandbox_template_matches_subject_defaults() -> None:
    """The template is the subject's default SandboxConfig as data."""
    assert TEMPLATE_PATH.is_file()
    data = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert set(data) == {
        "authorized_imports",
        "allowed_directories",
        "max_execution_time_seconds",
        "max_memory_mb",
    }
    # Subject defaults (20) + the single documented addition
    # (_strptime, see ADR-0005 when it lands).
    imports = data["authorized_imports"]
    assert len(imports) == 21
    assert data["allowed_directories"] == ["/testbed", "/tmp/agent"]
    assert data["max_execution_time_seconds"] == 30
    assert data["max_memory_mb"] == 512
