# ADR-0007: Async MCP SDK on a dedicated thread with a synchronous
# bridge
- Status: Accepted
- Date: 2026-11-11
- Deciders: A + B (pre-aligned in PROJECT_PLAN §2, committed 95c6169)

## Context

The `mcp` SDK (v1 line, pinned `<2`) is asyncio-based: sessions,
transports (stdio subprocess, streamable HTTP) and tool calls are
coroutines. Our agent loop, the sandbox parent, and both CLIs are
synchronous Python 3.10 code, and sandbox tools must be callable as
plain blocking functions from guest code. The SDK is verified to
import and run on 3.10: `mcp==1.30.0` resolved by uv.lock, both
transports smoke-tested against `tests/fixtures/hello_server.py`
(`test_stdio_transport_add`, `test_streamable_http_transport_add`).

## Options considered

(a) Make the whole agent async — rewrites the loop, the sandbox
    parent, and both CLIs; the sandbox world (signals, process
    groups, blocking reads) fits asyncio poorly.

(b) A synchronous re-implementation of the MCP client — protocol
    drift against a moving spec; unmaintained by construction.

(c) A dedicated daemon thread owning one asyncio event loop, with
    every public client method bridged via
    `asyncio.run_coroutine_threadsafe(...).result(timeout)`.

## Decision

Option (c). One thread, one loop, one session per server. Every
public client method is a blocking call with an explicit timeout;
`close()` is idempotent and never raises. Pin `mcp<2` on Python
3.10 (resolved: 1.30.0).

## Consequences

- The thread's loop outlives individual calls — created once at
  client construction, never per call.
- Timeouts are enforced twice: `asyncio.wait_for` inside the
  coroutine, a slightly larger outer `.result(timeout)` — no hang
  from either side.
- Error paths must marshal exceptions across the thread boundary
  (`.result()` re-raises in the caller's thread).
- The SDK's stdio and streamable-HTTP transports are both verified
  on 3.10 by `test_stdio_transport_add` and
  `test_streamable_http_transport_add` (mcp 1.30 deprecates
  `streamablehttp_client` in favor of `streamable_http_client`; we
  use the modern name).
- T12 builds `MCPClientManager` directly on this decision.
