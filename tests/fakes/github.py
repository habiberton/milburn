"""In-memory GitHub MCP server that exposes only deterministic local state."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from milburn.integrations.github.gateway import (
    ADD_COMMENT,
    ALLOWED_TOOLS,
    CREATE_ISSUE,
    GET_ISSUE,
    GET_REPOSITORY,
    LIST_COMMENTS,
    LIST_ISSUES,
    REQUIRED_TOOL_ARGUMENTS,
    UPDATE_ISSUE,
)
from milburn.integrations.mcp import JsonObject, McpProtocolError, McpTool
from tests.fakes.mcp import DeterministicMcpClient


class FakeGitHubMcpServer:
    """Minimal GitHub state machine behind the real wire-format adapter."""

    def __init__(self, owner: str = "acme", repo: str = "milburn") -> None:
        self.owner = owner
        self.repo = repo
        self.issues: dict[int, JsonObject] = {}
        self.comments: dict[int, list[JsonObject]] = {}
        self.mutation_counts: dict[str, int] = {}
        tools = tuple(
            McpTool(
                name=name,
                input_schema={
                    "type": "object",
                    "required": sorted(REQUIRED_TOOL_ARGUMENTS[name]),
                },
            )
            for name in sorted(ALLOWED_TOOLS)
        )
        self.client = DeterministicMcpClient(tools, self.handle)

    def seed_issue(
        self,
        *,
        title: str = "Seed issue",
        body: str = "Seed body",
        state: str = "open",
        labels: tuple[str, ...] = (),
    ) -> int:
        number = max(self.issues, default=0) + 1
        self.issues[number] = {
            "number": number,
            "title": title,
            "body": body,
            "state": state,
            "labels": list(labels),
        }
        self.comments[number] = []
        return number

    def handle(self, tool: str, arguments: JsonObject) -> JsonObject:
        self._check_repository(arguments)
        if tool == GET_REPOSITORY:
            return {
                "repository": {
                    "owner": self.owner,
                    "name": self.repo,
                    "default_branch": "main",
                }
            }
        if tool == LIST_ISSUES:
            state = arguments.get("state", "open")
            issues = [
                deepcopy(issue)
                for issue in self.issues.values()
                if state == "all" or issue["state"] == state
            ]
            return {"issues": issues}
        if tool == GET_ISSUE:
            return {"issue": deepcopy(self._issue(arguments))}
        if tool == CREATE_ISSUE:
            self._mutated(tool)
            number = self.seed_issue(
                title=_string(arguments, "title"), body=_string(arguments, "body")
            )
            return {"issue": deepcopy(self.issues[number])}
        if tool == LIST_COMMENTS:
            number = _positive(arguments, "issue_number")
            self._require_issue(number)
            return {"comments": deepcopy(self.comments[number])}
        if tool == ADD_COMMENT:
            self._mutated(tool)
            number = _positive(arguments, "issue_number")
            self._require_issue(number)
            comment = {
                "id": f"comment-{number}-{len(self.comments[number]) + 1}",
                "issue_number": number,
                "body": _string(arguments, "body"),
            }
            self.comments[number].append(comment)
            return {"comment": deepcopy(comment)}
        if tool == UPDATE_ISSUE:
            self._mutated(tool)
            issue = self._issue(arguments)
            if "body" in arguments:
                issue["body"] = _string(arguments, "body")
            if "state" in arguments:
                issue["state"] = _string(arguments, "state")
            if "labels" in arguments:
                labels = arguments["labels"]
                if not isinstance(labels, list) or any(
                    not isinstance(label, str) for label in labels
                ):
                    raise McpProtocolError("labels must be a string list")
                issue["labels"] = list(labels)
            return {"issue": deepcopy(issue)}
        raise McpProtocolError(f"fake does not implement tool {tool!r}")

    def _check_repository(self, arguments: JsonObject) -> None:
        if arguments.get("owner") != self.owner or arguments.get("repo") != self.repo:
            raise McpProtocolError("unknown fake repository")

    def _issue(self, arguments: JsonObject) -> JsonObject:
        number = _positive(arguments, "issue_number")
        self._require_issue(number)
        return self.issues[number]

    def _require_issue(self, number: int) -> None:
        if number not in self.issues:
            raise McpProtocolError(f"unknown fake issue {number}")

    def _mutated(self, tool: str) -> None:
        self.mutation_counts[tool] = self.mutation_counts.get(tool, 0) + 1


def _string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str):
        raise McpProtocolError(f"{key} must be a string")
    return value


def _positive(arguments: dict[str, Any], key: str) -> int:
    value = arguments.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise McpProtocolError(f"{key} must be a positive integer")
    return value
