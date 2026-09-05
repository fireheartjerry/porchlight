# Deploying Porchlight

Porchlight runs on AWS as two halves, deployed by two different tools, meeting through four
shared names.

| What | Who creates it | How the other half finds it |
|---|---|---|
| AgentCore Runtime | `agentcore/` (AgentCore CLI → CDK) | SSM `/porchlight/runtime_arn` → env `PORCHLIGHT_AGENT_RUNTIME_ARN` |
| AgentCore Memory | `agentcore/` | SSM `/porchlight/memory_id` → env `PORCHLIGHT_MEMORY_ID` |
| DynamoDB table `porchlight` | `infra/` (CDK) | env `PORCHLIGHT_DYNAMO_TABLE`, a literal in `agentcore.json` |
| S3 `porchlight-sessions-<account>-<region>` | `infra/` (CDK) | env `PORCHLIGHT_SESSION_BUCKET`, a literal in `agentcore.json` |

Both halves read the same `PORCHLIGHT_*` settings from [`porchlight/config.py`](../porchlight/config.py),
so the runtime and the API agree about where state lives without either one importing the other.
`tests/v_test_deploy_config.py` asserts that agreement on every test run — it parses
`agentcore.json`, `aws-targets.json`, `runtime/iam-policy.json` and the CDK stack's TypeScript and
fails if the four names above stop matching.

**You can deploy only the app stack.** With no runtime ARN, the API runs the Strands graph
in-process (`LocalOrchestrator`) and calls Bedrock directly. That is a complete, demoable system —
the AgentCore half moves the agents out of the request path and gives them their own traces,
sessions and memory.

This guide runs in order: [what you need](#1-what-you-need) → [deploy](#2-deploy) →
[verify](#3-verify) → [when it does not work](#4-when-it-does-not-work) →
[tear down](#5-tear-down) → [costs](#6-costs). Everything after that is reference:
[the app stack](#the-app-stack-infra), [the AgentCore runtime](#the-agentcore-runtime-agentcore).

---

## 1. What you need

### Tools

| Tool | Why | Check |
|---|---|---|
| Python 3.12+ and the repo's venv | Everything | `make install` |
| [`uv`](https://docs.astral.sh/uv/) | Builds the Lambda bundle and the CodeZip, cross-platform, no Docker | `uv --version` |
| Node 20+ and npm | Both CDK apps | `node --version` |
| AWS CLI v2 | Credentials, SSM, spot checks | `aws --version` |
| AgentCore CLI (`@aws/agentcore`) | The runtime half | `agentcore --version` |

The CDK CLI comes from each app's own `node_modules` — `npx cdk` inside `infra/` or
`agentcore/cdk/`. Nothing needs a global install.

### Credentials

```bash
aws login                      # or your usual profile / SSO flow
aws sts get-caller-identity    # must resolve before anything below
```

Nothing in this repo reads AWS at import time, so tests, `cdk synth`, `agentcore validate` and both
package builds all work with no credentials at all. Everything in §2 needs them.

### Bedrock model access

Model access is granted per account, per region, per model. Having credentials is not enough:

```bash
make smoke-bedrock              # scripts/smoke_bedrock.py
```

This is the check worth running first. It calls `bedrock:ListFoundationModels` for the inventory,
then a one-token `Converse` against each configured model id — the only thing that proves *access*
was granted rather than that the model exists — then runs one routine sample (expected: handled
quietly) and one safety sample (expected: a Decision Card) through the real graph on a throwaway
SQLite store. Every failure prints the fix.

```
0  all good        1  a check failed        2  no credentials        3  Porchlight not importable
```

`--skip-graph` runs the cheap half only. `--region`, `--sonnet` and `--haiku` override what it tests.

### Bootstrap CDK, once per account and region

Both CDK apps deploy into the same environment, so one bootstrap covers both:

```bash
cd infra && npx cdk bootstrap aws://<account>/<region>
```

### Point the config at your account

`agentcore.json` is a static JSON file: it cannot interpolate an account id, so two values are
literals that have to match what CDK creates. For any account other than the default, edit both
files together:

```jsonc
// agentcore/aws-targets.json
[{ "name": "default", "account": "<your account>", "region": "<your region>" }]

// agentcore/agentcore.json → runtimes[0].envVars
{ "name": "PORCHLIGHT_SESSION_BUCKET", "value": "porchlight-sessions-<account>-<region>" }
{ "name": "PORCHLIGHT_AWS_REGION",     "value": "<region>" }
```

Then update `FALLBACK_ACCOUNT` / `FALLBACK_REGION` in [`infra/bin/porchlight.ts`](../infra/bin/porchlight.ts)
(they are only synth-time fallbacks, but the consistency test compares against them), and run
`pytest -q tests/v_test_deploy_config.py` — it will name anything you missed.

### A verified SES sender (optional, but do it for a real demo)

Outbound messages go out as email through SES, and SES rejects an unverified sender. Until you set
one, `make_channel` keeps `EmailChannel` in `dry_run` and logs every message instead of sending it
— the graph still runs end to end, the Quiet Log still records what would have gone out, and
nothing silently fails. To send for real:

```bash
aws ses verify-email-identity --email-address porch@your-domain.org
export PORCHLIGHT_FROM_ADDR=porch@your-domain.org        # picked up by make deploy-infra
```

and add the same variable to `runtimes[0].envVars` in `agentcore.json` — **the runtime sends the
messages, not the API**, so setting it on only one half sends nothing. A brand-new SES account is
in the sandbox: recipients must be verified too.

---

## 2. Deploy

```bash
make deploy
```

is the whole thing, in dependency order:

```
make deploy
  ├─ deploy-runtime   agentcore/  sync → validate → cdk deploy
  │                               → .env.deploy  (PORCHLIGHT_AGENT_RUNTIME_ARN, PORCHLIGHT_MEMORY_ID)
  │                               → SSM  /porchlight/runtime_arn, /porchlight/memory_id
  ├─ build-lambda     scripts/build_lambda.sh → build/lambda  (arm64, ~72 MB)
  ├─ build-web        web/ → web/dist
  └─ deploy-infra     infra/  cdk deploy -c runtimeArn=… -c memoryId=… -c fromAddr=…
                              → .env.deploy  (CloudFront URL, Function URL, table, bucket, distribution)
```

Expect 10–15 minutes the first time, most of it CloudFront.

### Or one step at a time

```bash
make package-runtime     # build the CodeZip only — no credentials needed, proves the build
make deploy-runtime      # AgentCore Runtime + Memory, then publish the ARN and memory id
make build-lambda        # the API bundle
make build-web           # the UI
make synth               # render the app stack's template — no credentials needed
make deploy-infra        # the app stack, picking the ARN up from .env.deploy or SSM
```

The order between the two halves does not matter. `deploy-infra` resolves the runtime ARN from
`.env.deploy` first and SSM second; if neither has one it says so and deploys the API in
`LocalOrchestrator` mode. Re-running `deploy-infra` after `deploy-runtime` is what wires them
together.

### The handoff

```
make deploy-runtime ──▶ agentcore/.cli/deployed-state.json
                          ├─▶ .env.deploy  (merged, never clobbered)
                          └─▶ SSM /porchlight/runtime_arn, /porchlight/memory_id
                                 │
make deploy-infra ◀──────────────┘   cdk deploy -c runtimeArn=… -c memoryId=…
                                        └─▶ Lambda env PORCHLIGHT_AGENT_RUNTIME_ARN
                                              └─▶ make_orchestrator → AgentCoreOrchestrator
```

Both values come out of `agentcore/.cli/deployed-state.json` through
[`agentcore/deployed_state.py`](../agentcore/deployed_state.py), which makes no AWS call:

```bash
make runtime-arn                                              # both, as KEY=VALUE
python agentcore/deployed_state.py --format cdk-context       # -c runtimeArn=… -c memoryId=…
python agentcore/deployed_state.py --key PORCHLIGHT_MEMORY_ID
```

### What lands in `.env.deploy`

Gitignored, and the two halves merge into it rather than overwriting each other:

```
PORCHLIGHT_AGENT_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-east-1:…:runtime/porchlight_Porchlight-XXXXXXXX
PORCHLIGHT_MEMORY_ID=PorchlightMemory-XXXXXXXXXX
PORCHLIGHT_CLOUDFRONT_URL=https://dxxxxxxxxxxxxx.cloudfront.net
PORCHLIGHT_FUNCTION_URL=https://xxxxxxxx.lambda-url.us-east-1.on.aws/
PORCHLIGHT_DYNAMO_TABLE=porchlight
PORCHLIGHT_SESSION_BUCKET=porchlight-sessions-<account>-<region>
PORCHLIGHT_DISTRIBUTION_ID=EXXXXXXXXXXXXX
```

---

## 3. Verify

```bash
set -a; . ./.env.deploy; set +a
```

**The porch is up.** Open `$PORCHLIGHT_CLOUDFRONT_URL`. The UI and the API are the same origin, so
nothing needs CORS at runtime.

**The API is healthy, and knows which orchestrator it picked.**

```bash
curl -s "$PORCHLIGHT_CLOUDFRONT_URL/api/health" | jq
```

`orchestrator: "AgentCoreOrchestrator"` means the runtime ARN was threaded through;
`"LocalOrchestrator"` means it was not, and the API is running the graph itself.

**The trace streams instead of buffering.**

```bash
curl -sN "$PORCHLIGHT_CLOUDFRONT_URL/api/events?limit=1"
```

Events should arrive as they happen. If the whole response lands at once, the Function URL is not in
`RESPONSE_STREAM` mode or the Lambda Web Adapter is not wrapping the process.

**The runtime answers on its own.**

```bash
agentcore status
agentcore invoke --runtime Porchlight --target default '{"action": "sweep"}'
```

**A request goes end to end.** Seed the fixtures, drop a message in, and watch the porch:

```bash
curl -s -X POST "$PORCHLIGHT_CLOUDFRONT_URL/api/inbox" \
  -H 'Content-Type: application/json' \
  -d '{"text": "Mum needs a ride to dialysis Thursday 9am", "source": "sms", "contact": "+15550100"}'
```

**The scheduler fires.**

```bash
aws lambda invoke --function-name "$(aws cloudformation describe-stacks \
  --stack-name PorchlightAppStack --query \
  'Stacks[0].Outputs[?OutputKey==`SweepFunctionName`].OutputValue' --output text)" \
  --payload '{"action":"sweep"}' --cli-binary-format raw-in-base64-out /dev/stdout
```

**Logs and traces.**

```bash
agentcore logs --runtime Porchlight --since 30m
agentcore logs --runtime Porchlight --level error --query Traceback
agentcore traces list --runtime Porchlight --since 1h
aws logs tail /aws/lambda/<api function name> --follow
```

### Traces: CloudWatch GenAI Observability

`instrumentation.enableOtel` in `agentcore/agentcore.json` makes the CLI start the entrypoint as
`opentelemetry-instrument main.py`, and the runtime's `envVars` carry `AGENT_OBSERVABILITY_ENABLED`,
`OTEL_PYTHON_DISTRO=aws_distro` and `OTEL_PYTHON_CONFIGURATOR=aws_configurator`. That means the AWS
Distro for OpenTelemetry owns the export pipeline before Porchlight imports anything, so
`porchlight/telemetry.py` **adds no exporter of its own**: it attaches `StrandsTelemetry` to the
provider the distro installed (`strands.telemetry.Tracer` reads the global provider, so every agent,
graph-node, and tool span joins the same trace) and otherwise keeps its hands off. Two exporters on
one provider would post every span twice, and the second one — built from `OTEL_EXPORTER_OTLP_*`
by hand rather than by the distro — is the classic source of `Failed to export span batch code:
400`. The guard in `adot_instrumented()` is three-way: the AgentCore switch, an ADOT or
auto-instrumentation variable (or its `sitecustomize` directory on `PYTHONPATH`), or a provider
that already carries span processors. If none of those holds — a self-hosted collector — Porchlight
configures the exporter itself.

Where to look, after an invocation:

1. **CloudWatch → GenAI Observability → Bedrock AgentCore**, region `us-east-1`. Pick the
   `Porchlight` runtime: sessions, traces, token counts and latency per invocation. A whole request
   is one trace — `intake → matcher → outreach → steward` as nested spans, with the tool calls and
   the model calls underneath.
2. **CloudWatch → X-Ray traces** for the same spans without the GenAI framing
   (`agentcore traces list --runtime Porchlight --since 1h` prints trace ids from the CLI).
3. **Log group** `/aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT` for the stdout side.
   `agentcore logs --runtime Porchlight --query "span batch"` is the quick check that no duplicate
   exporter came back.

**Transaction Search must be on** before any of that has anything in it: enable it once per account
under **CloudWatch → Application Signals → Transaction Search** (`aws xray
get-trace-segment-destination` should say `CloudWatchLogs` / `ACTIVE`, and an `aws/spans` log group
should exist). It takes a few minutes to come into effect, and spans exported during that window
are rejected — which is exactly what the first live run hit: the account's indexing rule was
modified at 00:22 UTC and the `400 Bad Request` batches are from 00:23. Re-check after a fresh
invocation before treating a 400 as a code problem.

If 400s survive an account with Transaction Search active, the next suspect is payload size rather
than a duplicate exporter: Strands records prompts, tool arguments and tool results on the spans,
and a 39k-token request makes a large batch. Two levers, both environment-only (set them in
`agentcore.json`'s `envVars`, since the SDK reads them before Porchlight starts):
`OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT=4096` truncates long attribute values, and
`OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_unredacted_attributes=` makes Strands redact message content
entirely — which also keeps neighbours' words out of CloudWatch, at the cost of a much less
interesting trace.

Verified on the deployed stack on 2026-09-05: zero `Failed to export` lines and zero `ERROR`-level
records in the runtime log group over an hour of real invocations, and `aws xray get-trace-summaries`
returning twelve traces whose durations line up with the runs that produced them (34.8s for a full
graph run, 17.4s for a resumed decision, 6.5s for a sweep). One of those traces holds 556
segments — `invoke_agent matcher` → `execute_event_loop_cycle` → `execute_tool recall_memory` →
the DynamoDB and Bedrock calls underneath. The only stack traces in the log group are OTLP span
*events*, not application errors: `S3.GetObject` `NoSuchKey` from `S3SessionManager` reading a
session file that does not exist on the first turn, which the SDK handles.

Locally, `PORCHLIGHT_TRACE_CONSOLE=1` prints the same spans to stdout without any AWS involvement.

---

## 4. When it does not work

| Symptom | Cause | Fix |
|---|---|---|
| `/api/health` says `LocalOrchestrator` after deploying both halves | `deploy-infra` ran before `deploy-runtime`, or found no ARN | `make runtime-arn` to confirm one exists, then `make deploy-infra` again |
| `AccessDeniedException` on a model id | Model access not granted in this region | `make smoke-bedrock` — it names the model and the console page |
| Every outbound message is logged, none sent | `PORCHLIGHT_FROM_ADDR` unset, so the channel stays in dry-run | Verify a sender, set it in **both** `agentcore.json` and `make deploy-infra`'s environment |
| Messages marked `FAILED` in the Quiet Log | A sender *is* set but SES rejects it (unverified, or sandbox recipient) | `aws ses get-identity-verification-attributes --identities <addr>` |
| `/api/events` arrives all at once | `AWS_LWA_INVOKE_MODE` or the Function URL's `InvokeMode` is not `response_stream` | Redeploy the stack; both are set in `infra/lib/porchlight-stack.ts` |
| The porch shows no trace on AWS | `PORCHLIGHT_EVENTS_SOURCE` is not `store` on one of the halves | It must be `store` on both — the API and the agents are different processes |
| `Failed to export span batch code: 400` in the runtime log | Transaction Search not active yet (most likely), or a second OTLP exporter alongside ADOT's | Confirm `aws xray get-trace-segment-destination` is `ACTIVE`, invoke again, then read *Traces* in § 3; `agentcore logs --runtime Porchlight --query telemetry` should say "reusing the tracer provider" |
| No traces in CloudWatch GenAI Observability | Transaction Search not enabled, or `instrumentation.enableOtel` is false | See *Traces* in § 3 |
| `ResourceNotFoundException` on the table | The two halves disagree about the table name | `pytest -q tests/v_test_deploy_config.py` |
| `cdk deploy` says the environment is not bootstrapped | New account or region | `cd infra && npx cdk bootstrap aws://<account>/<region>` |
| `build/lambda is missing` | The bundle was never built, or `make clean` removed it | `make build-lambda` |
| The CodeZip is over 250 MB | A new dependency dragged in its full tree | Check `runtime/pyproject.toml`; `strands-agents-tools` is deliberately `--no-deps` |
| `make deploy-runtime` fails with `No such command 'validate'` | The venv is active, and `bedrock-agentcore-starter-toolkit` puts its own `agentcore` on `PATH` ahead of the npm CLI | Run `make deploy-runtime` from a shell with the venv *deactivated*; `agentcore --help` should list `validate`. Everything else in the Makefile uses `.venv/bin/python` explicitly, so no other target cares |
| `POST /api/inbox` returns 504 through CloudFront while the run finishes anyway | The origin response timeout is shorter than a real graph run | The behaviour's `readTimeout` is 120s, the account ceiling for quota `L-AECE9FA7`. Measured runs are 40–55s. Call the Function URL directly to rule CloudFront in or out |
| `agentcore invoke '{"action":"sweep"}'` runs `process_request` instead | The CLI treats its positional argument as a chat prompt and wraps it as `{"prompt": "..."}` | Nothing to do — `unwrap_prompt` in `porchlight/runtime.py` unwraps a `prompt` that parses as a JSON object. If you see this, the deployed build predates that fix |
| A red "Possible emergency" card about an unpaid bill | Intake put hardship into `safety_flags`; the prompt asks it to over-flag | Fixed twice over: the prompt now says hardship is not a safety flag, and an uncorroborated intake flag ranks below the rules that matched (`PolicyFlag.source`, `card_for`). See `tests/n_test_flag_provenance.py` |

---

## 5. Tear down

```bash
make destroy
```

which is:

```bash
cd infra && npx cdk destroy PorchlightAppStack --force
cd agentcore/cdk && npm run build && npx cdk destroy AgentCore-porchlight-default --force
aws ssm delete-parameters --names /porchlight/runtime_arn /porchlight/memory_id
```

Every bucket is `RemovalPolicy.DESTROY` with `autoDeleteObjects`, and the table goes with the stack:
hackathon hygiene, not production posture. Nothing survives except the CDK bootstrap stack and
whatever CloudWatch retained. Local state (`.env.deploy`, `build/cdk-outputs.json`) is removed too;
`make clean` clears the rest of the working tree.

---

## 6. Costs

Everything is on-demand and idles at approximately nothing:

| Resource | Idle | Under load |
|---|---|---|
| DynamoDB | $0 (PAY_PER_REQUEST) | fractions of a cent per demo day |
| Lambda (arm64) | $0 | per-ms; a request is seconds of wall time, mostly waiting on Bedrock |
| CloudFront + S3 | free tier / pennies | pennies |
| AgentCore Runtime | $0 when no session is live | per-session; `idleRuntimeSessionTimeout` is 900 s so sessions do not linger |
| AgentCore Memory | storage only | small |
| EventBridge Scheduler | ~$0 | the hourly sweep costs nothing when nothing is due |

**The real spend is Bedrock tokens.** Measured on the live stack (us-east-1, September 2026), one
*routine* request — intake, matcher, outreach, steward, with tool calls and the structured-output
tool schemas in every turn — used **~39k tokens end to end, about $0.15**. A request that stops at a
decision card costs less (intake plus the gate, no outreach loop); a resumed card costs roughly
another half-request when the graph picks up again.

So budget **~$0.15 per request, ~$4 for the full 24-sample demo day**, and a little more if you
answer every card. Fine for a demo; a real group's Tuesday would want the levers, in the order
worth pulling: Haiku already does intake, the reply reader and the steward, and Sonnet is kept for
the two jobs with judgement in them (matching, and writing to a real person); the hourly sweep is
model-free by design; and a group at volume would cache the shared values block, which is the same
~700 tokens on the front of every call. `PORCHLIGHT_MODEL_PROVIDER=mock` costs nothing at all and
still exercises the whole graph, which is the cheapest way to check that the plumbing is right
before spending a token.

The one thing that can surprise you is a runaway sweep against a large store, since every due
request is a model call. `PORCHLIGHT_MAX_CANDIDATES` bounds outreach per request; the escalation
rules bound how long a request keeps trying.

---
---

# Reference

## The app stack (`infra/`)

CDK v2, TypeScript. One stack, `PorchlightAppStack`, holding everything except the AgentCore
runtime.

```
CloudFront ─┬─ default  ─▶ S3 (web/dist, origin access control)
            └─ /api/*   ─▶ Lambda Function URL (FastAPI under the Lambda Web Adapter)
                               │
                               ├─ DynamoDB "porchlight" (single table, GSI1)
                               ├─ S3 "porchlight-sessions-<account>-<region>" (S3SessionManager)
                               └─ AgentCore Runtime (when runtimeArn is set), else Bedrock directly
EventBridge Scheduler ─ hourly sweep + 06:00 UTC brief ─▶ sweep Lambda (api.scheduled.handler)
```

### What it creates

| Resource | Detail |
|---|---|
| **DynamoDB `porchlight`** | `PAY_PER_REQUEST`; `pk`/`sk` strings; GSI `GSI1` on `gsi1pk`/`gsi1sk` (projection ALL); TTL attribute `ttl`; PITR on. Exactly the layout [`porchlight/store/dynamo_store.py`](../porchlight/store/dynamo_store.py) writes. |
| **S3 `porchlight-sessions-<account>-<region>`** | Private, SSE-S3, TLS-only, 30-day expiry. Strands' `S3SessionManager` keeps graph sessions and persisted interrupts here, so a Decision Card raised in one process resumes in another. |
| **API Lambda** | Python 3.12, **arm64**, 1536 MB, 15-minute timeout, `build/lambda` as the code asset. |
| **Function URL** | `AuthType: NONE`, `InvokeMode: RESPONSE_STREAM`, CORS `*` — response streaming is what makes `/api/events` (SSE) work. |
| **Sweep Lambda** | Same bundle, handler `api.scheduled.handler`, 1024 MB. |
| **EventBridge Scheduler** | `rate(1 hour)` → `{"action": "sweep"}`; `cron(0 6 * * ? *)` → `{"action": "brief"}`. |
| **S3 + CloudFront** | `web/dist` behind origin access control; a `/api/*` behaviour pointed at the Function URL so the UI is same-origin. |
| **Log groups** | Explicit, two-week retention, destroyed with the stack. |

**Outputs:** `CloudFrontUrl`, `FunctionUrl`, `TableName`, `SessionBucketName`, `WebBucketName`,
`ApiFunctionName`, `SweepFunctionName`, `DistributionId`.

### The API Lambda runs a real web server

The function does not use a Lambda event handler for the main path. The
[AWS Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter) layer
(`arn:aws:lambda:<region>:753240598075:layer:LambdaAdapterLayerArm64:28`) sits in front of an
ordinary uvicorn process:

* handler is `run.sh` — written by `scripts/build_lambda.sh`, it execs
  `python -m uvicorn api.main:app --host 0.0.0.0 --port 8000`;
* `AWS_LAMBDA_EXEC_WRAPPER=/opt/bootstrap` hands the sandbox to the adapter;
* `AWS_LWA_INVOKE_MODE=response_stream` makes it stream the Function URL response instead of
  buffering it — SSE would otherwise arrive all at once, at the end;
* `AWS_LWA_PORT=8000`, `PORT=8000`, `AWS_LWA_READINESS_CHECK_PATH=/api/health`,
  `AWS_LWA_ASYNC_INIT=true`.

Running a real ASGI server also means FastAPI's lifespan runs, which is what starts the store
tailer behind `PORCHLIGHT_EVENTS_SOURCE=store`.
[`api/lambda_handler.py`](../api/lambda_handler.py) (Mangum) is kept as an alternative entry point:
set the handler to `api.lambda_handler.handler`, drop the layer and the LWA variables, and the same
app runs buffered. Useful for debugging; it cannot stream and has no lifespan.

### Environment the stack sets

```
PORCHLIGHT_MODE=live              PORCHLIGHT_STORE=dynamo
PORCHLIGHT_DYNAMO_TABLE=<table>   PORCHLIGHT_SESSION_BUCKET=<bucket>
PORCHLIGHT_EVENTS_SOURCE=store    PORCHLIGHT_AWS_REGION=<region>
PORCHLIGHT_AGENT_RUNTIME_ARN=<-c runtimeArn, default "">
PORCHLIGHT_MEMORY_ID=<-c memoryId, default "">
PORCHLIGHT_FROM_ADDR=<-c fromAddr, only when set>
```

`PORCHLIGHT_EVENTS_SOURCE=store` matters on AWS: the API and the agents run in different processes,
so `/api/events` tails the persisted trace in DynamoDB rather than this process's in-memory bus.
An empty `PORCHLIGHT_AGENT_RUNTIME_ARN` makes `make_orchestrator` return `LocalOrchestrator`.

### IAM

Both functions get: read/write on the table and its index, read/write on the session bucket,
`bedrock-agentcore:InvokeAgentRuntime` (scoped to the runtime ARN when known, otherwise `*`),
the AgentCore Memory data-plane actions (`CreateEvent`, `RetrieveMemoryRecords`, …), `ses:SendEmail`
for the live `EmailChannel`, Bedrock inference for the in-process fallback, and their own log
groups.

Bedrock inference is `InvokeModel`, `InvokeModelWithResponseStream`, `CountTokens`,
`Get`/`ListInferenceProfile`, `List`/`GetFoundationModel` — the same set as
[`runtime/iam-policy.json`](../runtime/iam-policy.json). There is **no** `bedrock:Converse` IAM
action: Converse and ConverseStream authorise against `InvokeModel` and
`InvokeModelWithResponseStream`. `tests/v_test_deploy_config.py` asserts neither string comes back.

### Context

Set with `-c key=value`, defaults in [`infra/cdk.json`](../infra/cdk.json):

| key | default | meaning |
|---|---|---|
| `stackName` | `PorchlightAppStack` | |
| `tableName` | `porchlight` | DynamoDB table name |
| `runtimeArn` | `''` | AgentCore Runtime ARN |
| `memoryId` | `''` | AgentCore Memory id |
| `fromAddr` | `''` | Verified SES sender for live mode |
| `lambdaBundle` | `../build/lambda` | Output of `scripts/build_lambda.sh` |
| `webDist` | `../web/dist` | Built UI |
| `lwaLayerVersion` | `28` | Lambda Web Adapter layer version |
| `apiMemoryMb` / `sweepMemoryMb` | `1536` / `1024` | |
| `sweepRateMinutes` / `briefCron` | `60` / `cron(0 6 * * ? *)` | |
| `account` / `region` | from `CDK_DEFAULT_*` | Falls back to `892077329800` / `us-east-1` so `cdk synth` works with no credentials |

### Building the Lambda bundle — no Docker

```bash
make build-lambda      # scripts/build_lambda.sh
```

`uv` resolves and downloads wheels for a platform it is not running on, so a macOS arm64 laptop
produces a Linux arm64 bundle directly:

```
uv pip install --python-platform aarch64-manylinux2014 --python-version 3.12 \
               --only-binary=:all: --target build/lambda -r build/requirements-lambda.txt
```

`--only-binary=:all:` turns a source-only dependency into a loud failure rather than a bundle that
breaks at cold start. The requirements file is generated from `pyproject.toml`'s
`[project].dependencies` (dev dependencies are never bundled). `strands-agents-tools` is installed
with `--no-deps`: no agent imports it any more (the clock moved from the deprecated `current_time`
tool to a Strands `ContextInjector` — see *Traces* below and `porchlight/agents/base.py`), and its
full dependency tree (pillow, sympy, aiohttp, slack-bolt) would add ~70 MB of dead weight. The
`porchlight` and `api` packages are copied in, and `run.sh` is generated.

The script prints the final size and refuses to finish over Lambda's 250 MB unzipped limit. Today:

```
unzipped  : 72 MB      zipped : 29 MB      files : ~4300
```

It also checks that every entry point is present, that `run.sh` is executable, and that the compiled
extensions are `aarch64-linux-gnu` rather than the host's.

### Synth without credentials

```bash
make synth        # or: cd infra && npx cdk synth
```

This always works: the account/region fall back to `892077329800` / `us-east-1`, a missing
`build/lambda` synthesises a stub asset with a warning, and a missing `web/dist` skips the bucket
deployment with a warning. Nothing in the app touches AWS at synth time.

---

## The AgentCore runtime (`agentcore/`)

The other half. It deploys [`porchlight/runtime.py`](../porchlight/runtime.py) — the whole Strands
graph — to Amazon Bedrock AgentCore Runtime as a **CodeZip** build, together with an **AgentCore
Memory**, and publishes `/porchlight/runtime_arn` and `/porchlight/memory_id` to SSM so the app
stack can find them.

### The directories

| Path | What it is |
|---|---|
| [`agentcore/agentcore.json`](../agentcore/agentcore.json) | The project: one runtime, one memory, their env vars and IAM. |
| [`agentcore/aws-targets.json`](../agentcore/aws-targets.json) | The deployment target `default` → account, region. |
| [`agentcore/cdk/`](../agentcore/cdk/) | The CDK app the CLI vends and drives. Unmodified — everything Porchlight needs is expressible in `agentcore.json`. Its stack is `AgentCore-porchlight-default`. |
| [`agentcore/.llm-context/`](../agentcore/.llm-context/) | Read-only type definitions for the two JSON files. Consult these before editing them. |
| [`agentcore/.cli/deployed-state.json`](../agentcore/.cli/deployed-state.json) | Committed on purpose: after a deploy it holds the runtime ARN and memory id. |
| [`runtime/`](../runtime/) | The `codeLocation` — everything in it goes into the zip. |

### How `porchlight` gets into the zip

`porchlight` is not on PyPI and a `file://` path dependency is not portable, so the build copies it:

```
make package-runtime
  └─ rsync -a --delete porchlight/ runtime/porchlight/     # gitignored mirror
  └─ agentcore package --runtime Porchlight
       └─ uv pip install -r runtime/pyproject.toml --target <staging> \
            --python-version 3.14 --python-platform aarch64-manylinux2014 --only-binary :all:
       └─ copy runtime/ over the top, zip → agentcore/Porchlight.zip
```

`runtime/porchlight/` is a **build artifact** — `rsync --delete` overwrites it every time. The
source of truth is always `/porchlight`. `make clean` removes it.

The packager skips `.git`, `.venv`, `__pycache__`, `.pytest_cache`, `.DS_Store` and `node_modules`,
and refuses any artifact over **250 MB**. Today the zip is **55 MB / 8,755 entries**: the runtime
dependency set (no FastAPI, no uvicorn, no Mangum — those belong to the API Lambda) plus
`aws-opentelemetry-distro`.

`agentcore package` needs no AWS credentials, so it is the cheapest way to prove the build is sound.

### The runtime

```jsonc
{
  "name": "Porchlight",       "build": "CodeZip",   "entrypoint": "main.py",
  "codeLocation": "runtime/", "runtimeVersion": "PYTHON_3_14",
  "protocol": "HTTP",         "networkMode": "PUBLIC", "authorizerType": "AWS_IAM",
  "instrumentation": { "enableOtel": true },
  "lifecycleConfiguration": { "idleRuntimeSessionTimeout": 900, "maxLifetime": 28800 }
}
```

`PYTHON_3_14` is the highest the CLI schema offers. It resolves to exactly the same dependency
versions as `PYTHON_3_13`, and the suite passes on CPython 3.14, so there is no reason to take less.

Because `enableOtel` is true, the CLI's CDK sets the container entry point to
`["opentelemetry-instrument", "main.py"]`: the ADOT distro wraps the process, installs a tracer
provider wired to the AgentCore collector, and traces land in CloudWatch under
`/aws/bedrock-agentcore/runtimes/*`. [`porchlight/telemetry.py`](../porchlight/telemetry.py) notices
that provider and **attaches** `StrandsTelemetry` to it rather than replacing the global one, so
Strands' spans join ADOT's trace instead of forming a second, orphaned one — and it is idempotent,
so calling it once per invocation does not stack a `BatchSpanProcessor` per request.

### The entrypoint

[`runtime/main.py`](../runtime/main.py) is four lines: import `app` from `porchlight.runtime`, run
it. The real entrypoint is `porchlight_entrypoint(payload, context)`. The second parameter has to be
named `context` — that is how `BedrockAgentCoreApp` decides whether to pass one.

```
POST /invocations   {"action": "process_request", "request_id": "req_...", "image_base64": "..."}
                    {"action": "resume_decision", "decision_id": "dec_...", "option_id": "...", "note": "..."}
                    {"action": "sweep"}
                    {"action": "brief", "day": "2026-09-08"}
GET  /ping          {"status": "Healthy", ...}
```

Add `"stream": true` to any of them for the trace events as SSE while the graph is still running.
Every response echoes `session_id`, and an unknown action comes back as
`{"ok": false, "error": "unknown action; expected one of [...]"}` rather than a 500.

`context.session_id` is whatever the API put in `invoke_agent_runtime(runtimeSessionId=…)`, which for
a request is `porchlight.orchestrator.runtime_session_id(request_id)` — the request id padded to
AgentCore's 33-character minimum with a stable digest. The runtime echoes it back on every response,
logs it with every invocation, and decodes the request id out of it when a caller sends
`{"action": "process_request"}` with nothing else.

### Environment

Set in `agentcore.json`, plus `MEMORY_PORCHLIGHTMEMORY_ID`, which the CLI's CDK injects with the
deployed memory id (`MEMORY_<NAME uppercased>_ID`).
[`porchlight/config.py`](../porchlight/config.py) reads it as an alias for `memory_id`, so nothing
else in the code has to know that name.

```
PORCHLIGHT_MODE=live                PORCHLIGHT_MODEL_PROVIDER=bedrock
PORCHLIGHT_STORE=dynamo             PORCHLIGHT_TOOLS=local
PORCHLIGHT_CHANNEL=sim              PORCHLIGHT_QUIET_HOURS=[0,0]
PORCHLIGHT_EVENTS_SOURCE=store      PORCHLIGHT_AWS_REGION=us-east-1
PORCHLIGHT_DYNAMO_TABLE=porchlight
PORCHLIGHT_SESSION_BUCKET=porchlight-sessions-892077329800-us-east-1
PORCHLIGHT_MODEL_SONNET=global.anthropic.claude-sonnet-4-6
PORCHLIGHT_MODEL_HAIKU=global.anthropic.claude-haiku-4-5-20251001-v1:0
PORCHLIGHT_GROUP_NAME="Maple Street Mutual Aid"   PORCHLIGHT_TIMEZONE=America/Toronto
AGENT_OBSERVABILITY_ENABLED=true    OTEL_PYTHON_DISTRO=aws_distro
OTEL_PYTHON_CONFIGURATOR=aws_configurator
MEMORY_PORCHLIGHTMEMORY_ID=<injected>            AWS_REGION=<set by the service>
```

`PORCHLIGHT_CHANNEL=sim` and `PORCHLIGHT_QUIET_HOURS=[0,0]` are the two settings that make this a
*hosted demo* rather than a production deployment, and both must match the Lambda environment in
`infra/lib/porchlight-stack.ts` — the graph messages volunteers on the runtime side, the hourly
sweep delivers on the Lambda side, and a disagreement means one half holds a message the other
half thinks it already sent. `sim` role-plays the volunteers with Haiku instead of emailing real
people; the empty quiet-hours window (start equal to end) turns quiet hours off, because nobody is
asleep on the other end of a simulator and a visitor arriving at 23:00 in the group's timezone
should still see the loop close instead of a message held until 08:00. `tests/v_test_deploy_config.py`
asserts both pairs. For a real group, drop both lines: the defaults are `auto` (which resolves to
email in live mode) and 21:00–08:00.

`AWS_REGION` is deliberately *not* listed: the service provides it, and `PORCHLIGHT_AWS_REGION`
takes precedence in `config.py` anyway. `PORCHLIGHT_FROM_ADDR` is also absent — see
[§1](#a-verified-ses-sender-optional-but-do-it-for-a-real-demo) for what that means and how to set
one. `PORCHLIGHT_MODE=demo` here gives a deployed demo that uses `SimChannel` and never touches SES;
the store stays DynamoDB either way, since that is chosen by `PORCHLIGHT_STORE`.

### IAM

The CLI's CDK already grants the execution role Bedrock model invocation, X-Ray, its CloudWatch log
group, and — because a memory is declared in the same project — the AgentCore Memory data plane.
Everything else Porchlight touches is attached through `additionalPolicies`, which takes a JSON
policy document resolved relative to `codeLocation`:
[`runtime/iam-policy.json`](../runtime/iam-policy.json).

| Statement | Grants |
|---|---|
| `PorchlightSingleTable` | `dynamodb:GetItem/PutItem/UpdateItem/Query/Scan/BatchWriteItem/…` on `table/porchlight` **and** `table/porchlight/index/*` (the store reads `GSI1`). |
| `PorchlightSessionBucket` | `s3:GetObject/PutObject/DeleteObject/ListBucket` on `porchlight-sessions-*` — Strands' `S3SessionManager`, i.e. where a persisted interrupt lives between the card and the tap. |
| `PorchlightBedrockInference` | `bedrock:InvokeModel`, `InvokeModelWithResponseStream`, `CountTokens`, `Get/ListInferenceProfile` on `foundation-model/*` and `inference-profile/*`, which is what the `global.anthropic.*` profiles need. |
| `PorchlightAgentCoreMemory` | `CreateEvent`, `ListEvents`, `RetrieveMemoryRecords`, `ListMemoryRecords`, … on `memory/*`. |
| `PorchlightObservability` | X-Ray segments and `cloudwatch:PutMetricData`. |

Resource ARNs use `*` for account and region so the file stays portable; the role itself only exists
in the target account.

### Memory

```jsonc
{
  "name": "PorchlightMemory", "eventExpiryDuration": 90,
  "strategies": [
    { "type": "USER_PREFERENCE", "namespaceTemplates": ["/porchlight/{actorId}/preferences"] },
    { "type": "SEMANTIC",        "namespaceTemplates": ["/porchlight/{actorId}/facts"] }
  ]
}
```

Long-term only. `{actorId}` is the volunteer or requester id, which is exactly how
[`porchlight/memory/agentcore_store.py`](../porchlight/memory/agentcore_store.py) writes: namespace
prefix `/porchlight`, one actor per person. Preferences are the "prefers mornings, great with
seniors" notes the matcher recalls; facts are what happened. Short-term conversation state does not
belong here — the graph's own session manager (S3) already persists it, including the interrupts.

### Deploying it by hand

```bash
cd agentcore/cdk && npm ci && cd ../..        # once
make sync-runtime
agentcore validate
agentcore deploy --target default -y
```

`agentcore deploy --dry-run` previews and `--diff` shows a CloudFormation diff.

### Operating it

```bash
agentcore status                                  # runtime, endpoint, memory: state and ids
agentcore status --json
agentcore logs --runtime Porchlight --since 30m
agentcore logs --runtime Porchlight --level error --query Traceback
agentcore traces list --runtime Porchlight --since 1h
agentcore invoke --runtime Porchlight --session-id "$SESSION" '{"action": "sweep"}'
```

`--session-id` must be at least 33 characters, the same rule `runtime_session_id` exists to satisfy.
To resume a Decision Card by hand, use the session id of the request the card came from — that is
where the interrupt was persisted.

### Running it locally

The same file, the same port, none of AWS:

```bash
make runtime-local        # sync → python runtime/main.py on :8080, mock model, SQLite
```

```bash
python scripts/seed.py
curl -s localhost:8080/ping
curl -s -X POST localhost:8080/invocations \
  -H 'Content-Type: application/json' \
  -H 'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: req_9c72e440ff-000000000000000000000000000' \
  -d '{"action": "process_request", "request_id": "req_9c72e440ff"}'
curl -sN -X POST localhost:8080/invocations -H 'Content-Type: application/json' \
  -d '{"action": "sweep", "stream": true}'          # server-sent events
```

Python puts the script's own directory on `sys.path`, so `runtime/main.py` imports
`runtime/porchlight/` — the same copy the zip will contain, not the repo's working tree. Re-run
`make sync-runtime` after editing `porchlight/`, or use `python -m porchlight.runtime` to serve the
working tree directly.

### Changing the configuration

`agentcore.json` and `aws-targets.json` are typed. Before editing either, read the matching `.ts`
file in [`agentcore/.llm-context/`](../agentcore/.llm-context/) — it carries the exact enums,
regexes and bounds — then run `agentcore validate` **and** `pytest -q tests/v_test_deploy_config.py`.
The first catches a malformed file; the second catches a well-formed file that no longer agrees
with the app stack.
