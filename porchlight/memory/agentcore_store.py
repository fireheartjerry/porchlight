"""A ``strands.memory.MemoryStore`` backed by Amazon Bedrock AgentCore Memory.

The same notes as :class:`~porchlight.memory.sqlite_store.SqliteMemoryStore`, but stored in
AgentCore Memory so several runtime instances share one long-term brain. Nothing here touches
boto3 until the first call, so importing this module with no AWS credentials is safe.
"""

from __future__ import annotations

import logging
from typing import Any

from strands.memory.types import MemoryEntry, SearchOptions

logger = logging.getLogger(__name__)

DEFAULT_NAMESPACE_PREFIX = "/porchlight"
DEFAULT_ACTOR_ID = "porchlight"
DEFAULT_SESSION_ID = "porchlight-longterm"
DEFAULT_MAX_RESULTS = 5


class AgentCoreMemoryStore:
    """Long-term memory in AgentCore Memory.

    Args:
        memory_id: The AgentCore Memory resource id.
        region: AWS region; defaults to the boto session's region.
        namespace_prefix: Namespace root; per-person notes live under ``<prefix>/<about_id>``.
        actor_id: Actor the events are written as.
        session_id: Logical session grouping the written events.
        name: Store name required by the Strands ``MemoryStore`` protocol.
        description: Shown to the model in memory tool descriptions.
        max_search_results: Default result cap for :meth:`search`.
        writable: Whether the manager may write to this store.
        extraction: Automatic-extraction config; ``False`` by default.
        client: Pre-built ``bedrock_agentcore.memory.MemoryClient`` (tests inject a fake).
    """

    def __init__(
        self,
        memory_id: str,
        region: str | None = None,
        *,
        namespace_prefix: str = DEFAULT_NAMESPACE_PREFIX,
        actor_id: str = DEFAULT_ACTOR_ID,
        session_id: str = DEFAULT_SESSION_ID,
        name: str = "agentcore_memory",
        description: str = (
            "Durable neighbourhood notes stored in AgentCore Memory: volunteer preferences, "
            "requester facts, and how past jobs went."
        ),
        max_search_results: int = DEFAULT_MAX_RESULTS,
        writable: bool = True,
        extraction: Any = False,
        client: Any | None = None,
    ) -> None:
        self.memory_id = memory_id
        self.region = region
        self.namespace_prefix = namespace_prefix.rstrip("/")
        self.actor_id = actor_id
        self.session_id = session_id
        self.name = name
        self.description = description
        self.max_search_results = max_search_results
        self.writable = writable
        self.extraction = extraction
        self._client = client

    # --- plumbing -----------------------------------------------------------

    @property
    def client(self) -> Any:
        """The ``MemoryClient``, created on first use so imports never need credentials."""
        if self._client is None:
            from bedrock_agentcore.memory import MemoryClient

            self._client = MemoryClient(region_name=self.region, integration_source="porchlight")
        return self._client

    def namespace_for(self, about_id: str | None) -> str:
        """Namespace a note about ``about_id`` belongs in."""
        return f"{self.namespace_prefix}/{about_id}/" if about_id else f"{self.namespace_prefix}/group/"

    def __repr__(self) -> str:
        return f"AgentCoreMemoryStore(memory_id={self.memory_id!r}, region={self.region!r})"

    # --- writing ------------------------------------------------------------

    def add_sync(self, content: str, metadata: dict[str, Any] | None = None) -> str:
        """Write one note as an AgentCore event and return its event id."""
        text = (content or "").strip()
        if not text:
            raise ValueError("memory content must not be empty")
        meta = dict(metadata or {})
        about_id = meta.get("about_id")
        event_metadata = {
            key: {"stringValue": str(value)}
            for key, value in (("about_id", about_id), ("kind", meta.get("kind") or "fact"))
            if value is not None
        }
        response = self.client.create_event(
            memory_id=self.memory_id,
            actor_id=str(about_id or self.actor_id),
            session_id=self.session_id,
            messages=[(text, "ASSISTANT")],
            metadata=event_metadata or None,
        )
        event = response.get("event", response) if isinstance(response, dict) else {}
        return str(event.get("eventId", "")) if isinstance(event, dict) else ""

    async def add(self, content: str, metadata: dict[str, Any] | None = None) -> str:
        """Strands ``MemoryStore.add``."""
        return self.add_sync(content, metadata)

    # --- reading ------------------------------------------------------------

    def search_sync(
        self, query: str, limit: int | None = None, about: str | None = None
    ) -> list[MemoryEntry]:
        """Semantic search over stored memory records.

        Args:
            query: What to recall, in plain language.
            limit: Maximum results; defaults to ``max_search_results``.
            about: Scope to one person's namespace; otherwise the whole Porchlight tree.
        """
        cap = max(1, limit or self.max_search_results or DEFAULT_MAX_RESULTS)
        kwargs: dict[str, Any] = {"memory_id": self.memory_id, "query": query, "top_k": cap}
        if about:
            kwargs["namespace"] = self.namespace_for(about)
        else:
            kwargs["namespace_path"] = f"{self.namespace_prefix}/"
        try:
            records = self.client.retrieve_memories(**kwargs) or []
        except Exception:  # pragma: no cover - network/permission failures must not break a run
            logger.warning("AgentCore memory retrieval failed", exc_info=True)
            return []
        return [entry for entry in (self._to_entry(record) for record in records) if entry is not None]

    async def search(self, query: str, options: SearchOptions | None = None) -> list[MemoryEntry]:
        """Strands ``MemoryStore.search`` (supports ``max_search_results`` and ``about``)."""
        opts: dict[str, Any] = dict(options or {})
        return self.search_sync(query, limit=opts.get("max_search_results"), about=opts.get("about"))

    async def initialize(self) -> None:
        """Strands ``MemoryStore.initialize``: nothing to do; the resource is provisioned by CDK."""
        return None

    def _to_entry(self, record: Any) -> MemoryEntry | None:
        """Convert one ``memoryRecordSummary`` into a :class:`MemoryEntry`."""
        if not isinstance(record, dict):
            return None
        content = record.get("content")
        text = content.get("text", "") if isinstance(content, dict) else str(content or "")
        if not text:
            return None
        metadata = {
            "id": record.get("memoryRecordId"),
            "about_id": (record.get("namespaces") or [None])[0],
            "kind": record.get("memoryStrategyId", "fact"),
            "ts": str(record.get("createdAt", "")),
            "score": record.get("score"),
        }
        return MemoryEntry(content=text, store_name=self.name, metadata=metadata)
