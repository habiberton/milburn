from copy import deepcopy
from dataclasses import replace

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
    ADD_COMMENT,
    CREATE_ISSUE,
    EffectPreviouslyObservedError,
    GET_REPOSITORY,
    GET_ISSUE,
    UPDATE_ISSUE,
    GitHubMcpGateway,
    ReconciliationUnavailableError,
    ToolCompatibilityError,
    UncertainEffectError,
)
from milburn.integrations.mcp import (
    EffectStatus,
    EffectConflictError,
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
    generation_fence.activate(FENCE.task_id, FENCE.attempt_id, FENCE.generation)
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
    generation_fence.activate(FENCE.task_id, FENCE.attempt_id, FENCE.generation)

    def require_requested(tool: str, arguments: dict[str, object]) -> None:
        if tool == CREATE_ISSUE:
            assert journal.get("effect-create") is not None
            assert journal.get("effect-create").status is EffectStatus.CALL_STARTED

    server.client.set_before_call(require_requested)
    adapter = GitHubMcpGateway(server.client, journal, generation_fence)

    issue = adapter.create_issue(create_command())

    assert issue.number == 1
    assert "milburn-effect:" in issue.body
    assert "effect-id:effect-create;digest:" in issue.body
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


def test_malformed_readback_after_applied_mutation_is_journaled_uncertain() -> None:
    adapter, server, journal, _ = gateway()
    server.client.script(
        "github_list_issues",
        ScriptedOutcome.SUCCESS,
        ScriptedOutcome.MALFORMED_AFTER,
    )

    with pytest.raises(UncertainEffectError):
        adapter.create_issue(create_command())

    assert len(server.issues) == 1
    assert journal.get("effect-create").status is EffectStatus.UNCERTAIN


@pytest.mark.parametrize("tampered_field", ["title", "body"])
def test_create_readback_requires_exact_requested_title_and_body(
    tampered_field: str,
) -> None:
    adapter, server, journal, _ = gateway()

    def tamper(tool: str, arguments: dict[str, object], result: dict[str, object]) -> None:
        if tool != CREATE_ISSUE:
            return
        if tampered_field == "title":
            server.issues[1]["title"] = "Changed outside the requested effect"
        else:
            server.issues[1]["body"] = server.issues[1]["body"].replace(
                "Acceptance evidence.", "Tampered body."
            )

    server.client.set_after_call(tamper)

    with pytest.raises(UncertainEffectError):
        adapter.create_issue(create_command())

    assert journal.get("effect-create").status is EffectStatus.UNCERTAIN
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


def test_marker_reuse_by_another_effect_conflicts_in_journal_and_remote_state() -> None:
    adapter, server, _, generation_fence = gateway()
    adapter.create_issue(create_command())
    conflicting = replace(
        create_command("effect-other"), title="A different semantic request"
    )

    with pytest.raises(EffectConflictError, match="already bound"):
        adapter.create_issue(conflicting)

    restarted = GitHubMcpGateway(
        server.client, InMemoryEffectJournal(), generation_fence
    )
    with pytest.raises(EffectConflictError, match="another.*semantic effect"):
        restarted.create_issue(conflicting)

    assert len(server.issues) == 1
    assert server.mutation_counts[CREATE_ISSUE] == 1


def test_exact_marker_plus_same_prefix_evil_marker_is_a_conflict() -> None:
    adapter, server, _, _ = gateway()
    adapter.create_issue(create_command())
    server.issues[1]["body"] += (
        "\n<!-- milburn-effect:milburn:acme/milburn:feature:MB-008;"
        "effect-id:evil;digest:evil -->"
    )

    with pytest.raises(EffectConflictError, match="multiple semantic effects"):
        adapter.create_issue(create_command())

    assert server.mutation_counts[CREATE_ISSUE] == 1


@pytest.mark.parametrize("tamper_kind", ["body", "issue_number"])
def test_comment_readback_requires_exact_body_and_issue_correlation(
    tamper_kind: str,
) -> None:
    adapter, server, journal, _ = gateway()
    number = server.seed_issue()
    command = AddCommentCommand(
        effect_id="effect-comment-tampered",
        idempotency_marker="comment-tampered-marker",
        fence=FENCE,
        repository_id=REPOSITORY,
        issue_number=number,
        body="Exact comment body.",
    )

    def tamper(tool: str, arguments: dict[str, object], result: dict[str, object]) -> None:
        if tool != ADD_COMMENT:
            return
        comment = server.comments[number][-1]
        if tamper_kind == "body":
            comment["body"] = comment["body"].replace(
                "Exact comment body.", "Tampered comment body."
            )
        else:
            comment["issue_number"] = number + 1

    server.client.set_after_call(tamper)

    with pytest.raises(UncertainEffectError):
        adapter.add_comment(command)

    assert journal.get(command.effect_id).status is EffectStatus.UNCERTAIN
    assert server.mutation_counts[ADD_COMMENT] == 1


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


@pytest.mark.parametrize(
    ("ignored_field", "operation"),
    [("labels", "labels"), ("state", "close")],
)
def test_update_requires_marker_and_requested_semantic_postcondition(
    ignored_field: str, operation: str
) -> None:
    adapter, server, journal, _ = gateway()
    number = server.seed_issue()
    server.ignored_update_fields.add(ignored_field)

    if operation == "labels":
        command = SetLabelsCommand(
            effect_id="effect-dropped-labels",
            idempotency_marker="dropped-labels-marker",
            fence=FENCE,
            repository_id=REPOSITORY,
            issue_number=number,
            labels=("milburn:done",),
        )
        invoke = lambda: adapter.set_labels(command)
    else:
        command = CloseIssueCommand(
            effect_id="effect-dropped-close",
            idempotency_marker="dropped-close-marker",
            fence=FENCE,
            repository_id=REPOSITORY,
            issue_number=number,
        )
        invoke = lambda: adapter.close_issue(command)

    with pytest.raises(UncertainEffectError):
        invoke()

    assert journal.get(command.effect_id).status is EffectStatus.UNCERTAIN
    if operation == "labels":
        assert server.issues[number]["labels"] == []
    else:
        assert server.issues[number]["state"] == "open"


def test_external_reopen_cannot_reconcile_completed_close_as_observed() -> None:
    adapter, server, journal, _ = gateway()
    number = server.seed_issue()
    command = CloseIssueCommand(
        effect_id="effect-close-reopened",
        idempotency_marker="close-reopened-marker",
        fence=FENCE,
        repository_id=REPOSITORY,
        issue_number=number,
    )
    adapter.close_issue(command)
    server.issues[number]["state"] = "open"

    with pytest.raises(EffectPreviouslyObservedError):
        adapter.close_issue(command)

    assert journal.get(command.effect_id).status is EffectStatus.OBSERVED
    assert server.mutation_counts[UPDATE_ISSUE] == 1


@pytest.mark.parametrize("operation", ["labels", "close"])
def test_generation_is_rechecked_after_prepare_read_immediately_before_update(
    operation: str,
) -> None:
    adapter, server, journal, generation_fence = gateway()
    number = server.seed_issue()
    reads = 0

    def fence_during_second_get(tool: str, arguments: dict[str, object]) -> None:
        nonlocal reads
        if tool != GET_ISSUE:
            return
        reads += 1
        if reads == 2:
            generation_fence.activate(FENCE.task_id, FENCE.attempt_id, 2)

    server.client.set_before_call(fence_during_second_get)
    if operation == "labels":
        command = SetLabelsCommand(
            effect_id="effect-raced-labels",
            idempotency_marker="raced-labels-marker",
            fence=FENCE,
            repository_id=REPOSITORY,
            issue_number=number,
            labels=("milburn:done",),
        )
        invoke = lambda: adapter.set_labels(command)
    else:
        command = CloseIssueCommand(
            effect_id="effect-raced-close",
            idempotency_marker="raced-close-marker",
            fence=FENCE,
            repository_id=REPOSITORY,
            issue_number=number,
        )
        invoke = lambda: adapter.close_issue(command)

    with pytest.raises(StaleGenerationError):
        invoke()

    assert reads == 2
    assert server.mutation_counts.get(UPDATE_ISSUE, 0) == 0
    assert journal.get(command.effect_id).status is EffectStatus.RECONCILED
    assert EffectStatus.OBSERVED not in {
        record.status
        for record in journal.history
        if record.request.effect_id == command.effect_id
    }


def test_stale_generation_is_rejected_before_journal_or_remote_read() -> None:
    adapter, server, journal, generation_fence = gateway()
    generation_fence.activate(FENCE.task_id, FENCE.attempt_id, 2)

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
    with pytest.raises(ToolCompatibilityError, match="closed object schema"):
        GitHubMcpGateway(incompatible, InMemoryEffectJournal(), fence)

    with pytest.raises(TypeError, match="verify_tools"):
        GitHubMcpGateway(
            incompatible,
            InMemoryEffectJournal(),
            fence,
            verify_tools=False,  # type: ignore[call-arg]
        )


@pytest.mark.parametrize(
    ("tool_name", "field", "replacement"),
    [
        (UPDATE_ISSUE, "body", None),
        (UPDATE_ISSUE, "labels", None),
        (UPDATE_ISSUE, "state", None),
        (UPDATE_ISSUE, "labels", {"type": "array", "items": {"type": "integer"}}),
        (CREATE_ISSUE, "title", {"type": "integer"}),
    ],
)
def test_discovery_fails_closed_on_missing_or_mistyped_properties(
    tool_name: str, field: str, replacement: dict[str, object] | None
) -> None:
    server = FakeGitHubMcpServer()
    tools = list(server.client.list_tools())
    index = next(index for index, tool in enumerate(tools) if tool.name == tool_name)
    schema = deepcopy(tools[index].input_schema)
    properties = schema["properties"]
    if replacement is None:
        del properties[field]
    else:
        properties[field] = replacement
    tools[index] = McpTool(tool_name, schema)

    with pytest.raises(ToolCompatibilityError, match="properties or types"):
        GitHubMcpGateway(
            DeterministicMcpClient(tuple(tools), server.handle),
            InMemoryEffectJournal(),
            InMemoryGenerationFence(),
        )


def test_discovery_rejects_open_additional_properties() -> None:
    server = FakeGitHubMcpServer()
    tools = list(server.client.list_tools())
    schema = deepcopy(tools[0].input_schema)
    schema["additionalProperties"] = True
    tools[0] = McpTool(tools[0].name, schema)

    with pytest.raises(ToolCompatibilityError, match="closed object schema"):
        GitHubMcpGateway(
            DeterministicMcpClient(tuple(tools), server.handle),
            InMemoryEffectJournal(),
            InMemoryGenerationFence(),
        )


def test_discovery_rejects_incomplete_required_fields() -> None:
    server = FakeGitHubMcpServer()
    tools = list(server.client.list_tools())
    index = next(
        index for index, tool in enumerate(tools) if tool.name == CREATE_ISSUE
    )
    schema = deepcopy(tools[index].input_schema)
    schema["required"].remove("body")
    tools[index] = McpTool(CREATE_ISSUE, schema)

    with pytest.raises(ToolCompatibilityError, match="required fields"):
        GitHubMcpGateway(
            DeterministicMcpClient(tuple(tools), server.handle),
            InMemoryEffectJournal(),
            InMemoryGenerationFence(),
        )


def test_discovery_rejects_duplicate_required_fields() -> None:
    server = FakeGitHubMcpServer()
    tools = list(server.client.list_tools())
    index = next(
        index for index, tool in enumerate(tools) if tool.name == CREATE_ISSUE
    )
    schema = deepcopy(tools[index].input_schema)
    schema["required"].append("body")
    tools[index] = McpTool(CREATE_ISSUE, schema)

    with pytest.raises(ToolCompatibilityError, match="required fields"):
        GitHubMcpGateway(
            DeterministicMcpClient(tuple(tools), server.handle),
            InMemoryEffectJournal(),
            InMemoryGenerationFence(),
        )
