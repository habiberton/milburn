"""Deterministic MCP client for local integration and fault-injection tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from milburn.integrations.mcp import (
    JsonObject,
    McpTimeoutError,
    McpTool,
    McpUnavailableError,
)


class ScriptedOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT_BEFORE = "timeout_before"
    TIMEOUT_AFTER = "timeout_after"
    MALFORMED_AFTER = "malformed_after"


@dataclass(frozen=True, slots=True)
class McpCall:
    tool: str
    arguments: JsonObject


class DeterministicMcpClient:
    """Run an in-process tool handler with explicit one-shot failures."""

    def __init__(
        self,
        tools: tuple[McpTool, ...],
        handler: Callable[[str, JsonObject], JsonObject],
        *,
        before_call: Callable[[str, JsonObject], None] | None = None,
        after_call: Callable[[str, JsonObject, JsonObject], None] | None = None,
    ) -> None:
        self._tools = tools
        self._handler = handler
        self._before_call = before_call
        self._after_call = after_call
        self._scripts: dict[str, list[ScriptedOutcome]] = {}
        self.calls: list[McpCall] = []

    def list_tools(self) -> tuple[McpTool, ...]:
        return self._tools

    def script(self, tool: str, *outcomes: ScriptedOutcome) -> None:
        self._scripts.setdefault(tool, []).extend(outcomes)

    def set_before_call(
        self, callback: Callable[[str, JsonObject], None] | None
    ) -> None:
        self._before_call = callback

    def set_after_call(
        self, callback: Callable[[str, JsonObject, JsonObject], None] | None
    ) -> None:
        self._after_call = callback

    def call_tool(self, name: str, arguments: JsonObject) -> JsonObject:
        detached = dict(arguments)
        self.calls.append(McpCall(name, detached))
        if self._before_call is not None:
            self._before_call(name, detached)
        queue = self._scripts.get(name, [])
        outcome = queue.pop(0) if queue else ScriptedOutcome.SUCCESS
        if outcome is ScriptedOutcome.FAILURE:
            raise McpUnavailableError(f"scripted MCP failure for {name}")
        if outcome is ScriptedOutcome.TIMEOUT_BEFORE:
            raise McpTimeoutError(f"scripted pre-effect timeout for {name}")
        result = self._handler(name, detached)
        if self._after_call is not None:
            self._after_call(name, detached, result)
        if outcome is ScriptedOutcome.TIMEOUT_AFTER:
            raise McpTimeoutError(f"scripted post-effect timeout for {name}")
        if outcome is ScriptedOutcome.MALFORMED_AFTER:
            return {"malformed": "scripted response shape"}
        return result
