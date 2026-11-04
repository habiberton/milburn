import pytest

from milburn.integrations.github.contracts import (
    AddCommentCommand,
    CloseIssueCommand,
    CreateIssueCommand,
    EffectFence,
    IssueQuery,
    RepositoryId,
    SetLabelsCommand,
)
from milburn.integrations.github.gateway import (
    CREATE_ISSUE,
    EffectPreviouslyObservedError,
    GET_REPOSITORY,
    UPDATE_ISSUE,
    GitHubMcpGateway,
    ReconciliationUnavailableError,
    ToolCompatibilityError,
    UncertainEffectError,
)
from milburn.integrations.mcp import (
    EffectStatus,
    InMemoryEffectJournal,
    InMemoryGenerationFence,
    McpTool,
    StaleGenerationError,
)
from tests.fakes.github import FakeGitHubMcpServer
from tests.fakes.mcp import DeterministicMcpClient, ScriptedOutcome


REPOSITORY = RepositoryId("acme", "milburn")
FENCE = EffectFence("MB-008", "attempt-1", 1)


def gateway(
    server: FakeGitHubMcpServer | None = None,
) -> tuple[
    GitHubMcpGateway,
    FakeGitHubMcpServer,
    InMemoryEffectJournal,
    InMemoryGenerationFence,
]:
    server = server or FakeGitHubMcpServer()
    journal = InMemoryEffectJournal()
    generation_fence = InMemoryGenerationFence()
    generation_fence.activate(FENCE.attempt_id, FENCE.generation)
    return (
        GitHubMcpGateway(server.client, journal, generation_fence),
        server,
        journal,
        generation_fence,
    )


def create_command(effect_id: str = "effect-create") -> CreateIssueCommand:
    return CreateIssueCommand(
        effect_id=effect_id,
        idempotency_marker="milburn:acme/milburn:feature:MB-008",
        fence=FENCE,
        repository_id=REPOSITORY,
        title="Implement bounded GitHub gateway",
        body="Acceptance evidence.",
    )


def test_effect_markers_reject_comment_delimiter_injection() -> None:
    with pytest.raises(ValueError, match="compact identifier"):
        CreateIssueCommand(
            effect_id="effect-injection",
            idempotency_marker="marker-->",
            fence=FENCE,
            repository_id=REPOSITORY,
            title="Unsafe marker",
            body="Must not reach MCP.",
        )


def test_narrow_gateway_converts_wire_reads_to_domain_values() -> None:
    adapter, server, _, _ = gateway()
    server.seed_issue(title="One", labels=("milburn:ready",))

    repository = adapter.get_repository(REPOSITORY)
    issues = adapter.list_issues(IssueQuery(REPOSITORY))

    assert repository.repository_id == REPOSITORY
    assert repository.default_branch == "main"
    assert [(issue.number, issue.title, issue.labels) for issue in issues] == [
        (1, "One", ("milburn:ready",))
    ]
    assert server.client.calls[0].tool == GET_REPOSITORY


def test_create_is_journaled_before_invocation_and_read_back() -> None:
    server = FakeGitHubMcpServer()
    journal = InMemoryEffectJournal()
    generation_fence = InMemoryGenerationFence()
    generation_fence.activate(FENCE.attempt_id, FENCE.generation)

    def require_requested(tool: str, arguments: dict[str, object]) -> None:
        if tool == CREATE_ISSUE:
            assert journal.get("effect-create") is not None
            assert journal.get("effect-create").status is EffectStatus.CALL_STARTED

    server.client.set_before_call(require_requested)
    adapter = GitHubMcpGateway(server.client, journal, generation_fence)

    issue = adapter.create_issue(create_command())

    assert issue.number == 1
    assert "milburn-effect:" in issue.body
    assert journal.get("effect-create").status is EffectStatus.OBSERVED
    assert journal.get("effect-create").remote_identity == "1"
    assert [call.tool for call in server.client.calls].count(CREATE_ISSUE) == 1
    assert [call.tool for call in server.client.calls][-1] != CREATE_ISSUE


def test_timeout_after_remote_apply_is_uncertain_then_adopted_without_duplicate() -> None:
    adapter, server, journal, _ = gateway()
    server.client.script(CREATE_ISSUE, ScriptedOutcome.TIMEOUT_AFTER)

    with pytest.raises(UncertainEffectError, match="uncertain"):
        adapter.create_issue(create_command())

    assert journal.get("effect-create").status is EffectStatus.UNCERTAIN
    assert len(server.issues) == 1

    recovered = adapter.create_issue(create_command())

    assert recovered.number == 1
    assert len(server.issues) == 1
    assert server.mutation_counts[CREATE_ISSUE] == 1
    assert journal.get("effect-create").status is EffectStatus.OBSERVED


def test_timeout_before_remote_apply_reconciles_absence_before_same_id_retry() -> None:
    adapter, server, journal, _ = gateway()
    server.client.script(CREATE_ISSUE, ScriptedOutcome.TIMEOUT_BEFORE)

    with pytest.raises(UncertainEffectError):
        adapter.create_issue(create_command())

    assert not server.issues
    recovered = adapter.create_issue(create_command())

    assert recovered.number == 1
    assert server.mutation_counts[CREATE_ISSUE] == 1
    assert journal.get("effect-create").status is EffectStatus.OBSERVED


def test_unreadable_reconciliation_never_blindly_invokes_mutation() -> None:
    adapter, server, journal, _ = gateway()
    server.client.script("github_list_issues", ScriptedOutcome.FAILURE)

    with pytest.raises(ReconciliationUnavailableError):
        adapter.create_issue(create_command())

    assert CREATE_ISSUE not in [call.tool for call in server.client.calls]
    assert journal.get("effect-create").status is EffectStatus.REQUESTED


def test_unreadable_read_after_write_is_uncertain_and_not_blindly_retried() -> None:
    adapter, server, journal, _ = gateway()
    server.client.script(
        "github_list_issues", ScriptedOutcome.SUCCESS, ScriptedOutcome.FAILURE
    )

    with pytest.raises(UncertainEffectError):
        adapter.create_issue(create_command())

    assert len(server.issues) == 1
    assert journal.get("effect-create").status is EffectStatus.UNCERTAIN
    server.client.script("github_list_issues", ScriptedOutcome.FAILURE)
    with pytest.raises(UncertainEffectError):
        adapter.create_issue(create_command())
    assert server.mutation_counts[CREATE_ISSUE] == 1


def test_duplicate_completed_effect_is_read_back_without_second_mutation() -> None:
    adapter, server, _, _ = gateway()

    first = adapter.create_issue(create_command())
    duplicate = adapter.create_issue(create_command())

    assert duplicate == first
    assert server.mutation_counts[CREATE_ISSUE] == 1


def test_completed_effect_with_missing_remote_marker_is_never_recreated() -> None:
    adapter, server, _, _ = gateway()
    adapter.create_issue(create_command())
    server.issues[1]["body"] = "marker removed outside Milburn"

    with pytest.raises(EffectPreviouslyObservedError, match="missing remotely"):
        adapter.create_issue(create_command())

    assert len(server.issues) == 1
    assert server.mutation_counts[CREATE_ISSUE] == 1


def test_comments_labels_and_close_use_markers_and_bounded_update_tool() -> None:
    adapter, server, _, _ = gateway()
    number = server.seed_issue()

    comment = adapter.add_comment(
        AddCommentCommand(
            effect_id="effect-comment",
            idempotency_marker="comment-marker",
            fence=FENCE,
            repository_id=REPOSITORY,
            issue_number=number,
            body="QA passed.",
        )
    )
    labeled = adapter.set_labels(
        SetLabelsCommand(
            effect_id="effect-labels",
            idempotency_marker="labels-marker",
            fence=FENCE,
            repository_id=REPOSITORY,
            issue_number=number,
            labels=("milburn:done",),
        )
    )
    closed = adapter.close_issue(
        CloseIssueCommand(
            effect_id="effect-close",
            idempotency_marker="close-marker",
            fence=FENCE,
            repository_id=REPOSITORY,
            issue_number=number,
        )
    )

    assert "comment-marker" in comment.body
    assert labeled.labels == ("milburn:done",)
    assert closed.state == "closed"
    assert server.mutation_counts[UPDATE_ISSUE] == 2


def test_stale_generation_is_rejected_before_journal_or_remote_read() -> None:
    adapter, server, journal, generation_fence = gateway()
    generation_fence.activate(FENCE.attempt_id, 2)

    with pytest.raises(StaleGenerationError):
        adapter.create_issue(create_command())

    assert journal.get("effect-create") is None
    assert not server.client.calls


def test_discovery_requires_only_the_fixed_allow_list_and_rejects_bad_schema() -> None:
    server = FakeGitHubMcpServer()
    incomplete = DeterministicMcpClient(
        tuple(tool for tool in server.client.list_tools() if tool.name != UPDATE_ISSUE),
        server.handle,
    )
    fence = InMemoryGenerationFence()

    with pytest.raises(ToolCompatibilityError, match="missing approved tools"):
        GitHubMcpGateway(incomplete, InMemoryEffectJournal(), fence)

    tools = list(server.client.list_tools())
    tools[0] = McpTool(tools[0].name, {"type": "array", "required": []})
    incompatible = DeterministicMcpClient(tuple(tools), server.handle)
    with pytest.raises(ToolCompatibilityError, match="incompatible input schema"):
        GitHubMcpGateway(incompatible, InMemoryEffectJournal(), fence)
