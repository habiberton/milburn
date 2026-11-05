"""Deterministic Claude Code adapter fixtures with no process or network effects."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from milburn.agents.codex_adapter import (
    Ack,
    AgentEndpoint,
    AgentResult,
    AgentStatus,
    ClaudeCodeAdapter,
    ControlResult,
    LaunchRequest,
    SteeringMessage,
)
from tests.fakes.codex import FakeCodexRuntime, ScriptedCodexRun


def claude_stream(result_document: str | None) -> str:
    """Render the event shape of ``claude -p --output-format stream-json``.

    Mirrors the recorded run in ``tests/fixtures/harness``: an init event, then a
    result event whose ``structured_output`` holds the schema-checked object.
    A document that is not a JSON object is reported as plain ``result`` text.
    """

    events: list[dict[str, object]] = [
        {"type": "system", "subtype": "init", "session_id": "fake-session"},
    ]
    if result_document is not None:
        try:
            structured = json.loads(result_document)
        except json.JSONDecodeError:
            structured = None
        events.append(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "session_id": "fake-session",
                "structured_output": structured if isinstance(structured, dict) else None,
                "result": result_document,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        )
    return "\n".join(json.dumps(event) for event in events) + "\n"


class FakeClaudeCodeAdapter:
    """Public fake with the same lifecycle as ``ClaudeCodeAdapter``."""

    def __init__(
        self, scripts: tuple[ScriptedCodexRun, ...], *, schema_dir: Path | None = None
    ) -> None:
        self.runtime = FakeCodexRuntime(scripts, render=claude_stream, prefix="fake-claude")
        self._adapter = ClaudeCodeAdapter(
            self.runtime,
            executable="fake-claude",
            schema_dir=schema_dir or Path(tempfile.mkdtemp(prefix="milburn-schemas-")),
        )

    def launch(self, request: LaunchRequest) -> AgentEndpoint:
        return self._adapter.launch(request)

    def steer(self, endpoint: AgentEndpoint, message: SteeringMessage) -> Ack:
        return self._adapter.steer(endpoint, message)

    def status(self, endpoint: AgentEndpoint) -> AgentStatus:
        return self._adapter.status(endpoint)

    def interrupt(self, endpoint: AgentEndpoint) -> ControlResult:
        return self._adapter.interrupt(endpoint)

    def collect(self, endpoint: AgentEndpoint) -> AgentResult:
        return self._adapter.collect(endpoint)

    def retire(self, endpoint: AgentEndpoint) -> ControlResult:
        return self._adapter.retire(endpoint)
