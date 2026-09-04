"""Model factory: real Bedrock models in production, :class:`MockModel` in tests and demos."""

from __future__ import annotations

from typing import Literal

from strands.models.model import Model

from .config import Settings

Tier = Literal["sonnet", "haiku"]

TEMPERATURE = 0.2
MAX_TOKENS = 4096


def model_id_for(settings: Settings, tier: Tier) -> str:
    """Return the configured Bedrock model id for a tier."""
    if tier == "haiku":
        return settings.model_haiku
    if tier == "sonnet":
        return settings.model_sonnet
    raise ValueError(f"unknown model tier: {tier!r}")


def make_model(settings: Settings, tier: Tier = "sonnet") -> Model:
    """Build the model for one agent tier.

    Args:
        settings: Application settings; ``model_provider`` decides between Bedrock and the mock.
        tier: ``"sonnet"`` for reasoning-heavy agents, ``"haiku"`` for fast ones.

    Returns:
        A ``strands.models.Model``. With ``PORCHLIGHT_MODEL_PROVIDER=mock`` nothing touches AWS:
        the model is a :class:`~porchlight.sim.mock_scenarios.PorchlightScenarioModel`, a
        ``MockModel`` subclass that plays each agent's part against the live store so the
        offline demo exercises the real tools, hooks, and policy instead of empty stubs.
    """
    if settings.model_provider == "mock":
        from .sim.mock_scenarios import PorchlightScenarioModel

        return PorchlightScenarioModel(tier=tier)

    from strands.models import BedrockModel

    return BedrockModel(
        model_id=model_id_for(settings, tier),
        region_name=settings.aws_region,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
    )
