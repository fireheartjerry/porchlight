# Porchlight

**Runs the coordination. Lights up only when you're needed.**

An autonomous dispatcher for small volunteer groups, built on [Strands Agents](https://strandsagents.com)
and Amazon Bedrock AgentCore. Built for the AWS *Agents for Humans* hackathon — **Good Neighbor** track.

![Architecture](docs/architecture.png)

---

## The pitch

Every mutual-aid group, food pantry, church volunteer team, and tenants' association runs on one
exhausted human. Requests arrive as texts, emails, form submissions, voicemails, and photographs of
paper slips. The coordinator reads each one, works out who could help, texts three people, waits,
texts two more, confirms with the neighbour, sends a reminder, handles the no-show, and then forgets
to write any of it down — twenty to sixty times a week. Coordinator burnout is the single most common
reason these groups fold.

Almost none of that work needs a person. What *does* need a person is rare and important: a message
that hints at danger, a request for money, a volunteer who reports that something felt off, an urgent
need nobody can cover. Today those get buried in the same pile as *"can someone grab milk for Mrs.
Chen."* The problem isn't that the coordinator lacks tools. It's that everything arrives at the same
priority, and only a human sorting the pile can tell the difference.

Porchlight takes every inbound request, turns it into a structured job, ranks the roster on skills,
zone, availability, fairness and memory, does the outreach and the follow-up, confirms with the
neighbour, and writes the outcome to long-term memory — on its own. When a real judgement call comes
up, the porch light turns on: the coordinator gets a **Decision Card** with the context, the agent's
recommendation, and one-tap options. Everything else lands in a **Quiet Log** they can skim whenever
they like. The autonomy boundary is not a prompt asking the model to be careful; it is a
deterministic policy engine plus a Strands `InterventionHandler`, and every card is a real Strands
interrupt that persists across processes and resumes hours later exactly where it paused.

---

## How it works

Four Strands agents in a `Graph`, with a bounded retry cycle for outreach:

```
raw message ──▶ intake ──▶ matcher ──▶ outreach ──▶ steward
   (sms/email/     │           ▲           │
    form/photo)    │           └─ decline ─┘   (bounded by max_candidates)
                   │
              [Decision Card]  ← a Strands interrupt, persisted by the session manager
```

| Agent | Model | Job |
|---|---|---|
| `intake` | Haiku 4.5 | Any inbound channel (including a photo of a paper slip) → structured `AidRequest` |
| `matcher` | Sonnet 4.6 | Ranked, fairness-aware `MatchPlan` with an honest confidence |
| `outreach` | Sonnet 4.6 | Writes personal messages, reads replies via an `interpret_reply` sub-agent, advances to the next candidate |
| `steward` | Haiku 4.5 | Confirms the neighbour, schedules reminders, distils the outcome into memory |
| `brief` | Sonnet 4.6 | The nightly digest the coordinator actually reads |
| `volunteer_sim` | Haiku 4.5 | Demo only: role-plays volunteers so the demo shows real negotiation without real SMS |

### The policy — what "only surface a real decision" actually means

Deterministic rules in [`porchlight/policy.py`](porchlight/policy.py), enforced twice: once at the
graph gate before any outreach happens, and again at the tool boundary as defence in depth.

| Situation | Action | Where |
|---|---|---|
| Danger language — child alone, chest pain, threats, self-harm, abuse | **Deny** outreach, red Decision Card, tell the requester to call emergency services | `DANGER_PATTERNS`, `safety_card` |
| Money: gift cards, bills, cash, anything over the group's petty-cash limit | **Confirm** — a card before any commitment | `MONEY_PATTERNS`, `extract_amount`, `money_card` |
| First-time requester asking for help *inside* their home | **Confirm** — a vetting card | `IN_HOME_PATTERNS`, `vetting_card` |
| A volunteer reports a concern about a requester or a visit | **Confirm** — a concern card | `CONCERN_PATTERNS`, `concern_card` |
| Nobody accepted after `max_candidates` asks, or the window is closing | Card with options: widen pool, reschedule, I'll take it, decline | `unmatched_card`, `run_sweep` |
| Matcher confidence below `confidence_threshold` | Card instead of a guess | `PolicyGateHook` |
| A message would go out during quiet hours (21:00–08:00 local) | **Guide** — schedule it for the morning instead | `is_quiet_hours`, `next_send_time` |
| An outbound message carries the neighbour's phone or address to a volunteer who has not accepted | **Transform** — redact; share only after acceptance | `redact_pii` |
| Everything else — a routine ride, groceries, a meal, with a good match | Fully autonomous, logged with a rationale | — |

A card is asked **once** per request per kind: the graph gate raises it, the coordinator answers, and
`already_approved()` stops the tool-level policy asking the same question again.

---

## Strands feature map

Judges score depth, so here is exactly where each feature lives.

- **`Agent` + `structured_output_model` on every agent** — [`porchlight/agents/base.py`](porchlight/agents/base.py), [`porchlight/agents/outputs.py`](porchlight/agents/outputs.py)
- **`@tool(context=True)`** — 14 tools reading `AppContext` from `invocation_state` — [`porchlight/tools/`](porchlight/tools/)
- **Agent-as-tool sub-agent** — `interpret_reply` is a one-shot agent exposed as a tool — [`porchlight/agents/outreach.py`](porchlight/agents/outreach.py)
- **`GraphBuilder`** with conditional edges, `set_max_node_executions`, `reset_on_revisit`, a bounded outreach cycle — [`porchlight/graph.py`](porchlight/graph.py)
- **Interventions** — `InterventionHandler` returning `Deny` / `Confirm` / `Guide` / `Transform` / `Proceed` — `PorchlightPolicy` in [`porchlight/policy.py`](porchlight/policy.py)
- **Interrupts as Decision Cards** — raised with `event.interrupt(...)`, persisted by the session manager, resumed with `interruptResponse` — `PolicyGateHook`, `resume_decision` in [`porchlight/graph.py`](porchlight/graph.py)
- **Hooks** — `BeforeToolCallEvent` / `AfterToolCallEvent` → the Quiet Log audit trail; `MessageAddedEvent` / `AfterModelCallEvent` / `BeforeNodeCallEvent` → the live trace and cost meter — `AuditHook`, `TraceHook` in [`porchlight/policy.py`](porchlight/policy.py)
- **`SlidingWindowConversationManager`** — [`porchlight/agents/base.py`](porchlight/agents/base.py)
- **Session managers** — `FileSessionManager` locally, `S3SessionManager` when `PORCHLIGHT_SESSION_BUCKET` is set — `make_session_manager` in [`porchlight/graph.py`](porchlight/graph.py)
- **`MemoryManager` + a custom `MemoryStore`** — SQLite FTS5/BM25 locally, AgentCore Memory on AWS — [`porchlight/memory/`](porchlight/memory/)
- **MCP** — the same data tools served over stdio and consumed with `MCPClient` when `PORCHLIGHT_TOOLS=mcp` — [`porchlight/mcp_server.py`](porchlight/mcp_server.py), [`porchlight/tools/mcp_bridge.py`](porchlight/tools/mcp_bridge.py)
- **`strands_tools`** — `current_time` on intake — [`porchlight/agents/intake.py`](porchlight/agents/intake.py)
- **Multimodal intake** — image content blocks for photographed paper slips — `build_intake_task` in [`porchlight/agents/intake.py`](porchlight/agents/intake.py)
- **`StrandsTelemetry` OTLP** → AgentCore Observability — [`porchlight/telemetry.py`](porchlight/telemetry.py)
- **AgentCore Runtime** — `BedrockAgentCoreApp` entrypoint with SSE streaming — [`porchlight/runtime.py`](porchlight/runtime.py)
- **A `strands.models.Model` implementation** — `MockModel` / `PorchlightScenarioModel`, so the whole system runs with no AWS account — [`porchlight/testing/mock_model.py`](porchlight/testing/mock_model.py), [`porchlight/sim/mock_scenarios.py`](porchlight/sim/mock_scenarios.py)

---

## Quickstart

No AWS account or credentials are needed for any of this.

```bash
git clone <this repo> && cd porchlight
python3.12 -m venv .venv && source .venv/bin/activate
make install          # uv pip install -e ".[dev]"

make test             # 523 tests, no network
make demo-mock        # six neighbourhood requests through the real Strands graph
make api              # FastAPI on http://localhost:8000
```

`make demo-mock` narrates the whole day — every node, tool call, message, and policy decision —
then prints what was handled quietly and what needs the coordinator:

```
== SUMMARY ==========================================================================
  request           sample                      status          outcome
  ------------------------------------------------------------------------------
  req_9c72e440ff    Routine ride to dialysis    confirmed       handled quietly
  req_bc7148c395    Grocery run                 confirmed       handled quietly
  req_382f572fab    Hot meal for new parents    confirmed       handled quietly
  req_29a84b2f99    Child home alone, stove on  escalated       needs you — Possible emergency
  req_99416d559c    Prescription pickup         confirmed       handled quietly
  req_6ba8f3fa0a    Snow shovelling             confirmed       handled quietly

  5 handled quietly · 1 needed the coordinator · 544 trace events
```

Other useful entry points:

```bash
python scripts/run_day.py --reset                  # all 24 sample messages
python scripts/run_day.py --sample-id sm_gift_card # one specific message
python scripts/seed.py                             # load the Maple Street fixtures
make lint                                          # ruff check .
```

With Bedrock credentials configured, drop `PORCHLIGHT_MODEL_PROVIDER=mock` and the same commands run
against Claude Sonnet 4.6 and Haiku 4.5.

---

## Environment

Every variable is optional; copy [`.env.example`](.env.example) to `.env` to change any of them.

| Variable | Default | What it does |
|---|---|---|
| `PORCHLIGHT_MODE` | `demo` | `demo` = SQLite + simulated channel; `live` = configured store + email |
| `PORCHLIGHT_MODEL_PROVIDER` | `bedrock` | `mock` runs the whole system with no AWS |
| `PORCHLIGHT_STORE` | `sqlite` | `sqlite` or `dynamo` (single table) |
| `PORCHLIGHT_TOOLS` | `local` | `mcp` consumes the same tools over MCP instead |
| `PORCHLIGHT_SQLITE_PATH` | `data/local/porchlight.db` | Local database (`:memory:` allowed) |
| `PORCHLIGHT_SESSION_DIR` | `data/sessions` | Where graph sessions and persisted interrupts live |
| `PORCHLIGHT_SESSION_BUCKET` | — | Set to use `S3SessionManager` instead of files |
| `PORCHLIGHT_MEMORY_ID` | — | AgentCore Memory id; unset uses the SQLite memory store |
| `PORCHLIGHT_DYNAMO_TABLE` | `porchlight` | Single-table name when `store=dynamo` |
| `PORCHLIGHT_AWS_REGION` | `us-west-2` | Falls back to `AWS_REGION` / `AWS_DEFAULT_REGION` |
| `PORCHLIGHT_AGENT_RUNTIME_ARN` | — | When set, the API calls AgentCore Runtime instead of running in-process |
| `PORCHLIGHT_MODEL_SONNET` | `global.anthropic.claude-sonnet-4-6` | Judgement-tier model |
| `PORCHLIGHT_MODEL_HAIKU` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` | Fast-tier model |
| `PORCHLIGHT_GROUP_NAME` | `Maple Street Mutual Aid` | Whose porch this is |
| `PORCHLIGHT_TIMEZONE` | `America/Toronto` | Local time for windows and quiet hours |
| `PORCHLIGHT_QUIET_HOURS` | `[21, 8]` | Nothing goes out between these local hours |
| `PORCHLIGHT_PETTY_CASH_LIMIT` | `40.0` | Above this, money needs a Decision Card |
| `PORCHLIGHT_MAX_CANDIDATES` | `3` | Volunteers asked before escalating |
| `PORCHLIGHT_ESCALATE_HOURS_BEFORE_WINDOW` | `6` | Escalate this close to the window with nobody booked |
| `PORCHLIGHT_CONFIDENCE_THRESHOLD` | `0.55` | Below this the matcher raises a card instead of guessing |

---

## Repo layout

```
porchlight/
  agents/          intake, matcher, outreach (+ interpret_reply), steward, brief, prompts, outputs
  channels/        Channel protocol; SimChannel (demo) and EmailChannel (SES)
  memory/          SqliteMemoryStore (FTS5 + BM25) and AgentCoreMemoryStore
  sim/             fixtures (14 volunteers, 8 neighbours, 24 sample messages), volunteer
                   simulator, and mock_scenarios.py (the offline demo's model)
  store/           Store protocol; SqliteStore and DynamoStore
  testing/         MockModel / ScenarioModel and the Pydantic example synthesizer
  tools/           the 14 @tool functions, grouped per agent, plus the MCP bridge
  graph.py         the Strands Graph, run_request / resume_decision / run_sweep / run_brief
  policy.py        deterministic rules, decision cards, PorchlightPolicy, AuditHook, TraceHook
  matching.py      the six-component volunteer scoring model
  orchestrator.py  LocalOrchestrator (in-process) and AgentCoreOrchestrator (invoke_agent_runtime)
  runtime.py       the AgentCore Runtime entrypoint
  mcp_server.py    the read-only tools, served over MCP
api/               FastAPI app; api/lambda_handler.py wraps it with Mangum
web/               "The Porch" — React + Vite + Tailwind
scripts/           seed.py, run_day.py
docs/              DESIGN.md, CONTRACTS.md, UI.md, architecture.png, research/
tests/             pytest; foundation_*, a_*, b_*, c_*, i_* by area
```

---

## Testing

```bash
make test                       # everything
pytest -q tests/i_test_integration.py   # the end-to-end graph tests
```

523 tests, all offline. They cover the domain model and store, the six-component matcher, all 14
tools (called directly *and* through a real `strands.Agent`), the channels, the memory stores, a
real MCP round trip over stdio, every policy rule, the agents, the graph's four scenarios
(routine / safety / decline-decline-accept / resume-in-a-new-process), the runtime, the API, and an
end-to-end pass of every one of the 24 sample messages through the real Strands graph.

The offline demo is driven by `PorchlightScenarioModel`, a `strands.models.Model` that plays each
agent's part from live state rather than replaying a canned script — it ranks the real roster, texts
real volunteers through `SimChannel`, and reads their replies — so the mock run exercises the same
tools, hooks, and interventions as a Bedrock run.

---

## License

MIT — see [LICENSE](LICENSE).
