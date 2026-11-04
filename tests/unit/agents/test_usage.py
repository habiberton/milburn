"""Codex semantic token-usage conversion tests."""

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from milburn.agents.usage import (
    CodexUsageConverter,
    SemanticUsageError,
    UsageCorrelation,
)
from milburn.domain.states import Role
from milburn.domain.usage import UsageObservationKind


NOW = datetime(2026, 11, 3, tzinfo=UTC)
FIXTURES = Path(__file__).parents[2] / "fixtures" / "agents" / "usage"
CORRELATION = UsageCorrelation(
    task_id="MB-017",
    role=Role.CODER,
    attempt_id="a01",
    endpoint="endpoint-1",
    session_id="session-1",
    model="codex-model",
)


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_converts_supported_structured_partial_and_final_payloads() -> None:
    converter = CodexUsageConverter()
    partial = converter.observe(
        observation_id="usage-1",
        correlation=CORRELATION,
        observed_at=NOW,
        semantic_payload=fixture("partial.json"),
    )
    final = converter.observe(
        observation_id="usage-2",
        correlation=CORRELATION,
        observed_at=NOW,
        semantic_payload=fixture("final.json"),
    )

    assert partial.kind is UsageObservationKind.PARTIAL
    assert partial.counts is not None
    assert partial.counts.cached_input_tokens == 40
    assert partial.counts.reasoning_tokens is None
    assert final.kind is UsageObservationKind.FINAL
    assert final.counts is not None
    assert final.counts.reasoning_tokens == 12
    assert final.task_id == "MB-017"
    assert final.endpoint == "endpoint-1"
    assert final.model == "codex-model"


def test_missing_semantic_usage_becomes_explicit_unavailable_observation() -> None:
    observed = CodexUsageConverter().observe(
        observation_id="usage-unavailable",
        correlation=CORRELATION,
        observed_at=NOW,
        semantic_payload=None,
        unavailable_source_version="codex-unsupported",
    )

    assert observed.kind is UsageObservationKind.UNAVAILABLE
    assert observed.counts is None
    assert observed.source_version == "codex-unsupported"


def test_rejects_human_text_unknown_fields_and_invalid_token_values() -> None:
    converter = CodexUsageConverter()
    with pytest.raises(SemanticUsageError, match="structured"):
        converter.observe(
            observation_id="usage-text",
            correlation=CORRELATION,
            observed_at=NOW,
            semantic_payload="1,000 tokens used",  # type: ignore[arg-type]
        )
    with pytest.raises(SemanticUsageError, match="unknown"):
        converter.observe(
            observation_id="usage-extra",
            correlation=CORRELATION,
            observed_at=NOW,
            semantic_payload={**fixture("partial.json"), "transcript": "private"},
        )
    with pytest.raises(SemanticUsageError, match="non-negative integer"):
        converter.observe(
            observation_id="usage-negative",
            correlation=CORRELATION,
            observed_at=NOW,
            semantic_payload={**fixture("partial.json"), "input_tokens": -1},
        )


def test_unavailable_payload_cannot_smuggle_counts() -> None:
    with pytest.raises(SemanticUsageError, match="fabricated"):
        CodexUsageConverter().observe(
            observation_id="usage-invalid-unavailable",
            correlation=CORRELATION,
            observed_at=NOW,
            semantic_payload={
                "source_version": "usage-unavailable",
                "kind": "unavailable",
                "cumulative": False,
                "input_tokens": 0,
            },
        )
