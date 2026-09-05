# Live-deployment findings (2026-09-04, first real run on AWS)

Live stack: CloudFront https://d3epee0qvo95vm.cloudfront.net → Lambda (FastAPI, LWA) → AgentCore Runtime
`porchlight_Porchlight-tKZxVxH9Tf` (us-east-1) → Bedrock (Claude Sonnet 4.6 / Haiku 4.5). Memory
`porchlight_PorchlightMemory-TDZOm8D1Cf`. `.env.deploy` holds the ARNs/URLs.

What worked: health, demo reset, a routine request went intake → matcher → outreach on real models with
plain-English Quiet Log lines; `/api/events/poll` and SSE through CloudFront both work.

## Defects to fix (in priority order)

A. **Safety must beat the not-a-request short-circuit.** On real Claude, the child-home-alone message came
   back from intake with `is_request=false`, `safety_flags=[...]`, `needs_human=true`, and the graph took the
   `intake → steward` short-circuit and closed it as *cancelled* with no Decision Card. Rule: any safety flag,
   `urgency == emergency`, `needs_human`, or money flag routes to the policy card path regardless of
   `is_request`. Tighten the intake prompt: an emergency *is* a request for the coordinator's attention;
   `is_request=false` is only for thank-yous, chatter, updates, spam. Add a regression test with a scripted
   IntakeResult exactly like the real one.

B. **Live demo needs simulated volunteer replies.** In `live` mode the channel is `EmailChannel` (dry-run), so
   requests stall at `awaiting_reply`. Add `PORCHLIGHT_CHANNEL = auto|sim|email` (default `auto` = sim in demo
   mode, email in live mode) and set `PORCHLIGHT_CHANNEL=sim` in `agentcore/agentcore.json` envVars and in the
   Lambda env (infra) so the hosted demo shows the full loop with the Haiku-powered volunteer simulator. The
   sim must work against `DynamoStore` (replies persisted in the store, not in-process memory).

C. **`POST /api/inbox` on Lambda returned `{"status":"new","log_events":0,"summary":""}` after ~39 s while the
   runtime kept processing.** Investigate `AgentCoreOrchestrator._invoke` / response parsing and the Lambda
   logs (`aws lambda get-function-configuration --function-name <fn> --query LoggingConfig` for the log group).
   Likely causes: reading a streamed response wrong, an HTTP read timeout in boto3 (set `read_timeout=900`,
   `retries={"total_max_attempts": 1}` — a retry would re-run the graph!), or the runtime returning before the
   graph finishes. The API must return the real `RunOutcome`.

D. **`POST /api/demo/run_day` uses a FastAPI background task — unreliable on Lambda.** Make "Run a Tuesday"
   client-driven: the UI fetches `/api/demo/samples`, posts each sample to `/api/inbox` sequentially, and shows
   progress itself (keep `demo_progress` events for the local server). Keep the server endpoint for local use.

E. **`current_time` tool is deprecated in strands_tools** ("inject the current time as context with
   ContextInjector"). Migrate intake/steward to the Strands `ContextInjector` plugin pattern (read
   `.venv/lib/python3.12/site-packages/strands/plugins/` for the current API) — judges will see the latest SDK
   idioms.

F. **OTEL: "Failed to export span batch code: 400, reason: Bad Request" in runtime logs.** The AgentCore CLI
   runs the entrypoint under `opentelemetry-instrument` (ADOT) and our `setup_telemetry` adds another OTLP
   exporter. When `AGENT_OBSERVABILITY_ENABLED`/ADOT env is present, do not add our own exporter; verify
   traces appear in CloudWatch (GenAI Observability) after redeploy.

G. **Sweep on AWS** — after B/C, invoke `{"action":"sweep"}` via `agentcore invoke` and confirm reminders /
   escalation work against DynamoDB; confirm the EventBridge schedule targets the right handler.

H. Cost: a routine request used ~39k tokens (~$0.15). Fine for the demo; note in docs/DEPLOY.md.
