import pytest

from milburn.integrations.github.contracts import EffectFence
from milburn.integrations.mcp import (
    EffectConflictError,
    EffectRequest,
    EffectStatus,
    InMemoryEffectJournal,
    InMemoryGenerationFence,
    StaleGenerationError,
)


def request(*, digest: str = "a" * 64) -> EffectRequest:
    return EffectRequest(
        effect_id="effect-1",
        repository_id="acme/milburn",
        operation="create_issue",
        idempotency_marker="milburn:acme/milburn:feature:task",
        arguments_digest=digest,
        fence=EffectFence("MB-008", "a01", 2),
    )


def test_journal_records_request_before_transitions_and_preserves_history() -> None:
    journal = InMemoryEffectJournal()

    initial = journal.request(request())
    journal.transition("effect-1", EffectStatus.RECONCILED)
    final = journal.transition(
        "effect-1", EffectStatus.OBSERVED, remote_identity="issue-17"
    )

    assert initial.status is EffectStatus.REQUESTED
    assert [record.status for record in journal.history] == [
        EffectStatus.REQUESTED,
        EffectStatus.RECONCILED,
        EffectStatus.OBSERVED,
    ]
    assert final.remote_identity == "issue-17"


def test_effect_id_is_bound_to_exact_arguments_and_generation() -> None:
    journal = InMemoryEffectJournal()
    original = journal.request(request())

    duplicate = journal.request(request())

    assert duplicate is original
    with pytest.raises(EffectConflictError, match="another request"):
        journal.request(request(digest="b" * 64))


def test_generation_fence_rejects_stale_or_unknown_generation() -> None:
    fence = InMemoryGenerationFence()
    fence.activate("a01", 3)

    fence.assert_current(EffectFence("MB-008", "a01", 3))

    with pytest.raises(StaleGenerationError, match="not active"):
        fence.assert_current(EffectFence("MB-008", "a01", 2))
    with pytest.raises(StaleGenerationError, match="older generation"):
        fence.activate("a01", 1)
