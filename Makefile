# Agent Smith — developer commands (uv is the only package manager).

.PHONY: test lint types sandbox-tests sandbox-tests-linux clean-containers bench-mbpp bench-swebench

# Default selection for the sandbox security battery (the file lands
# in T06). Override on the command line:
#   make sandbox-tests-linux TESTS=tests/test_skeleton.py
TESTS = tests/test_worker_security.py

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check .

types:
	uv run mypy

sandbox-tests:
	uv run pytest $(TESTS)

# Authoritative for memory/kill semantics (Linux container).
# UV_PROJECT_ENVIRONMENT keeps the container's uv from touching the
# host's macOS .venv inside the mounted repo (binaries are not
# portable across the two).
sandbox-tests-linux:
	docker run --rm -v $(CURDIR):/repo -w /repo \
		-e UV_PROJECT_ENVIRONMENT=/opt/venv \
		ghcr.io/astral-sh/uv:python3.10-bookworm \
		uv run pytest $(TESTS)

clean-containers:
	@echo "clean-containers: implemented with docker_env.py in a later task"

bench-mbpp:
	@echo "benchmark harness lands in a later task"

bench-swebench:
	@echo "benchmark harness lands in a later task"
