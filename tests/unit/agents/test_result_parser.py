import json

import pytest

from milburn.agents.result_parser import (
    AgentResultParser,
    ResultCorrelation,
    ResultCorrelationError,
    ResultDecodingError,
    ResultExpectation,
    result_contract,
)
from milburn.domain import CoderOutcome, CoderResult, EvidenceItem, Role


CORRELATION = ResultCorrelation(Role.CODER, "task-6", "attempt-1")
EXPECTED = ResultExpectation(CORRELATION, "coder_result")


def coder_payload(*, attempt_id: str = "attempt-1") -> dict[str, object]:
    return CoderResult(
        attempt_id=attempt_id,
        issue_number=6,
        outcome=CoderOutcome.CANDIDATE,
        head_sha="abc123",
        progress_path=".milburn/issues/6/progress.txt",
        commits=("abc123",),
        files_changed=("src/example.py",),
        test_claims=(EvidenceItem(name="pytest", outcome="passed", evidence="19"),),
        risks=(),
    ).to_dict()


def document(**changes: object) -> str:
    value = {
        "schema_version": 1,
        "role": "coder",
        "task_id": "task-6",
        "attempt_id": "attempt-1",
        "task_success": True,
        "result_type": "coder_result",
        "payload": coder_payload(),
    }
    value.update(changes)
    return json.dumps(value)


def jsonl(message: str | None = None) -> str:
    events: list[dict[str, object]] = [
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {"id": "cmd-1", "type": "command_execution", "text": "ignored"},
        },
    ]
    if message is not None:
        events.append(
            {
                "type": "item.completed",
                "item": {"id": "msg-1", "type": "agent_message", "text": message},
            }
        )
    events.append({"type": "turn.completed", "usage": {"input_tokens": 1}})
    return "\n".join(json.dumps(event) for event in events)


def test_parse_jsonl_extracts_only_semantic_completed_agent_message() -> None:
    parsed = AgentResultParser().parse_jsonl(jsonl(document()), EXPECTED)

    assert parsed.correlation == CORRELATION
    assert parsed.task_success is True
    assert parsed.result_type == "coder_result"
    assert isinstance(parsed.payload, CoderResult)
    assert parsed.payload.head_sha == "abc123"


@pytest.mark.parametrize("version", [0, 1.0, 2, 99])
def test_parse_rejects_result_schema_different_from_launch(version: object) -> None:
    with pytest.raises(ResultDecodingError, match="schema version mismatch"):
        AgentResultParser().parse(document(schema_version=version), EXPECTED)


@pytest.mark.parametrize(
    "change",
    [
        {"role": "tester"},
        {"task_id": "task-7"},
        {"attempt_id": "attempt-2"},
    ],
)
def test_parse_requires_exact_role_task_and_attempt_correlation(
    change: dict[str, object],
) -> None:
    with pytest.raises(ResultCorrelationError, match="correlation mismatch"):
        AgentResultParser().parse(document(**change), EXPECTED)


def test_launch_expectation_rejects_result_type_not_allowed_for_role() -> None:
    with pytest.raises(ResultDecodingError, match="not allowed for role"):
        ResultExpectation(CORRELATION, "qa_report")


def test_parse_rejects_result_type_different_from_launch() -> None:
    with pytest.raises(ResultDecodingError, match="result_type mismatch"):
        AgentResultParser().parse(document(result_type="decision_request"), EXPECTED)


def test_parse_validates_typed_payload_fields_and_payload_correlation() -> None:
    incomplete = coder_payload()
    del incomplete["head_sha"]
    with pytest.raises(ResultDecodingError, match="invalid coder_result payload"):
        AgentResultParser().parse(document(payload=incomplete), EXPECTED)

    with pytest.raises(ResultCorrelationError, match="payload attempt_id"):
        AgentResultParser().parse(
            document(payload=coder_payload(attempt_id="attempt-2")), EXPECTED
        )


def test_parse_rejects_unknown_fields_and_non_boolean_success() -> None:
    with pytest.raises(ResultDecodingError, match="task_success must be a boolean"):
        AgentResultParser().parse(document(task_success=1), EXPECTED)

    value = json.loads(document())
    value["surprise"] = True
    with pytest.raises(ResultDecodingError, match="unknown"):
        AgentResultParser().parse(json.dumps(value), EXPECTED)

    with pytest.raises(ResultDecodingError, match="invalid result correlation"):
        AgentResultParser().parse(document(task_id=6), EXPECTED)


@pytest.mark.parametrize(
    ("events", "message"),
    [
        ("human prose", "line 1 is not valid JSON"),
        (jsonl(None), "at least one completed agent_message"),
        (json.dumps({"type": "turn.failed"}), "turn.failed"),
        (
            jsonl(document()) + "\n" + json.dumps({"type": "turn.started"}),
            "event after turn.completed",
        ),
    ],
)
def test_jsonl_extraction_rejects_prose_missing_results_and_failures(
    events: str, message: str
) -> None:
    with pytest.raises(ResultDecodingError, match=message):
        AgentResultParser().parse_jsonl(events, EXPECTED)


def test_result_contract_pins_typed_schema_type_and_correlation() -> None:
    contract = result_contract(EXPECTED)

    assert "typed CoderResult domain contract" in contract
    assert '"schema_version":1' in contract
    assert '"role":"coder"' in contract
    assert '"task_id":"task-6"' in contract
    assert '"attempt_id":"attempt-1"' in contract
    assert '"result_type":"coder_result"' in contract


def _with_messages(*messages: str) -> str:
    events: list[dict[str, object]] = [{"type": "turn.started"}]
    for index, message in enumerate(messages):
        events.append({
            "type": "item.completed",
            "item": {"id": f"msg-{index}", "type": "agent_message", "text": message},
        })
    events.append({"type": "turn.completed"})
    return "\n".join(json.dumps(event) for event in events)


def test_commentary_before_the_final_message_is_ignored() -> None:
    parsed = AgentResultParser().parse_jsonl(
        _with_messages("I'll read the skill first.", document()), EXPECTED
    )

    assert parsed.task_success is True


def test_a_prose_final_message_is_rejected_even_after_an_earlier_valid_result() -> None:
    with pytest.raises(ResultDecodingError, match="not valid JSON"):
        AgentResultParser().parse_jsonl(
            _with_messages(document(), "Done! Let me know if you need more."),
            EXPECTED,
        )
