"""The synthetic-instance builder must produce a valid instance of every project model."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

import pytest
from pydantic import BaseModel, Field
from strands.tools.structured_output.structured_output_utils import convert_pydantic_to_tool_spec

from porchlight.models import ALL_MODELS, AidRequest, Category, MatchPlan, Volunteer
from porchlight.testing.synth import (
    EXAMPLE_TIME,
    SynthError,
    example_dict,
    example_for_schema,
    example_instance,
)


@pytest.mark.parametrize("model_cls", ALL_MODELS, ids=lambda cls: cls.__name__)
def test_example_instance_for_every_domain_model(model_cls: type[BaseModel]) -> None:
    instance = example_instance(model_cls)
    assert isinstance(instance, model_cls)
    # Re-validating the dump proves the instance is genuinely valid, not just constructed.
    model_cls.model_validate(instance.model_dump(mode="json"))


@pytest.mark.parametrize("model_cls", ALL_MODELS, ids=lambda cls: cls.__name__)
def test_example_dict_is_json_safe(model_cls: type[BaseModel]) -> None:
    payload = example_dict(model_cls)
    assert isinstance(payload, dict)
    assert not any(isinstance(value, datetime) for value in payload.values())


@pytest.mark.parametrize("model_cls", ALL_MODELS, ids=lambda cls: cls.__name__)
def test_schema_synthesis_validates_against_the_model(model_cls: type[BaseModel]) -> None:
    spec = convert_pydantic_to_tool_spec(model_cls)
    payload = example_for_schema(spec["inputSchema"]["json"])
    assert isinstance(payload, dict)
    model_cls.model_validate(payload)


def test_defaults_are_preserved_and_required_fields_filled() -> None:
    request = example_instance(AidRequest)
    assert isinstance(request, AidRequest)
    assert request.category is Category.OTHER
    assert request.attempts == []

    plan = example_instance(MatchPlan)
    assert isinstance(plan, MatchPlan)
    assert plan.request_id  # required, so synthesized


class Colour(StrEnum):
    """Enum whose first member should be chosen."""

    RED = "red"
    BLUE = "blue"


class Inner(BaseModel):
    """Nested model."""

    label: str


class Sample(BaseModel):
    """A model exercising every branch of the synthesizer."""

    name: str
    count: int = Field(ge=3, le=9)
    ratio: float = Field(ge=0.0, le=1.0)
    flag: bool
    colour: Colour
    mode: Literal["fast", "slow"]
    when: datetime
    tags: list[str]
    pair: tuple[int, str]
    lookup: dict[str, int]
    nested: Inner
    maybe: str | None
    anything: Any
    provided: str = Field(examples=["from the example"])


def test_synthesizer_handles_every_annotation_kind() -> None:
    sample = example_instance(Sample)
    assert isinstance(sample, Sample)
    assert sample.count == 3
    assert 0.0 <= sample.ratio <= 1.0
    assert sample.flag is False
    assert sample.colour is Colour.RED
    assert sample.mode == "fast"
    assert sample.when == EXAMPLE_TIME
    assert sample.tags and isinstance(sample.tags[0], str)
    assert sample.pair[0] == 0 and isinstance(sample.pair[1], str)
    assert sample.lookup
    assert isinstance(sample.nested, Inner)
    assert isinstance(sample.maybe, str)
    assert sample.provided == "from the example"


def test_min_length_is_respected() -> None:
    class Padded(BaseModel):
        code: str = Field(min_length=40)

    assert len(example_instance(Padded).code) >= 40


def test_unsupported_type_raises() -> None:
    class Weird(BaseModel):
        model_config = {"arbitrary_types_allowed": True}
        thing: complex

    with pytest.raises(SynthError):
        example_instance(Weird)


def test_example_for_schema_handles_primitives() -> None:
    assert example_for_schema({"type": "boolean"}) is False
    assert example_for_schema({"type": "integer", "minimum": 5}) == 5
    assert example_for_schema({"type": ["string", "null"]}) == "example value"
    assert example_for_schema({"enum": ["a", "b"]}) == "a"
    assert example_for_schema({"type": "string", "format": "date-time"}) == EXAMPLE_TIME.isoformat()
    assert example_for_schema({"type": "array", "items": {"type": "string"}}) == []
    assert example_for_schema({"type": "array", "items": {"type": "string"}, "minItems": 1}) == [
        "example value"
    ]


def test_example_for_schema_only_fills_required_object_properties() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
        "required": ["a"],
    }
    assert example_for_schema(schema) == {"a": "example a"}


def test_volunteer_example_is_usable() -> None:
    volunteer = example_instance(Volunteer)
    assert isinstance(volunteer, Volunteer)
    assert volunteer.id.startswith("vol_")
    assert volunteer.can_do(Category.OTHER)
