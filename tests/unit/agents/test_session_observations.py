"""Codex semantic session-observation conversion tests."""

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from milburn.agents.session_observations import (
    CodexSessionObservationConverter,
    SemanticSessionObservationError,
    SessionCorrelation,
)
from milburn.domain.sessions import (
    ObservationAvailability,
    ObservationFinality,
    SessionObservationKind,
)
from milburn.domain.states import Role


NOW = datetime(2026, 11, 3, tzinfo=UTC)
FIXTURES = Path(__file__).parents[2] / "fixtures" / "agents" / "sessions"
CORRELATION = SessionCorrelation(
    task_id="MB-018",
    role=Role.CODER,
    attempt_id="a01",
    generation=2,
    endpoint="pane-1",
    session_id="session-1",
)


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_converts_compaction_and_context_usage_from_semantic_payloads() -> None:
    converter = CodexSessionObservationConverter()
    compacted = converter.observe(
        observation_id="session-observation-1",
        correlation=CORRELATION,
        observed_at=NOW,
        semantic_payload=fixture("compaction.json"),
    )
    context = converter.observe(
        observation_id="session-observation-2",
        correlation=CORRELATION,
        observed_at=NOW,
        semantic_payload=fixture("context.json"),
    )

    assert compacted.kind is SessionObservationKind.COMPACTION
    assert compacted.compaction_count == 1
    assert compacted.finality is ObservationFinality.PARTIAL
    assert context.context_used_tokens == 8000
    assert context.generation == 2
    assert context.to_dict()["role"] == "coder"


def test_missing_capability_is_explicitly_unavailable_without_fabricated_values() -> None:
    observed = CodexSessionObservationConverter().observe(
        observation_id="session-unavailable",
        correlation=CORRELATION,
        observed_at=NOW,
        semantic_payload=None,
        unavailable_kind=SessionObservationKind.CONTEXT_USAGE,
        unavailable_source_version="codex-unsupported",
    )

    assert observed.availability is ObservationAvailability.UNAVAILABLE
    assert observed.context_used_tokens is None
    assert observed.context_window_tokens is None


def test_unsupported_compaction_and_context_have_distinct_stable_source_versions() -> None:
    converter = CodexSessionObservationConverter()
    compaction = converter.observe(
        observation_id="compaction-unavailable",
        correlation=CORRELATION,
        observed_at=NOW,
        semantic_payload=None,
        unavailable_kind=SessionObservationKind.COMPACTION,
    )
    context = converter.observe(
        observation_id="context-unavailable",
        correlation=CORRELATION,
        observed_at=NOW,
        semantic_payload=None,
        unavailable_kind=SessionObservationKind.CONTEXT_USAGE,
    )

    assert compaction.source_version == "unavailable-compaction"
    assert context.source_version == "unavailable-context_usage"
    assert compaction.semantic_key != context.semantic_key


def test_rejects_terminal_prose_unknown_private_fields_and_invalid_counts() -> None:
    converter = CodexSessionObservationConverter()
    with pytest.raises(SemanticSessionObservationError, match="structured"):
        converter.observe(
            observation_id="text",
            correlation=CORRELATION,
            observed_at=NOW,
            semantic_payload="context is half full",  # type: ignore[arg-type]
        )
    with pytest.raises(SemanticSessionObservationError, match="unknown"):
        converter.observe(
            observation_id="private",
            correlation=CORRELATION,
            observed_at=NOW,
            semantic_payload={**fixture("context.json"), "transcript": "private"},
        )
    with pytest.raises(SemanticSessionObservationError, match="non-negative"):
        converter.observe(
            observation_id="negative",
            correlation=CORRELATION,
            observed_at=NOW,
            semantic_payload={**fixture("compaction.json"), "compaction_count": -1},
        )
