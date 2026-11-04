"""Deterministic, bounded launch briefs for Codex roles."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from milburn.domain import Role, SkillBinding


class BriefError(ValueError):
    """Base class for invalid launch-brief input."""


class BriefTooLargeError(BriefError):
    """Raised instead of silently truncating launch authority or context."""


@dataclass(frozen=True, slots=True)
class BriefBounds:
    """Hard limits applied before a brief reaches an external process."""

    max_total_chars: int = 32_768
    max_section_chars: int = 8_192
    max_skills: int = 16

    def __post_init__(self) -> None:
        if self.max_total_chars <= 0 or self.max_section_chars <= 0:
            raise BriefError("brief character limits must be positive")
        if self.max_section_chars > self.max_total_chars:
            raise BriefError("section limit must not exceed total limit")
        if self.max_skills < 0:
            raise BriefError("max_skills must be non-negative")


@dataclass(frozen=True, slots=True)
class LaunchBrief:
    """The complete, transcript-free input for one bounded role attempt."""

    role: Role
    task_id: str
    attempt_id: str
    objective: str
    role_rules: str
    task_context: str
    repository_instructions: str
    result_contract: str
    skill_bindings: tuple[SkillBinding, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.role, Role):
            raise BriefError("role must be a known Milburn role")
        for field_name in ("task_id", "attempt_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise BriefError(f"{field_name} must be a non-empty identifier")
            if any(character.isspace() for character in value):
                raise BriefError(f"{field_name} must not contain whitespace")
        for field_name in (
            "objective",
            "role_rules",
            "task_context",
            "repository_instructions",
            "result_contract",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise BriefError(f"{field_name} must be non-empty text")
        if not isinstance(self.skill_bindings, tuple):
            raise BriefError("skill_bindings must be an immutable tuple")
        if any(
            not isinstance(binding, SkillBinding) for binding in self.skill_bindings
        ):
            raise BriefError("skill_bindings must contain validated SkillBinding values")
        names = tuple(binding.skill_name for binding in self.skill_bindings)
        if len(set(names)) != len(names):
            raise BriefError("skill_bindings must not contain duplicate skill names")


@dataclass(frozen=True, slots=True)
class RenderedBrief:
    content: str
    digest: str
    rules_digest: str
    skill_bindings: tuple[SkillBinding, ...]


class BriefRenderer:
    """Render stable briefs while preserving every supplied authority rule."""

    def __init__(self, bounds: BriefBounds | None = None) -> None:
        self._bounds = bounds or BriefBounds()

    def render(self, brief: LaunchBrief) -> RenderedBrief:
        if not isinstance(brief, LaunchBrief):
            raise BriefError("brief must be a LaunchBrief")
        if len(brief.skill_bindings) > self._bounds.max_skills:
            raise BriefTooLargeError(
                f"required_skills exceeds limit {self._bounds.max_skills}"
            )

        sections = (
            ("Objective", brief.objective),
            ("Mandatory role rules", brief.role_rules),
            ("Task context", brief.task_context),
            ("Repository instructions", brief.repository_instructions),
            ("Required result contract", brief.result_contract),
        )
        for name, content in sections:
            if len(content) > self._bounds.max_section_chars:
                raise BriefTooLargeError(
                    f"{name} exceeds section limit {self._bounds.max_section_chars}"
                )

        skills = "\n".join(
            _render_skill_binding(binding) for binding in brief.skill_bindings
        ) or "- none"
        rendered_sections = "\n\n".join(
            f"## {name}\n{content}" for name, content in sections
        )
        content = (
            "# Milburn agent launch brief\n\n"
            "This is a bounded role assignment. Durable artifacts, not a private "
            "transcript, are the handoff record.\n\n"
            "## Correlation\n"
            f"- role: {brief.role.value}\n"
            f"- task_id: {brief.task_id}\n"
            f"- attempt_id: {brief.attempt_id}\n\n"
            "## Required skills\n"
            f"{skills}\n\n"
            f"{rendered_sections}\n"
        )
        if len(content) > self._bounds.max_total_chars:
            raise BriefTooLargeError(
                f"rendered brief exceeds total limit {self._bounds.max_total_chars}"
            )
        return RenderedBrief(
            content=content,
            digest=_digest(content),
            rules_digest=_digest(brief.role_rules),
            skill_bindings=brief.skill_bindings,
        )


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _render_skill_binding(binding: SkillBinding) -> str:
    resource_digests = ",".join(binding.resource_digests) or "none"
    return (
        f"- name={binding.skill_name} version={binding.version} "
        f"root_digest={binding.root_digest} "
        f"resource_digests={resource_digests} "
        f"workspace_path={binding.workspace_path} "
        f"validated_at={binding.validated_at.isoformat()}"
    )
