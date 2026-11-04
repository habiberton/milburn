"""Token-usage domain contract tests."""

from datetime import UTC, datetime

import pytest

from milburn.domain.errors import InvalidEnvelopeError
from milburn.domain.states import Role
from milburn.domain.usage import (
    TokenCounts,
    TokenUsageObservation,
    UsageObservationKind,
)


NOW = datetime(2026, 11, 3, tzinfo=UTC)


def observation(**changes: object) -> TokenUsageObservation:
    values: dict[str, object] = {
        "observation_id": "usage-observation-1",
        "source_version": "usage-1",
        "task_id": "MB-017",
        "role": Role.CODER,
        "attempt_id": "a01",
        "endpoint": "endpoint-1",
        "session_id": "session-1",
        "model": "codex-model",
        "kind": UsageObservationKind.PARTIAL,
        "counts": TokenCounts(input_tokens=10, output_tokens=2),
        "cumulative": True,
        "observed_at": NOW,
    }
    values.update(changes)
    return TokenUsageObservation(**values)  # type: ignore[arg-type]


def test_observation_round_trips_only_reported_dimensions() -> None:
    expected = observation()

    restored = TokenUsageObservation.from_dict(expected.to_dict())

    assert restored == expected
    assert restored.counts is not None
    assert restored.counts.input_tokens == 10
    assert restored.counts.cached_input_tokens is None
    assert restored.source_key == (
        "MB-017",
        "coder",
        "a01",
        "session-1",
        "endpoint-1",
    )


def test_explicit_unavailable_usage_has_no_counts_or_cumulative_claim() -> None:
    unavailable = observation(
        kind=UsageObservationKind.UNAVAILABLE,
        counts=None,
        cumulative=False,
        endpoint=None,
        session_id=None,
        model=None,
    )

    assert unavailable.kind is UsageObservationKind.UNAVAILABLE
    assert unavailable.counts is None

    with pytest.raises(InvalidEnvelopeError, match="fabricated"):
        observation(kind=UsageObservationKind.UNAVAILABLE, cumulative=False)
    with pytest.raises(InvalidEnvelopeError, match="cannot claim cumulative"):
        observation(
            kind=UsageObservationKind.UNAVAILABLE, counts=None, cumulative=True
        )


def test_available_usage_requires_reported_counts_and_final_is_cumulative() -> None:
    with pytest.raises(InvalidEnvelopeError, match="at least one"):
        observation(counts=TokenCounts())
    with pytest.raises(InvalidEnvelopeError, match="authoritative cumulative"):
        observation(kind=UsageObservationKind.FINAL, cumulative=False)


@pytest.mark.parametrize("value", [-1, True])
def test_token_counts_reject_invalid_values(value: object) -> None:
    with pytest.raises(InvalidEnvelopeError, match="non-negative integer|allowed type"):
        TokenCounts(input_tokens=value)  # type: ignore[arg-type]


def test_observation_requires_known_role_and_timezone_aware_timestamp() -> None:
    with pytest.raises(InvalidEnvelopeError, match="role must be Role"):
        observation(role="coder")
    with pytest.raises(InvalidEnvelopeError, match="timezone-aware"):
        observation(observed_at=datetime(2026, 11, 3))
