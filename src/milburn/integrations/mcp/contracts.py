"""Small MCP boundary used by controller-owned integrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


JsonObject = dict[str, Any]


@dataclass(frozen=True, slots=True)
class McpTool:
    name: str
    input_schema: JsonObject


class McpClient(Protocol):
    def list_tools(self) -> tuple[McpTool, ...]: ...

    def call_tool(self, name: str, arguments: JsonObject) -> JsonObject: ...


class McpError(RuntimeError):
    """Base class for failures at the MCP transport boundary."""


class McpTimeoutError(McpError):
    """The caller cannot know whether the remote effect occurred."""


class McpUnavailableError(McpError):
    """The MCP server cannot currently serve a definitive request."""


class McpProtocolError(McpError):
    """The server returned an incompatible tool set or response."""
