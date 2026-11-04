"""Validation of transcript-free handoff checkpoints against durable state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from milburn.domain.sessions import HandoffManifest
from milburn.domain.states import Role


class HandoffManifestError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class HandoffExpectation:
    task_id: str
    role: Role
    attempt_id: str
    generation: int
    issue_ref: str
    acceptance_refs: tuple[str, ...]
    worktree: str
    branch: str
    base_sha: str
    head_sha: str
    progress_ref: str
    inbox_sequence: int
    outbox_sequence: int
    acknowledged_decisions: tuple[str, ...]
    known_uncertain_effects: tuple[str, ...]
    brief_digest: str
    rules_digest: str
    now: datetime
    maximum_age: timedelta = timedelta(minutes=30)
    required_test_commands: tuple[str, ...] = ()


class HandoffManifestValidator:
    """Reject a handoff unless it exactly matches current durable authority."""

    def validate(
        self, manifest: HandoffManifest, expectation: HandoffExpectation
    ) -> HandoffManifest:
        if not isinstance(manifest, HandoffManifest):
            raise HandoffManifestError("handoff must be a versioned HandoffManifest")
        comparisons = {
            "task_id": expectation.task_id,
            "role": expectation.role,
            "attempt_id": expectation.attempt_id,
            "generation": expectation.generation,
            "issue_ref": expectation.issue_ref,
            "worktree": expectation.worktree,
            "branch": expectation.branch,
            "base_sha": expectation.base_sha,
            "head_sha": expectation.head_sha,
            "progress_ref": expectation.progress_ref,
            "inbox_sequence": expectation.inbox_sequence,
            "outbox_sequence": expectation.outbox_sequence,
            "brief_digest": expectation.brief_digest,
            "rules_digest": expectation.rules_digest,
        }
        for name, expected in comparisons.items():
            if getattr(manifest, name) != expected:
                raise HandoffManifestError(
                    f"handoff {name} does not match current durable state"
                )
        if manifest.acceptance_refs != expectation.acceptance_refs:
            raise HandoffManifestError("handoff acceptance references are stale")
        age = expectation.now - manifest.created_at
        if age < timedelta(0) or age > expectation.maximum_age:
            raise HandoffManifestError("handoff manifest is stale")
        if any(evidence.revision != manifest.head_sha for evidence in manifest.test_evidence):
            raise HandoffManifestError("test evidence does not target the handoff head SHA")
        evidence_by_command = {
            evidence.command: evidence for evidence in manifest.test_evidence
        }
        missing_tests = set(expectation.required_test_commands) - set(
            evidence_by_command
        )
        if missing_tests:
            raise HandoffManifestError(
                "handoff is missing exact test evidence: "
                + ", ".join(sorted(missing_tests))
            )
        failed_tests = [
            command
            for command in expectation.required_test_commands
            if not evidence_by_command[command].passed
        ]
        if failed_tests:
            raise HandoffManifestError(
                "handoff required tests did not pass: "
                + ", ".join(sorted(failed_tests))
            )
        missing_acks = set(manifest.open_decisions) - set(
            expectation.acknowledged_decisions
        )
        if missing_acks:
            raise HandoffManifestError(
                "handoff is missing required decision acknowledgements: "
                + ", ".join(sorted(missing_acks))
            )
        manifest_effects = {effect.effect_id for effect in manifest.uncertain_effects}
        hidden = set(expectation.known_uncertain_effects) - manifest_effects
        if hidden:
            raise HandoffManifestError(
                "handoff hides uncertain external effects: " + ", ".join(sorted(hidden))
            )
        unresolved = [
            effect.effect_id
            for effect in manifest.uncertain_effects
            if not effect.reconciled
        ]
        if unresolved:
            raise HandoffManifestError(
                "handoff contains unresolved uncertain effects: "
                + ", ".join(sorted(unresolved))
            )
        return manifest
