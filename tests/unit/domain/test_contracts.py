"""Public contract behavior for immutable, versioned domain envelopes."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from milburn.domain import (
    AgentAttempt,
    ArchitecturePackage,
    AttemptState,
    CoderOutcome,
    CoderResult,
    CommandArgument,
    CommandEnvelope,
    CommandType,
    DecisionRequest,
    DomainEvent,
    EventFact,
    EventType,
    EvidenceItem,
    FeatureState,
    GitHubEffect,
    GitHubEffectStatus,
    InvalidEnvelopeError,
    InvalidIdentifierError,
    IssueDraft,
    PlanEnvelope,
    PlanStage,
    QAOutcome,
    QAReport,
    RequestEnvelope,
    Role,
    RoleRouteProposal,
    SkillBinding,
    UnsupportedSchemaVersionError,
)


NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def request() -> RequestEnvelope:
    return RequestEnvelope(
        request_id="request-1",
        feature_id="feature-1",
        objective="Build the approved workflow",
        repository_id="habiberton/milburn",
        base_branch="main",
        delivery_posture="review-before-delivery",
        submitted_at=NOW,
    )


def decision() -> DecisionRequest:
    return DecisionRequest(
        decision_id="decision-1",
        source_attempt_id="attempt-1",
        feature_id="feature-1",
        issue_number=2,
        question="Which supported option should be used?",
        why_it_matters="The worker cannot proceed without it.",
        options=("first", "second"),
        recommendation="first",
        blocking=True,
    )


def issue_draft() -> IssueDraft:
    return IssueDraft(
        task_key="task-1",
        title="Implement one bounded task",
        objective="Create the approved implementation",
        spec_links=("PRD.md", "ARCH.md"),
        acceptance_criteria=("Behavior is observable",),
        dependencies=(),
        test_instructions=("python3 -m pytest -q",),
        expected_artifacts=("source and tests",),
        risks=("external state",),
        non_goals=("deployment",),
    )


@pytest.mark.parametrize(
    "model",
    [
        request(),
        RoleRouteProposal(
            request_id="request-1",
            current_state=FeatureState.RECEIVED,
            proposed_role=Role.PLANNER,
            reason="A plan is required.",
            confidence=0.9,
            decision_needed=False,
        ),
        decision(),
        PlanEnvelope(
            feature_id="feature-1",
            summary="A staged plan",
            stages=(
                PlanStage(
                    stage_id="stage-1",
                    title="Foundation",
                    description="Build contracts first.",
                ),
            ),
            dependencies=(),
            risks=("Ambiguous input",),
            decisions_needed=(decision(),),
        ),
        ArchitecturePackage(
            feature_id="feature-1",
            prd_artifact="PRD.md",
            arch_artifact="ARCH.md",
            issue_drafts=(issue_draft(),),
            open_decisions=(decision(),),
        ),
        GitHubEffect(
            effect_id="effect-1",
            repository_id="habiberton/milburn",
            operation="create_issue",
            idempotency_marker="milburn:feature-1:task-1",
            requested_arguments_digest="a1b2c3",
            status=GitHubEffectStatus.REQUESTED,
            remote_identity=None,
            last_observation=None,
        ),
        CommandEnvelope(
            command_id="command-1",
            command_type=CommandType.REQUEST_AGENT_LAUNCH,
            actor_role=Role.COORDINATOR,
            feature_id="feature-1",
            issue_number=2,
            attempt_id="attempt-1",
            correlation_id="correlation-1",
            arguments=(CommandArgument(name="generation", value="1"),),
        ),
        DomainEvent(
            event_id="event-1",
            stream="feature:feature-1",
            sequence=0,
            event_type=EventType.REQUEST_ACCEPTED,
            occurred_at=NOW,
            correlation_id="correlation-1",
            causation_id="command-1",
            facts=(EventFact(name="feature_id", value="feature-1"),),
        ),
    ],
)
def test_contracts_round_trip_with_explicit_schema_version(model: object) -> None:
    payload = model.to_dict()  # type: ignore[attr-defined]

    assert payload["schema_version"] == 1
    assert type(model).from_dict(payload) == model


def test_nested_collections_are_detached_from_serialized_input() -> None:
    payload = ArchitecturePackage(
        feature_id="feature-1",
        prd_artifact="PRD.md",
        arch_artifact="ARCH.md",
        issue_drafts=(issue_draft(),),
        open_decisions=(decision(),),
    ).to_dict()

    restored = ArchitecturePackage.from_dict(payload)
    payload["issue_drafts"][0]["acceptance_criteria"].append("mutated")

    assert restored.issue_drafts[0].acceptance_criteria == ("Behavior is observable",)


def test_contracts_are_frozen_and_use_tuples() -> None:
    value = decision()

    with pytest.raises(FrozenInstanceError):
        value.question = "changed"  # type: ignore[misc]

    assert isinstance(value.options, tuple)

    with pytest.raises(InvalidEnvelopeError, match="immutable tuple"):
        DecisionRequest(
            decision_id="decision-2",
            source_attempt_id="attempt-1",
            feature_id="feature-1",
            issue_number=None,
            question="Choose",
            why_it_matters="The choice is blocking.",
            options=["first", "second"],  # type: ignore[arg-type]
            recommendation=None,
            blocking=True,
        )


def test_unknown_missing_and_unsupported_envelope_fields_are_explicit_errors() -> None:
    payload = request().to_dict()
    payload["unknown"] = "value"
    with pytest.raises(InvalidEnvelopeError, match="unknown"):
        RequestEnvelope.from_dict(payload)

    payload = request().to_dict()
    del payload["feature_id"]
    with pytest.raises(InvalidEnvelopeError, match="missing"):
        RequestEnvelope.from_dict(payload)

    payload = request().to_dict()
    payload["schema_version"] = 99
    with pytest.raises(UnsupportedSchemaVersionError, match="99"):
        RequestEnvelope.from_dict(payload)


def test_unknown_roles_and_states_fail_during_deserialization() -> None:
    payload = RoleRouteProposal(
        request_id="request-1",
        current_state=FeatureState.RECEIVED,
        proposed_role=Role.PLANNER,
        reason="A plan is required.",
        confidence=0.8,
        decision_needed=False,
    ).to_dict()
    payload["proposed_role"] = "administrator"

    with pytest.raises(InvalidEnvelopeError, match="unknown Role"):
        RoleRouteProposal.from_dict(payload)


def test_unknown_role_fails_during_direct_construction() -> None:
    with pytest.raises(InvalidEnvelopeError, match="Role"):
        RoleRouteProposal(
            request_id="request-1",
            current_state=FeatureState.RECEIVED,
            proposed_role="administrator",  # type: ignore[arg-type]
            reason="This role is not part of v1.",
            confidence=0.1,
            decision_needed=True,
        )


@pytest.mark.parametrize("identifier", ["", " ", "has whitespace", " trailing "])
def test_malformed_identifiers_fail_explicitly(identifier: str) -> None:
    with pytest.raises(InvalidIdentifierError):
        RequestEnvelope(
            request_id=identifier,
            feature_id="feature-1",
            objective="Build it",
            repository_id="owner/repo",
            base_branch="main",
            delivery_posture="review",
            submitted_at=NOW,
        )


def test_datetime_requires_timezone() -> None:
    with pytest.raises(InvalidEnvelopeError, match="timezone-aware"):
        RequestEnvelope(
            request_id="request-1",
            feature_id="feature-1",
            objective="Build it",
            repository_id="owner/repo",
            base_branch="main",
            delivery_posture="review",
            submitted_at=datetime(2026, 11, 3),
        )


def test_result_contracts_carry_nested_versioned_evidence() -> None:
    evidence = EvidenceItem(name="unit tests", outcome="passed", evidence="12 passed")
    coder = CoderResult(
        attempt_id="attempt-1",
        issue_number=2,
        outcome=CoderOutcome.CANDIDATE,
        head_sha="abcdef",
        progress_path=".milburn/issues/2/progress.txt",
        commits=("abcdef",),
        files_changed=("src/milburn/domain/models.py",),
        test_claims=(evidence,),
        risks=(),
    )
    qa = QAReport(
        attempt_id="test-attempt-1",
        issue_number=2,
        candidate_sha="abcdef",
        outcome=QAOutcome.PASSED,
        acceptance_results=(evidence,),
        commands=("python3 -m pytest -q",),
        evidence_artifacts=("report.json",),
        defects=(),
        summary="All criteria passed.",
    )

    assert CoderResult.from_dict(coder.to_dict()) == coder
    assert QAReport.from_dict(qa.to_dict()) == qa


def test_agent_attempt_preserves_skill_bindings_as_values() -> None:
    binding = SkillBinding(
        skill_name="milburn-qa",
        version="1",
        root_digest="abcdef",
        resource_digests=("123456",),
        workspace_path=".agents/skills/milburn-qa",
        validated_at=NOW,
    )
    attempt = AgentAttempt(
        attempt_id="attempt-1",
        generation=1,
        role=Role.TESTER,
        feature_id="feature-1",
        issue_number=None,
        endpoint="session:@1.%1",
        worktree=None,
        branch=None,
        base_sha=None,
        rules_digest="fedcba",
        skill_bindings=(binding,),
        status=AttemptState.STARTING,
    )

    assert AgentAttempt.from_dict(attempt.to_dict()) == attempt


def test_command_catalog_covers_role_requests_and_lifecycle_controls() -> None:
    assert {
        "submit_intake_proposal",
        "request_status_summary",
        "submit_issue_drafts",
        "report_progress",
        "submit_candidate",
        "submit_qa_report",
        "interrupt_agent",
        "terminate_agent",
        "resume_agent",
        "replace_agent",
        "retire_agent",
    } <= {command.value for command in CommandType}


def command(**overrides: object) -> CommandEnvelope:
    values: dict[str, object] = {
        "command_id": "command-1",
        "command_type": CommandType.REPORT_PROGRESS,
        "actor_role": Role.CODER,
        "feature_id": "feature-1",
        "issue_number": 2,
        "attempt_id": "attempt-1",
        "correlation_id": "correlation-1",
        "arguments": (CommandArgument(name="status", value="working"),),
    }
    values.update(overrides)
    return CommandEnvelope(**values)  # type: ignore[arg-type]


def test_command_rejects_invalid_actor_role() -> None:
    with pytest.raises(InvalidEnvelopeError, match="actor_role"):
        command(actor_role="coder")


def test_command_rejects_negative_issue_number() -> None:
    with pytest.raises(InvalidEnvelopeError, match="non-negative"):
        command(issue_number=-1)


def test_command_rejects_malformed_attempt_id() -> None:
    with pytest.raises(InvalidIdentifierError, match="attempt_id"):
        command(attempt_id="bad attempt")


def test_command_rejects_duplicate_argument_names() -> None:
    with pytest.raises(InvalidEnvelopeError, match="unique"):
        command(
            arguments=(
                CommandArgument(name="status", value="working"),
                CommandArgument(name="status", value="waiting"),
            )
        )


def test_event_catalog_covers_approved_durable_facts() -> None:
    assert {
        "RequestAccepted",
        "RoleRouteProposed",
        "RoleRouteApproved",
        "DecisionRequested",
        "CoordinatorNotificationQueued",
        "SteeringAcknowledged",
        "AgentLaunchRequested",
        "AgentStarted",
        "PlanReceived",
        "ArchitecturePackageReceived",
        "GitHubEffectRequested",
        "GitHubEffectObserved",
        "GitHubEffectReconciled",
        "CoderAttemptStarted",
        "CoderCheckpointObserved",
        "CoderResultReceived",
        "TestingRequested",
        "TestResultReceived",
        "IssueApproved",
        "RecoveryStarted",
        "RecoveryCompleted",
        "FeatureCompleted",
    } <= {event.value for event in EventType}
