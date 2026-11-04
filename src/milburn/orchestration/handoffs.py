"""Role-aware session replacement planning from validated durable handoffs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Callable

from milburn.domain.sessions import (
    HandoffManifest,
    SessionLifecycleEvent,
    SessionLifecycleKind,
)
from milburn.domain.states import Role
from milburn.persistence.session_projections import SessionProjection
from milburn.validation.handoff_manifest import (
    HandoffExpectation,
    HandoffManifestValidator,
)


class ReplacementTrigger(StrEnum):
    COMPACTION = "compaction"
    DEGRADED_CONTEXT = "degraded_context"
    UNRECOVERABLE_FAILURE = "unrecoverable_failure"
    INDEPENDENCE_REQUIRED = "independence_required"
    SEMANTIC_BOUNDARY = "semantic_boundary"


class ReplacementPolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReplacementEvidence:
    trigger: ReplacementTrigger
    compaction_observations: int = 0
    candidate_sha: str | None = None


@dataclass(frozen=True, slots=True)
class ReplacementDecision:
    replace: bool
    reason: str


class SessionReplacementPolicy:
    """Keep role boundaries explicit without making token usage a budget policy."""

    def decide(self, role: Role, evidence: ReplacementEvidence) -> ReplacementDecision:
        if not isinstance(role, Role):
            raise ReplacementPolicyError("replacement requires a known role")
        if not isinstance(evidence, ReplacementEvidence):
            raise ReplacementPolicyError("replacement evidence is required")
        if evidence.compaction_observations < 0:
            raise ReplacementPolicyError("compaction observations cannot be negative")

        if evidence.trigger is ReplacementTrigger.COMPACTION:
            if evidence.compaction_observations < 2:
                return ReplacementDecision(
                    False, "one compaction alone is not a replacement trigger"
                )
            return ReplacementDecision(True, "repeated semantic compaction observed")
        if evidence.trigger in {
            ReplacementTrigger.DEGRADED_CONTEXT,
            ReplacementTrigger.UNRECOVERABLE_FAILURE,
            ReplacementTrigger.INDEPENDENCE_REQUIRED,
        }:
            return ReplacementDecision(True, evidence.trigger.value)
        if evidence.trigger is ReplacementTrigger.SEMANTIC_BOUNDARY:
            if role in {Role.PLANNER, Role.ARCHITECT}:
                return ReplacementDecision(
                    False, "planner and architect end at approved artifact boundaries"
                )
            if role is Role.CLASSIFIER_ROUTER:
                return ReplacementDecision(True, "router calls are short and fresh")
            if role is Role.TESTER:
                if (
                    not isinstance(evidence.candidate_sha, str)
                    or not evidence.candidate_sha.strip()
                ):
                    return ReplacementDecision(
                        False, "tester fresh start requires an exact candidate SHA"
                    )
                return ReplacementDecision(
                    True, "tester starts fresh from the exact candidate SHA"
                )
            if role is Role.CODER:
                return ReplacementDecision(
                    False, "coder normally retains one session per task attempt"
                )
            return ReplacementDecision(
                True, "coordinator identity continues in a fresh session generation"
            )
        raise ReplacementPolicyError(f"unsupported trigger {evidence.trigger!r}")


@dataclass(frozen=True, slots=True)
class ReplacementPlan:
    decision: ReplacementDecision
    events: tuple[SessionLifecycleEvent, ...]


class SessionHandoffCoordinator:
    """Validate, request, and fence before any replacement launch effect."""

    def __init__(
        self,
        *,
        validator: HandoffManifestValidator,
        policy: SessionReplacementPolicy,
        clock: Callable[[], datetime],
        event_ids: Callable[[], str],
    ) -> None:
        self._validator = validator
        self._policy = policy
        self._clock = clock
        self._event_ids = event_ids

    def plan_replacement(
        self,
        *,
        state: SessionProjection,
        manifest: HandoffManifest,
        expectation: HandoffExpectation,
        evidence: ReplacementEvidence,
    ) -> ReplacementPlan:
        if state.current_generation.generation != expectation.generation:
            raise ReplacementPolicyError("replacement expectation targets a stale generation")
        if state.task_id != expectation.task_id or state.attempt_id != expectation.attempt_id:
            raise ReplacementPolicyError("replacement expectation changed task ownership")
        validated = self._validator.validate(manifest, expectation)
        if state.role is Role.TESTER and (
            not isinstance(evidence.candidate_sha, str)
            or not evidence.candidate_sha.strip()
            or evidence.candidate_sha != validated.head_sha
        ):
            raise ReplacementPolicyError(
                "tester replacement candidate SHA must exactly match the validated handoff head"
            )
        decision = self._policy.decide(state.role, evidence)
        if not decision.replace:
            return ReplacementPlan(decision, ())

        now = self._clock()
        base = {
            "task_id": state.task_id,
            "role": state.role,
            "attempt_id": state.attempt_id,
            "generation": state.current_generation.generation,
            "endpoint": state.current_generation.endpoint,
            "session_id": state.current_generation.session_id,
            "source_version": f"handoff-{validated.schema_version}",
            "occurred_at": now,
        }
        next_sequence = state.version + 1
        events = (
            SessionLifecycleEvent(
                event_id=self._event_ids(),
                sequence=next_sequence,
                kind=SessionLifecycleKind.HANDOFF_VALIDATED,
                manifest=validated,
                **base,
            ),
            SessionLifecycleEvent(
                event_id=self._event_ids(),
                sequence=next_sequence + 1,
                kind=SessionLifecycleKind.REPLACEMENT_REQUESTED,
                **base,
            ),
            SessionLifecycleEvent(
                event_id=self._event_ids(),
                sequence=next_sequence + 2,
                kind=SessionLifecycleKind.GENERATION_FENCED,
                **base,
            ),
        )
        return ReplacementPlan(decision, events)
