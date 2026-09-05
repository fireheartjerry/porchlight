# Porchlight — Internal Contracts (shared by all builders)

These interfaces are fixed so that modules built in parallel fit together. If you must deviate,
document it at the top of the module you changed and keep the old name as an alias.

## 0. Conventions
- Python 3.12, Pydantic v2, type hints everywhere, `ruff` clean (line length 110).
- Package: `porchlight/`. Tests: `tests/`. Run with `source .venv/bin/activate && pytest -q`.
- Never require AWS at import time. Boto3 clients are created lazily inside functions.
- Time: always timezone-aware UTC `datetime`s; `porchlight.clock.Clock` (real / frozen for tests).
- IDs: `str`, prefixed: `req_`, `vol_`, `rqr_`, `dec_`, `msg_`, `log_` + 10 hex chars (`porchlight.ids.new_id("req")`).

## 1. AppContext (`porchlight/context.py`)
All tools, agents, and the graph get one `AppContext`:
```python
@dataclass
class AppContext:
    settings: Settings                 # porchlight.config.Settings
    store: Store                       # porchlight.store.Store
    channel: Channel                   # porchlight.channels.Channel
    memory: MemoryStore | None         # strands.memory.MemoryStore impl (SqliteMemoryStore / AgentCoreMemoryStore)
    clock: Clock
    emit: Callable[[dict], None]       # push a trace event (dict) to whoever is listening (SSE / logs). No-op default.
```
Tools receive it via `tool_context.invocation_state["ctx"]` (tools are declared with `@tool(context=True)`).
The graph/agents are invoked with `invocation_state={"ctx": ctx, "request_id": ...}`.
Helper: `porchlight.context.get_ctx(tool_context) -> AppContext`.
Factory: `porchlight.context.build_context(settings: Settings | None = None, **overrides) -> AppContext`
(picks Sqlite/Sim/Sqlite-memory in demo mode; Dynamo/SES/AgentCore memory in live mode).

## 2. Settings (`porchlight/config.py`, pydantic-settings, env prefix `PORCHLIGHT_`)
```
mode: "demo" | "live" = "demo"
model_provider: "bedrock" | "mock" = "bedrock"
store: "sqlite" | "dynamo" = "sqlite"
tools: "local" | "mcp" = "local"
events_source: "memory" | "store" = "memory"   # "store" when API and agents are separate processes
sqlite_path: str = "data/local/porchlight.db"
session_dir: str = "data/sessions"
session_bucket: str | None
memory_id: str | None                 # AgentCore Memory id
dynamo_table: str = "porchlight"
aws_region: str = "us-east-1"         # falls back to AWS_REGION
model_sonnet: str = "global.anthropic.claude-sonnet-4-6"
model_haiku: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
agent_runtime_arn: str | None         # when API should call AgentCore instead of in-process
from_addr: str = "porchlight@example.org"   # verified SES sender used by EmailChannel
group_name: str = "Maple Street Mutual Aid"
timezone: str = "America/Toronto"
quiet_hours: tuple[int, int] = (21, 8)
petty_cash_limit: float = 40.0
max_candidates: int = 3
escalate_hours_before_window: int = 6
confidence_threshold: float = 0.55
```
`porchlight.config.get_settings()` cached; `Settings()` constructible in tests with kwargs.

## 3. Models (`porchlight/models.py`) — exactly the entities in DESIGN.md §5
Enums as `StrEnum`: `Category`, `Urgency`, `RequestStatus`, `Source`, `ReplyIntent`, `DecisionKind`,
`DecisionStatus`, `LogKind`, `MessageStatus`, `Recipient` ("volunteer"|"requester"|"coordinator").
Every model has `model_config = ConfigDict(extra="forbid")` except `LogEvent.detail: dict[str, Any]`.
`LogEvent.visible: bool = True` — False marks bookkeeping (lookups, reads, the audit copy of a row a tool
already wrote, and a `GUIDANCE:` policy verdict, which is a nudge at the model that the row it
redirects to already tells); the Quiet Log hides those. Wording for every row comes from
`porchlight.tools.summaries.describe_tool(ctx, tool_name, inputs, result)`, which strips verdict
prefixes and scrubs internal ids (`req_…`, `vol_…`) out of every string it prints.
`AidRequest.attempts: list[Attempt]` where `Attempt(volunteer_id, sent_at, outcome: "pending"|"accepted"|"declined"|"counter"|"concern"|"timeout", note: str | None)`.
`AidRequest` also carries `version: int` (optimistic concurrency, store-managed), `is_request: bool = True`, and
`duplicate_of: str | None`; `AidRequest.needs_outreach()` is false for either of the last two.
`Decision.options: list[DecisionOption(id, label, description)]`; option ids are short snake_case (`"approve"`, `"widen_pool"`, `"i_will_handle"`, `"decline_request"`, `"reschedule"`).

## 4. Store (`porchlight/store/base.py`) — `Protocol`
```
# volunteers
put_volunteer(v) / get_volunteer(id) -> Volunteer | None / list_volunteers(zone=None, skill=None, vetted=None) -> list
# requesters
put_requester(r) / get_requester(id) / find_requester_by_contact(contact: str) -> Requester | None / list_requesters()
# requests
put_request(req) / get_request(id) / list_requests(status: RequestStatus | None = None, limit=200) -> list (newest first)
requests_for_volunteer(volunteer_id, since: datetime) -> list
update_request_fields(request_id, *, expected_version: int | None = None, **fields) -> AidRequest | None  # atomic, bumps version
append_attempt(request_id, attempt: Attempt) -> AidRequest | None            # appends, rewrites nothing else
resolve_attempt(request_id, attempt: Attempt) -> AidRequest | None           # settles that volunteer's open ask
# decisions
put_decision(d) / get_decision(id) / list_decisions(status: DecisionStatus | None = None) -> list (newest first)
# messages
put_message(m) / list_messages(request_id=None, status=None, due_before: datetime | None = None) -> list
# log
append_log(e: LogEvent) / list_log(request_id=None, limit=200, since=None) -> list (newest first)
# trace (persisted so a split deployment still has a live trace)
append_trace(event: dict) -> int (cursor) / list_trace(since_cursor=0, limit=500, request_id=None) -> list (oldest first, each carrying "cursor")
# settings
get_group_settings() -> GroupSettings / put_group_settings(gs)
# util
reset() (wipe; tests/demo) / stats(day: date) -> dict(handled_autonomously:int, decisions_open:int, decisions_resolved:int, requests_by_status: dict)
```
`SqliteStore(path)` (thread-safe, WAL, JSON columns; `":memory:"` allowed). `DynamoStore(table, region)` same API (single table; pk=`ENTITY#id`, sk=`ENTITY`, GSI1 by entity+status+created_at).
Field-level writes are atomic in both: SQLite uses one `UPDATE ... WHERE id = ? AND version = ?` under the store lock; Dynamo uses
`UpdateExpression` + `ConditionExpression version = :expected`, and `append_attempt` is a `list_append` on an `attempts` attribute.
A lost race raises `porchlight.store.base.StaleVersionError`. Persisted trace items carry an `expires_at` epoch second for a DynamoDB TTL.

## 5. Channel (`porchlight/channels/base.py`) — `Protocol`
```
send(msg: OutboundMessage) -> OutboundMessage          # sets sent_at/status; SimChannel may auto-generate a reply
fetch_replies(request_id: str) -> list[InboundReply]   # InboundReply(id, request_id, from_volunteer_id, text, received_at)
schedule(msg: OutboundMessage, when: datetime) -> OutboundMessage
```
`SimChannel(store, clock, reply_fn: Callable[[Volunteer, AidRequest, str], str] | None)` — stores messages, and when a
volunteer is messaged, produces a reply by calling `reply_fn` (the volunteer simulator agent) or scripted fixture replies
(`porchlight/sim/fixtures.py: SCRIPTED_REPLIES`). `EmailChannel(ses_client_factory, from_addr, dry_run=True)`. `make_channel` returns `EmailChannel(dry_run=False)` in live mode **only** when `from_addr` differs from the `porchlight@example.org` placeholder; otherwise it warns and stays in dry-run, because SES rejects an unverified sender.

## 6. Tools (`porchlight/tools/`) — all `@tool(context=True)`, importable from `porchlight.tools`
Return plain dicts/lists/str (JSON-serializable). Names are fixed:
```
lookup_requester_history(contact_or_name: str) -> dict           # {requester: {...}|None, recent_requests: [...]}
find_similar_open_requests(requester_id: str, category: str | None = None, window_hours: int = 72) -> list[dict]  # duplicate detection
find_candidates(request_id: str, limit: int = 5) -> list[dict]     # [{volunteer_id, name, score, reasons: [..], load_this_week, zones, skills, memory_notes}]
volunteer_load(volunteer_id: str) -> dict                          # {this_week: n, max_per_week: n, last_active: iso}
recall_memory(query: str, about: str | None = None) -> list[dict]  # [{content, metadata}] from ctx.memory
remember(content: str, about_id: str | None = None, kind: str = "fact") -> dict
send_message(request_id: str, to: str, recipient_id: str, body: str) -> dict   # to in {"volunteer","requester","coordinator"}; returns {message_id, status}
schedule_message(request_id: str, to: str, recipient_id: str, body: str, send_at_iso: str) -> dict
read_replies(request_id: str) -> list[dict]
assign_volunteer(request_id: str, volunteer_id: str) -> dict       # marks request confirmed
record_attempt(request_id: str, volunteer_id: str, outcome: str, note: str | None = None) -> dict
update_request(request_id: str, **fields) -> dict                  # status/window/etc.; validated
close_request(request_id: str, outcome: str, note: str | None = None) -> dict   # completed|cancelled|declined
query_requests(status: str | None = None, since_iso: str | None = None) -> list[dict]
query_log(request_id: str | None = None, since_iso: str | None = None, limit: int = 100) -> list[dict]
```
Side-effect tools (policy-gated): `send_message`, `schedule_message`, `assign_volunteer`, `close_request`, `remember`.
Tool groups exported: `INTAKE_TOOLS`, `MATCHER_TOOLS`, `OUTREACH_TOOLS`, `STEWARD_TOOLS`, `BRIEF_TOOLS`, `ALL_TOOLS`.

## 7. Agents & graph (`porchlight/agents/`, `porchlight/graph.py`)
```
make_intake_agent(ctx) / make_matcher_agent(ctx) / make_outreach_agent(ctx) / make_steward_agent(ctx) / make_brief_agent(ctx)
    -> strands.Agent (name set to "intake"/"matcher"/...; structured_output_model set; tools from §6; hooks + interventions attached)
build_graph(ctx, session_id: str) -> strands.multiagent.Graph
run_request(ctx, request_id: str) -> RunOutcome           # entry: process a new/updated request end-to-end (may interrupt)
resume_decision(ctx, decision_id: str, option_id: str, note: str | None) -> RunOutcome
run_sweep(ctx) -> SweepOutcome                            # due scheduled messages, stale outreach → escalate, timeouts
run_brief(ctx, day: date) -> str                          # markdown digest
RunOutcome(request_id, status: RequestStatus, decisions_created: list[Decision], log_events: int, interrupted: bool, summary: str)
```
Session id for a request's graph = `request_id`; session manager = `FileSessionManager(session_id, storage_dir=settings.session_dir)` locally,
`S3SessionManager` when `session_bucket` set. Interrupts → `Decision` rows (`interrupt_id`, `session_id`, `node`) so
`resume_decision` can rebuild the graph and pass `[{"interruptResponse": {"interruptId": ..., "response": {"option": option_id, "note": note}}}]`.

Policy (`porchlight/policy.py`): `evaluate_request(req: AidRequest, settings) -> list[PolicyFlag]` (deterministic) and
`class PorchlightPolicy(InterventionHandler)` implementing the table in DESIGN.md §3, plus
`class AuditHook(HookProvider)` (writes `LogEvent`s and calls `ctx.emit`) and `class TraceHook(HookProvider)` (node/tool/model events → `ctx.emit`).
Trace event shape (dict): `{"type": "node_start"|"node_end"|"tool_call"|"tool_result"|"model_call"|"message"|"decision"|"log", "ts": iso, "request_id": str|None, "agent": str|None, "summary": str, "detail": {...}}`.

## 8. AgentCore runtime entrypoint (`porchlight/runtime.py`)
Payload: `{"action": "process_request"|"resume_decision"|"sweep"|"brief", ...args}`. Returns the outcome as JSON. Streams trace events when
`"stream": true`. `BedrockAgentCoreApp` with `@app.entrypoint`. Runs with `PORCHLIGHT_MODE=live` defaults.

## 9. API (`api/`) — FastAPI, JSON, CORS open in demo
```
GET  /api/health
GET  /api/porch[?all=1]             -> {status_line, light_on: bool, open_decisions: [Decision], quiet_log: [LogEvent], stats}
                                       quiet_log holds only rows with LogEvent.visible unless ?all=1
GET  /api/requests?status=          -> [AidRequest]
GET  /api/requests/{id}             -> {request, attempts, messages, log}
POST /api/inbox                     -> {text, source, contact?, image_base64?} -> creates AidRequest via run_request; returns RunOutcome
GET  /api/decisions?status=open     -> [Decision]
POST /api/decisions/{id}/resolve    -> {option_id, note?} -> RunOutcome
GET  /api/volunteers                -> [Volunteer + load]
GET  /api/log?request_id=&limit=    -> [LogEvent]
GET  /api/events                    -> SSE stream of trace events (text/event-stream)
GET  /api/events/poll?since=&limit= -> {events: [TraceEvent + cursor], cursor} read from the persisted trace
POST /api/demo/reset                -> reseed fixtures
POST /api/demo/run_day              -> {count?: int} streams N sample requests through run_request (background task), progress via /api/events
GET  /api/demo/samples              -> list of sample inbound messages (id, label, text, expected: "quiet"|"card")
POST /api/sweep                     -> SweepOutcome
GET  /api/brief?day=                -> {markdown}
```
`api/main.py` exposes `app`; `api/lambda_handler.py` exposes `handler = Mangum(app)`. Orchestration goes through
`porchlight.orchestrator.Orchestrator` with `LocalOrchestrator(ctx)` (in-process) and `AgentCoreOrchestrator(ctx, arn)` (boto3 `invoke_agent_runtime`).

## 10. Mock model (`porchlight/testing/mock_model.py`)
`MockModel(script: list[MockTurn] | None = None, default_structured: bool = True)` implements `strands.models.Model`.
- `MockTurn(text: str | None = None, tool_calls: list[tuple[name, input_dict]] | None = None, structured: BaseModel | dict | None = None)`.
- When the agent requests structured output and no scripted turn matches, synthesize a valid instance of the requested
  Pydantic model (`porchlight.testing.synth.example_instance(model_cls)`), so unscripted flows still complete.
- Must emit correct `StreamEvent`s (messageStart, contentBlockStart/Delta/Stop, messageStop with stopReason "tool_use" or "end_turn", metadata usage).
- `ScenarioModel(name -> responses)` helper to script per-agent behaviour by `agent.name` (read from `invocation_state` or system prompt marker).
`porchlight.models_provider.make_model(settings, tier: "sonnet"|"haiku") -> Model` returns `BedrockModel` or `MockModel`.
