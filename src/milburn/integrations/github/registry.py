"""Controller-owned GitHub issue registry above the journaled MCP gateway."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Mapping

from milburn.domain import CommandEnvelope, CommandType, IssueDraft, IssueState
from milburn.domain.policies import ensure_command_allowed
from milburn.integrations.mcp import EffectFence
from milburn.validation.issue_contracts import issue_marker, render_issue_body, validate_issue_draft

from .contracts import CreateIssueCommand, GitHubGateway, Issue, RepositoryId, SetLabelsCommand

_LABEL = re.compile(r"milburn:[a-z][a-z-]*\Z")


@dataclass(frozen=True, slots=True)
class LabelConfig:
    task: str
    states: Mapping[IssueState, str]

    @classmethod
    def load(cls, path: Path) -> LabelConfig:
        """Read the JSON-subset YAML config without a runtime YAML dependency."""
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or set(value) != {"task", "states"}:
            raise ValueError("label config must define task and states only")
        states = value["states"]
        if not isinstance(states, dict) or set(states) != {state.value for state in IssueState}:
            raise ValueError("label config must map every issue state")
        if not isinstance(value["task"], str) or not _LABEL.fullmatch(value["task"]):
            raise ValueError("invalid task label")
        if any(not isinstance(label, str) or not _LABEL.fullmatch(label) for label in states.values()):
            raise ValueError("invalid state label")
        if value["task"] in states.values():
            raise ValueError("task and state labels must differ")
        return cls(value["task"], {IssueState(state): label for state, label in states.items()})

    def labels_for(self, state: IssueState) -> tuple[str, str]:
        if not isinstance(state, IssueState):
            raise ValueError("unknown issue state")
        return (self.task, self.states[state])

    @property
    def lifecycle_labels(self) -> frozenset[str]:
        return frozenset(self.states.values())


class IssueRegistry:
    """Accept narrow Architect commands and create one issue per stable task key."""

    def __init__(self, gateway: GitHubGateway, repository: RepositoryId, labels: LabelConfig):
        self._gateway = gateway
        self._repository = repository
        self._labels = labels

    def create(
        self,
        command: CommandEnvelope,
        draft: IssueDraft,
        fence: EffectFence,
        dependency_states: Mapping[str, IssueState],
    ) -> Issue:
        if not isinstance(command, CommandEnvelope) or command.command_type is not CommandType.SUBMIT_ISSUE_DRAFTS:
            raise ValueError("only submit_issue_drafts commands can create issues")
        ensure_command_allowed(command)
        if (command.issue_number is not None or command.arguments or
            command.correlation_id != command.feature_id or
            command.feature_id != fence.task_id or command.attempt_id != fence.attempt_id):
            raise ValueError("issue command is not correlated to the Architect attempt")
        validate_issue_draft(draft)
        marker = issue_marker(self._repository.value, command.feature_id, draft.task_key)
        if not isinstance(dependency_states, Mapping) or set(dependency_states) != set(draft.dependencies):
            raise ValueError("dependency state keys must match draft dependencies")
        if any(not isinstance(state, IssueState) for state in dependency_states.values()):
            raise ValueError("dependency state must be a known IssueState")
        state = (IssueState.READY if all(value is IssueState.DONE for value in dependency_states.values())
                 else IssueState.BLOCKED)
        body = render_issue_body(draft, marker)
        create = CreateIssueCommand(
            effect_id=_effect_id(marker, "create"), idempotency_marker=marker,
            fence=fence, repository_id=self._repository, title=draft.title, body=body,
        )
        issue = self._gateway.create_issue(create)
        expected = self._labels.labels_for(state)
        if set(issue.labels) == set(expected):
            return issue
        other_lifecycle = set(issue.labels) & self._labels.lifecycle_labels
        if issue.labels and (other_lifecycle or set(issue.labels) - {self._labels.task}):
            raise ValueError("existing issue has a different lifecycle label")
        return self._gateway.set_labels(SetLabelsCommand(
            effect_id=_effect_id(marker, "initial-labels"),
            idempotency_marker=f"{marker}:initial-labels",
            fence=fence, repository_id=self._repository, issue_number=issue.number,
            labels=expected,
        ))


def _effect_id(marker: str, operation: str) -> str:
    return f"issue-{operation}-{sha256(marker.encode()).hexdigest()[:32]}"
