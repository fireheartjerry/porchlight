# Agents for Humans: building Porchlight, an autonomous mutual-aid dispatcher with Strands Agents and AgentCore

*Working title for builder.aws.com. Must contain "Agents for Humans" in the title. Publish before the deadline.*

Every neighborhood mutual-aid group has the same bottleneck: one coordinator, one phone, forty unread messages. Most of those messages are routine ("can someone drive my mom to dialysis Thursday?"). A few are not ("my neighbour's kid is home alone"). The coordinator has to read all of them to find the few.

Porchlight is my entry for the Agents for Humans hackathon (Good Neighbor track). It's an agent that runs the whole coordination loop, intake, matching, outreach, follow-up, on its own, and only interrupts a human for decisions that should be human. This post is about the one design decision that made everything else fall into place: **using Strands interventions and interrupts as the autonomy boundary.**

## The problem with "ask the model to be careful"

The obvious approach is a system prompt: "if the request involves safety or money, ask the coordinator." It doesn't hold up. The model decides *how* to help; it shouldn't also be the only thing deciding *whether* it's allowed to act alone.

Strands has a better primitive. An `InterventionHandler` sits between the agent and every tool call and returns a typed decision:

```python
from strands.interventions import Confirm, Deny, Guide, InterventionHandler, Proceed, Transform

class PorchlightPolicy(InterventionHandler):
    name = "porchlight-policy"

    def before_tool_call(self, event):
        request = current_request(event)
        if event.tool_use["name"] not in SIDE_EFFECT_TOOLS:
            return Proceed()
        if has_danger_language(request):
            return Deny(reason="danger language: autonomous outreach is not allowed")
        if is_quiet_hours(now()):
            return Guide(feedback="It's quiet hours. Use schedule_message for 8am instead.")
        if request.money_involved and not already_approved(request, "money"):
            return Confirm(prompt="Money is involved. Approve?", reason=card_json(request, kind="money"))
        return Transform(apply=redact_private_details)
```

`Confirm` raises a Strands **interrupt**. The graph stops, the `GraphResult` comes back with `status == INTERRUPTED` and a list of interrupts, and we turn each one into a Decision Card row. Hours later, when the coordinator taps an option, we rebuild the same graph with the same session id and resume:

```python
graph = build_graph(ctx, session_id=request_id)
result = graph([{"interruptResponse": {"interruptId": card.interrupt_id,
                                       "response": {"option": "approve", "note": note}}}],
               invocation_state={"ctx": ctx, "request_id": request_id})
```

The pause is a first-class, persisted, resumable state. Nothing about it is bolted on.

## The rest of the pipeline

- Five agents (intake, matcher, outreach, steward, brief), each with a Pydantic `structured_output_model`.
- A `GraphBuilder` graph: intake → matcher → outreach → steward, with conditional edges (safety and money branches, a bounded retry cycle when a volunteer declines, a short-circuit for messages that aren't requests).
- Hooks for the audit trail: every tool call becomes a plain-English line in the coordinator's Quiet Log.
- A `MemoryManager` with a custom store: SQLite FTS5 locally, AgentCore Memory in production, so "Maria was great with Mr. Okafor" survives across sessions.
- MCP for the data tools, agents-as-tools for reply interpretation.

## Deploying on AgentCore

The graph runs on Amazon Bedrock AgentCore Runtime as a CodeZip deploy (no containers) through the AgentCore CLI, with AgentCore Memory for long-term facts and AgentCore Observability for traces. The API is FastAPI on Lambda, the UI is React on CloudFront, and an EventBridge sweep does reminders and escalations hourly.

*(Add: screenshots of a Decision Card and the trace panel, the architecture diagram, a link to the repo and the demo video.)*

Repo: https://github.com/fireheartjerry/porchlight
