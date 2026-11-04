import json

import pytest

from milburn.agents.result_parser import (
    AgentResultParser,
    ResultCorrelation,
    ResultCorrelationError,
    ResultDecodingError,
    result_contract,
)
from milburn.domain import Role


EXPECTED = ResultCorrelation(Role.CODER, "task-6", "attempt-1")


def document(**changes: object) -> str:
    value = {
        "schema_version": 1,
        "role": "coder",
        "task_id": "task-6",
        "attempt_id": "attempt-1",
        "task_success": True,
        "result_type": "coder_result",
        "payload": {"head_sha": "abc123", "tests": ["pytest: pass"]},
    }
    value.update(changes)
    return json.dumps(value)


def test_parse_accepts_known_version_and_freezes_payload() -> None:
    parsed = AgentResultParser().parse(document(), EXPECTED)

    assert parsed.correlation == EXPECTED
    assert parsed.task_success is True
    assert parsed.result_type == "coder_result"
    assert parsed.payload["head_sha"] == "abc123"
    assert parsed.payload["tests"] == ("pytest: pass",)
    with pytest.raises(TypeError):
        parsed.payload["head_sha"] = "changed"  # type: ignore[index]


@pytest.mark.parametrize("version", [0, 2, 99])
def test_parse_rejects_unknown_result_schema_versions(version: int) -> None:
    with pytest.raises(ResultDecodingError, match="unsupported result schema"):
        AgentResultParser().parse(document(schema_version=version), EXPECTED)


@pytest.mark.parametrize(
    ("change", "expected_message"),
    [
        ({"role": "tester"}, "correlation mismatch"),
        ({"task_id": "task-7"}, "correlation mismatch"),
        ({"attempt_id": "attempt-2"}, "correlation mismatch"),
    ],
)
def test_parse_requires_exact_role_task_and_attempt_correlation(
    change: dict[str, object], expected_message: str
) -> None:
    with pytest.raises(ResultCorrelationError, match=expected_message):
        AgentResultParser().parse(document(**change), EXPECTED)


def test_parse_rejects_unknown_types_fields_and_non_boolean_success() -> None:
    with pytest.raises(ResultDecodingError, match="unknown result_type"):
        AgentResultParser().parse(document(result_type="free_form"), EXPECTED)
    with pytest.raises(ResultDecodingError, match="task_success must be a boolean"):
        AgentResultParser().parse(document(task_success=1), EXPECTED)

    value = json.loads(document())
    value["surprise"] = True
    with pytest.raises(ResultDecodingError, match="unknown"):
        AgentResultParser().parse(json.dumps(value), EXPECTED)

    with pytest.raises(ResultDecodingError, match="invalid result correlation"):
        AgentResultParser().parse(document(task_id=6), EXPECTED)


def test_result_contract_pins_schema_type_and_correlation() -> None:
    contract = result_contract(EXPECTED, "coder_result")

    assert '"schema_version":1' in contract
    assert '"role":"coder"' in contract
    assert '"task_id":"task-6"' in contract
    assert '"attempt_id":"attempt-1"' in contract
    assert '"result_type":"coder_result"' in contract
