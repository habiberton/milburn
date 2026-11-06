"""In-memory ``GitHubGateway`` for registry tests; no transport, no network.

It enforces the gateway contract the registry relies on, as the retired MCP
gateway did:

- every mutation checks the repository and the caller's generation fence;
- issues are found by the exact ``<!-- milburn-issue:<marker> -->`` token in
  the body, so a marker that prefixes another never matches it;
- every mutation is idempotent by its ``idempotency_marker``: a repeat returns
  the first result and counts once;
- an unknown issue raises ``ValueError``.
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
    MutationCommand,
    Repository,
    RepositoryId,
    SetLabelsCommand,
)
from milburn.integrations.mcp import InMemoryGenerationFence


def _token(marker: str) -> str:
    return f"<!-- milburn-issue:{marker} -->"


def _arguments(command: MutationCommand) -> tuple:
    """Everything but the effect ID and fence, which may differ on a retry."""

    return tuple(
        (name, getattr(command, name)) for name in sorted(command.__dataclass_fields__)
        if name not in ("effect_id", "fence")
    )


class FakeGitHubGateway:
    def __init__(
        self, repository: RepositoryId, fence: InMemoryGenerationFence | None = None
    ) -> None:
        self.repository = repository
        self.fence = fence or InMemoryGenerationFence()
        self.issues: dict[int, dict[str, Any]] = {}
        self.calls: list[tuple[str, Any]] = []
        self.mutation_counts: dict[str, int] = {}
        self._applied: dict[str, Any] = {}
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

    def _require_issue(self, number: int) -> None:
        if number not in self.issues:
            raise ValueError(f"unknown issue #{number}")

    def _mutation(self, name: str, command: MutationCommand) -> Any | None:
        """Common checks; returns the earlier result for a repeated marker."""

        self._call(name, command)
        self._require_repository(command.repository_id)  # type: ignore[attr-defined]
        self.fence.assert_current(command.fence)
        earlier = self._applied.get(f"{name}:{command.idempotency_marker}")
        if earlier is not None and earlier[0] != _arguments(command):
            raise ValueError(
                f"idempotency marker {command.idempotency_marker!r} reused with different arguments"
            )
        return None if earlier is None else earlier[1]

    def _record(self, name: str, command: MutationCommand, result: Any) -> Any:
        self._applied[f"{name}:{command.idempotency_marker}"] = (_arguments(command), result)
        self.mutation_counts[name] = self.mutation_counts.get(name, 0) + 1
        return result

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
            and (query.idempotency_marker is None
                 or _token(query.idempotency_marker) in data["body"].splitlines())
        )

    def create_issue(self, command: CreateIssueCommand) -> Issue:
        earlier = self._mutation("create_issue", command)
        if earlier is not None:
            return self._issue(earlier)
        for number, data in self.issues.items():
            if _token(command.idempotency_marker) in data["body"].splitlines():
                self._applied[f"create_issue:{command.idempotency_marker}"] = (
                    _arguments(command), number,
                )
                return self._issue(number)
        number = max(self.issues, default=0) + 1
        self.issues[number] = {"title": command.title, "body": command.body,
                               "state": "open", "labels": []}
        self._record("create_issue", command, number)
        return self._issue(number)

    def add_comment(self, command: AddCommentCommand) -> IssueComment:
        earlier = self._mutation("add_comment", command)
        if earlier is not None:
            return earlier
        self._require_issue(command.issue_number)
        comment = IssueComment(self.repository, f"comment-{len(self._applied) + 1}",
                               command.issue_number, command.body)
        return self._record("add_comment", command, comment)

    def set_labels(self, command: SetLabelsCommand) -> Issue:
        if self._mutation("set_labels", command) is not None:
            return self._issue(command.issue_number)
        self._require_issue(command.issue_number)
        self.issues[command.issue_number]["labels"] = list(command.labels)
        self._record("set_labels", command, True)
        return self._issue(command.issue_number)

    def close_issue(self, command: CloseIssueCommand) -> Issue:
        if self._mutation("close_issue", command) is not None:
            return self._issue(command.issue_number)
        self._require_issue(command.issue_number)
        self.issues[command.issue_number]["state"] = "closed"
        self._record("close_issue", command, True)
        return self._issue(command.issue_number)
