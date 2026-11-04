from hashlib import sha256

import pytest

from milburn.agents.briefs import (
    BriefBounds,
    BriefError,
    BriefRenderer,
    BriefTooLargeError,
    LaunchBrief,
)
from milburn.domain import Role


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
        "required_skills": ("milburn-long-running-coder",),
    }
    values.update(changes)
    return LaunchBrief(**values)  # type: ignore[arg-type]


def test_render_is_deterministic_correlated_and_digest_recorded() -> None:
    rendered = BriefRenderer().render(brief())

    assert "- role: coder" in rendered.content
    assert "- task_id: task-6" in rendered.content
    assert "- attempt_id: attempt-1" in rendered.content
    assert "milburn-long-running-coder" in rendered.content
    assert "private transcript" in rendered.content
    assert rendered.digest == sha256(rendered.content.encode()).hexdigest()
    assert rendered.rules_digest == sha256(
        b"Work only in the assigned worktree."
    ).hexdigest()
    assert BriefRenderer().render(brief()) == rendered


def test_renderer_rejects_oversized_sections_instead_of_truncating_rules() -> None:
    renderer = BriefRenderer(BriefBounds(max_total_chars=1_000, max_section_chars=50))

    with pytest.raises(BriefTooLargeError, match="Mandatory role rules"):
        renderer.render(brief(role_rules="x" * 51))


def test_renderer_enforces_total_bound() -> None:
    renderer = BriefRenderer(BriefBounds(max_total_chars=350, max_section_chars=100))

    with pytest.raises(BriefTooLargeError, match="total limit"):
        renderer.render(brief())


def test_launch_brief_rejects_unknown_roles_and_mutable_skill_lists() -> None:
    with pytest.raises(BriefError, match="known Milburn role"):
        brief(role="coder")
    with pytest.raises(BriefError, match="immutable tuple"):
        brief(required_skills=["milburn-long-running-coder"])
