"""Build valid example instances of any Pydantic model in this project.

Used by :class:`porchlight.testing.mock_model.MockModel` so unscripted agent flows still return
well-formed structured output, and by tests that need a throwaway-but-valid entity.
"""

from __future__ import annotations

import types
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, Union, get_args, get_origin
from uuid import UUID

from annotated_types import Ge, Gt, Le, Lt, MaxLen, MinLen
from pydantic import BaseModel
from pydantic.fields import FieldInfo

EXAMPLE_TIME = datetime(2026, 9, 8, 14, 0, 0, tzinfo=UTC)
"""Fixed timestamp so synthesized instances are deterministic."""

MAX_DEPTH = 8

_UNION_TYPES = (Union, types.UnionType)


class SynthError(TypeError):
    """Raised when a type cannot be synthesized."""


def example_instance(model_cls: type[BaseModel], _depth: int = 0) -> BaseModel:
    """Build a valid instance of ``model_cls``.

    Required fields get a synthesized value derived from their annotation and constraints;
    optional fields keep their declared default. ``Field(examples=[...])`` wins when present.

    Args:
        model_cls: Any Pydantic v2 model class.
        _depth: Internal recursion guard.

    Returns:
        A validated instance of ``model_cls``.
    """
    if _depth > MAX_DEPTH:
        raise SynthError(f"model nesting too deep at {model_cls.__name__}")

    values: dict[str, Any] = {}
    for name, field in model_cls.model_fields.items():
        if field.examples:
            values[name] = field.examples[0]
            continue
        if not field.is_required():
            continue
        values[name] = _value_for(field.annotation, name, field, _depth + 1)
    return model_cls(**values)


def example_dict(model_cls: type[BaseModel]) -> dict[str, Any]:
    """Return :func:`example_instance` as a JSON-safe dict."""
    return example_instance(model_cls).model_dump(mode="json")


# --------------------------------------------------------------------------------------
# Annotation-driven synthesis
# --------------------------------------------------------------------------------------


def _constraints(field: FieldInfo | None) -> dict[str, Any]:
    """Extract the numeric/length constraints we know how to honor."""
    found: dict[str, Any] = {}
    for meta in getattr(field, "metadata", []) or []:
        if isinstance(meta, Ge):
            found["ge"] = meta.ge
        elif isinstance(meta, Gt):
            found["gt"] = meta.gt
        elif isinstance(meta, Le):
            found["le"] = meta.le
        elif isinstance(meta, Lt):
            found["lt"] = meta.lt
        elif isinstance(meta, MinLen):
            found["min_len"] = meta.min_length
        elif isinstance(meta, MaxLen):
            found["max_len"] = meta.max_length
    return found


def _number(field: FieldInfo | None, integer: bool) -> Any:
    """Pick a number satisfying the field's bounds."""
    limits = _constraints(field)
    value: float = 0.0
    if "ge" in limits:
        value = max(value, float(limits["ge"]))
    if "gt" in limits:
        value = max(value, float(limits["gt"]) + 1.0)
    if "le" in limits and value > float(limits["le"]):
        value = float(limits["le"])
    if "lt" in limits and value >= float(limits["lt"]):
        value = float(limits["lt"]) - 1.0
    return int(value) if integer else value


def _string(name: str, field: FieldInfo | None) -> str:
    """Pick a readable string satisfying any length constraints."""
    limits = _constraints(field)
    text = f"example {name}".strip() or "example"
    min_len = int(limits.get("min_len", 0) or 0)
    if len(text) < min_len:
        text = text.ljust(min_len, "x")
    max_len = limits.get("max_len")
    if max_len is not None and len(text) > int(max_len):
        text = text[: int(max_len)]
    return text


def _value_for(annotation: Any, name: str, field: FieldInfo | None, depth: int) -> Any:
    """Synthesize a value for one annotation."""
    if depth > MAX_DEPTH:
        raise SynthError(f"annotation nesting too deep for field {name!r}")

    if annotation is None or annotation is type(None):
        return None
    if annotation is Any:
        return _string(name, field)

    origin = get_origin(annotation)

    if origin is Literal:
        return get_args(annotation)[0]

    if origin in _UNION_TYPES:
        options = [arg for arg in get_args(annotation) if arg is not type(None)]
        if not options:
            return None
        return _value_for(options[0], name, field, depth + 1)

    if origin in (list, set, frozenset):
        (item_type,) = get_args(annotation) or (str,)
        items = [_value_for(item_type, name, None, depth + 1)]
        return set(items) if origin is set else frozenset(items) if origin is frozenset else items

    if origin is tuple:
        args = get_args(annotation)
        if not args:
            return ()
        if len(args) == 2 and args[1] is Ellipsis:
            return (_value_for(args[0], name, None, depth + 1),)
        return tuple(_value_for(arg, name, None, depth + 1) for arg in args)

    if origin is dict:
        args = get_args(annotation)
        if not args:
            return {}
        key = _value_for(args[0], "key", None, depth + 1)
        return {key: _value_for(args[1], name, None, depth + 1)}

    if isinstance(annotation, type):
        if issubclass(annotation, Enum):
            return next(iter(annotation))
        if issubclass(annotation, BaseModel):
            return example_instance(annotation, depth)
        if issubclass(annotation, bool):
            return False
        if issubclass(annotation, int):
            return _number(field, integer=True)
        if issubclass(annotation, float):
            return _number(field, integer=False)
        if issubclass(annotation, Decimal):
            return Decimal(str(_number(field, integer=False)))
        if issubclass(annotation, str):
            return _string(name, field)
        if issubclass(annotation, bytes):
            return b"example"
        if issubclass(annotation, datetime):
            return EXAMPLE_TIME
        if issubclass(annotation, date):
            return EXAMPLE_TIME.date()
        if issubclass(annotation, time):
            return EXAMPLE_TIME.time()
        if issubclass(annotation, timedelta):
            return timedelta(hours=1)
        if issubclass(annotation, UUID):
            return UUID(int=0)

    raise SynthError(f"cannot synthesize a value for field {name!r} of type {annotation!r}")


# --------------------------------------------------------------------------------------
# JSON-schema-driven synthesis (for tool specs, where the class is not available)
# --------------------------------------------------------------------------------------


def example_for_schema(schema: dict[str, Any], name: str = "value", _depth: int = 0) -> Any:
    """Build a value that satisfies a (flattened) JSON schema.

    Strands converts a Pydantic model to a tool spec whose ``$ref``s are already resolved, so
    this only needs to handle inline types.

    Args:
        schema: A JSON-schema fragment.
        name: Property name, used to make generated strings readable.
        _depth: Internal recursion guard.
    """
    if _depth > MAX_DEPTH:
        return None

    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    if "default" in schema:
        return schema["default"]

    kinds = schema.get("type", "string")
    kinds = [kinds] if isinstance(kinds, str) else list(kinds)
    kind = next((k for k in kinds if k != "null"), "null")

    if kind == "null":
        return None
    if kind == "boolean":
        return False
    if kind in ("integer", "number"):
        value = float(schema.get("minimum", schema.get("exclusiveMinimum", 0)) or 0)
        maximum = schema.get("maximum")
        if maximum is not None and value > float(maximum):
            value = float(maximum)
        return int(value) if kind == "integer" else value
    if kind == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            return []
        return [example_for_schema(items, name, _depth + 1)] if schema.get("minItems", 0) else []
    if kind == "object":
        properties: dict[str, Any] = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        return {
            key: example_for_schema(value, key, _depth + 1)
            for key, value in properties.items()
            if key in required
        }

    fmt = schema.get("format")
    if fmt == "date-time":
        return EXAMPLE_TIME.isoformat()
    if fmt == "date":
        return EXAMPLE_TIME.date().isoformat()
    if fmt == "time":
        return EXAMPLE_TIME.time().isoformat()
    if fmt == "uuid":
        return str(UUID(int=0))
    text = f"example {name}".strip()
    min_len = int(schema.get("minLength", 0) or 0)
    return text.ljust(min_len, "x") if len(text) < min_len else text
