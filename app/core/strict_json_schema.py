"""StrictJsonSchema: a Pydantic model as the strict JSON schema the Model API accepts (s05 §4.1).

With `strict: true` the API requires: an object root, no `allOf`/`oneOf`, `additionalProperties:
false` on every object, and every property listed in `required`. A model that breaks a rule is
refused with ConfigError naming it; the schema is never rewritten to fit. Recursive models are
refused too (the API returns 400 for them, spike E).
"""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from app.core.errors import ConfigError
from app.core.types import JsonValue

type JsonObject = dict[str, JsonValue]

_DEFINITION_PREFIX = "#/$defs/"


class StrictJsonSchema:
    @staticmethod
    def from_model(model: type[BaseModel]) -> JsonObject:
        schema: JsonObject = model.model_json_schema()
        problems = StrictJsonSchema.problems(schema)
        if problems:
            raise ConfigError(f"{model.__name__} isn't a strict schema: {'; '.join(problems)}")
        return schema

    @staticmethod
    def problems(schema: Mapping[str, JsonValue]) -> list[str]:
        problems: list[str] = []
        if schema.get("type") != "object":
            problems.append("the root must be an object")
        if StrictJsonSchema._has_recursion(schema):
            problems.append("recursive models are not supported")
        problems.extend(StrictJsonSchema._node_problems(schema, "root"))
        return problems

    @staticmethod
    def _node_problems(node: Mapping[str, JsonValue], path: str) -> list[str]:
        problems = [
            f"{path}: {keyword} is not allowed" for keyword in ("allOf", "oneOf") if keyword in node
        ]
        properties = node.get("properties")
        if isinstance(properties, Mapping):
            if node.get("additionalProperties") is not False:
                problems.append(f"{path}: additionalProperties must be false (use extra='forbid')")
            required = node.get("required")
            required_names = set(required) if isinstance(required, list) else set()
            for name, child in properties.items():
                if name not in required_names:
                    problems.append(f"{path}.{name}: has a default; make it required")
                if isinstance(child, Mapping):
                    problems.extend(StrictJsonSchema._node_problems(child, f"{path}.{name}"))
        items = node.get("items")
        if isinstance(items, Mapping):
            problems.extend(StrictJsonSchema._node_problems(items, f"{path}[]"))
        branches = node.get("anyOf")
        if isinstance(branches, list):
            for index, branch in enumerate(branches):
                if isinstance(branch, Mapping):
                    problems.extend(
                        StrictJsonSchema._node_problems(branch, f"{path}.anyOf[{index}]")
                    )
        definitions = node.get("$defs")
        if isinstance(definitions, Mapping):
            for name, definition in definitions.items():
                if isinstance(definition, Mapping):
                    problems.extend(StrictJsonSchema._node_problems(definition, f"$defs.{name}"))
        return problems

    @staticmethod
    def _has_recursion(schema: Mapping[str, JsonValue]) -> bool:
        """True when a definition refers back to itself, directly or through others."""
        definitions = schema.get("$defs")
        if not isinstance(definitions, Mapping):
            return False
        references = {
            name: StrictJsonSchema._referenced_definitions(definition)
            for name, definition in definitions.items()
        }
        for start, direct_references in references.items():
            to_visit = list(direct_references)
            seen: set[str] = set()
            while to_visit:
                current = to_visit.pop()
                if current == start:
                    return True
                if current not in seen:
                    seen.add(current)
                    to_visit.extend(references.get(current, set()))
        return False

    @staticmethod
    def _referenced_definitions(value: JsonValue) -> set[str]:
        """Every `#/$defs/<name>` reachable inside one JSON value."""
        found: set[str] = set()
        to_visit: list[JsonValue] = [value]
        while to_visit:
            current = to_visit.pop()
            if isinstance(current, Mapping):
                reference = current.get("$ref")
                if isinstance(reference, str) and reference.startswith(_DEFINITION_PREFIX):
                    found.add(reference.removeprefix(_DEFINITION_PREFIX))
                to_visit.extend(current.values())
            elif isinstance(current, Sequence) and not isinstance(current, str):
                to_visit.extend(current)
        return found
