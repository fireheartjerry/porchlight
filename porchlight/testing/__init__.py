"""Test doubles: a scriptable model provider and a synthetic-instance builder."""

from __future__ import annotations

from .mock_model import MockModel, MockTurn, ScenarioModel
from .synth import example_dict, example_for_schema, example_instance

__all__ = [
    "MockModel",
    "MockTurn",
    "ScenarioModel",
    "example_dict",
    "example_for_schema",
    "example_instance",
]
