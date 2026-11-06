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


def request(
    *,
    digest: str = "a" * 64,
    effect_id: str = "effect-1",
    marker: str = "milburn:acme/milburn:feature:task",
) -> EffectRequest:
    return EffectRequest(
        effect_id=effect_id,
        repository_id="acme/milburn",
        operation="create_issue",
        idempotency_marker=marker,
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


def test_marker_is_bound_to_one_effect_within_a_repository() -> None:
    journal = InMemoryEffectJournal()
    journal.request(request())

    with pytest.raises(EffectConflictError, match="already bound"):
        journal.request(request(effect_id="effect-2"))

    other_repository = request(effect_id="effect-2")
    other_repository = EffectRequest(
        effect_id=other_repository.effect_id,
        repository_id="other/repository",
        operation=other_repository.operation,
        idempotency_marker=other_repository.idempotency_marker,
        arguments_digest=other_repository.arguments_digest,
        fence=other_repository.fence,
    )
    assert journal.request(other_repository).status is EffectStatus.REQUESTED


def test_generation_fence_rejects_stale_or_unknown_generation() -> None:
    fence = InMemoryGenerationFence()
    fence.activate("MB-008", "a01", 3)

    fence.assert_current(EffectFence("MB-008", "a01", 3))

    with pytest.raises(StaleGenerationError, match="not active"):
        fence.assert_current(EffectFence("MB-008", "a01", 2))
    with pytest.raises(StaleGenerationError, match="older generation"):
        fence.activate("MB-008", "a01", 1)


def test_generation_fence_scopes_reused_attempt_ids_by_task() -> None:
    fence = InMemoryGenerationFence()
    fence.activate("MB-008", "a01", 3)
    fence.activate("MB-009", "a01", 1)

    fence.assert_current(EffectFence("MB-008", "a01", 3))
    fence.assert_current(EffectFence("MB-009", "a01", 1))

    with pytest.raises(StaleGenerationError):
        fence.assert_current(EffectFence("MB-008", "a01", 1))


ALLOWED = {
    EffectStatus.REQUESTED: {EffectStatus.RECONCILED},
    EffectStatus.RECONCILED: {EffectStatus.CALL_STARTED, EffectStatus.OBSERVED},
    EffectStatus.CALL_STARTED: {EffectStatus.RECONCILED, EffectStatus.OBSERVED, EffectStatus.UNCERTAIN},
    EffectStatus.UNCERTAIN: {EffectStatus.RECONCILED, EffectStatus.OBSERVED},
    EffectStatus.OBSERVED: {EffectStatus.OBSERVED},
}
PATHS = {
    EffectStatus.REQUESTED: [],
    EffectStatus.RECONCILED: [EffectStatus.RECONCILED],
    EffectStatus.CALL_STARTED: [EffectStatus.RECONCILED, EffectStatus.CALL_STARTED],
    EffectStatus.UNCERTAIN: [EffectStatus.RECONCILED, EffectStatus.CALL_STARTED, EffectStatus.UNCERTAIN],
    EffectStatus.OBSERVED: [EffectStatus.RECONCILED, EffectStatus.OBSERVED],
}


def _at(status: EffectStatus) -> InMemoryEffectJournal:
    journal = InMemoryEffectJournal()
    journal.request(request())
    for step in PATHS[status]:
        identity = "issue-1" if step is EffectStatus.OBSERVED else None
        journal.transition("effect-1", step, remote_identity=identity)
    assert journal.get("effect-1").status is status
    return journal


@pytest.mark.parametrize("source", list(EffectStatus))
@pytest.mark.parametrize("target", list(EffectStatus))
def test_every_transition_is_allowed_or_refused_exactly_as_specified(source, target) -> None:
    journal = _at(source)
    identity = "issue-1" if target is EffectStatus.OBSERVED else None
    if target in ALLOWED[source]:
        record = journal.transition("effect-1", target, remote_identity=identity)
        assert record.status is target and record.remote_identity == identity
    else:
        with pytest.raises(EffectConflictError, match="invalid effect transition"):
            journal.transition("effect-1", target, remote_identity=identity)
        assert journal.get("effect-1").status is source


def test_observed_requires_a_remote_identity_and_others_refuse_one() -> None:
    journal = _at(EffectStatus.RECONCILED)
    with pytest.raises(EffectConflictError, match="require a remote identity"):
        journal.transition("effect-1", EffectStatus.OBSERVED)
    with pytest.raises(EffectConflictError, match="only observed"):
        journal.transition("effect-1", EffectStatus.CALL_STARTED, remote_identity="issue-1")
    assert journal.get("effect-1").status is EffectStatus.RECONCILED


def test_unknown_effect_id_is_refused() -> None:
    with pytest.raises(EffectConflictError, match="unknown effect ID"):
        InMemoryEffectJournal().transition("missing", EffectStatus.RECONCILED)
