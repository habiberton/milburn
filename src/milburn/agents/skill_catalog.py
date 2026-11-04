"""Validated role-to-skill bindings for bounded agent launches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Callable

from milburn.domain import Role, SkillBinding
from milburn.validation.skill_validation import (
    SkillFailureCode,
    SkillValidationError,
    validate_skill_package,
)


class SkillCatalogConfigurationError(ValueError):
    """Raised when role configuration cannot define a safe catalog."""


@dataclass(frozen=True, slots=True)
class SkillFailure:
    skill_name: str
    code: SkillFailureCode
    detail: str


@dataclass(frozen=True, slots=True)
class SkillLaunchResult:
    bindings: tuple[SkillBinding, ...]
    failures: tuple[SkillFailure, ...]

    @property
    def allowed(self) -> bool:
        return not self.failures


class SkillCatalog:
    """Resolve required skills into immutable launch evidence."""

    def __init__(
        self,
        skills_root: Path,
        roles_path: Path,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._skills_root = skills_root.resolve()
        self._roles = _load_roles(roles_path)
        self._clock = clock

    def required_skills(self, role: Role) -> tuple[str, ...]:
        if not isinstance(role, Role):
            raise SkillCatalogConfigurationError("role must be a known Milburn role")
        return self._roles[role]

    def resolve_launch(
        self,
        role: Role,
        *,
        expected_bindings: tuple[SkillBinding, ...] = (),
    ) -> SkillLaunchResult:
        """Return bindings or explicit failures; never silently omit a requirement."""

        required = self.required_skills(role)
        if not isinstance(expected_bindings, tuple) or any(
            not isinstance(binding, SkillBinding) for binding in expected_bindings
        ):
            raise SkillCatalogConfigurationError(
                "expected_bindings must be an immutable tuple of SkillBinding values"
            )
        expected_by_name = {binding.skill_name: binding for binding in expected_bindings}
        if len(expected_by_name) != len(expected_bindings):
            raise SkillCatalogConfigurationError("expected bindings contain duplicates")
        unexpected = sorted(set(expected_by_name) - set(required))
        if unexpected:
            raise SkillCatalogConfigurationError(
                f"expected bindings include skills not required by {role.value}: "
                + ", ".join(unexpected)
            )

        bindings: list[SkillBinding] = []
        failures: list[SkillFailure] = []
        validated_at = self._clock()
        for skill_name in required:
            try:
                validated = validate_skill_package(self._skills_root, skill_name)
            except SkillValidationError as error:
                failures.append(SkillFailure(skill_name, error.code, error.detail))
                continue
            expected = expected_by_name.get(skill_name)
            if expected is not None and (
                expected.version != validated.manifest.version
                or expected.root_digest != validated.root_digest
                or expected.resource_digests != validated.resource_digests
            ):
                failures.append(
                    SkillFailure(
                        skill_name,
                        SkillFailureCode.CHANGED,
                        "validated version or digest differs from the required binding",
                    )
                )
                continue
            bindings.append(
                SkillBinding(
                    skill_name=skill_name,
                    version=validated.manifest.version,
                    root_digest=validated.root_digest,
                    resource_digests=validated.resource_digests,
                    workspace_path=str(validated.skill_path),
                    validated_at=validated_at,
                )
            )
        if failures:
            return SkillLaunchResult((), tuple(failures))
        return SkillLaunchResult(tuple(bindings), ())


def _load_roles(path: Path) -> dict[Role, tuple[str, ...]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SkillCatalogConfigurationError(f"cannot read role configuration: {error}") from error
    if not isinstance(payload, dict) or set(payload) != {"roles"}:
        raise SkillCatalogConfigurationError("role configuration must contain only roles")
    roles = payload["roles"]
    if not isinstance(roles, dict) or set(roles) != {role.value for role in Role}:
        raise SkillCatalogConfigurationError("role configuration must define every known role")
    result: dict[Role, tuple[str, ...]] = {}
    for role in Role:
        entry = roles[role.value]
        if not isinstance(entry, dict) or set(entry) != {"required_skills"}:
            raise SkillCatalogConfigurationError(
                f"role {role.value} must define only required_skills"
            )
        skills = entry["required_skills"]
        if not isinstance(skills, list) or not skills or any(
            not isinstance(skill, str) for skill in skills
        ):
            raise SkillCatalogConfigurationError(
                f"role {role.value} required_skills must be a non-empty string list"
            )
        if len(skills) != len(set(skills)):
            raise SkillCatalogConfigurationError(
                f"role {role.value} required_skills contain duplicates"
            )
        result[role] = tuple(skills)
    return result
