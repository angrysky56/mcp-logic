# Plan: migrate mcp-logic to MCP Python SDK 2.0

Researched against the official migration guide and PyPI, August 2026.
Written for handoff.

## The short answer

**Not much pain.** The low-level `Server` we use still exists in v2 — it was
not removed, only reshaped. The change is mechanical and concentrated in
two functions. Python 3.10 stays supported (`mcp 2.0.0` declares
`requires_python >=3.10`), so CI does not move.

## What "MCP 2" means — two separate things

Worth separating, because they get conflated:

1. **SDK 2.0.0** — the `mcp` PyPI package. Released; currently the latest.
   This is what broke our test run with
   `AttributeError: 'Server' object has no attribute 'list_tools'`.
2. **Protocol revision `2026-07-28`** — the wire spec. In SDK v2,
   `LATEST_PROTOCOL_VERSION` is `"2026-07-28"` (v1: `"2025-11-25"`), and
   the handshake versions are now tracked separately in
   `HANDSHAKE_PROTOCOL_VERSIONS` vs `MODERN_PROTOCOL_VERSIONS`.

We negotiate the protocol through the SDK and never hand-build an
`initialize`, so (2) comes free once (1) is done.

## Urgency: low risk today, real risk on any dependency bump

`uv.lock` pins `mcp==1.6.0`, so CI and the local venv are green. But
`pyproject.toml` declares:

```toml
dependencies = ["mcp>=1.0.0", ...]
```

Unbounded. Anyone installing outside the lockfile resolves 2.0.0 and gets
a server that dies at import. **Cap it now, migrate deliberately after**:

```toml
dependencies = ["mcp>=1.6,<2", ...]
```

That one line is worth doing immediately and independently of everything
below.

## What actually changes for us

Our usage is small and all low-level (`src/mcp_logic/server.py`):

| v1 (current)                                         | v2                                                                   |
| ---------------------------------------------------- | -------------------------------------------------------------------- |
| `from mcp.server import NotificationOptions, Server` | `Server` stays; constructor params become keyword-only               |
| `@server.list_tools()` decorator                     | `Server(..., on_list_tools=handler)` constructor arg                 |
| `@server.call_tool()` decorator                      | `Server(..., on_call_tool=handler)` constructor arg                  |
| handler `(name: str, arguments: dict)`               | handler `(ctx: ServerRequestContext, params: CallToolRequestParams)` |
| return `list[TextContent]`, SDK wraps it             | return `CallToolResult(content=[...])` yourself                      |
| raising → `CallToolResult(is_error=True)`            | raising → **protocol error**; return errors explicitly               |
| `McpError`                                           | `MCPError`                                                           |
| `mcp.server.stdio.stdio_server()`                    | unchanged (streams moved to private descriptors)                     |

Scope in this repo: 2 decorators, ~20 `TextContent` construction sites,
4 import lines. The ~700 lines of `inputSchema` dicts are **data** and
carry over untouched.

The one behavioural change that needs attention is exception handling.
In v1 an uncaught exception in a tool handler came back to the client as
a tool result with `is_error=True`; in v2 it is a JSON-RPC protocol
error. Our handlers already catch and return structured JSON for the
error paths, so the observable behaviour should be preserved — but the
outer `try/except` in `call_tool` must be checked to confirm nothing
relies on the old auto-wrapping.

## Work packages

### M1 — Cap the dependency (do immediately, standalone)

Set `mcp>=1.6,<2` in `pyproject.toml`. No code change, no lock change.
Protects anyone installing outside the lockfile.

**Acceptance:** `uv lock --check` still passes; suite unchanged.

### M2 — Port the low-level server to v2

Depends on M1.

1. Bump to `mcp>=2,<3`; `uv lock`.
2. Convert the two decorated handlers to module-level `async def`s taking
   `(ctx, params)` and returning `ListToolsResult` / `CallToolResult`.
3. Pass them as `on_list_tools=` / `on_call_tool=` to `Server(...)`.
4. Wrap the existing `list[TextContent]` returns in `CallToolResult(...)`.
   A small helper (`_text_result(payload) -> CallToolResult`) keeps this
   to one edit per site.
5. Rename `McpError` → `MCPError` if referenced.
6. Re-check the outer exception handler against the new semantics.

**Do not** also switch to the high-level `MCPServer` in this package.
Two simultaneous changes — SDK version _and_ server architecture — makes
any regression ambiguous.

**Acceptance:**

- Full suite green on 3.10 **and** 3.13.
- `tests/test_mcp_stdio_integration.py` passes — it drives a real stdio
  client, so it is the test that actually proves the port.
- Every one of the 11 tools still lists, with descriptions byte-identical
  to today (they encode routing guidance and the `verified` warning).
- Manual: `prove`, `find_model`, `prove_arithmetic` and
  `ask_logic_advisor` each return the same JSON shape as before.

### M3 — Evaluate `MCPServer` (high-level) separately

Depends on M2 landing and being stable.

v2 renames `FastMCP` to `MCPServer`. Moving to it would let type hints
generate the `inputSchema` dicts, deleting several hundred lines. That is
attractive but is a **rewrite of the tool surface**, and our descriptions
are load-bearing prose that must survive verbatim.

Treat as a separate, optional investigation with its own acceptance
criteria. Not required for v2 compatibility — the low-level `Server` is
fully supported in v2.

## Sequencing

`M1` today (one line). `M2` as a single focused change. `M3` only if the
boilerplate reduction proves worth it.

M2 is independent of Packages 2–4 in the decision-procedures plan and can
run in parallel — it touches transport and handler plumbing, they touch
solver semantics. The only shared file is `server.py`, so land one before
starting the other to avoid conflicts.

## Verification

```bash
cd /home/ty/Repositories/ai_workspace/mcp-logic
.venv/bin/python -m pytest tests/ -q
trunk check --no-progress --ci
```

For the 3.10 check, build the throwaway env **from the lockfile version**,
not with ad-hoc installs — an unpinned `uv pip install mcp` pulls 2.0.0
and produces a failure that looks like a code bug but is an environment
artefact. (That is exactly how this issue was found.)

## Sources

- <https://py.sdk.modelcontextprotocol.io/migration/>
- <https://py.sdk.modelcontextprotocol.io/whats-new/>
- <https://github.com/modelcontextprotocol/python-sdk/releases>
- <https://pypi.org/project/mcp/>
