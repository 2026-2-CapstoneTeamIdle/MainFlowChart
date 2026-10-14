"""Inject node-scoped MCP access without changing node implementations."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from contextvars import ContextVar
from functools import wraps
from typing import ParamSpec, TypeVar, cast

from MCP.manager import MCPManager

Parameters = ParamSpec("Parameters")
Result = TypeVar("Result")

_CURRENT_MCP_MANAGER: ContextVar[MCPManager | None] = ContextVar(
    "current_mcp_manager",
    default=None,
)


def get_current_mcp_manager() -> MCPManager:
    """Return the manager injected for the currently executing graph node."""

    manager = _CURRENT_MCP_MANAGER.get()
    if manager is None:
        raise RuntimeError("No MCP manager is active outside a bound workflow node")
    return manager


def bind_mcp_tools(
    node_name: str,
    node: Callable[Parameters, Result],
) -> Callable[Parameters, Result]:
    """Wrap a sync or async node with its MCP policy context."""

    manager = MCPManager(node_name)
    if inspect.iscoroutinefunction(node):

        @wraps(node)
        async def async_bound(*args: Parameters.args, **kwargs: Parameters.kwargs) -> Result:
            token = _CURRENT_MCP_MANAGER.set(manager)
            try:
                return await node(*args, **kwargs)  # type: ignore[misc]
            finally:
                _CURRENT_MCP_MANAGER.reset(token)

        return cast(Callable[Parameters, Result], async_bound)

    @wraps(node)
    def sync_bound(*args: Parameters.args, **kwargs: Parameters.kwargs) -> Result:
        token = _CURRENT_MCP_MANAGER.set(manager)
        try:
            return node(*args, **kwargs)
        finally:
            _CURRENT_MCP_MANAGER.reset(token)

    return sync_bound
