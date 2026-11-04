from milburn.integrations.github.contracts import (
    CreateIssueCommand,
    EffectFence,
    IssueQuery,
    RepositoryId,
)
from milburn.integrations.github.gateway import CREATE_ISSUE, GitHubMcpGateway
from milburn.integrations.mcp import InMemoryEffectJournal, InMemoryGenerationFence
from tests.fakes.github import FakeGitHubMcpServer


def test_local_stub_covers_discovery_conversion_idempotency_and_read_after_write() -> None:
    repository = RepositoryId("acme", "milburn")
    fence_value = EffectFence("MB-008", "attempt-contract", 4)
    fence = InMemoryGenerationFence()
    fence.activate(fence_value.attempt_id, fence_value.generation)
    server = FakeGitHubMcpServer()
    gateway = GitHubMcpGateway(server.client, InMemoryEffectJournal(), fence)
    command = CreateIssueCommand(
        effect_id="contract-effect",
        idempotency_marker="milburn:contract:issue",
        fence=fence_value,
        repository_id=repository,
        title="Contract issue",
        body="Created by the local contract stub.",
    )

    created = gateway.create_issue(command)
    replayed = gateway.create_issue(command)
    found = gateway.list_issues(
        IssueQuery(repository, state="all", idempotency_marker=command.idempotency_marker)
    )

    assert created == replayed == found[0]
    assert server.mutation_counts[CREATE_ISSUE] == 1
