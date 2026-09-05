# Porchlight — demo video

`make video` → `media/out/porchlight-demo.mp4` (1920×1080, 30 fps, h264 + aac, **4:14**, limit 5:00) and
`media/out/thumbnail.png` (1920×1280, 3:2, for Devpost). Everything else under `media/out/` is a
regenerable intermediate and is gitignored; the thumbnail is the one file kept in the repo.

Everything in the film is the real application: a FastAPI app on `:8000` with `PORCHLIGHT_MODEL_PROVIDER=mock`,
the real React UI on `:5173`, driven by Playwright. Nothing is mocked for the camera and no frame is drawn by
hand. No AWS credentials are needed to produce it.

Judges must hear, explicitly: (1) the problem, (2) who it is for, (3) why it matters, and see the whole thing
work end to end. Every claim in the narration is on screen while it is said.

## Running order

Times are measured, not planned: each shot is exactly as long as its voiceover plus a 0.6 s tail.

| # | Time | Shot | Picture | What is said |
|---|------|------|---------|--------------|
| 1 | 0:00–0:32 | `01-title` | Title card: lantern lit, wordmark, tagline | Every group runs on one exhausted coordinator; every request becomes the same job, forty times a week, after her own work day. That is why coordinators burn out and good groups fold. |
| 2 | 0:32–0:45 | `02-track` | Track card: "Good Neighbor Agents" + persona | Porchlight, our Good Neighbor track entry: an autonomous dispatcher that does the coordinator's job for her. |
| 3 | 0:45–0:59 | `03-porch-quiet` | The Porch, lantern dim, "All quiet" | It runs the loop in the background and makes the safe calls itself. It only lights up when a decision needs a person. |
| 4 | 0:59–1:41 | `04-dialysis` | Inbox → typed request → send → Trace drawer read top to bottom → Quiet Log | Intake structures the message; the matcher scores on skills, distance, availability, fairness and memory; outreach writes and waits, and would work down the shortlist on a refusal; the steward confirms and schedules the reminder. Nobody touched it. |
| 5 | 1:41–2:24 | `05-safety` | "child home alone… smell gas" → lantern on → red Decision Card → "I'll handle this" → resumed | The policy layer stops everything before a volunteer is contacted. The autonomy boundary is explicit code: a Strands intervention returning `Confirm`, which raises an interrupt — and that interrupt *is* the Decision Card. Persisted, answerable hours later, resumes where it paused. |
| 6 | 2:24–2:48 | `06-tuesday` | "Run a Tuesday" (12) → progress → Porch counters → Volunteers roster | Twelve requests start to finish; nine handled without anyone, three surfaced with options attached. The load is spread and the memory notes keep growing. |
| 7 | 2:48–3:08 | `07-architecture` | `docs/architecture.png`, pushing in on the AgentCore half | Strands Agents end to end: five agents with structured outputs, a Graph with conditional edges and a bounded retry loop, hooks for the audit trail, MCP for the data tools, a memory manager. |
| 8 | 3:08–3:24 | `08-code-policy` | `porchlight/policy.py` — `before_tool_call` | Before every tool call the policy intervention decides: allow, guide, rewrite, or stop and ask. |
| 9 | 3:24–3:37 | `09-code-graph` | `porchlight/graph.py` — `GraphBuilder` | A node per agent, conditional edges on what the last agent returned, a retry loop that widens the pool. |
| 10 | 3:37–3:56 | `10-code-runtime` | `porchlight/runtime.py` — `BedrockAgentCoreApp` | AgentCore Runtime, AgentCore Memory, Observability in CloudWatch, Sonnet and Haiku on Bedrock, an EventBridge sweep overnight. |
| 11 | 3:56–4:14 | `11-closing` | Closing card: lantern, repo URL, "Live demo: see README" | Coordinators quit because it never stops. Porchlight gives them their evenings back and keeps the decisions that matter human. |

The exact spoken text lives in [`media/narration.json`](../media/narration.json) — that file is the single source
of truth for what is said, how long each shot is, and what the burned-in captions read.

## Producing it

```bash
make video          # ~6 minutes, cold, on a laptop
```

It starts the API and the UI, produces everything, and stops the servers again (even on Ctrl-C). Ports are
`MEDIA_API_PORT`/`MEDIA_WEB_PORT` if 8000/5173 are busy. Output lands in `media/out/` (gitignored).

The steps, in the order the target runs them:

1. **`media/tts.py`** — synthesizes one WAV per shot with macOS `say -v Samantha -r 175` and writes
   `media/out/vo/durations.json`. `--engine polly` is a drop-in for Amazon Polly (`Matthew`, `long-form` with a
   `neural` fallback) when AWS credentials exist; nothing downstream knows which one spoke.
   *This runs first on purpose*: the recorder and the cutter both take their clock from the measured voiceover,
   so speeding a line up or rewriting it re-times the picture automatically.
2. **`media/record.mjs`** — Playwright drives the real UI through shots 3–6 and records one `.webm` per shot at
   1440×900, starting from `POST /api/demo/reset`. Each shot is paced by a metronome expressed in *fractions of
   its own narration* (`pace.until(0.62)` = "hold here until the narrator is 62% through"), so the picture stays
   in step with the words. It also writes `media/out/clips.json` with the head-trim for each file.
3. **`media/render-cards.mjs`** — renders `media/cards/*.html` to PNG at 2× (3840×2160; the thumbnail at
   3840×2560). Those are the four title cards, the 3:2 thumbnail, and `05-frame` — the night-blue plate with the
   real CSS drop shadow that the screen recordings are composited onto.
4. **`media/code-cards.mjs`** — renders the three code close-ups. The snippets are *line ranges into the real
   source files*, each with an anchor string; if a range stops matching, the build fails rather than filming a
   stale screenshot.
5. **`media/assemble.py`** — cuts the film. Each shot becomes one 1920×1080 MP4 the exact length of its
   voiceover plus 0.6 s: a screencast is composited onto the plate at its native 1440×900 (no resampling at all,
   which is the crispest the UI type can be), freezing its last frame if it ran short; a still card gets a slow
   Ken Burns push cropped out of the 2× render, so the move only ever spends supersampling it already had.
   Captions are transparent PNGs overlaid on `enable=between(t,…)` windows. The shots are concatenated with
   `-c copy`, so the whole film is encoded exactly once (h264, crf 20, yuv420p). The voiceover is padded per
   shot, concatenated, normalized to −16 LUFS and faded. It prints the running order and **fails if the result
   is over 5:00**.

Two of those steps look unusual and are deliberate:

- **Captions are PNGs, not `drawtext`.** The ffmpeg in Homebrew is built without libfreetype, so `drawtext` and
  `subtitles` do not exist. Laying the type out in a browser (`media/captions.mjs`) is the better half of that
  trade anyway: real Inter, real kerning, real line breaking, and the same scrim treatment the app uses. The
  splitter breaks the narration into sentences and halves any sentence over 112 characters, so nothing ever runs
  past two lines.
- **The recording group's quiet hours are moved** (`PORCHLIGHT_QUIET_HOURS=[3,4]`, set only by the `video`
  target). After 21:00 the group's real policy holds outreach until morning — a good feature and a terrible
  forty-second story: the narration says "someone says yes" over a screen that would say "held until 8am", and
  which of the two you filmed would depend on what time you pressed `make`. Everything else is stock.

## Checking it

`media/assemble.py` already refuses to finish over 5:00. To check that the picture says what the narrator says:

```bash
ffmpeg -ss 79 -i media/out/porchlight-demo.mp4 -frames:v 1 media/out/frames/at-79s.png
```

`media/out/frames/` holds eight evenly spaced frames from the last verified cut.

## Publishing

Upload `media/out/porchlight-demo.mp4` to YouTube (public or unlisted-public) and use
`media/out/thumbnail.png` as the Devpost image and the video thumbnail.
