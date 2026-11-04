"""Replayable token-usage summary tests."""

from datetime import UTC, datetime, timedelta

import pytest

from milburn.domain.states import Role
from milburn.domain.usage import (
    TokenCounts,
    TokenUsageObservation,
    UsageObservationKind,
)
from milburn.persistence.usage_projections import (
    UsageAvailability,
    UsageFinality,
    UsageProjectionError,
    project_usage_events,
)


NOW = datetime(2026, 11, 3, tzinfo=UTC)


def usage(
    observation_id: str,
    source_version: str,
    *,
    task_id: str = "MB-017",
    role: Role = Role.CODER,
    attempt_id: str = "a01",
    endpoint: str | None = "endpoint-1",
    session_id: str | None = "session-1",
    kind: UsageObservationKind = UsageObservationKind.PARTIAL,
    counts: TokenCounts | None = None,
    cumulative: bool = True,
    observed_at: datetime = NOW,
) -> TokenUsageObservation:
    if counts is None and kind is not UsageObservationKind.UNAVAILABLE:
        counts = TokenCounts(input_tokens=10, output_tokens=2)
    return TokenUsageObservation(
        observation_id=observation_id,
        source_version=source_version,
        task_id=task_id,
        role=role,
        attempt_id=attempt_id,
        endpoint=endpoint,
        session_id=session_id,
        model="codex-model",
        kind=kind,
        counts=counts,
        cumulative=cumulative,
        observed_at=observed_at,
    )


def test_cumulative_partials_and_final_reconcile_without_double_counting() -> None:
    observations = (
        usage(
            "usage-1",
            "source-1",
            counts=TokenCounts(input_tokens=10, output_tokens=2),
        ),
        usage(
            "usage-2",
            "source-2",
            counts=TokenCounts(input_tokens=15, output_tokens=4),
        ),
        usage(
            "usage-3",
            "source-3",
            kind=UsageObservationKind.FINAL,
            counts=TokenCounts(
                input_tokens=20,
                output_tokens=5,
                cached_input_tokens=3,
                reasoning_tokens=2,
            ),
        ),
    )

    summary = project_usage_events(observations)
    attempt = summary.attempt_totals["a01"]

    assert attempt.reported_tokens.input_tokens == 20
    assert attempt.reported_tokens.output_tokens == 5
    assert attempt.reported_tokens.cached_input_tokens == 3
    assert attempt.availability is UsageAvailability.COMPLETE
    assert attempt.finality is UsageFinality.FINAL
    assert summary.task_totals["MB-017"] == attempt
    assert summary.role_totals["coder"] == attempt
    assert summary.workflow_totals == attempt


def test_exact_duplicate_and_same_source_version_delivery_are_idempotent() -> None:
    first = usage("usage-1", "source-1")
    duplicate_version = usage(
        "delivery-copy", "source-1", observed_at=NOW + timedelta(minutes=5)
    )

    expected = project_usage_events((first,))

    assert project_usage_events((first, first, duplicate_version)) == expected
    serialized = TokenUsageObservation.from_dict(first.to_dict())
    assert project_usage_events((serialized,)) == expected


def test_delayed_unavailable_source_version_delivery_is_idempotent() -> None:
    first = usage(
        "missing-1",
        "missing-source-1",
        endpoint=None,
        session_id=None,
        kind=UsageObservationKind.UNAVAILABLE,
        counts=None,
        cumulative=False,
    )
    redelivery = usage(
        "missing-redelivery",
        "missing-source-1",
        endpoint=None,
        session_id=None,
        kind=UsageObservationKind.UNAVAILABLE,
        counts=None,
        cumulative=False,
        observed_at=NOW + timedelta(hours=1),
    )

    assert project_usage_events((first, redelivery)) == project_usage_events((first,))


def test_incremental_partial_is_replaced_by_authoritative_final_total() -> None:
    summary = project_usage_events(
        (
            usage(
                "usage-1",
                "source-1",
                counts=TokenCounts(input_tokens=5),
                cumulative=False,
            ),
            usage(
                "usage-2",
                "source-2",
                counts=TokenCounts(input_tokens=3),
                cumulative=False,
            ),
            usage(
                "usage-3",
                "source-3",
                kind=UsageObservationKind.FINAL,
                counts=TokenCounts(input_tokens=10),
            ),
        )
    )

    assert summary.attempt_totals["a01"].reported_tokens.input_tokens == 10


def test_unavailable_usage_is_explicit_and_never_fabricates_zero_counts() -> None:
    unavailable = usage(
        "usage-unavailable",
        "source-unavailable",
        endpoint=None,
        session_id=None,
        kind=UsageObservationKind.UNAVAILABLE,
        counts=None,
        cumulative=False,
    )

    summary = project_usage_events((unavailable,))
    aggregate = summary.attempt_totals["a01"]

    assert aggregate.availability is UsageAvailability.UNAVAILABLE
    assert aggregate.finality is UsageFinality.UNAVAILABLE
    assert aggregate.reported_tokens.input_tokens is None
    assert summary.workflow_totals.reported_tokens.output_tokens is None


def test_attempt_task_role_and_workflow_aggregates_sum_distinct_sources() -> None:
    observations = (
        usage(
            "coder-final",
            "coder-v1",
            kind=UsageObservationKind.FINAL,
            counts=TokenCounts(input_tokens=20, output_tokens=5),
        ),
        usage(
            "tester-final",
            "tester-v1",
            task_id="MB-017",
            role=Role.TESTER,
            attempt_id="qa01",
            endpoint="endpoint-2",
            session_id="session-2",
            kind=UsageObservationKind.FINAL,
            counts=TokenCounts(input_tokens=7, output_tokens=3),
        ),
    )

    summary = project_usage_events(observations)

    assert summary.attempt_totals["a01"].reported_tokens.input_tokens == 20
    assert summary.attempt_totals["qa01"].reported_tokens.input_tokens == 7
    assert summary.task_totals["MB-017"].reported_tokens.input_tokens == 27
    assert summary.role_totals["coder"].reported_tokens.output_tokens == 5
    assert summary.role_totals["tester"].reported_tokens.output_tokens == 3
    assert summary.workflow_totals.reported_tokens.input_tokens == 27
    with pytest.raises(TypeError):
        summary.attempt_totals["other"] = summary.attempt_totals[  # type: ignore[index]
            "a01"
        ]


@pytest.mark.parametrize(
    ("final_session", "final_endpoint"),
    (("session-late", None), (None, "endpoint-late")),
)
def test_authoritative_final_reconciles_late_source_identity_enrichment(
    final_session: str | None, final_endpoint: str | None
) -> None:
    partial = usage(
        "partial",
        "source-1",
        endpoint=None,
        session_id=None,
        counts=TokenCounts(input_tokens=10),
    )
    final = usage(
        "final",
        "source-2",
        endpoint=final_endpoint,
        session_id=final_session,
        kind=UsageObservationKind.FINAL,
        counts=TokenCounts(input_tokens=15),
    )

    aggregate = project_usage_events((partial, final)).attempt_totals["a01"]

    assert aggregate.reported_tokens.input_tokens == 15
    assert aggregate.finality is UsageFinality.FINAL


def test_final_can_add_session_to_an_endpoint_correlated_partial() -> None:
    partial = usage(
        "partial",
        "source-1",
        endpoint="endpoint-1",
        session_id=None,
        counts=TokenCounts(input_tokens=10),
    )
    final = usage(
        "final",
        "source-2",
        endpoint="endpoint-1",
        session_id="session-late",
        kind=UsageObservationKind.FINAL,
        counts=TokenCounts(input_tokens=15),
    )

    assert (
        project_usage_events((partial, final))
        .attempt_totals["a01"]
        .reported_tokens.input_tokens
        == 15
    )


def test_distinct_session_and_endpoint_sources_are_aggregated_separately() -> None:
    first = usage(
        "first-final",
        "source-1",
        endpoint="endpoint-1",
        session_id="session-1",
        kind=UsageObservationKind.FINAL,
        counts=TokenCounts(input_tokens=10),
    )
    second = usage(
        "second-final",
        "source-1",
        endpoint="endpoint-2",
        session_id="session-2",
        kind=UsageObservationKind.FINAL,
        counts=TokenCounts(input_tokens=7),
    )

    aggregate = project_usage_events((first, second)).attempt_totals["a01"]

    assert aggregate.reported_tokens.input_tokens == 17
    assert aggregate.finality is UsageFinality.FINAL


def test_missing_identity_is_rejected_when_multiple_sources_are_compatible() -> None:
    first = usage(
        "first",
        "source-1",
        endpoint=None,
        session_id="session-1",
        counts=TokenCounts(input_tokens=10),
    )
    second = usage(
        "second",
        "source-1",
        endpoint=None,
        session_id="session-2",
        counts=TokenCounts(input_tokens=7),
    )
    ambiguous = usage(
        "ambiguous",
        "source-2",
        endpoint=None,
        session_id=None,
        counts=TokenCounts(input_tokens=12),
    )

    with pytest.raises(UsageProjectionError, match="ambiguous"):
        project_usage_events((first, second, ambiguous))


def test_conflicts_regressions_post_final_and_correlation_reuse_are_rejected() -> None:
    first = usage("usage-1", "source-1")
    conflict = usage(
        "usage-1", "source-1", counts=TokenCounts(input_tokens=11, output_tokens=2)
    )
    version_conflict = usage(
        "usage-copy", "source-1", counts=TokenCounts(input_tokens=11, output_tokens=2)
    )
    with pytest.raises(UsageProjectionError, match="observation ID"):
        project_usage_events((first, conflict))
    with pytest.raises(UsageProjectionError, match="source version"):
        project_usage_events((first, version_conflict))
    with pytest.raises(UsageProjectionError, match="regressed"):
        project_usage_events(
            (
                usage("usage-1", "source-1", counts=TokenCounts(input_tokens=10)),
                usage("usage-2", "source-2", counts=TokenCounts(input_tokens=9)),
            )
        )
    with pytest.raises(UsageProjectionError, match="after the source's final"):
        project_usage_events(
            (
                usage("final", "source-1", kind=UsageObservationKind.FINAL),
                usage("late", "source-2"),
            )
        )
    with pytest.raises(UsageProjectionError, match="changed task or role"):
        project_usage_events(
            (first, usage("other", "source-2", task_id="MB-other"))
        )


def test_restart_replay_is_deterministic_for_partial_and_unavailable_sources() -> None:
    observations = (
        usage("usage-1", "source-1", counts=TokenCounts(input_tokens=10)),
        usage(
            "missing",
            "missing-1",
            attempt_id="qa01",
            role=Role.TESTER,
            endpoint=None,
            session_id=None,
            kind=UsageObservationKind.UNAVAILABLE,
            counts=None,
            cumulative=False,
        ),
    )
    serialized = tuple(
        TokenUsageObservation.from_dict(item.to_dict()) for item in observations
    )

    assert project_usage_events(serialized) == project_usage_events(observations)
