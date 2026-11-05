from tests.unit.integrations.github.test_registry import (
    FENCE, command, draft, registry,
)
from milburn.domain import IssueState
from milburn.integrations.github.gateway import CREATE_ISSUE, UPDATE_ISSUE, UncertainEffectError
from tests.fakes.mcp import ScriptedOutcome
import pytest


def test_scripted_local_mcp_recovers_timeout_during_labeling():
    service, server = registry()
    server.client.script(UPDATE_ISSUE, ScriptedOutcome.TIMEOUT_AFTER)
    with pytest.raises(UncertainEffectError):
        service.create(command(), draft(("task-0",)), FENCE,
                       {"task-0": IssueState.DONE})
    recovered = service.create(command(), draft(("task-0",)), FENCE,
                               {"task-0": IssueState.DONE})
    assert recovered.labels == ("milburn:task", "milburn:ready")
    assert server.mutation_counts[CREATE_ISSUE] == 1
    assert server.mutation_counts[UPDATE_ISSUE] == 1
