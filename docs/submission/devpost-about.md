# Porchlight

*Runs the coordination. Lights up only when you're needed.*

## Inspiration

Every mutual-aid group, food pantry, and church volunteer team we've seen runs on one exhausted coordinator. Requests arrive as texts, emails, form submissions, voicemails, and paper slips. Each one becomes the same job: work out who could help, ask three people, wait, ask two more, confirm with the family, send a reminder, handle the no-show, and then forget to write any of it down. Forty times a week.

Almost none of that work needs a human. What *does* need a human is rare and important: a message that hints at danger, a request for money, a volunteer who reports something off, an urgent need nobody can cover. Today those get buried in the same pile as "can someone grab milk for Mrs. Chen".

Porchlight is built for that coordinator. It does the whole loop in the background and turns the porch light on only for the decisions that should be theirs.

## What it does

Porchlight is an autonomous dispatcher for small volunteer groups (Good Neighbor track).

1. **Intake.** Any inbound message, including a photo of a paper request slip, becomes a structured job: category, time window, zone, constraints ("uses a walker"), urgency, and flags for safety, money, or a first-time requester.
2. **Match.** Volunteers are scored on skills, zone adjacency, availability overlap, weekly-load fairness, reliability, and long-term memory ("Maria was great with Mr. Okafor last month").
3. **Outreach.** Porchlight messages one volunteer at a time, reads the reply (accept / decline / counter / concern), moves to the next candidate on a decline, and never shares a requester's private details before someone has accepted.
4. **Steward.** It confirms with the requester, schedules reminders, does a post-event check-in, and distills what it learned into memory so next week's matches are better.
5. **The porch light.** When policy says a human must decide (safety language, money, vetting, an unmatched urgent request, a volunteer's concern) the run pauses and the coordinator gets a **Decision Card**: context, Porchlight's recommendation, and one-tap options. Everything else lands in a **Quiet Log** they can skim whenever they like.

An hourly background sweep sends due reminders, escalates stale outreach, and writes a nightly brief.

## How we built it

Porchlight is Strands Agents end to end, deployed on Amazon Bedrock AgentCore.

- **Five Strands agents** (intake, matcher, outreach, steward, brief) with Pydantic `structured_output_model`s on every call, orchestrated as a **Strands Graph** with conditional edges, a bounded retry cycle for outreach, and a short-circuit for messages that aren't requests.
- **Strands interventions are the autonomy boundary.** `PorchlightPolicy` is an `InterventionHandler`: it returns `Deny` for danger language, `Guide` during quiet hours, `Transform` to redact private details, and `Confirm` when a human must decide. `Confirm` raises a Strands **interrupt**; that interrupt *is* the Decision Card. It's persisted through a session manager, so the coordinator can answer hours later from their phone and the graph resumes exactly where it paused.
- **Hooks** (`BeforeToolCallEvent`, `AfterToolCallEvent`, `MessageAddedEvent`, `AfterModelCallEvent`) build the audit trail and the live trace panel.
- **Agents-as-tools** for reply interpretation, **MCP** for the data tools (an MCP server the agents connect to with `MCPClient`), and a **MemoryManager** with a custom store (SQLite FTS5 locally, **AgentCore Memory** on AWS).
- **Amazon Bedrock AgentCore Runtime** hosts the graph (CodeZip deploy via the AgentCore CLI), **AgentCore Memory** holds long-term volunteer and requester facts, and **AgentCore Observability** streams OTEL traces to CloudWatch. Models: Claude Sonnet 4.6 and Claude Haiku 4.5 on Amazon Bedrock.
- Around it: FastAPI on Lambda (Function URL with response streaming for SSE), DynamoDB, S3 session state, EventBridge Scheduler for the background sweep, and a React UI on CloudFront.
- A **volunteer simulator** (another Strands agent that role-plays each volunteer's persona) lets the demo show real negotiation without sending anyone a text.

## Challenges we ran into

- **Making "only surface when it matters" a property of the code, not the prompt.** Policy lives in a deterministic rule layer plus the intervention handler, with tests for every row of the policy table. The model decides *how* to help; the policy decides *whether* it may act alone.
- **Interrupts across processes.** A Decision Card can be answered hours later. Reconstructing the same graph with the same session id and feeding back an `interruptResponse` took care to get right, especially the de-duplication of interrupt ids across requests.
- **Concurrent tool calls.** When a model emits two tool calls in one turn, Strands runs them concurrently, and naive read-modify-write of a request row lost data. We moved to atomic field-level updates with optimistic versioning.
- **Testing without burning tokens.** A mock `Model` provider that emits real Strands stream events lets 500+ tests, and the full 24-message demo day, run with no AWS credentials.

## Accomplishments that we're proud of

- A coordinator can run a whole "Tuesday" of requests and read three cards instead of forty threads.
- The autonomy boundary is explicit, testable, and explainable: every autonomous action has a plain-English rationale in the Quiet Log.
- The whole thing is deployable with one command and runs on managed AgentCore services.

## What we learned

Strands interventions and interrupts are a natural fit for human-in-the-loop products: the pause is a first-class, resumable state rather than a bolted-on approval flow. And the Graph primitive made the multi-agent pipeline readable enough that the policy table in the README maps one-to-one onto edges and handlers.

## What's next for Porchlight

Real channels (SES email and SMS receipt are wired but disabled in the demo), a volunteer-facing reply flow, multi-group tenancy, and evaluation datasets built from the Quiet Log so groups can tune the policy thresholds to their own comfort level.

## Links

- Repository: https://github.com/fireheartjerry/porchlight (MIT)
- Live demo: TBD
- Architecture diagram: in the README
