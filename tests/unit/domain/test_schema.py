from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, StrEnum

import pytest

from milburn.agents.result_parser import RESULT_MODELS
from milburn.domain import CoderOutcome, CoderResult, EvidenceItem
from milburn.domain.base import VersionedModel
from milburn.domain.schema import SchemaGenerationError, model_schema
from tests.schema_check import schema_errors


class Colour(StrEnum):
    RED = "red"
    BLUE = "blue"


class Number(Enum):
    ONE = 1


@dataclass(frozen=True, slots=True)
class Inner(VersionedModel):
    name: str


@dataclass(frozen=True, slots=True)
class Sample(VersionedModel):
    count: int
    ratio: float
    flag: bool
    colour: Colour
    when: datetime
    inner: Inner
    names: tuple[str, ...]
    maybe: int | None


@dataclass(frozen=True, slots=True)
class WithDict(VersionedModel):
    data: dict


@dataclass(frozen=True, slots=True)
class WithIntEnum(VersionedModel):
    number: Number


def sample() -> Sample:
    return Sample(
        count=1,
        ratio=0.5,
        flag=True,
        colour=Colour.RED,
        when=datetime(2026, 11, 4, tzinfo=timezone.utc),
        inner=Inner(name="x"),
        names=("a",),
        maybe=None,
    )


def test_unsupported_annotation_fails_instead_of_emitting_a_weak_schema() -> None:
    with pytest.raises(SchemaGenerationError, match="data"):
        model_schema(WithDict)


def test_non_string_enum_is_refused() -> None:
    with pytest.raises(SchemaGenerationError, match="number"):
        model_schema(WithIntEnum)


def test_non_model_is_refused() -> None:
    with pytest.raises(SchemaGenerationError):
        model_schema(int)  # type: ignore[arg-type]


def test_schema_rejects_missing_extra_and_mistyped_fields() -> None:
    schema = model_schema(Sample)
    valid = sample().to_dict()

    missing = dict(valid)
    del missing["count"]
    extra = dict(valid, surprise=1)
    wrong_enum = dict(valid, colour="green")
    wrong_version = dict(valid, schema_version=2)
    bool_as_int = dict(valid, count=True)
    nested_missing = dict(valid, inner={"schema_version": 1})
    array_item = dict(valid, names=[1])

    for document in (
        missing,
        extra,
        wrong_enum,
        wrong_version,
        bool_as_int,
        nested_missing,
        array_item,
    ):
        assert schema_errors(schema, document), document


def test_schema_accepts_the_model_encoding_and_null_for_optional() -> None:
    schema = model_schema(Sample)
    assert schema_errors(schema, sample().to_dict()) == []
    assert schema_errors(schema, dict(sample().to_dict(), maybe=3)) == []


def test_every_object_lists_all_properties_as_required() -> None:
    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert sorted(node["required"]) == sorted(node["properties"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(model_schema(Sample))


@pytest.mark.parametrize("result_type", sorted(RESULT_MODELS))
def test_every_result_model_has_a_schema(result_type: str) -> None:
    schema = model_schema(RESULT_MODELS[result_type])
    assert schema["type"] == "object"


def test_real_result_payload_validates() -> None:
    payload = CoderResult(
        attempt_id="attempt-1",
        issue_number=6,
        outcome=CoderOutcome.CANDIDATE,
        head_sha="abc123",
        progress_path=".milburn/issues/6/progress.txt",
        commits=("abc123",),
        files_changed=("src/example.py",),
        test_claims=(EvidenceItem(name="pytest", outcome="passed", evidence="19"),),
        risks=(),
    )
    assert schema_errors(model_schema(CoderResult), payload.to_dict()) == []
