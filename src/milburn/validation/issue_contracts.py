"""Validate and render bounded Architect issue drafts."""

from __future__ import annotations

import re

from milburn.domain import IssueDraft

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SPEC = re.compile(r"(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9_./-]+\.md\Z")


def issue_marker(repository: str, feature_id: str, task_key: str) -> str:
    """Stable identity across retries, scoped to repository, feature, and task."""
    if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
        raise ValueError("repository must be owner/name")
    for name, value in (("feature_id", feature_id), ("task_key", task_key)):
        if not isinstance(value, str) or not _TOKEN.fullmatch(value):
            raise ValueError(f"{name} must be a compact safe identifier")
    return f"milburn:{repository}:{feature_id}:{task_key}"


def validate_issue_draft(draft: IssueDraft) -> None:
    """Reject draft variants that domain-level shape validation cannot reject."""
    if not isinstance(draft, IssueDraft):
        raise ValueError("issue draft must use the known schema")
    if not _TOKEN.fullmatch(draft.task_key):
        raise ValueError("task_key must be a safe compact identifier")
    if not draft.expected_artifacts:
        raise ValueError("expected_artifacts must not be empty")
    if any(not _SPEC.fullmatch(link) for link in draft.spec_links):
        raise ValueError("spec_links must be repository Markdown paths")
    if len(set(draft.spec_links)) != len(draft.spec_links):
        raise ValueError("spec_links must be unique")
    if len(set(draft.dependencies)) != len(draft.dependencies):
        raise ValueError("dependencies must be unique")
    if draft.task_key in draft.dependencies:
        raise ValueError("draft cannot depend on itself")
    if any(not _TOKEN.fullmatch(key) for key in draft.dependencies):
        raise ValueError("dependency keys must be safe identifiers")


def render_issue_body(draft: IssueDraft, marker: str) -> str:
    validate_issue_draft(draft)
    if not isinstance(marker, str) or not marker.startswith("milburn:") or "-->" in marker:
        raise ValueError("invalid issue marker")
    sections = (
        ("Objective", (draft.objective,)),
        ("Specifications", draft.spec_links),
        ("Acceptance criteria", draft.acceptance_criteria),
        ("Expected components", draft.expected_artifacts),
        ("Dependencies", draft.dependencies or ("None",)),
        ("Test instructions", draft.test_instructions),
        ("Risks", draft.risks or ("None recorded",)),
        ("Non-goals", draft.non_goals or ("None",)),
        ("Required artifacts", draft.expected_artifacts),
    )
    content = [f"<!-- milburn-issue:{marker} -->", f"# {draft.title}"]
    for heading, lines in sections:
        content.extend(("", f"## {heading}", "", *(f"- {line}" for line in lines)))
    return "\n".join(content) + "\n"
