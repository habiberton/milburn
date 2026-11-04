from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import pytest

from milburn.agents.role_rules import RoleRuleCatalog, RoleRuleError
from milburn.agents.skill_catalog import SkillCatalog, SkillCatalogConfigurationError
from milburn.domain import Role
from milburn.validation.skill_validation import SkillFailureCode


ROOT = Path(__file__).parents[3]
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
ROLE_SKILLS = {
    Role.COORDINATOR: "milburn-coordination",
    Role.PLANNER: "milburn-planning",
    Role.CLASSIFIER_ROUTER: "milburn-routing",
    Role.ARCHITECT: "milburn-architecture",
    Role.CODER: "milburn-long-running-coder",
    Role.TESTER: "milburn-qa",
}


def catalog(skills_root: Path | None = None) -> SkillCatalog:
    return SkillCatalog(
        skills_root or ROOT / ".agents/skills",
        ROOT / "config/roles.yaml",
        clock=lambda: NOW,
    )


def test_every_role_resolves_one_valid_skill_binding() -> None:
    subject = catalog()

    for role, skill_name in ROLE_SKILLS.items():
        result = subject.resolve_launch(role)
        assert result.allowed
        assert result.failures == ()
        assert len(result.bindings) == 1
        binding = result.bindings[0]
        assert binding.skill_name == skill_name
        assert binding.version == "1.0.0"
        assert len(binding.root_digest) == 64
        assert binding.validated_at == NOW
        assert Path(binding.workspace_path).is_absolute()


def test_missing_required_skill_blocks_launch_with_explicit_result(tmp_path: Path) -> None:
    result = catalog(tmp_path).resolve_launch(Role.COORDINATOR)

    assert not result.allowed
    assert result.bindings == ()
    assert result.failures[0].code is SkillFailureCode.MISSING
    assert result.failures[0].skill_name == "milburn-coordination"


def test_changed_required_skill_blocks_resumed_launch(tmp_path: Path) -> None:
    shutil.copytree(ROOT / ".agents/skills", tmp_path / "skills")
    subject = catalog(tmp_path / "skills")
    original = subject.resolve_launch(Role.PLANNER)
    assert original.allowed
    guide = tmp_path / "skills/milburn-planning/references/planning-checklist.md"
    guide.write_text(guide.read_text(encoding="utf-8") + "\n- New content.\n", encoding="utf-8")

    changed = subject.resolve_launch(
        Role.PLANNER, expected_bindings=original.bindings
    )

    assert not changed.allowed
    assert changed.bindings == ()
    assert changed.failures[0].code is SkillFailureCode.CHANGED


def test_malformed_skill_blocks_launch_without_partial_bindings(tmp_path: Path) -> None:
    shutil.copytree(ROOT / ".agents/skills", tmp_path / "skills")
    manifest = tmp_path / "skills/milburn-qa/SKILL.md"
    manifest.write_text("invalid", encoding="utf-8")

    result = catalog(tmp_path / "skills").resolve_launch(Role.TESTER)

    assert not result.allowed
    assert result.bindings == ()
    assert result.failures[0].code is SkillFailureCode.MALFORMED


def test_role_configuration_is_strict_and_complete(tmp_path: Path) -> None:
    path = tmp_path / "roles.yaml"
    path.write_text(json.dumps({"roles": {"coordinator": {"required_skills": []}}}))

    with pytest.raises(SkillCatalogConfigurationError, match="every known role"):
        SkillCatalog(ROOT / ".agents/skills", path, clock=lambda: NOW)


def test_role_rules_are_separate_and_contain_mandatory_authority_limits() -> None:
    rules = RoleRuleCatalog(
        ROOT / "src/milburn/agents/role_rules", ROOT / "config/policies.yaml"
    )

    for role in Role:
        loaded = rules.load(role)
        assert loaded.role is role
        assert loaded.authority_limits
        assert all(limit.casefold() in loaded.content.casefold() for limit in loaded.authority_limits)
        assert len(loaded.digest) == 64
        assert ".agents/skills" not in loaded.content


def test_missing_mandatory_role_limit_is_rejected(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "src/milburn/agents/role_rules", tmp_path / "rules")
    coordinator = tmp_path / "rules/coordinator.md"
    coordinator.write_text("# Coordinator\n\nCannot launch processes.\n", encoding="utf-8")
    rules = RoleRuleCatalog(tmp_path / "rules", ROOT / "config/policies.yaml")

    with pytest.raises(RoleRuleError, match="omit mandatory limits"):
        rules.load(Role.COORDINATOR)
