"""Application settings, loaded from ``PORCHLIGHT_*`` environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Mode = Literal["demo", "live"]
ModelProvider = Literal["bedrock", "mock"]
StoreKind = Literal["sqlite", "dynamo"]
ChannelKind = Literal["auto", "sim", "email"]
ToolsKind = Literal["local", "mcp"]
EventsSource = Literal["memory", "store"]


class Settings(BaseSettings):
    """Runtime configuration. Every field can be overridden by ``PORCHLIGHT_<FIELD>``."""

    model_config = SettingsConfigDict(
        env_prefix="PORCHLIGHT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- wiring -------------------------------------------------------------
    mode: Mode = "demo"
    model_provider: ModelProvider = "bedrock"
    store: StoreKind = "sqlite"
    tools: ToolsKind = "local"
    channel: ChannelKind = "auto"
    """How Porchlight talks to volunteers: ``sim``, ``email``, or ``auto``.

    ``auto`` follows the mode — the simulator in demo mode, email in live mode. Set it to
    ``sim`` on a live deployment to show the whole loop (outreach, reply, confirmation)
    without texting a real person: the replies come from the Haiku-powered volunteer
    simulator and are persisted through the store rather than held in one process.
    """
    events_source: EventsSource = "memory"
    """Where ``/api/events`` reads from: this process's bus, or the store's persisted trace.

    Set it to ``store`` when the API and the agents run in different processes — the API on
    Lambda, the graph on AgentCore Runtime — so the porch still sees a live trace.
    """

    # --- local persistence --------------------------------------------------
    sqlite_path: str = "data/local/porchlight.db"
    session_dir: str = "data/sessions"

    # --- AWS ----------------------------------------------------------------
    session_bucket: str | None = None
    memory_id: str | None = Field(
        default=None,
        # The AgentCore CLI's CDK injects the deployed memory id as MEMORY_<NAME>_ID, where
        # <NAME> is the memory's name upper-cased — "PorchlightMemory" in agentcore/agentcore.json.
        validation_alias=AliasChoices("PORCHLIGHT_MEMORY_ID", "MEMORY_PORCHLIGHTMEMORY_ID"),
    )
    dynamo_table: str = "porchlight"
    aws_region: str = Field(
        default="us-east-1",
        validation_alias=AliasChoices("PORCHLIGHT_AWS_REGION", "AWS_REGION", "AWS_DEFAULT_REGION"),
    )
    agent_runtime_arn: str | None = None

    # --- messaging ----------------------------------------------------------
    from_addr: str = Field(
        default="porchlight@example.org",
        description="Verified SES sender address used by EmailChannel in live mode",
    )

    # --- models -------------------------------------------------------------
    model_sonnet: str = "global.anthropic.claude-sonnet-4-6"
    model_haiku: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

    # --- group policy -------------------------------------------------------
    group_name: str = "Maple Street Mutual Aid"
    timezone: str = "America/Toronto"
    quiet_hours: tuple[int, int] = (21, 8)
    petty_cash_limit: float = 40.0
    max_candidates: int = 3
    escalate_hours_before_window: int = 6
    confidence_threshold: float = 0.55

    @property
    def is_demo(self) -> bool:
        """True when running the local demo wiring (sqlite + simulated channel)."""
        return self.mode == "demo"

    @property
    def channel_kind(self) -> Literal["sim", "email"]:
        """The channel to build, with ``auto`` resolved against the mode."""
        return ("sim" if self.is_demo else "email") if self.channel == "auto" else self.channel

    @property
    def simulates_replies(self) -> bool:
        """True when volunteers are role-played rather than messaged for real."""
        return self.channel_kind == "sim"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings`."""
    return Settings()


def reset_settings() -> None:
    """Clear the cached settings (tests, or after mutating the environment)."""
    get_settings.cache_clear()
