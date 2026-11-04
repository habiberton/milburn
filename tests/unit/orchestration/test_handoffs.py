"""Role-specific handoff and generation-fencing orchestration tests."""

from datetime import UTC, datetime, timedelta
from itertools import count

from milburn.domain.sessions import HandoffManifest, SessionLifecycleEvent, SessionLifecycleKind
from milburn.domain.states import Role
from milburn.orchestration.handoffs import (
    ReplacementEvidence,
    ReplacementTrigger,
    SessionHandoffCoordinator,
    SessionReplacementPolicy,
)
from milburn.persistence.session_projections import project_session_events
from milburn.validation.handoff_manifest import HandoffExpectation, HandoffManifestValidator


NOW = datetime(2026, 11, 3, tzinfo=UTC)


def manifest(role: Role = Role.CODER) -> HandoffManifest:
    return HandoffManifest(
        role=role,
        task_id="MB-018",
        attempt_id="a01",
        generation=0,
        issue_ref="issue-22",
        acceptance_refs=("AC-1",),
        worktree="/repo/worktree",
        branch="branch-name",
        base_sha="base123",
        head_sha="head456",
        progress_ref="progress.md",
        completed=("slice",),
        remaining=("tests",),
        test_evidence=(),
        open_decisions=(),
        inbox_sequence=2,
        outbox_sequence=3,
        uncertain_effects=(),
        brief_digest="briefdigest",
        rules_digest="rulesdigest",
        created_at=NOW,
    )


def expectation(role: Role = Role.CODER) -> HandoffExpectation:
    return HandoffExpectation(
        task_id="MB-018",
        role=role,
        attempt_id="a01",
        generation=0,
        issue_ref="issue-22",
        acceptance_refs=("AC-1",),
        worktree="/repo/worktree",
        branch="branch-name",
        base_sha="base123",
        head_sha="head456",
        progress_ref="progress.md",
        inbox_sequence=2,
        outbox_sequence=3,
        acknowledged_decisions=(),
        known_uncertain_effects=(),
        brief_digest="briefdigest",
        rules_digest="rulesdigest",
        now=NOW + timedelta(minutes=1),
    )


def start(role: Role = Role.CODER) -> SessionLifecycleEvent:
    return SessionLifecycleEvent(
        event_id="start",
        sequence=0,
        task_id="MB-018",
        role=role,
        attempt_id="a01",
        generation=0,
        endpoint="pane-0",
        session_id="session-0",
        source_version="start-v1",
        occurred_at=NOW,
        kind=SessionLifecycleKind.GENERATION_STARTED,
    )


def coordinator(role: Role = Role.CODER) -> SessionHandoffCoordinator:
    ids = count(1)
    return SessionHandoffCoordinator(
        validator=HandoffManifestValidator(),
        policy=SessionReplacementPolicy(),
        clock=lambda: NOW + timedelta(minutes=1),
        event_ids=lambda: f"replacement-{next(ids)}",
    )


def test_one_compaction_does_not_replace_coder_but_repeated_compaction_does() -> None:
    state = project_session_events((start(),))
    assert state is not None
    one = coordinator().plan_replacement(
        state=state,
        manifest=manifest(),
        expectation=expectation(),
        evidence=ReplacementEvidence(ReplacementTrigger.COMPACTION, 1),
    )
    repeated = coordinator().plan_replacement(
        state=state,
        manifest=manifest(),
        expectation=expectation(),
        evidence=ReplacementEvidence(ReplacementTrigger.COMPACTION, 2),
    )

    assert not one.decision.replace
    assert one.events == ()
    assert repeated.decision.replace
    assert [event.kind for event in repeated.events] == [
        SessionLifecycleKind.HANDOFF_VALIDATED,
        SessionLifecycleKind.REPLACEMENT_REQUESTED,
        SessionLifecycleKind.GENERATION_FENCED,
    ]
    fenced = project_session_events((start(), *repeated.events))
    assert fenced is not None
    assert fenced.current_generation.status.value == "fenced"


def test_role_boundaries_preserve_coder_and_refresh_specialized_calls() -> None:
    policy = SessionReplacementPolicy()
    boundary = ReplacementEvidence(ReplacementTrigger.SEMANTIC_BOUNDARY)

    assert not policy.decide(Role.CODER, boundary).replace
    assert not policy.decide(Role.PLANNER, boundary).replace
    assert not policy.decide(Role.ARCHITECT, boundary).replace
    assert policy.decide(Role.CLASSIFIER_ROUTER, boundary).replace
    assert not policy.decide(Role.TESTER, boundary).replace
    assert policy.decide(
        Role.TESTER,
        ReplacementEvidence(
            ReplacementTrigger.SEMANTIC_BOUNDARY, candidate_sha="candidate123"
        ),
    ).replace
    assert policy.decide(Role.COORDINATOR, boundary).replace


def test_degraded_context_can_replace_without_using_token_budget_policy() -> None:
    decision = SessionReplacementPolicy().decide(
        Role.CODER, ReplacementEvidence(ReplacementTrigger.DEGRADED_CONTEXT)
    )
    assert decision.replace
    assert decision.reason == "degraded_context"
