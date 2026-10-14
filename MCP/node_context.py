"""Inject node-scoped MCP access without changing node implementations."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
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


def _project_id_from_call(
    args: tuple[object, ...],
    kwargs: Mapping[str, object],
) -> str | None:
    state = args[0] if args else kwargs.get("state")
    if not isinstance(state, Mapping):
        return None
    project_id = state.get("project_id")
    if project_id is None:
        return None
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("Workflow state project_id must be a non-empty string")
    return project_id


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

    if inspect.iscoroutinefunction(node):

        @wraps(node)
        async def async_bound(*args: Parameters.args, **kwargs: Parameters.kwargs) -> Result:
            manager = MCPManager(
                node_name,
                project_id=_project_id_from_call(args, kwargs),
            )
            token = _CURRENT_MCP_MANAGER.set(manager)
            try:
                return await node(*args, **kwargs)  # type: ignore[misc]
            finally:
                _CURRENT_MCP_MANAGER.reset(token)

        return cast(Callable[Parameters, Result], async_bound)

    @wraps(node)
    def sync_bound(*args: Parameters.args, **kwargs: Parameters.kwargs) -> Result:
        manager = MCPManager(
            node_name,
            project_id=_project_id_from_call(args, kwargs),
        )
        token = _CURRENT_MCP_MANAGER.set(manager)
        try:
            return node(*args, **kwargs)
        finally:
            _CURRENT_MCP_MANAGER.reset(token)

    return sync_bound
