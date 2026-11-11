"""Transport smoke tests for the mcp SDK pin (T05) on Python 3.10.

Both transports run against tests/fixtures/hello_server.py with no
internet access: stdio spawns the fixture as a subprocess; streamable
HTTP serves the same fixture app on an ephemeral localhost port in a
background thread. Every await is wrapped in a timeout (session-level
read_timeout_seconds plus asyncio.wait_for) so a hang fails the test
instead of stalling the suite.
"""

import asyncio
import importlib.util
import os
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import TextIO

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "fixtures"
    / "hello_server.py"
)
TIMEOUT = timedelta(seconds=10)
SECONDS = 10.0


async def _hello_over_stdio(errlog: TextIO) -> str:
    """Spawn the fixture over stdio, list tools, call add(1, 2)."""
    params = StdioServerParameters(
        command=sys.executable, args=[str(FIXTURE_PATH)]
    )
    async with (
        stdio_client(params, errlog=errlog) as (read, write),
        ClientSession(read, write, read_timeout_seconds=TIMEOUT) as session,
    ):
        await asyncio.wait_for(session.initialize(), timeout=SECONDS)
        tools = await asyncio.wait_for(session.list_tools(), timeout=SECONDS)
        assert any(tool.name == "add" for tool in tools.tools)
        result = await asyncio.wait_for(
            session.call_tool("add", {"a": 1, "b": 2}),
            timeout=SECONDS,
        )
        assert not result.isError
        return str(result.content[0].text)


def test_stdio_transport_add() -> None:
    # Discriminates: a broken SDK pin / wrong Python (the whole point
    # of T05) — any import, init or protocol failure lands here.
    with open(os.devnull, "w", encoding="utf-8") as errlog:
        assert asyncio.run(_hello_over_stdio(errlog)) == "3"


def _serve_hello_http() -> tuple[str, object]:
    """Serve the fixture's streamable-HTTP app on an ephemeral port.

    Runs uvicorn in a daemon thread; returns (url, server) so the
    caller can shut the server down. Import the fixture by file path
    — tests/fixtures has no __init__.py by design.
    """
    import uvicorn

    spec = importlib.util.spec_from_file_location("hello_server", FIXTURE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = module.mcp.streamable_http_app()
    path = next(
        route.path
        for route in app.routes
        if getattr(route, "path", "").endswith("mcp")
    )
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + SECONDS
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("uvicorn did not start within 10s")
    port = server.servers[0].sockets[0].getsockname()[1]
    return f"http://127.0.0.1:{port}{path}", server


async def _hello_over_http(url: str) -> str:
    """Connect over streamable HTTP, list tools, call add(1, 2)."""
    async with (
        streamable_http_client(url) as (read, write, _session_id),
        ClientSession(read, write, read_timeout_seconds=TIMEOUT) as session,
    ):
        await asyncio.wait_for(session.initialize(), timeout=SECONDS)
        tools = await asyncio.wait_for(session.list_tools(), timeout=SECONDS)
        assert any(tool.name == "add" for tool in tools.tools)
        result = await asyncio.wait_for(
            session.call_tool("add", {"a": 1, "b": 2}),
            timeout=SECONDS,
        )
        assert not result.isError
        return str(result.content[0].text)


def test_streamable_http_transport_add() -> None:
    # Discriminates: the HTTP transport regressing independently of
    # stdio (T12's connect_http path depends on it working on 3.10).
    url, server = _serve_hello_http()
    try:
        assert asyncio.run(_hello_over_http(url)) == "3"
    finally:
        server.should_exit = True
