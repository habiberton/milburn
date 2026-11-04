"""Durable handoff-manifest validation tests."""

from datetime import UTC, datetime, timedelta

import pytest

from milburn.domain.sessions import (
    HandoffManifest,
    TestEvidence as HandoffTestEvidence,
    UncertainEffect,
)
from milburn.domain.states import Role
from milburn.validation.handoff_manifest import (
    HandoffExpectation,
    HandoffManifestError,
    HandoffManifestValidator,
)


NOW = datetime(2026, 11, 3, 20, 0, tzinfo=UTC)


def manifest(**changes: object) -> HandoffManifest:
    values: dict[str, object] = {
        "role": Role.CODER,
        "task_id": "MB-018",
        "attempt_id": "a01",
        "generation": 0,
        "issue_ref": "issue-22",
        "acceptance_refs": ("AC-1", "AC-2"),
        "worktree": "/repo/worktree",
        "branch": "bootstrap/builder/MB-018/a01",
        "base_sha": "base123",
        "head_sha": "head456",
        "progress_ref": "bootstrap/progress/tasks/MB-018.md",
        "completed": ("domain contracts",),
        "remaining": ("integration",),
        "test_evidence": (
            HandoffTestEvidence(
                command="pytest tests/unit", result="12 passed", passed=True, revision="head456"
            ),
        ),
        "open_decisions": ("decision-1",),
        "inbox_sequence": 4,
        "outbox_sequence": 6,
        "uncertain_effects": (
            UncertainEffect(
                effect_id="effect-1",
                description="remote mutation timed out",
                reconciled=True,
                reconciliation_evidence="remote read showed no mutation",
            ),
        ),
        "brief_digest": "briefdigest",
        "rules_digest": "rulesdigest",
        "created_at": NOW,
    }
    values.update(changes)
    return HandoffManifest(**values)  # type: ignore[arg-type]


def expectation(**changes: object) -> HandoffExpectation:
    values: dict[str, object] = {
        "task_id": "MB-018",
        "role": Role.CODER,
        "attempt_id": "a01",
        "generation": 0,
        "issue_ref": "issue-22",
        "acceptance_refs": ("AC-1", "AC-2"),
        "worktree": "/repo/worktree",
        "branch": "bootstrap/builder/MB-018/a01",
        "base_sha": "base123",
        "head_sha": "head456",
        "progress_ref": "bootstrap/progress/tasks/MB-018.md",
        "inbox_sequence": 4,
        "outbox_sequence": 6,
        "acknowledged_decisions": ("decision-1",),
        "known_uncertain_effects": ("effect-1",),
        "brief_digest": "briefdigest",
        "rules_digest": "rulesdigest",
        "now": NOW + timedelta(minutes=5),
    }
    values.update(changes)
    return HandoffExpectation(**values)  # type: ignore[arg-type]


def test_validates_complete_transcript_free_manifest_and_round_trips() -> None:
    checkpoint = manifest()
    assert HandoffManifestValidator().validate(checkpoint, expectation()) == checkpoint
    assert HandoffManifest.from_dict(checkpoint.to_dict()) == checkpoint
    with pytest.raises(ValueError, match="unknown.*transcript"):
        HandoffManifest.from_dict({**checkpoint.to_dict(), "transcript": "private"})


@pytest.mark.parametrize(
    ("checkpoint", "expected", "message"),
    (
        (manifest(task_id="MB-999"), expectation(), "task_id"),
        (manifest(head_sha="oldsha"), expectation(), "head_sha"),
        (
            manifest(created_at=NOW - timedelta(hours=2)),
            expectation(),
            "stale",
        ),
        (manifest(), expectation(acknowledged_decisions=()), "acknowledgements"),
        (manifest(uncertain_effects=()), expectation(), "hides uncertain"),
    ),
)
def test_rejects_stale_mismatched_unacknowledged_or_hidden_effect_handoffs(
    checkpoint: HandoffManifest, expected: HandoffExpectation, message: str
) -> None:
    with pytest.raises(HandoffManifestError, match=message):
        HandoffManifestValidator().validate(checkpoint, expected)


def test_rejects_disclosed_but_unresolved_uncertain_effect() -> None:
    unresolved = UncertainEffect(
        effect_id="effect-1",
        description="outcome is still unknown",
        reconciled=False,
    )
    with pytest.raises(HandoffManifestError, match="unresolved"):
        HandoffManifestValidator().validate(
            manifest(uncertain_effects=(unresolved,)), expectation()
        )


def test_rejects_missing_or_failed_required_test_evidence() -> None:
    command = "pytest tests/unit"
    with pytest.raises(HandoffManifestError, match="missing exact test"):
        HandoffManifestValidator().validate(
            manifest(test_evidence=()), expectation(required_test_commands=(command,))
        )
    with pytest.raises(HandoffManifestError, match="did not pass"):
        HandoffManifestValidator().validate(
            manifest(
                test_evidence=(
                    HandoffTestEvidence(
                        command=command,
                        result="1 failed",
                        passed=False,
                        revision="head456",
                    ),
                )
            ),
            expectation(required_test_commands=(command,)),
        )


def test_rejects_duplicate_test_commands_even_when_results_contradict() -> None:
    command = "pytest tests/unit"
    with pytest.raises(ValueError, match="test evidence commands must be unique"):
        manifest(
            test_evidence=(
                HandoffTestEvidence(
                    command=command,
                    result="1 failed",
                    passed=False,
                    revision="head456",
                ),
                HandoffTestEvidence(
                    command=command,
                    result="12 passed",
                    passed=True,
                    revision="head456",
                ),
            )
        )
