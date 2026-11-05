"""Allow-listed GitHub MCP adapter with journaled uncertain-effect recovery."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
import json
import re
from typing import Any, TypeVar

from milburn.integrations.mcp import (
    EffectConflictError,
    EffectJournal,
    EffectRequest,
    EffectStatus,
    GenerationFence,
    JsonObject,
    McpClient,
    McpError,
    McpProtocolError,
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

_STRING = {"type": "string"}
_INTEGER = {"type": "integer"}
_STRING_ARRAY = {"type": "array", "items": {"type": "string"}}

TOOL_SCHEMAS: dict[str, tuple[dict[str, JsonObject], frozenset[str]]] = {
    GET_REPOSITORY: (
        {"owner": _STRING, "repo": _STRING},
        frozenset({"owner", "repo"}),
    ),
    LIST_ISSUES: (
        {"owner": _STRING, "repo": _STRING, "state": _STRING},
        frozenset({"owner", "repo", "state"}),
    ),
    GET_ISSUE: (
        {"owner": _STRING, "repo": _STRING, "issue_number": _INTEGER},
        frozenset({"owner", "repo", "issue_number"}),
    ),
    CREATE_ISSUE: (
        {"owner": _STRING, "repo": _STRING, "title": _STRING, "body": _STRING},
        frozenset({"owner", "repo", "title", "body"}),
    ),
    LIST_COMMENTS: (
        {"owner": _STRING, "repo": _STRING, "issue_number": _INTEGER},
        frozenset({"owner", "repo", "issue_number"}),
    ),
    ADD_COMMENT: (
        {
            "owner": _STRING,
            "repo": _STRING,
            "issue_number": _INTEGER,
            "body": _STRING,
        },
        frozenset({"owner", "repo", "issue_number", "body"}),
    ),
    UPDATE_ISSUE: (
        {
            "owner": _STRING,
            "repo": _STRING,
            "issue_number": _INTEGER,
            "body": _STRING,
            "labels": _STRING_ARRAY,
            "state": _STRING,
        },
        frozenset({"owner", "repo", "issue_number"}),
    ),
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
    ) -> None:
        self._client = client
        self._journal = journal
        self._generation_fence = generation_fence
        self.verify_compatibility()

    def verify_compatibility(self) -> None:
        try:
            tools = self._client.list_tools()
        except McpError as error:
            raise ToolCompatibilityError("unable to discover GitHub MCP tools") from error
        names = {tool.name for tool in tools}
        if len(names) != len(tools):
            raise ToolCompatibilityError("GitHub MCP server returned duplicate tool names")
        missing = ALLOWED_TOOLS - names
        if missing:
            raise ToolCompatibilityError(
                f"GitHub MCP server is missing approved tools: {sorted(missing)}"
            )
        for tool in tools:
            if tool.name not in ALLOWED_TOOLS:
                continue
            _verify_tool_schema(tool.name, tool.input_schema)

    def get_repository(self, repository: RepositoryId) -> Repository:
        payload = self._call(
            GET_REPOSITORY, {"owner": repository.owner, "repo": repository.name}
        )
        value = _object(payload, "repository")
        try:
            return Repository(
                repository_id=_repository_id(value),
                default_branch=_string(value, "default_branch"),
            )
        except ValueError as error:
            raise McpProtocolError("MCP repository payload is invalid") from error

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
        marker_prefix = _marker_prefix(query.idempotency_marker)
        return tuple(issue for issue in issues if marker_prefix in issue.body)

    def create_issue(self, command: CreateIssueCommand) -> Issue:
        arguments: JsonObject = {
            "repository": command.repository_id.value,
            "title": command.title,
            "body": command.body,
        }
        _require_unclaimed_marker(command.body, command)
        marker = _effect_marker(command, arguments)
        body = _with_marker(command.body, marker)

        def reconcile() -> Issue | None:
            issues = self.list_issues(
                IssueQuery(repository_id=command.repository_id, state="all")
            )
            return _one_marked(
                issues,
                body=lambda issue: issue.body,
                semantic_match=lambda issue: (
                    issue.title == command.title
                    and _creation_body_preserved(issue.body, body)
                ),
                command=command,
                arguments=arguments,
                object_name="issues",
            )

        return self._mutate(
            command,
            "create_issue",
            arguments,
            reconcile,
            lambda start_call: _started_call(
                start_call,
                lambda: self._call(
                    CREATE_ISSUE,
                    {
                        "owner": command.repository_id.owner,
                        "repo": command.repository_id.name,
                        "title": command.title,
                        "body": body,
                    },
                ),
            ),
            lambda issue: str(issue.number),
        )

    def add_comment(self, command: AddCommentCommand) -> IssueComment:
        arguments: JsonObject = {
            "repository": command.repository_id.value,
            "issue_number": command.issue_number,
            "body": command.body,
        }
        _require_unclaimed_marker(command.body, command)
        marker = _effect_marker(command, arguments)
        body = _with_marker(command.body, marker)

        def reconcile() -> IssueComment | None:
            payload = self._call(
                LIST_COMMENTS,
                _issue_coordinates(command.repository_id, command.issue_number),
            )
            comments = tuple(
                _comment(command.repository_id, value)
                for value in _list(payload, "comments")
            )
            return _one_marked(
                comments,
                body=lambda comment: comment.body,
                semantic_match=lambda comment: (
                    comment.issue_number == command.issue_number
                    and comment.body == body
                ),
                command=command,
                arguments=arguments,
                object_name="comments",
            )

        return self._mutate(
            command,
            "add_comment",
            arguments,
            reconcile,
            lambda start_call: _started_call(
                start_call,
                lambda: self._call(
                    ADD_COMMENT,
                    {
                        **_issue_coordinates(
                            command.repository_id, command.issue_number
                        ),
                        "body": body,
                    },
                ),
            ),
            lambda comment: comment.comment_id,
        )

    def set_labels(self, command: SetLabelsCommand) -> Issue:
        arguments: JsonObject = {
            "repository": command.repository_id.value,
            "issue_number": command.issue_number,
            "labels": list(command.labels),
        }
        marker = _effect_marker(command, arguments)

        def current() -> Issue:
            return self._get_issue(command.repository_id, command.issue_number)

        def reconcile() -> Issue | None:
            issue = current()
            if _has_exact_marker(issue.body, command, arguments) and (
                set(issue.labels) == set(command.labels)
            ):
                return issue
            return None

        def invoke(start_call: Callable[[], None]) -> JsonObject:
            issue = current()
            call_arguments = {
                **_issue_coordinates(command.repository_id, command.issue_number),
                "body": _with_marker(issue.body, marker),
                "labels": list(command.labels),
            }
            start_call()
            return self._call(
                UPDATE_ISSUE,
                call_arguments,
            )

        return self._mutate(
            command,
            "set_labels",
            arguments,
            reconcile,
            invoke,
            lambda issue: str(issue.number),
        )

    def close_issue(self, command: CloseIssueCommand) -> Issue:
        arguments: JsonObject = {
            "repository": command.repository_id.value,
            "issue_number": command.issue_number,
            "state": "closed",
        }
        marker = _effect_marker(command, arguments)

        def current() -> Issue:
            return self._get_issue(command.repository_id, command.issue_number)

        def reconcile() -> Issue | None:
            issue = current()
            if (
                _has_exact_marker(issue.body, command, arguments)
                and issue.state == "closed"
            ):
                return issue
            return None

        def invoke(start_call: Callable[[], None]) -> JsonObject:
            issue = current()
            call_arguments = {
                **_issue_coordinates(command.repository_id, command.issue_number),
                "body": _with_marker(issue.body, marker),
                "state": "closed",
            }
            start_call()
            return self._call(
                UPDATE_ISSUE,
                call_arguments,
            )

        return self._mutate(
            command,
            "close_issue",
            arguments,
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
        invoke: Callable[[Callable[[], None]], JsonObject],
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
        except (McpError, GitHubGatewayError) as error:
            if record.status is EffectStatus.CALL_STARTED:
                self._journal.transition(command.effect_id, EffectStatus.UNCERTAIN)
            if record.status in {EffectStatus.CALL_STARTED, EffectStatus.UNCERTAIN}:
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

        if record.status is not EffectStatus.RECONCILED:
            self._journal.transition(command.effect_id, EffectStatus.RECONCILED)
        call_started = False

        def start_call() -> None:
            nonlocal call_started
            if call_started:
                raise RuntimeError("mutation call can start only once")
            self._generation_fence.assert_current(command.fence)
            self._journal.transition(command.effect_id, EffectStatus.CALL_STARTED)
            call_started = True

        try:
            invoke(start_call)
        except McpError as error:
            if call_started:
                self._journal.transition(command.effect_id, EffectStatus.UNCERTAIN)
                raise UncertainEffectError(command.effect_id) from error
            raise ReconciliationUnavailableError(
                f"cannot prepare GitHub effect {command.effect_id!r}"
            ) from error
        if not call_started:
            raise RuntimeError("mutation invocation returned without starting a call")

        try:
            observed = reconcile()
        except (McpError, GitHubGatewayError, EffectConflictError) as error:
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


def _marker_prefix(marker: str) -> str:
    return f"<!-- milburn-effect:{marker};"


def _effect_marker(command: MutationCommand, arguments: JsonObject) -> str:
    return (
        f"{_marker_prefix(command.idempotency_marker)}"
        f"effect-id:{command.effect_id};digest:{_digest(arguments)} -->"
    )


def _require_unclaimed_marker(body: str, command: MutationCommand) -> None:
    if _marker_prefix(command.idempotency_marker) in body:
        raise EffectConflictError(
            "command body contains a reserved idempotency marker prefix"
        )


def _has_exact_marker(
    body: str, command: MutationCommand, arguments: JsonObject
) -> bool:
    exact = _effect_marker(command, arguments)
    prefix = _marker_prefix(command.idempotency_marker)
    prefix_count = body.count(prefix)
    exact_count = body.count(exact)
    if prefix_count == 1 and exact_count == 1:
        return True
    if prefix_count:
        raise EffectConflictError(
            f"idempotency marker {command.idempotency_marker!r} is bound to "
            "another or multiple semantic effects"
        )
    return False


def _with_marker(body: str, encoded: str) -> str:
    if encoded in body:
        return body
    return f"{body.rstrip()}\n\n{encoded}"


def _creation_body_preserved(observed: str, created: str) -> bool:
    """Allow only subsequent gateway effect markers after the original issue body."""
    if observed == created:
        return True
    prefix = created + "\n\n"
    if not observed.startswith(prefix):
        return False
    suffixes = observed[len(prefix):].split("\n\n")
    return all(
        re.fullmatch(
            r"<!-- milburn-effect:[A-Za-z0-9._:/-]+;effect-id:[A-Za-z0-9._:/-]+;digest:[0-9a-f]{64} -->",
            suffix,
        ) is not None
        for suffix in suffixes
    )


def _one_marked(
    values: tuple[T, ...],
    *,
    body: Callable[[T], str],
    semantic_match: Callable[[T], bool],
    command: MutationCommand,
    arguments: JsonObject,
    object_name: str,
) -> T | None:
    matches = tuple(
        value for value in values if _has_exact_marker(body(value), command, arguments)
    )
    if len(matches) > 1:
        raise EffectConflictError(
            f"idempotency marker matches multiple remote {object_name}"
        )
    if not matches:
        return None
    match = matches[0]
    if not semantic_match(match):
        raise EffectConflictError(
            f"bound marker does not match requested remote {object_name} semantics"
        )
    return match


def _started_call(
    start_call: Callable[[], None], call: Callable[[], JsonObject]
) -> JsonObject:
    start_call()
    return call()


def _digest(arguments: JsonObject) -> str:
    encoded = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _verify_tool_schema(name: str, schema: JsonObject) -> None:
    expected_properties, expected_required = TOOL_SCHEMAS[name]
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ToolCompatibilityError(
            f"GitHub MCP tool {name!r} must be a closed object schema"
        )
    properties = schema.get("properties")
    if not isinstance(properties, dict) or properties != expected_properties:
        raise ToolCompatibilityError(
            f"GitHub MCP tool {name!r} has incompatible properties or types"
        )
    required = schema.get("required")
    if (
        not isinstance(required, list)
        or any(not isinstance(item, str) for item in required)
        or len(required) != len(set(required))
        or set(required) != expected_required
    ):
        raise ToolCompatibilityError(
            f"GitHub MCP tool {name!r} has incompatible required fields"
        )


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
    try:
        return RepositoryId(
            owner=_string(payload, "owner"), name=_string(payload, "name")
        )
    except ValueError as error:
        raise McpProtocolError("MCP repository identity is invalid") from error


def _issue(repository: RepositoryId, payload: JsonObject) -> Issue:
    labels = payload.get("labels")
    if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
        raise McpProtocolError("MCP issue labels must be a string list")
    try:
        return Issue(
            repository_id=repository,
            number=_integer(payload, "number"),
            title=_string(payload, "title"),
            body=_string(payload, "body"),
            state=_string(payload, "state"),
            labels=tuple(labels),
        )
    except ValueError as error:
        raise McpProtocolError("MCP issue payload is invalid") from error


def _comment(repository: RepositoryId, payload: JsonObject) -> IssueComment:
    try:
        return IssueComment(
            repository_id=repository,
            comment_id=_string(payload, "id"),
            issue_number=_integer(payload, "issue_number"),
            body=_string(payload, "body"),
        )
    except ValueError as error:
        raise McpProtocolError("MCP comment payload is invalid") from error
