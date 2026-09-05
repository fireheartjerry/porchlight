# Live-deployment findings (2026-09-04, first real run on AWS)

Live stack: CloudFront https://d3epee0qvo95vm.cloudfront.net → Lambda (FastAPI, LWA) → AgentCore Runtime
`porchlight_Porchlight-tKZxVxH9Tf` (us-east-1) → Bedrock (Claude Sonnet 4.6 / Haiku 4.5). Memory
`porchlight_PorchlightMemory-TDZOm8D1Cf`. `.env.deploy` holds the ARNs/URLs.

What worked: health, demo reset, a routine request went intake → matcher → outreach on real models with
plain-English Quiet Log lines; `/api/events/poll` and SSE through CloudFront both work.

## Status

**All eight are fixed, deployed and verified live** (2026-09-05, CloudFront
`https://d3epee0qvo95vm.cloudfront.net`). Each item below carries a one-line note. Two defects
that only the live stack could have shown up are recorded as I and J at the bottom.

## Defects to fix (in priority order)

A. **Safety must beat the not-a-request short-circuit.** On real Claude, the child-home-alone message came
   back from intake with `is_request=false`, `safety_flags=[...]`, `needs_human=true`, and the graph took the
   `intake → steward` short-circuit and closed it as *cancelled* with no Decision Card. Rule: any safety flag,
   `urgency == emergency`, `needs_human`, or money flag routes to the policy card path regardless of
   `is_request`. Tighten the intake prompt: an emergency *is* a request for the coordinator's attention;
   `is_request=false` is only for thank-yous, chatter, updates, spam. Add a regression test with a scripted
   IntakeResult exactly like the real one.

   **Done.** `needs_coordinator()` in `graph.py`, `IntakeResult.needs_coordinator()`, a `review_card` fallback in `PolicyGateHook`, and a tightened intake prompt. Regression suite: `tests/l_test_safety_first.py`. Live: the child-home-alone message returns `interrupted=true` with a red card, `escalated`, and zero messages sent.

B. **Live demo needs simulated volunteer replies.** In `live` mode the channel is `EmailChannel` (dry-run), so
   requests stall at `awaiting_reply`. Add `PORCHLIGHT_CHANNEL = auto|sim|email` (default `auto` = sim in demo
   mode, email in live mode) and set `PORCHLIGHT_CHANNEL=sim` in `agentcore/agentcore.json` envVars and in the
   Lambda env (infra) so the hosted demo shows the full loop with the Haiku-powered volunteer simulator. The
   sim must work against `DynamoStore` (replies persisted in the store, not in-process memory).

   **Done.** `Settings.channel` / `channel_kind` / `simulates_replies`, `attach_simulator` wired into `build_context`, `PORCHLIGHT_CHANNEL=sim` on both halves. Live: the dialysis ride reaches `confirmed` with `vol_maria` assigned, the requester messaged and a reminder scheduled — 30 log events, one HTTP call.

C. **`POST /api/inbox` on Lambda returned `{"status":"new","log_events":0,"summary":""}` after ~39 s while the
   runtime kept processing.** Investigate `AgentCoreOrchestrator._invoke` / response parsing and the Lambda
   logs (`aws lambda get-function-configuration --function-name <fn> --query LoggingConfig` for the log group).
   Likely causes: reading a streamed response wrong, an HTTP read timeout in boto3 (set `read_timeout=900`,
   `retries={"total_max_attempts": 1}` — a retry would re-run the graph!), or the runtime returning before the
   graph finishes. The API must return the real `RunOutcome`.

   **Done.** Root cause was neither: `dispatch` returns an envelope `{action, session_id, ok, outcome}` and `coerce_run_outcome` filtered every key out of it. `unwrap_runtime_result` + `RuntimeInvocationError` (502), plus `read_timeout=900` and `total_max_attempts=1` on the boto3 client. Live: real `RunOutcome`s, 41–56 s through CloudFront.

D. **`POST /api/demo/run_day` uses a FastAPI background task — unreliable on Lambda.** Make "Run a Tuesday"
   client-driven: the UI fetches `/api/demo/samples`, posts each sample to `/api/inbox` sequentially, and shows
   progress itself (keep `demo_progress` events for the local server). Keep the server endpoint for local use.

   **Done.** `web/src/hooks/useDayRun.ts` + `web/src/lib/demoSequence.ts` drive it client-side with a stop button and a failed count; `useEvents` falls back to `GET /api/events/poll` when SSE errors. The server endpoint stays for local dev.

E. **`current_time` tool is deprecated in strands_tools** ("inject the current time as context with
   ContextInjector"). Migrate intake/steward to the Strands `ContextInjector` plugin pattern (read
   `.venv/lib/python3.12/site-packages/strands/plugins/` for the current API) — judges will see the latest SDK
   idioms.

   **Done.** `clock_injector()` in `agents/base.py` builds a Strands `ContextInjector` (`trigger="everyTurn"`) carrying the UTC instant, the group's local time and the quiet-hours state; attached to every agent. `current_time` is gone from `intake.py`, README and DESIGN.

F. **OTEL: "Failed to export span batch code: 400, reason: Bad Request" in runtime logs.** The AgentCore CLI
   runs the entrypoint under `opentelemetry-instrument` (ADOT) and our `setup_telemetry` adds another OTLP
   exporter. When `AGENT_OBSERVABILITY_ENABLED`/ADOT env is present, do not add our own exporter; verify
   traces appear in CloudWatch (GenAI Observability) after redeploy.

   **Done, and the stated cause was wrong.** The deployed build was already reusing the ADOT provider — the 400s came from the distro's own exporter while Transaction Search was still switching on (the account's indexing rule changed 40 s earlier). `adot_instrumented()` hardens the guard anyway. Live: zero `Failed to export` and zero `ERROR` lines in an hour of invocations; twelve X-Ray traces, one with 556 spans.

G. **Sweep on AWS** — after B/C, invoke `{"action":"sweep"}` via `agentcore invoke` and confirm reminders /
   escalation work against DynamoDB; confirm the EventBridge schedule targets the right handler.

   **Done.** EventBridge Scheduler `rate(1 hour)` → `{"action":"sweep"}` and `cron(0 6 * * ? *)` → `{"action":"brief"}`, both targeting `api.scheduled.handler` on the sweep Lambda. Verified three ways: `POST /api/sweep` (200), a direct Lambda invoke (`ok:true`, 3.1 s), and `agentcore invoke '{"action":"sweep"}'`. `SweepOutcome` now actually fills `escalated`/`timed_out` — it was reporting empty lists.

H. Cost: a routine request used ~39k tokens (~$0.15). Fine for the demo; note in docs/DEPLOY.md.

   **Done.** Noted in `docs/DEPLOY.md` § 6 with the levers. Measured again on this stack: 14.5k tokens for the smoke run's three agents, ~39k for a full confirmed loop.

---

## Found during the live verification (both fixed in the same pass)

I. **A red "Possible emergency" card about an electric bill.** The money sample came back from
   Bedrock with `money_involved=true` *and* `safety_flags=["utility cutoff threat", "financial
   hardship"]` — the intake prompt tells the model to over-flag rather than under-flag, and it
   obliged — and `card_for` ranked safety above everything, so the coordinator was told to tell a
   neighbour who is $180 short to *dial emergency services*. Fixed at both ends: the prompt now
   says hardship is not a safety flag, and `PolicyFlag.source` distinguishes a flag a rule matched
   from one intake wrote, with an uncorroborated safety flag ranking below money/vetting/concern
   and riding along inside the winning card. `safety_card` also has a second, quieter shape for an
   uncorroborated flag. `tests/n_test_flag_provenance.py`. Live after the fix: a money card, and
   approving it resumes the run.

J. **Quiet hours held the hosted demo shut for eleven hours a day.** With the group at
   `America/Toronto`, a visitor between 21:00 and 08:00 local saw outreach *scheduled* rather than
   sent and the request stuck at `awaiting_reply` until the next sweep. Nobody is asleep on the
   other end of a simulator, so the hosted stack sets `PORCHLIGHT_QUIET_HOURS=[0,0]` (an empty
   window) on both halves; the default and the local demo keep 21:00–08:00. The values prompt now
   says so honestly instead of rendering "quiet hours are 0:00 to 0:00".

## Still open

- **CloudFront `readTimeout` was 60 s and a real run takes 40–56 s.** Raised to 120 s, the account
  ceiling for quota `L-AECE9FA7` (the 60 s figure was wrong — the default quota is 120). A run
  slower than that still 504s at the edge while the Lambda and runtime finish; the client-driven
  Tuesday counts it as failed and steps over it.
- **The sweep's escalation path is not proven against live DynamoDB.** It returns `ok` and touches
  the table, but with quiet hours off and the simulator replying immediately there has been no
  request left open long enough for the sweep to escalate one. Covered by unit tests only.
