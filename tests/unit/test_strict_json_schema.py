"""StrictJsonSchema: a model must already be strict; it is refused, never rewritten (s05 §4.1)."""

from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import ConfigError
from app.core.strict_json_schema import JsonObject, StrictJsonSchema
from app.layers.parent_question_layer import ParentAnswer
from app.safety.domain_policy import MinorPolicyCheck

pytestmark = pytest.mark.unit


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    tags: list[str]
    mood: Literal["calm", "busy"]


class Child(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class Nested(BaseModel):
    model_config = ConfigDict(extra="forbid")
    children: list[Child]
    best: Child | None


class Defaulted(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    note: str = ""


class OpenExtra(BaseModel):
    title: str


class LooseChild(BaseModel):
    name: str


class NestedLoose(BaseModel):
    model_config = ConfigDict(extra="forbid")
    child: LooseChild


class Tree(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    branches: list["Tree"]


class Bounded(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=10)


@pytest.mark.parametrize("model", [Strict, Nested, Bounded, ParentAnswer, MinorPolicyCheck])
def test_strict_models_pass_unchanged(model: type[BaseModel]) -> None:
    assert StrictJsonSchema.from_model(model) == model.model_json_schema()


@pytest.mark.parametrize(
    ("model", "problem"),
    [
        (Defaulted, "root.note: has a default; make it required"),
        (OpenExtra, "root: additionalProperties must be false"),
        (NestedLoose, "$defs.LooseChild: additionalProperties must be false"),
        (Tree, "recursive models are not supported"),
    ],
)
def test_a_non_strict_model_is_refused_naming_the_problem(
    model: type[BaseModel], problem: str
) -> None:
    with pytest.raises(ConfigError, match=f"{model.__name__} isn't a strict schema") as raised:
        StrictJsonSchema.from_model(model)
    assert problem in str(raised.value)


def test_a_non_object_root_is_a_problem() -> None:
    assert "the root must be an object" in StrictJsonSchema.problems({"type": "array"})


@pytest.mark.parametrize("keyword", ["allOf", "oneOf"])
def test_composition_keywords_are_problems(keyword: str) -> None:
    schema: JsonObject = {"type": "object", keyword: [{"type": "string"}]}
    assert f"root: {keyword} is not allowed" in StrictJsonSchema.problems(schema)
