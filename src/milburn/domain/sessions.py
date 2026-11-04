"""Versioned contracts for logical attempts, session generations, and handoffs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .base import (
    VersionedModel,
    require_bool,
    require_enum,
    require_identifier,
    require_non_negative,
    require_text,
    require_timezone_aware,
)
from .errors import InvalidEnvelopeError
from .states import Role


class ObservationAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class ObservationFinality(StrEnum):
    PARTIAL = "partial"
    FINAL = "final"


class SessionObservationKind(StrEnum):
    IDENTITY = "identity"
    COMPACTION = "compaction"
    CONTEXT_USAGE = "context_usage"


class SessionGenerationStatus(StrEnum):
    ACTIVE = "active"
    FENCED = "fenced"
    REPLACED = "replaced"


class SessionLifecycleKind(StrEnum):
    GENERATION_STARTED = "generation_started"
    HANDOFF_VALIDATED = "handoff_validated"
    REPLACEMENT_REQUESTED = "replacement_requested"
    GENERATION_FENCED = "generation_fenced"
    REPLACEMENT_COMPLETED = "replacement_completed"


@dataclass(frozen=True, slots=True)
class SessionGeneration(VersionedModel):
    attempt_id: str
    generation: int
    endpoint: str | None
    session_id: str | None
    source_version: str
    started_at: datetime
    status: SessionGenerationStatus
    fenced_at: datetime | None = None

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.attempt_id, "attempt_id")
        require_non_negative(self.generation, "generation")
        for name in ("endpoint", "session_id"):
            value = getattr(self, name)
            if value is not None:
                require_identifier(value, name)
        require_identifier(self.source_version, "source_version")
        require_timezone_aware(self.started_at, "started_at")
        require_enum(self.status, SessionGenerationStatus, "status")
        if self.fenced_at is not None:
            require_timezone_aware(self.fenced_at, "fenced_at")
        if self.status is SessionGenerationStatus.ACTIVE and self.fenced_at is not None:
            raise InvalidEnvelopeError("an active generation cannot have a fence time")
        if self.status is not SessionGenerationStatus.ACTIVE and self.fenced_at is None:
            raise InvalidEnvelopeError("a fenced or replaced generation needs a fence time")


@dataclass(frozen=True, slots=True)
class SessionObservation(VersionedModel):
    """One semantic Codex observation, never terminal text."""

    observation_id: str
    task_id: str
    role: Role
    attempt_id: str
    generation: int
    endpoint: str | None
    session_id: str | None
    kind: SessionObservationKind
    availability: ObservationAvailability
    source_version: str
    observed_at: datetime
    finality: ObservationFinality
    compaction_count: int | None = None
    context_used_tokens: int | None = None
    context_window_tokens: int | None = None

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.observation_id, "observation_id")
        require_identifier(self.task_id, "task_id")
        require_enum(self.role, Role, "role")
        require_identifier(self.attempt_id, "attempt_id")
        require_non_negative(self.generation, "generation")
        for name in ("endpoint", "session_id"):
            value = getattr(self, name)
            if value is not None:
                require_identifier(value, name)
        require_enum(self.kind, SessionObservationKind, "kind")
        require_enum(self.availability, ObservationAvailability, "availability")
        require_identifier(self.source_version, "source_version")
        require_timezone_aware(self.observed_at, "observed_at")
        require_enum(self.finality, ObservationFinality, "finality")
        for name in (
            "compaction_count",
            "context_used_tokens",
            "context_window_tokens",
        ):
            value = getattr(self, name)
            if value is not None:
                require_non_negative(value, name)

        values = (
            self.compaction_count,
            self.context_used_tokens,
            self.context_window_tokens,
        )
        if self.availability is ObservationAvailability.UNAVAILABLE:
            if any(value is not None for value in values):
                raise InvalidEnvelopeError(
                    "unavailable session observations cannot fabricate values"
                )
            return
        if self.kind is SessionObservationKind.IDENTITY:
            if self.endpoint is None and self.session_id is None:
                raise InvalidEnvelopeError("available identity needs an endpoint or session ID")
            if any(value is not None for value in values):
                raise InvalidEnvelopeError("identity observations cannot carry usage values")
        elif self.kind is SessionObservationKind.COMPACTION:
            if self.compaction_count is None:
                raise InvalidEnvelopeError("available compaction needs compaction_count")
            if self.context_used_tokens is not None or self.context_window_tokens is not None:
                raise InvalidEnvelopeError("compaction cannot carry context usage")
        elif (
            self.context_used_tokens is None
            and self.context_window_tokens is None
        ):
            raise InvalidEnvelopeError("available context usage needs a reported value")
        if (
            self.context_used_tokens is not None
            and self.context_window_tokens is not None
            and self.context_used_tokens > self.context_window_tokens
        ):
            raise InvalidEnvelopeError("context usage cannot exceed the reported window")

    @property
    def semantic_key(self) -> tuple[str, str, str, int, SessionObservationKind, str]:
        return (
            self.task_id,
            self.role.value,
            self.attempt_id,
            self.generation,
            self.kind,
            self.source_version,
        )


@dataclass(frozen=True, slots=True)
class TestEvidence(VersionedModel):
    command: str
    result: str
    passed: bool
    revision: str

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_text(self.command, "command")
        require_text(self.result, "result")
        require_bool(self.passed, "passed")
        require_identifier(self.revision, "revision")


@dataclass(frozen=True, slots=True)
class UncertainEffect(VersionedModel):
    effect_id: str
    description: str
    reconciled: bool
    reconciliation_evidence: str | None = None

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_identifier(self.effect_id, "effect_id")
        require_text(self.description, "description")
        require_bool(self.reconciled, "reconciled")
        if self.reconciliation_evidence is not None:
            require_text(self.reconciliation_evidence, "reconciliation_evidence")
        if self.reconciled and self.reconciliation_evidence is None:
            raise InvalidEnvelopeError("reconciled effects require evidence")
        if not self.reconciled and self.reconciliation_evidence is not None:
            raise InvalidEnvelopeError("unresolved effects cannot claim reconciliation evidence")


@dataclass(frozen=True, slots=True)
class HandoffManifest(VersionedModel):
    """Transcript-free durable checkpoint used to replace a session generation."""

    role: Role
    task_id: str
    attempt_id: str
    generation: int
    issue_ref: str
    acceptance_refs: tuple[str, ...]
    worktree: str
    branch: str
    base_sha: str
    head_sha: str
    progress_ref: str
    completed: tuple[str, ...]
    remaining: tuple[str, ...]
    test_evidence: tuple[TestEvidence, ...]
    open_decisions: tuple[str, ...]
    inbox_sequence: int
    outbox_sequence: int
    uncertain_effects: tuple[UncertainEffect, ...]
    brief_digest: str
    rules_digest: str
    created_at: datetime

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        require_enum(self.role, Role, "role")
        for name in (
            "task_id",
            "attempt_id",
            "issue_ref",
            "branch",
            "base_sha",
            "head_sha",
            "brief_digest",
            "rules_digest",
        ):
            require_identifier(getattr(self, name), name)
        require_non_negative(self.generation, "generation")
        require_text(self.worktree, "worktree")
        require_text(self.progress_ref, "progress_ref")
        require_non_negative(self.inbox_sequence, "inbox_sequence")
        require_non_negative(self.outbox_sequence, "outbox_sequence")
        require_timezone_aware(self.created_at, "created_at")
        if not self.acceptance_refs:
            raise InvalidEnvelopeError("acceptance_refs must not be empty")
        if not self.completed and not self.remaining:
            raise InvalidEnvelopeError("handoff must describe completed or remaining work")
        for field_name in (
            "acceptance_refs",
            "completed",
            "remaining",
            "open_decisions",
        ):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise InvalidEnvelopeError(f"{field_name} must not contain duplicates")
            for value in values:
                require_text(value, field_name)
        effect_ids = [effect.effect_id for effect in self.uncertain_effects]
        if len(effect_ids) != len(set(effect_ids)):
            raise InvalidEnvelopeError("uncertain effect IDs must be unique")
        test_commands = [evidence.command for evidence in self.test_evidence]
        if len(test_commands) != len(set(test_commands)):
            raise InvalidEnvelopeError("test evidence commands must be unique")


@dataclass(frozen=True, slots=True)
class SessionLifecycleEvent(VersionedModel):
    event_id: str
    sequence: int
    task_id: str
    role: Role
    attempt_id: str
    generation: int
    endpoint: str | None
    session_id: str | None
    source_version: str
    occurred_at: datetime
    kind: SessionLifecycleKind
    manifest: HandoffManifest | None = None

    def __post_init__(self) -> None:
        VersionedModel.__post_init__(self)
        for name in ("event_id", "task_id", "attempt_id", "source_version"):
            require_identifier(getattr(self, name), name)
        require_non_negative(self.sequence, "sequence")
        require_enum(self.role, Role, "role")
        require_non_negative(self.generation, "generation")
        for name in ("endpoint", "session_id"):
            value = getattr(self, name)
            if value is not None:
                require_identifier(value, name)
        require_timezone_aware(self.occurred_at, "occurred_at")
        require_enum(self.kind, SessionLifecycleKind, "kind")
        if self.kind is SessionLifecycleKind.HANDOFF_VALIDATED:
            if self.manifest is None:
                raise InvalidEnvelopeError("handoff validation needs the validated manifest")
            if (
                self.manifest.task_id != self.task_id
                or self.manifest.role is not self.role
                or self.manifest.attempt_id != self.attempt_id
                or self.manifest.generation != self.generation
            ):
                raise InvalidEnvelopeError("validated manifest correlation does not match event")
        elif self.manifest is not None:
            raise InvalidEnvelopeError("only handoff validation events carry a manifest")
