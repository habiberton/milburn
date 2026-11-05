from dataclasses import replace

import pytest

from milburn.domain import IssueDraft
from milburn.validation.issue_contracts import issue_marker, render_issue_body, validate_issue_draft


def draft(**overrides):
    values = dict(task_key="task-1", title="Build API", objective="Implement API",
                  spec_links=("PRD.md",), acceptance_criteria=("API responds",),
                  dependencies=("task-0",), test_instructions=("Run tests",),
                  expected_artifacts=("src/api.py",), risks=("Timeout",), non_goals=("UI",))
    values.update(overrides)
    return IssueDraft(**values)


@pytest.mark.parametrize("changes", [
    {"task_key": "task--><script>"},
    {"dependencies": ("task-1",)},
    {"dependencies": ("task-0", "task-0")},
    {"spec_links": ("https://unrelated.invalid",)},
    {"acceptance_criteria": (" ",)},
])
def test_rejects_weak_issue_drafts(changes):
    with pytest.raises(ValueError):
        validate_issue_draft(draft(**changes))


def test_rejects_bad_identity_and_missing_sections():
    with pytest.raises(ValueError):
        issue_marker("acme/milburn", "bad -->", "task-1")
    with pytest.raises(ValueError):
        validate_issue_draft(draft(expected_artifacts=()))


def test_body_contains_all_required_sections_and_stable_identity():
    item = draft()
    marker = issue_marker("acme/milburn", "feature-1", item.task_key)
    body = render_issue_body(item, marker)
    for text in ("Objective", "Specifications", "Acceptance criteria", "Expected components",
                 "Dependencies", "Test instructions", "Risks", "Non-goals", "Required artifacts",
                 "API responds", "task-0", marker):
        assert text in body
    assert render_issue_body(item, marker) == body
