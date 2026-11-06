"""In-memory ``GitHubGateway`` for registry tests; no transport, no network.

It keeps the gateway contract the registry relies on: every mutation is
idempotent by its ``idempotency_marker`` (a repeated create returns the issue
whose body carries the marker), and it records calls and mutation counts.
"""

from __future__ import annotations

from typing import Any, Callable

from milburn.integrations.github.contracts import (
    AddCommentCommand,
    CloseIssueCommand,
    CreateIssueCommand,
    Issue,
    IssueComment,
    IssueQuery,
    Repository,
    RepositoryId,
    SetLabelsCommand,
)


class FakeGitHubGateway:
    def __init__(self, repository: RepositoryId) -> None:
        self.repository = repository
        self.issues: dict[int, dict[str, Any]] = {}
        self.calls: list[tuple[str, Any]] = []
        self.mutation_counts: dict[str, int] = {}
        self._before: Callable[[str, Any], None] | None = None

    def set_before_call(self, hook: Callable[[str, Any], None]) -> None:
        self._before = hook

    def _call(self, name: str, argument: Any) -> None:
        self.calls.append((name, argument))
        if self._before is not None:
            self._before(name, argument)

    def _issue(self, number: int) -> Issue:
        data = self.issues[number]
        return Issue(self.repository, number, data["title"], data["body"], data["state"],
                     tuple(data["labels"]))

    def _require_repository(self, repository: RepositoryId) -> None:
        if repository != self.repository:
            raise ValueError("unknown repository")

    def get_repository(self, repository: RepositoryId) -> Repository:
        self._call("get_repository", repository)
        self._require_repository(repository)
        return Repository(repository, "main")

    def list_issues(self, query: IssueQuery) -> tuple[Issue, ...]:
        self._call("list_issues", query)
        self._require_repository(query.repository_id)
        return tuple(
            self._issue(number) for number, data in sorted(self.issues.items())
            if (query.state == "all" or data["state"] == query.state)
            and (query.idempotency_marker is None or query.idempotency_marker in data["body"])
        )

    def create_issue(self, command: CreateIssueCommand) -> Issue:
        self._call("create_issue", command)
        self._require_repository(command.repository_id)
        for number, data in self.issues.items():
            if command.idempotency_marker in data["body"]:
                return self._issue(number)
        number = max(self.issues, default=0) + 1
        self.issues[number] = {"title": command.title, "body": command.body,
                               "state": "open", "labels": []}
        self.mutation_counts["create_issue"] = self.mutation_counts.get("create_issue", 0) + 1
        return self._issue(number)

    def add_comment(self, command: AddCommentCommand) -> IssueComment:
        self._call("add_comment", command)
        self.mutation_counts["add_comment"] = self.mutation_counts.get("add_comment", 0) + 1
        return IssueComment(self.repository, f"comment-{len(self.calls)}", command.issue_number,
                            command.body)

    def set_labels(self, command: SetLabelsCommand) -> Issue:
        self._call("set_labels", command)
        if command.issue_number not in self.issues:
            raise ValueError("unknown issue")
        self.issues[command.issue_number]["labels"] = list(command.labels)
        self.mutation_counts["set_labels"] = self.mutation_counts.get("set_labels", 0) + 1
        return self._issue(command.issue_number)

    def close_issue(self, command: CloseIssueCommand) -> Issue:
        self._call("close_issue", command)
        self.issues[command.issue_number]["state"] = "closed"
        self.mutation_counts["close_issue"] = self.mutation_counts.get("close_issue", 0) + 1
        return self._issue(command.issue_number)
