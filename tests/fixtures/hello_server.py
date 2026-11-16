"""A minimal MCP server fixture: the ``hello`` server with one tool.

Spawned as a subprocess script (stdio) by the transport smoke tests,
and reused from T12 as the hello transport for client tests. Serve it
directly to poke at it:

    python tests/fixtures/hello_server.py                # stdio
    python tests/fixtures/hello_server.py http           # (T12 helper)
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("hello")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


if __name__ == "__main__":
    mcp.run()  # stdio transport by default
