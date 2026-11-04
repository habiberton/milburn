"""Allow-listed GitHub MCP adapter with journaled uncertain-effect recovery."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
import json
from typing import Any, TypeVar

from milburn.integrations.mcp import (
    EffectJournal,
    EffectRequest,
    EffectStatus,
    GenerationFence,
    JsonObject,
    McpClient,
    McpError,
    McpProtocolError,
    McpTimeoutError,
    McpUnavailableError,
)

from .contracts import (
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


GET_REPOSITORY = "github_get_repository"
LIST_ISSUES = "github_list_issues"
GET_ISSUE = "github_get_issue"
CREATE_ISSUE = "github_create_issue"
LIST_COMMENTS = "github_list_issue_comments"
ADD_COMMENT = "github_add_issue_comment"
UPDATE_ISSUE = "github_update_issue"

ALLOWED_TOOLS = frozenset(
    {
        GET_REPOSITORY,
        LIST_ISSUES,
        GET_ISSUE,
        CREATE_ISSUE,
        LIST_COMMENTS,
        ADD_COMMENT,
        UPDATE_ISSUE,
    }
)

REQUIRED_TOOL_ARGUMENTS = {
    GET_REPOSITORY: frozenset({"owner", "repo"}),
    LIST_ISSUES: frozenset({"owner", "repo", "state"}),
    GET_ISSUE: frozenset({"owner", "repo", "issue_number"}),
    CREATE_ISSUE: frozenset({"owner", "repo", "title", "body"}),
    LIST_COMMENTS: frozenset({"owner", "repo", "issue_number"}),
    ADD_COMMENT: frozenset({"owner", "repo", "issue_number", "body"}),
    UPDATE_ISSUE: frozenset({"owner", "repo", "issue_number"}),
}


class GitHubGatewayError(RuntimeError):
    """Base failure from the bounded GitHub integration."""


class ToolCompatibilityError(GitHubGatewayError):
    """The configured MCP server lacks the approved GitHub tool contract."""


class ReconciliationUnavailableError(GitHubGatewayError):
    """Remote state could not be read, so no mutation was attempted."""


class UncertainEffectError(GitHubGatewayError):
    """A mutation may have occurred and must be reconciled before retry."""

    def __init__(self, effect_id: str) -> None:
        super().__init__(f"GitHub effect {effect_id!r} is uncertain")
        self.effect_id = effect_id


class EffectNotObservedError(UncertainEffectError):
    """A call returned but its effect was absent during read-after-write."""


class EffectPreviouslyObservedError(GitHubGatewayError):
    """A completed effect disappeared remotely and must not be replayed."""


T = TypeVar("T", Issue, IssueComment)


class GitHubMcpGateway:
    """Translate narrow domain operations to a fixed, controller-owned tool set."""

    def __init__(
        self,
        client: McpClient,
        journal: EffectJournal,
        generation_fence: GenerationFence,
        *,
        verify_tools: bool = True,
    ) -> None:
        self._client = client
        self._journal = journal
        self._generation_fence = generation_fence
        if verify_tools:
            self.verify_compatibility()

    def verify_compatibility(self) -> None:
        try:
            tools = self._client.list_tools()
        except McpError as error:
            raise ToolCompatibilityError("unable to discover GitHub MCP tools") from error
        names = {tool.name for tool in tools}
        missing = ALLOWED_TOOLS - names
        if missing:
            raise ToolCompatibilityError(
                f"GitHub MCP server is missing approved tools: {sorted(missing)}"
            )
        for tool in tools:
            if tool.name not in ALLOWED_TOOLS:
                continue
            if tool.input_schema.get("type") != "object":
                raise ToolCompatibilityError(
                    f"GitHub MCP tool {tool.name!r} has an incompatible input schema"
                )
            required = tool.input_schema.get("required")
            if not isinstance(required, list) or any(
                not isinstance(item, str) for item in required
            ):
                raise ToolCompatibilityError(
                    f"GitHub MCP tool {tool.name!r} lacks a required-field schema"
                )
            missing_arguments = REQUIRED_TOOL_ARGUMENTS[tool.name] - set(required)
            if missing_arguments:
                raise ToolCompatibilityError(
                    f"GitHub MCP tool {tool.name!r} is missing required arguments: "
                    f"{sorted(missing_arguments)}"
                )

    def get_repository(self, repository: RepositoryId) -> Repository:
        payload = self._call(
            GET_REPOSITORY, {"owner": repository.owner, "repo": repository.name}
        )
        value = _object(payload, "repository")
        return Repository(
            repository_id=_repository_id(value),
            default_branch=_string(value, "default_branch"),
        )

    def list_issues(self, query: IssueQuery) -> tuple[Issue, ...]:
        arguments: JsonObject = {
            "owner": query.repository_id.owner,
            "repo": query.repository_id.name,
            "state": query.state,
        }
        payload = self._call(LIST_ISSUES, arguments)
        values = _list(payload, "issues")
        issues = tuple(_issue(query.repository_id, value) for value in values)
        if query.idempotency_marker is None:
            return issues
        marker = _marker(query.idempotency_marker)
        return tuple(issue for issue in issues if marker in issue.body)

    def create_issue(self, command: CreateIssueCommand) -> Issue:
        body = _with_marker(command.body, command.idempotency_marker)

        def reconcile() -> Issue | None:
            matches = self.list_issues(
                IssueQuery(
                    repository_id=command.repository_id,
                    state="all",
                    idempotency_marker=command.idempotency_marker,
                )
            )
            if len(matches) > 1:
                raise GitHubGatewayError("idempotency marker matches multiple issues")
            return matches[0] if matches else None

        return self._mutate(
            command,
            "create_issue",
            {
                "repository": command.repository_id.value,
                "title": command.title,
                "body": body,
            },
            reconcile,
            lambda: self._call(
                CREATE_ISSUE,
                {
                    "owner": command.repository_id.owner,
                    "repo": command.repository_id.name,
                    "title": command.title,
                    "body": body,
                },
            ),
            lambda issue: str(issue.number),
        )

    def add_comment(self, command: AddCommentCommand) -> IssueComment:
        body = _with_marker(command.body, command.idempotency_marker)

        def reconcile() -> IssueComment | None:
            payload = self._call(
                LIST_COMMENTS,
                _issue_coordinates(command.repository_id, command.issue_number),
            )
            marker = _marker(command.idempotency_marker)
            matches = tuple(
                _comment(command.repository_id, value)
                for value in _list(payload, "comments")
                if marker in _string(value, "body")
            )
            if len(matches) > 1:
                raise GitHubGatewayError("idempotency marker matches multiple comments")
            return matches[0] if matches else None

        return self._mutate(
            command,
            "add_comment",
            {
                "repository": command.repository_id.value,
                "issue_number": command.issue_number,
                "body": body,
            },
            reconcile,
            lambda: self._call(
                ADD_COMMENT,
                {
                    **_issue_coordinates(command.repository_id, command.issue_number),
                    "body": body,
                },
            ),
            lambda comment: comment.comment_id,
        )

    def set_labels(self, command: SetLabelsCommand) -> Issue:
        def current() -> Issue:
            return self._get_issue(command.repository_id, command.issue_number)

        def reconcile() -> Issue | None:
            issue = current()
            if _marker(command.idempotency_marker) in issue.body:
                return issue
            return None

        def invoke() -> JsonObject:
            issue = current()
            return self._call(
                UPDATE_ISSUE,
                {
                    **_issue_coordinates(command.repository_id, command.issue_number),
                    "body": _with_marker(issue.body, command.idempotency_marker),
                    "labels": list(command.labels),
                },
            )

        return self._mutate(
            command,
            "set_labels",
            {
                "repository": command.repository_id.value,
                "issue_number": command.issue_number,
                "labels": list(command.labels),
            },
            reconcile,
            invoke,
            lambda issue: str(issue.number),
        )

    def close_issue(self, command: CloseIssueCommand) -> Issue:
        def current() -> Issue:
            return self._get_issue(command.repository_id, command.issue_number)

        def reconcile() -> Issue | None:
            issue = current()
            if _marker(command.idempotency_marker) in issue.body:
                return issue
            return None

        def invoke() -> JsonObject:
            issue = current()
            return self._call(
                UPDATE_ISSUE,
                {
                    **_issue_coordinates(command.repository_id, command.issue_number),
                    "body": _with_marker(issue.body, command.idempotency_marker),
                    "state": "closed",
                },
            )

        return self._mutate(
            command,
            "close_issue",
            {
                "repository": command.repository_id.value,
                "issue_number": command.issue_number,
            },
            reconcile,
            invoke,
            lambda issue: str(issue.number),
        )

    def _get_issue(self, repository: RepositoryId, number: int) -> Issue:
        payload = self._call(GET_ISSUE, _issue_coordinates(repository, number))
        return _issue(repository, _object(payload, "issue"))

    def _mutate(
        self,
        command: MutationCommand,
        operation: str,
        arguments: JsonObject,
        reconcile: Callable[[], T | None],
        invoke: Callable[[], JsonObject],
        identity: Callable[[T], str],
    ) -> T:
        self._generation_fence.assert_current(command.fence)
        request = EffectRequest(
            effect_id=command.effect_id,
            repository_id=_command_repository(command).value,
            operation=operation,
            idempotency_marker=command.idempotency_marker,
            arguments_digest=_digest(arguments),
            fence=command.fence,
        )
        record = self._journal.request(request)
        try:
            existing = reconcile()
        except (McpTimeoutError, McpUnavailableError) as error:
            if record.status is EffectStatus.UNCERTAIN:
                raise UncertainEffectError(command.effect_id) from error
            raise ReconciliationUnavailableError(
                f"cannot reconcile GitHub effect {command.effect_id!r}"
            ) from error
        if existing is not None:
            if record.status not in {EffectStatus.OBSERVED, EffectStatus.RECONCILED}:
                self._journal.transition(command.effect_id, EffectStatus.RECONCILED)
            self._journal.transition(
                command.effect_id,
                EffectStatus.OBSERVED,
                remote_identity=identity(existing),
            )
            return existing

        if record.status is EffectStatus.OBSERVED:
            raise EffectPreviouslyObservedError(
                f"observed GitHub effect {command.effect_id!r} is missing remotely"
            )

        self._journal.transition(command.effect_id, EffectStatus.RECONCILED)
        self._generation_fence.assert_current(command.fence)
        self._journal.transition(command.effect_id, EffectStatus.CALL_STARTED)
        try:
            invoke()
        except McpTimeoutError as error:
            self._journal.transition(command.effect_id, EffectStatus.UNCERTAIN)
            raise UncertainEffectError(command.effect_id) from error

        try:
            observed = reconcile()
        except (McpTimeoutError, McpUnavailableError) as error:
            self._journal.transition(command.effect_id, EffectStatus.UNCERTAIN)
            raise UncertainEffectError(command.effect_id) from error
        if observed is None:
            self._journal.transition(command.effect_id, EffectStatus.UNCERTAIN)
            raise EffectNotObservedError(command.effect_id)
        self._journal.transition(
            command.effect_id,
            EffectStatus.OBSERVED,
            remote_identity=identity(observed),
        )
        return observed

    def _call(self, tool: str, arguments: JsonObject) -> JsonObject:
        if tool not in ALLOWED_TOOLS:
            raise PermissionError(f"MCP tool {tool!r} is outside the GitHub allow-list")
        try:
            payload = self._client.call_tool(tool, arguments)
        except McpError:
            raise
        if not isinstance(payload, dict):
            raise McpProtocolError(f"MCP tool {tool!r} returned a non-object payload")
        return payload


def _command_repository(command: MutationCommand) -> RepositoryId:
    repository = getattr(command, "repository_id", None)
    if not isinstance(repository, RepositoryId):
        raise TypeError("mutation command lacks a repository ID")
    return repository


def _issue_coordinates(repository: RepositoryId, number: int) -> JsonObject:
    return {"owner": repository.owner, "repo": repository.name, "issue_number": number}


def _marker(marker: str) -> str:
    return f"<!-- milburn-effect:{marker} -->"


def _with_marker(body: str, marker: str) -> str:
    encoded = _marker(marker)
    if encoded in body:
        return body
    return f"{body.rstrip()}\n\n{encoded}"


def _digest(arguments: JsonObject) -> str:
    encoded = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _object(payload: JsonObject, key: str) -> JsonObject:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise McpProtocolError(f"MCP response field {key!r} must be an object")
    return value


def _list(payload: JsonObject, key: str) -> tuple[JsonObject, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise McpProtocolError(f"MCP response field {key!r} must be an object list")
    return tuple(value)


def _string(payload: JsonObject, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise McpProtocolError(f"MCP response field {key!r} must be a string")
    return value


def _integer(payload: JsonObject, key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise McpProtocolError(f"MCP response field {key!r} must be a positive integer")
    return value


def _repository_id(payload: JsonObject) -> RepositoryId:
    return RepositoryId(owner=_string(payload, "owner"), name=_string(payload, "name"))


def _issue(repository: RepositoryId, payload: JsonObject) -> Issue:
    labels = payload.get("labels")
    if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
        raise McpProtocolError("MCP issue labels must be a string list")
    return Issue(
        repository_id=repository,
        number=_integer(payload, "number"),
        title=_string(payload, "title"),
        body=_string(payload, "body"),
        state=_string(payload, "state"),
        labels=tuple(labels),
    )


def _comment(repository: RepositoryId, payload: JsonObject) -> IssueComment:
    return IssueComment(
        repository_id=repository,
        comment_id=_string(payload, "id"),
        issue_number=_integer(payload, "issue_number"),
        body=_string(payload, "body"),
    )
