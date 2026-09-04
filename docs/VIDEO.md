# Porchlight — demo video (≤ 5:00, target 4:30)

Format: 1920×1080, 30 fps. Screen capture of The Porch (Playwright screencast, 1440×900 scaled up with a
soft shadow on the night-blue background) + a few full-frame title cards. Voiceover: warm, unhurried
(Polly "Matthew" neural / long-form if AWS is available, else macOS premium voice). Light ambient bed,
-24 LUFS. Captions burned in (short lines, bottom center) for accessibility and for judges watching muted.

Judges must hear, explicitly: (1) the problem, (2) who it is for, (3) why it matters, and see the whole
thing work end-to-end. Every claim below is shown on screen, not just said.

| # | Time | Shot | Narration (VO) |
|---|------|------|----------------|
| 1 | 0:00–0:20 | Title card: lantern dim → glows. "Porchlight — runs the coordination, lights up only when you're needed." | Every mutual-aid group, food pantry and volunteer team runs on one exhausted coordinator. Requests come in by text, email, forms and paper slips — and every one of them turns into the same job: figure out who can help, ask three people, wait, ask two more, confirm, remind, follow up. Forty times a week. |
| 2 | 0:20–0:40 | Card: "Good Neighbor Agents" + persona line. Cut to The Porch, Porch screen, lantern dim, "All quiet". | This is Porchlight, our entry for the Good Neighbor track. It's an autonomous dispatcher for neighborhood groups. It does the whole loop in the background and makes the safe calls itself. It only turns the porch light on when a real decision needs a human. |
| 3 | 0:40–1:40 | Inbox: paste "Hi, my mom needs a ride to dialysis Thursday 7am, Riverside, she uses a walker". Send. Trace drawer open on the right: intake → matcher → outreach; volunteer sim replies; first declines, second accepts; steward confirms. Quiet Log fills in. Requests board shows card moving to Confirmed. | Here's a request exactly as it arrives. Watch the trace. The intake agent turns it into a structured job — category, time window, zone, the walker constraint. The matcher scores volunteers on skills, distance, availability, and fairness, and recalls long-term memory: "Maria did great with Mrs. Okafor last month." Outreach messages Maria first — she's busy — so it moves to Dev, who says yes. The steward confirms with the family and schedules a reminder. Nobody had to touch it. It shows up in the Quiet Log, with the reasoning, in plain English. |
| 4 | 1:40–2:35 | Inbox: paste "my neighbor's 6 year old is home alone and I can smell gas". Lantern turns on. Porch shows a red Decision Card: context, recommendation ("Call the requester now and advise 911; Porchlight has paused all outreach"), options. Tap "I'll handle it". Card resolves; log shows "resumed". | Now a different message. The intake agent flags it; the policy layer stops everything. This is the whole idea: Porchlight's autonomy boundary is explicit code — a Strands intervention that returns Confirm, which raises an interrupt. That interrupt *is* the Decision Card. It's persisted, so the coordinator can answer hours later from her phone, and the agent graph resumes exactly where it paused. Safety, money, vetting a new requester, an urgent job nobody can cover — those come to a human. Everything else stays quiet. |
| 5 | 2:35–3:20 | Inbox: "Run a Tuesday". Progress bar; requests stream through; counters climb: "17 handled quietly · 3 need you". Quick scroll of Quiet Log. Volunteers screen: load bars balanced, memory notes. | Here's a whole Tuesday. Twenty requests. Seventeen handled without anyone. Three surfaced: a request for help paying a power bill, a first-time requester asking for in-home help, and a same-day ride nobody could take — each with options, not homework. And look at the volunteers: the load is spread, and the memory notes keep growing, so next week's matches are better than this week's. |
| 6 | 3:20–4:05 | Architecture card (docs/architecture.png), then code flashes: `policy.py` (Confirm/Deny/Guide/Transform), `graph.py` (GraphBuilder, conditional edges), `runtime.py` (BedrockAgentCoreApp), AgentCore console: runtime, memory, observability trace. | Under the hood it's Strands Agents end to end: five agents with structured outputs, orchestrated as a Strands Graph with conditional edges and a bounded retry loop; interventions for policy; hooks for the audit trail; MCP for the data tools; a MemoryManager backed by AgentCore Memory. It runs on Amazon Bedrock AgentCore Runtime, with AgentCore Observability traces in CloudWatch, Claude Sonnet and Haiku on Bedrock, and an EventBridge sweep that does follow-ups and escalations while everyone sleeps. |
| 7 | 4:05–4:30 | Closing card: lantern, repo URL, "Try it: <live demo URL>". | Coordinators don't quit because the work is hard. They quit because it never stops. Porchlight gives them back their evenings and keeps the important decisions human. Porchlight: it runs the coordination, and lights up only when you're needed. |

## Production pipeline (`media/`)
1. `media/record.mjs` — Playwright script that drives the real app (API in mock or Bedrock mode) through shots 2–5,
   using `page.video` (1440×900) with deliberate pauses; it also captures shot 6 code close-ups by rendering
   highlighted snippets as HTML.
2. `media/cards/*.html` — title cards rendered with Playwright to PNG (1920×1080).
3. `media/narration.json` — per-shot VO text; `media/tts.py` synthesizes per-shot audio (Polly neural
   `Matthew`, `engine=long-form` if available, else `say -v "Ava (Premium)"`), reports durations.
4. `media/assemble.py` — ffmpeg: scale/pad each clip to 1920×1080, trim to VO length (+0.6 s tail), concat,
   overlay captions (drawtext from narration.json), mix VO + bed, export `media/out/porchlight-demo.mp4`
   and a `thumbnail.png` (3:2 crop for Devpost).
5. Upload to YouTube (public/unlisted-public) — done by the user or via the YouTube tab in Chrome.
