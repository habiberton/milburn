from dataclasses import replace
from pathlib import Path

import pytest

from milburn.domain import CommandEnvelope, CommandType, IssueDraft, IssueState, Role
from milburn.integrations.github.contracts import RepositoryId
from milburn.integrations.github.gateway import CREATE_ISSUE, UPDATE_ISSUE, GitHubMcpGateway, UncertainEffectError
from milburn.integrations.github.registry import IssueRegistry, LabelConfig
from milburn.integrations.mcp import EffectFence, InMemoryEffectJournal, InMemoryGenerationFence
from tests.fakes.github import FakeGitHubMcpServer
from tests.fakes.mcp import ScriptedOutcome

REPOSITORY = RepositoryId("acme", "milburn")
FENCE = EffectFence("feature-1", "architect-1", 1)


def draft(dependencies=()):
    return IssueDraft(task_key="task-1", title="Build API", objective="Implement API",
                      spec_links=("PRD.md",), acceptance_criteria=("API responds",),
                      dependencies=dependencies, test_instructions=("Run tests",),
                      expected_artifacts=("src/api.py",), risks=(), non_goals=())


def command(role=Role.ARCHITECT):
    return CommandEnvelope(command_id="cmd-1", command_type=CommandType.SUBMIT_ISSUE_DRAFTS,
                           actor_role=role, feature_id="feature-1", issue_number=None,
                           attempt_id="architect-1", correlation_id="feature-1")


def registry(server=None):
    server = server or FakeGitHubMcpServer()
    fence = InMemoryGenerationFence()
    fence.activate(FENCE.task_id, FENCE.attempt_id, FENCE.generation)
    gateway = GitHubMcpGateway(server.client, InMemoryEffectJournal(), fence)
    config = LabelConfig.load(Path("config/github-labels.yaml"))
    return IssueRegistry(gateway, REPOSITORY, config), server


@pytest.mark.parametrize("bad", [
    command(Role.CODER),
    replace(command(), command_type=CommandType.SUBMIT_CANDIDATE),
    replace(command(), feature_id="another-feature"),
    replace(command(), attempt_id="another-attempt"),
    replace(command(), issue_number=4),
])
def test_rejects_unauthorized_or_uncorrelated_creation_before_remote_call(bad):
    service, server = registry()
    with pytest.raises(ValueError):
        service.create(bad, draft(), FENCE, {})
    assert not server.client.calls


def test_rejects_unknown_dependency_before_remote_call():
    service, server = registry()
    with pytest.raises(ValueError, match="dependency"):
        service.create(command(), draft(("task-0",)), FENCE, {})
    assert not server.client.calls


def test_creates_ready_issue_with_configured_labels_and_no_duplicate():
    service, server = registry()
    issue = service.create(command(), draft(), FENCE, {})
    again = service.create(command(), draft(), FENCE, {})
    assert issue.number == again.number == 1
    assert issue.labels == ("milburn:task", "milburn:ready")
    assert server.mutation_counts[CREATE_ISSUE] == 1
    assert server.mutation_counts[UPDATE_ISSUE] == 1
    assert "milburn:acme/milburn:feature-1:task-1" in issue.body


def test_blocked_dependency_maps_to_blocked_label():
    service, _ = registry()
    issue = service.create(command(), draft(("task-0",)), FENCE,
                           {"task-0": IssueState.READY})
    assert issue.labels == ("milburn:task", "milburn:blocked")


def test_does_not_reset_later_lifecycle_label_on_replay():
    service, server = registry()
    service.create(command(), draft(), FENCE, {})
    server.issues[1]["labels"] = ["milburn:task", "milburn:in-progress"]
    with pytest.raises(ValueError, match="lifecycle"):
        service.create(command(), draft(), FENCE, {})
    assert server.mutation_counts[UPDATE_ISSUE] == 1


@pytest.mark.parametrize("labels", [[], ["milburn:task", "milburn:ready"]])
def test_closed_issue_cannot_be_returned_or_labeled_ready(labels):
    service, server = registry()
    service.create(command(), draft(), FENCE, {})
    server.issues[1]["state"] = "closed"
    server.issues[1]["labels"] = labels
    before = server.mutation_counts[UPDATE_ISSUE]
    with pytest.raises(ValueError, match="closed"):
        service.create(command(), draft(), FENCE, {})
    assert server.mutation_counts[UPDATE_ISSUE] == before


def test_replacement_attempt_reconciles_same_stable_creation_effect():
    server = FakeGitHubMcpServer()
    journal = InMemoryEffectJournal()
    generations = InMemoryGenerationFence()
    generations.activate(FENCE.task_id, FENCE.attempt_id, FENCE.generation)
    service = IssueRegistry(GitHubMcpGateway(server.client, journal, generations),
                            REPOSITORY, LabelConfig.load(Path("config/github-labels.yaml")))
    server.client.script(CREATE_ISSUE, ScriptedOutcome.TIMEOUT_AFTER)
    with pytest.raises(UncertainEffectError):
        service.create(command(), draft(), FENCE, {})
    replacement = EffectFence("feature-1", "architect-2", 1)
    generations.activate(replacement.task_id, replacement.attempt_id, replacement.generation)
    issue = service.create(replace(command(), attempt_id="architect-2"), draft(), replacement, {})
    assert issue.number == 1
    assert server.mutation_counts[CREATE_ISSUE] == 1


def test_replacement_attempt_reconciles_label_effect():
    server = FakeGitHubMcpServer()
    journal = InMemoryEffectJournal()
    generations = InMemoryGenerationFence()
    generations.activate(FENCE.task_id, FENCE.attempt_id, FENCE.generation)
    service = IssueRegistry(GitHubMcpGateway(server.client, journal, generations),
                            REPOSITORY, LabelConfig.load(Path("config/github-labels.yaml")))
    server.client.script(UPDATE_ISSUE, ScriptedOutcome.TIMEOUT_AFTER)
    with pytest.raises(UncertainEffectError):
        service.create(command(), draft(), FENCE, {})
    replacement = EffectFence("feature-1", "architect-2", 1)
    generations.activate(replacement.task_id, replacement.attempt_id, replacement.generation)
    issue = service.create(replace(command(), attempt_id="architect-2"), draft(), replacement, {})
    assert issue.number == 1
    assert server.mutation_counts[UPDATE_ISSUE] == 1


def test_label_config_rejects_renamed_approved_labels(tmp_path):
    text = Path("config/github-labels.yaml").read_text().replace("milburn:ready", "milburn:almost-ready")
    path = tmp_path / "labels.yaml"
    path.write_text(text)
    with pytest.raises(ValueError):
        LabelConfig.load(path)


def test_timeout_after_create_reconciles_without_duplicate():
    service, server = registry()
    server.client.script(CREATE_ISSUE, ScriptedOutcome.TIMEOUT_AFTER)
    with pytest.raises(UncertainEffectError):
        service.create(command(), draft(), FENCE, {})
    issue = service.create(command(), draft(), FENCE, {})
    assert issue.number == 1
    assert server.mutation_counts[CREATE_ISSUE] == 1
