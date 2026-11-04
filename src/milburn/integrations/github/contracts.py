"""Transport-independent contracts for Milburn's bounded GitHub gateway."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol

from milburn.integrations.mcp.journal import EffectFence


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")


def _require_identifier(value: str, name: str) -> None:
    _require_text(value, name)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", value) is None:
        raise ValueError(f"{name} must be a compact identifier")


@dataclass(frozen=True, slots=True)
class RepositoryId:
    owner: str
    name: str

    def __post_init__(self) -> None:
        _require_identifier(self.owner, "owner")
        _require_identifier(self.name, "name")

    @property
    def value(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True, slots=True)
class Repository:
    repository_id: RepositoryId
    default_branch: str

    def __post_init__(self) -> None:
        _require_identifier(self.default_branch, "default_branch")


@dataclass(frozen=True, slots=True)
class Issue:
    repository_id: RepositoryId
    number: int
    title: str
    body: str
    state: str
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_positive(self.number, "number")
        _require_text(self.title, "title")
        if not isinstance(self.body, str):
            raise ValueError("body must be a string")
        if self.state not in {"open", "closed"}:
            raise ValueError("state must be open or closed")
        if not isinstance(self.labels, tuple):
            raise ValueError("labels must be an immutable tuple")
        for label in self.labels:
            _require_text(label, "label")


@dataclass(frozen=True, slots=True)
class IssueComment:
    repository_id: RepositoryId
    comment_id: str
    issue_number: int
    body: str

    def __post_init__(self) -> None:
        _require_identifier(self.comment_id, "comment_id")
        _require_positive(self.issue_number, "issue_number")
        _require_text(self.body, "body")


@dataclass(frozen=True, slots=True)
class IssueQuery:
    repository_id: RepositoryId
    state: str = "open"
    idempotency_marker: str | None = None

    def __post_init__(self) -> None:
        if self.state not in {"open", "closed", "all"}:
            raise ValueError("state must be open, closed, or all")
        if self.idempotency_marker is not None:
            _require_identifier(self.idempotency_marker, "idempotency_marker")


@dataclass(frozen=True, slots=True)
class MutationCommand:
    effect_id: str
    idempotency_marker: str
    fence: EffectFence

    def __post_init__(self) -> None:
        _require_identifier(self.effect_id, "effect_id")
        _require_identifier(self.idempotency_marker, "idempotency_marker")


@dataclass(frozen=True, slots=True)
class CreateIssueCommand(MutationCommand):
    repository_id: RepositoryId
    title: str
    body: str

    def __post_init__(self) -> None:
        MutationCommand.__post_init__(self)
        _require_text(self.title, "title")
        _require_text(self.body, "body")


@dataclass(frozen=True, slots=True)
class AddCommentCommand(MutationCommand):
    repository_id: RepositoryId
    issue_number: int
    body: str

    def __post_init__(self) -> None:
        MutationCommand.__post_init__(self)
        _require_positive(self.issue_number, "issue_number")
        _require_text(self.body, "body")


@dataclass(frozen=True, slots=True)
class SetLabelsCommand(MutationCommand):
    repository_id: RepositoryId
    issue_number: int
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        MutationCommand.__post_init__(self)
        _require_positive(self.issue_number, "issue_number")
        if not self.labels:
            raise ValueError("labels must not be empty")
        for label in self.labels:
            _require_text(label, "label")


@dataclass(frozen=True, slots=True)
class CloseIssueCommand(MutationCommand):
    repository_id: RepositoryId
    issue_number: int

    def __post_init__(self) -> None:
        MutationCommand.__post_init__(self)
        _require_positive(self.issue_number, "issue_number")


class GitHubGateway(Protocol):
    """The only GitHub operations exposed to Milburn application code."""

    def get_repository(self, repository: RepositoryId) -> Repository: ...

    def list_issues(self, query: IssueQuery) -> tuple[Issue, ...]: ...

    def create_issue(self, command: CreateIssueCommand) -> Issue: ...

    def add_comment(self, command: AddCommentCommand) -> IssueComment: ...

    def set_labels(self, command: SetLabelsCommand) -> Issue: ...

    def close_issue(self, command: CloseIssueCommand) -> Issue: ...


def _require_positive(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
