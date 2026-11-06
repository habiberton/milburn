from hashlib import sha256
from datetime import datetime, timezone

import pytest

from milburn.agents.briefs import (
    BriefBounds,
    BriefError,
    BriefRenderer,
    BriefTooLargeError,
    LaunchBrief,
)
from milburn.domain import Role, SkillBinding


SKILL = SkillBinding(
    skill_name="milburn-long-running-coder",
    version="1",
    root_digest="rootabc",
    resource_digests=("resource123", "resource456"),
    workspace_path=".agents/skills/milburn-long-running-coder",
    validated_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
)


def brief(**changes: object) -> LaunchBrief:
    values = {
        "role": Role.CODER,
        "task_id": "task-6",
        "attempt_id": "attempt-1",
        "objective": "Implement one bounded issue.",
        "role_rules": "Work only in the assigned worktree.",
        "task_context": "Issue #6 and its approved acceptance criteria.",
        "repository_instructions": "Read AGENTS.md before editing.",
        "result_contract": "Return the required versioned JSON result.",
        "skill_bindings": (SKILL,),
    }
    values.update(changes)
    return LaunchBrief(**values)  # type: ignore[arg-type]


def test_render_is_deterministic_correlated_and_digest_recorded() -> None:
    rendered = BriefRenderer().render(brief())

    assert "- role: coder" in rendered.content
    assert "- task_id: task-6" in rendered.content
    assert "- attempt_id: attempt-1" in rendered.content
    assert "milburn-long-running-coder" in rendered.content
    assert "root_digest=rootabc" in rendered.content
    assert "resource_digests=resource123,resource456" in rendered.content
    assert rendered.skill_bindings == (SKILL,)
    assert "private transcript" in rendered.content
    assert rendered.digest == sha256(rendered.content.encode()).hexdigest()
    rules = rendered.content.split("## Mandatory role rules\n", 1)[1].split("\n\n## Task context", 1)[0]
    assert rendered.rules_digest == sha256(rules.encode()).hexdigest()
    assert BriefRenderer().render(brief()) == rendered


def test_direct_coder_brief_cannot_omit_six_boundary_questions() -> None:
    rendered = BriefRenderer().render(brief(role_rules="Work on issue #6."))
    for phrase in ("what could pass", "every field", "bypass", "unique",
                   "preconditions", "test double"):
        assert phrase in rendered.content.lower()
    assert rendered.rules_digest == sha256(
        rendered.content.split("## Mandatory role rules\n", 1)[1]
        .split("\n\n## Task context", 1)[0].encode()
    ).hexdigest()


def test_renderer_rejects_oversized_sections_instead_of_truncating_rules() -> None:
    renderer = BriefRenderer(BriefBounds(max_total_chars=1_000, max_section_chars=50))

    with pytest.raises(BriefTooLargeError, match="Mandatory role rules"):
        renderer.render(brief(role_rules="x" * 51))


def test_renderer_enforces_total_bound() -> None:
    renderer = BriefRenderer(BriefBounds(max_total_chars=350, max_section_chars=100))

    with pytest.raises(BriefTooLargeError, match="total limit"):
        renderer.render(brief(role=Role.TESTER))


def test_launch_brief_rejects_unknown_roles_and_unvalidated_skill_bindings() -> None:
    with pytest.raises(BriefError, match="known Milburn role"):
        brief(role="coder")
    with pytest.raises(BriefError, match="immutable tuple"):
        brief(skill_bindings=[SKILL])
    with pytest.raises(BriefError, match="validated SkillBinding"):
        brief(skill_bindings=("milburn-long-running-coder",))
