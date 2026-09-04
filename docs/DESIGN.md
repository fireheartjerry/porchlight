# Porchlight — Design Spec

> **Tagline:** *Runs the coordination. Lights up only when you're needed.*
>
> Track: **Good Neighbor Agents** (Agents for Humans Hackathon, AWS + Devpost, deadline 2026-09-14 17:00 PDT)

## 1. The problem

Every mutual-aid group, food pantry, church volunteer team, and neighborhood association runs on one
exhausted coordinator. Requests arrive as texts, emails, form submissions, voicemails, and paper slips.
The coordinator reads each one, figures out who could help, texts three people, waits, texts two more,
confirms with the requester, sends reminders, handles the no-show, and then forgets to write any of it
down. Twenty to sixty times a week. Coordinator burnout is the #1 reason these groups fold.

Almost none of that work needs a human. What *does* need a human is rare and important: a request that
hints at danger, a request for money, a volunteer who reports something off, an urgent need nobody can
cover. Today those get buried in the same pile as "can someone grab milk for Mrs. Chen."

## 2. The product

**Porchlight** is an autonomous dispatcher for small volunteer groups. It takes every inbound request,
turns it into a structured job, picks the right volunteer, does the outreach and follow-up, confirms
with the requester, and writes the outcome to long-term memory. It makes the safe calls on its own.

When a real decision comes up, the porch light turns on: the coordinator gets a **Decision Card** with
the context, the agent's recommendation, and one-tap options. Everything else appears in a **Quiet Log**
they can skim whenever they like.

Primary user: **the coordinator** (Dana, runs "Maple Street Mutual Aid": ~40 volunteers, 25–60 requests/wk).
Secondary: volunteers (get clear, personal messages; never spammed) and requesters (get confirmations).

## 3. What "only surface when there's a real decision" means (the policy)

Porchlight's autonomy boundary is explicit, testable code, not vibes. The policy engine is a Strands
**InterventionHandler** (`PorchlightPolicy`) plus deterministic rules in `porchlight/policy.py`.

| Situation | Action |
|---|---|
| Medical emergency / danger language (child alone, threats, self-harm, abuse) | `Deny` autonomous outreach, tell requester to call emergency services in the reply draft, raise **Decision Card (red)** immediately |
| Any request involving money, gift cards, bills, cash, purchases above group's petty-cash limit | **Decision Card** before any commitment |
| Requester is new *and* asks for in-home help | **Decision Card** (vetting) |
| Volunteer reply contains a concern/complaint about a requester or safety | **Decision Card** |
| No accepted volunteer after `max_candidates` asks or within `escalate_hours_before_window` | **Decision Card** with options (widen pool, reschedule, coordinator takes it, decline) |
| Message would go out during quiet hours (21:00–08:00 local) | `Guide`: schedule for morning instead |
| Outbound message contains requester's phone/address to an unvetted volunteer | `Transform`: redact; share only after acceptance |
| Everything else (routine ride/groceries/meal/etc. with a good match) | fully autonomous |

Decision Cards are literally **Strands interrupts**. The graph pauses, the interrupt is persisted via the
session manager, the coordinator's tap becomes the `interruptResponse`, and the graph resumes exactly
where it stopped, possibly hours later in a different process.

## 4. Agents (Strands)

All agents are Strands `Agent`s with Pydantic `structured_output_model`s. Orchestrated by a Strands
`Graph` (`GraphBuilder`) with conditional edges and a bounded cycle for outreach retries.

```
                    ┌──────────┐
   raw message ───▶ │  intake  │ ── AidRequest (structured) ──┐
   (text/email/     └──────────┘                             │
    form/photo)          │ safety/money flag                 ▼
                         ▼                          ┌────────────┐
                 [Decision Card]                    │  matcher   │ ── MatchPlan (ranked candidates, confidence)
                                                    └────────────┘
                                                          │ confidence ≥ τ            │ confidence < τ or no candidates
                                                          ▼                            ▼
                                                    ┌────────────┐              [Decision Card]
                              ┌────── decline ───── │  outreach  │ ◀── volunteer reply
                              │   (next candidate)  └────────────┘
                              │                           │ accepted
                              └──▶ (cycle, max N) ◀──     ▼
                                                    ┌────────────┐
                                                    │  steward   │ ── confirms requester, schedules reminder,
                                                    └────────────┘    post-event check-in, writes memory
```

| Agent | Model | Job | Tools |
|---|---|---|---|
| `intake` | Claude Haiku 4.5 (fast, cheap) | Parse any inbound channel into `AidRequest`; detect urgency, category, constraints, safety & money flags; read photos of paper forms | `current_time`, `image_reader`, `lookup_requester_history` |
| `matcher` | Claude Sonnet 4.6 | Produce `MatchPlan`: top-3 volunteers with rationale + confidence, honoring fairness (spread load), zone, skills, availability, memory notes | `find_candidates`, `volunteer_load`, `recall_memory` |
| `outreach` | Claude Sonnet 4.6 | Write personal messages; interpret replies (`VolunteerReply`: accept / decline / counter / concern); advance to next candidate | `send_message`, `read_replies`, `assign_volunteer`, `schedule_message` |
| `steward` | Claude Haiku 4.5 | Confirm with requester, set reminders, post-event check-in, distill outcome into memory notes, update volunteer stats | `send_message`, `schedule_message`, `remember`, `close_request` |
| `brief` | Claude Sonnet 4.6 | Daily coordinator digest: what was handled, what's pending, patterns (e.g. "rides to dialysis up 3x") | `query_requests`, `query_log` |
| `volunteer_sim` (demo only) | Claude Haiku 4.5 | Role-plays volunteers with personalities (busy, flaky, eager, cautious) so the demo shows real negotiation without real SMS | — |

Sub-agent pattern: `outreach` uses `interpret_reply` as an **agent-as-tool** (a tiny Strands agent with
`structured_output_model=VolunteerReply`) so reply parsing is isolated and testable.

### Strands features used (be explicit in README; judges score depth)
- `Agent` + `@tool` (with `context=True` for `ToolContext.interrupt` and `invocation_state`)
- `structured_output_model` on every agent
- `GraphBuilder` with conditional edges, `set_max_node_executions`, `reset_on_revisit`, entry point
- **Interventions** (`InterventionHandler` returning `Confirm` / `Deny` / `Guide` / `Transform` / `Proceed`)
- **Interrupts** persisted across processes via session manager; resumed with `interruptResponse`
- **Hooks**: `BeforeToolCallEvent` / `AfterToolCallEvent` → audit trail (Quiet Log); `MessageAddedEvent` → live trace; `AfterModelCallEvent` → cost meter
- `SlidingWindowConversationManager` on long-lived agents
- Session managers: `FileSessionManager` (local) / `S3SessionManager` (AWS) / `AgentCoreMemorySessionManager` (AgentCore Memory)
- **MemoryManager** with a custom `MemoryStore` (SQLite locally, AgentCore Memory on AWS) for long-term volunteer/requester facts
- `strands_tools`: `current_time`, `image_reader`
- **MCP**: Porchlight's data tools are also exposed as an MCP server (`porchlight/mcp_server.py`) and consumed with `MCPClient` when `PORCHLIGHT_TOOLS=mcp` (locally via stdio, on AWS via AgentCore Gateway URL)
- `StrandsTelemetry` OTLP → AgentCore Observability (CloudWatch)
- Multimodal intake (image content blocks) for photographed paper request slips
- Deployed on **Amazon Bedrock AgentCore Runtime** (CodeZip) via the AgentCore CLI

## 5. Domain model (`porchlight/models.py`, Pydantic v2)

- `Volunteer`: id, name, phone/email (redactable), zones[], skills[] (drive, lift, cook, tech, translate:{lang}, childcare-cleared, companionship), availability (weekday windows), max_per_week, vetted: bool, notes (memory), stats (accepted, declined, completed, no_show, last_active)
- `Requester`: id, name, contact, zone, address (redactable), first_seen, notes, history_count
- `AidRequest`: id, source (form|email|sms|voicemail|paper|api), raw_text, requester_id, category, summary, window_start/end, flexible: bool, location_zone, constraints[], urgency (low|normal|high|emergency), money_involved: bool, safety_flags[], first_time_requester: bool, status (new|triaging|matching|awaiting_reply|confirmed|in_progress|completed|escalated|declined|cancelled), assigned_volunteer_id, attempts[] (volunteer_id, sent_at, outcome), created_at, updated_at
- `MatchPlan`: request_id, candidates[] ({volunteer_id, score 0–1, rationale}), confidence 0–1, notes
- `VolunteerReply`: intent (accept|decline|counter|concern|unclear), proposed_time?, concern_text?, confidence
- `Decision` (a card): id, request_id, kind (safety|money|vetting|unmatched|concern|policy), title, context (markdown), recommendation, options[] ({id, label, description}), interrupt_id, session_id, node, status (open|resolved), resolved_option, resolved_note, created_at, resolved_at
- `LogEvent` (Quiet Log): id, ts, request_id?, agent, kind (tool_call|message_sent|decision|memory|policy|model), summary, detail (json), autonomous: bool
- `OutboundMessage`: id, to (volunteer|requester), channel, body, scheduled_for?, sent_at?, status
- `GroupSettings`: name, timezone, quiet_hours, petty_cash_limit, max_candidates, escalate_hours_before_window, confidence_threshold, zones[]

## 6. Storage & adapters (swap by env)

`porchlight/store/`: `Store` protocol with `SqliteStore` (local + tests) and `DynamoStore` (AWS, single-table).
`porchlight/channels/`: `Channel` protocol with `SimChannel` (demo; replies produced by `volunteer_sim`
agent or scripted fixtures), `EmailChannel` (SES), `SmsChannel` (SNS/Pinpoint; optional).
`porchlight/memory/`: `SqliteMemoryStore` (implements Strands `MemoryStore`), `AgentCoreMemoryStore`.

Env: `PORCHLIGHT_MODE=demo|live`, `PORCHLIGHT_STORE=sqlite|dynamo`, `PORCHLIGHT_MODEL_PROVIDER=bedrock|mock`,
`PORCHLIGHT_TOOLS=local|mcp`, `AWS_REGION`, `PORCHLIGHT_MEMORY_ID`, `PORCHLIGHT_SESSION_BUCKET`.

## 7. Runtime topology on AWS

```
Coordinator ──▶ CloudFront + S3 (React UI "The Porch")
                      │  HTTPS (JSON)
                      ▼
            API: FastAPI on Lambda (Function URL) ── DynamoDB (single table: requests, volunteers, decisions, log, messages)
                      │ invoke_agent_runtime(session_id=request_id)          ▲
                      ▼                                                       │
            Amazon Bedrock AgentCore Runtime (CodeZip) ── Strands Graph ───────┘
                      │            │                │
                      │            │                └── AgentCore Memory (long-term: volunteer prefs, requester facts)
                      │            └── AgentCore Observability (OTEL traces → CloudWatch)
                      └── Amazon Bedrock (Claude Sonnet 4.6 / Haiku 4.5)
EventBridge Scheduler ──▶ Lambda "sweep" (hourly: due reminders, stale outreach → escalate, nightly brief) ──▶ AgentCore Runtime
Inbound: SES receipt → S3 → Lambda "ingest" → API (email); form webhook → API; demo inbox in UI
```

Infra as code: `infra/` CDK (TypeScript) for the app stack; `agentcore/` project (AgentCore CLI, CDK
under the hood) for runtime + memory. One `make deploy`.

## 8. Web UI "The Porch" (`web/`, React + Vite + Tailwind, no backend framework)

Design language: warm night-time porch. Deep navy background, amber light. A literal porch-light glyph
in the header that is dim when nothing needs the coordinator and glows when Decision Cards are open.

Screens (single page, left nav):
1. **Porch** (home): status line ("Quiet. 14 handled today · 2 need you."), Decision Cards column (each
   with context, recommendation, option buttons, optional note), Quiet Log timeline (autonomous actions
   with plain-English rationale, expandable detail).
2. **Requests**: board New → Matching → Awaiting reply → Confirmed → Done, with attempts timeline.
3. **Volunteers**: roster with load bars, skills, zones, memory notes ("prefers mornings, great with seniors").
4. **Inbox (demo)**: paste or pick a sample message / upload a photo of a paper slip / "Run a Tuesday"
   button that streams 20 requests through the system with the volunteer simulator replying.
5. **Trace** drawer: live SSE stream of graph node starts, tool calls, model calls (transparency; judges love it).

## 9. Demo script (≤5 min video, YouTube)

0:00 problem (coordinator's phone, 40 unread) → 0:35 what Porchlight is → 0:55 paste a request; watch
intake→matcher→outreach happen in the trace; volunteer sim declines, next accepts; requester confirmed;
Quiet Log shows it never needed Dana → 2:10 paste "my neighbor's kid is home alone and the stove is on":
porch light turns on; Decision Card explains, recommends, Dana taps; the graph resumes → 3:00 "Run a
Tuesday": 20 requests, 17 handled quietly, 3 cards → 3:40 memory: the next week the matcher recalls
"Mr. Okafor prefers Maria" → 4:00 architecture slide: Strands Graph, interventions, AgentCore Runtime +
Memory + Observability → 4:40 impact & close.

## 10. Repo layout

```
porchlight/                 # python package (agents, policy, graph, tools, models, store, channels, memory)
  agents/  graph.py  policy.py  tools/  models.py  store/  channels/  memory/  runtime.py (AgentCore entrypoint)
  mcp_server.py  sim/ (volunteer simulator + fixtures)  config.py  telemetry.py
api/                        # FastAPI app (local: uvicorn; AWS: Lambda via Mangum)
web/                        # React UI
infra/                      # CDK app stack
agentcore/                  # AgentCore CLI project config
tests/                      # pytest; uses MockModel provider, no AWS needed
docs/                       # DESIGN.md, ARCHITECTURE.md, architecture.png, research/
scripts/                    # seed, run_day, make_video helpers
Makefile  pyproject.toml  README.md  LICENSE (MIT)
```

## 11. Quality bar

- `make test` passes with no AWS credentials (mock model provider implementing `strands.models.Model`).
- `make demo` runs the full loop locally with SQLite + SimChannel + Bedrock (or `--mock`).
- Every autonomous side effect is logged with a rationale; every Decision Card is a persisted interrupt.
- README: problem, what it does, Strands feature map, architecture diagram, setup in <10 commands, AWS deploy, cost notes.
