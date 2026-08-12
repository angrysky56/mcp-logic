"""The v2 handler contract: always return a result, never raise.

SDK v1 wrapped any exception escaping a tool handler into
``CallToolResult(is_error=True)``. SDK v2 removed that safety net — an
escaping exception becomes a JSON-RPC protocol error, which fails the
request at the transport level instead of returning a readable message.

``_handle_call_tool`` promises in its docstring that it always returns a
``CallToolResult``. These tests hold it to that, including for exception
types nobody enumerated.
"""

from __future__ import annotations

from typing import Any

import mcp.types as types
import pytest

from mcp_logic.server import _err, _handle_call_tool, _handle_list_tools, _ok


class _FakeContext:
    """Minimal stand-in for ServerRequestContext."""

    def __init__(self, engine: Any = None, advisor: Any = None) -> None:
        self.lifespan_context = {"engine": engine, "advisor": advisor}


class _ExplodingEngine:
    """An engine whose every use raises something unenumerated."""

    mace4 = None

    def create_input_file(self, *args: Any, **kwargs: Any) -> Any:
        raise OSError("prover9 binary vanished mid-flight")


class TestResultHelpers:
    def test_ok_is_not_flagged_as_error(self) -> None:
        result = _ok({"result": "proved"})
        assert result.is_error is False
        assert "proved" in result.content[0].text

    def test_err_is_flagged(self) -> None:
        result = _err({"error": "boom"})
        assert result.is_error is True


class TestNeverRaises:
    """Exception types outside the original catch list must still return."""

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error_result(self) -> None:
        result = await _handle_call_tool(
            _FakeContext(),
            types.CallToolRequestParams(name="no_such_tool", arguments={}),
        )
        assert isinstance(result, types.CallToolResult)
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_oserror_from_solver_is_returned_not_raised(self) -> None:
        # OSError is not in (KeyError, ValueError, RuntimeError). Under v1 the
        # SDK caught it; under v2 nothing would.
        ctx = _FakeContext(engine=_ExplodingEngine())
        result = await _handle_call_tool(
            ctx,
            types.CallToolRequestParams(
                name="prove",
                arguments={"premises": ["p(a)"], "conclusion": "p(a)"},
            ),
        )
        assert isinstance(result, types.CallToolResult)
        assert result.is_error is True
        assert "vanished mid-flight" in result.content[0].text

    @pytest.mark.asyncio
    async def test_missing_lifespan_context_does_not_escape(self) -> None:
        class _Empty:
            lifespan_context: dict[str, Any] = {}

        result = await _handle_call_tool(
            _Empty(),
            types.CallToolRequestParams(name="prove", arguments={}),
        )
        assert isinstance(result, types.CallToolResult)
        assert result.is_error is True


class TestListToolsHandler:
    @pytest.mark.asyncio
    async def test_lists_every_tool_without_context(self) -> None:
        # Both handler arguments are unused by design; the SDK still passes
        # them positionally, so the signature must accept them.
        result = await _handle_list_tools(_FakeContext(), None)
        assert isinstance(result, types.ListToolsResult)
        assert len(result.tools) == 11

    @pytest.mark.asyncio
    async def test_routing_guidance_survives_in_descriptions(self) -> None:
        # These strings steer the calling agent away from sending arithmetic
        # to Prover9. Losing them in a refactor would be silent.
        result = await _handle_list_tools(_FakeContext(), None)
        by_name = {tool.name: tool.description or "" for tool in result.tools}
        assert "no theory of arithmetic" in by_name["prove_arithmetic"]
        assert "counterexample" in by_name["find_counterexample"]
