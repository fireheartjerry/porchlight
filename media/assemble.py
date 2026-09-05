"""Cut the demo video: clips + cards + voiceover + captions → one MP4.

    python media/assemble.py

Inputs (all produced by the other steps of `make video`):

    media/narration.json          what is said, and over which picture
    media/out/vo/*.wav            the voiceover, one file per shot
    media/out/vo/durations.json   how long each line actually runs
    media/out/clips/*.webm        the screen recordings (media/record.mjs)
    media/out/clips.json          how much head to trim off each one
    media/out/cards/*.png         title cards + the plate the clips sit on
    media/out/code/*.png          the shot-6 code close-ups

Outputs:

    media/out/porchlight-demo.mp4   1920×1080, 30 fps, h264 + aac
    media/out/thumbnail.png         1920×1280 (3:2, for Devpost)

How it is put together. Every shot becomes one 1920×1080 MP4 exactly as long as
its voiceover plus a short tail, so the programme is the sum of what is said and
nothing drifts. A screen recording is composited onto the night-blue plate that
already carries its drop shadow (the shadow is a real CSS box-shadow, baked into
media/cards/05-frame.html, not an ffmpeg approximation); if the recording is
short it freezes on its last frame, if it is long it is cut. A still card gets a
slow Ken Burns push, cropped 1:1 out of a 2× render so the move never softens
it. Captions are transparent PNGs overlaid on an `enable=between(t,…)` window —
this ffmpeg has no libfreetype, and browser-set Inter reads better than drawtext
would anyway. The shots are then concatenated without re-encoding, so the whole
film is encoded exactly once.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
NARRATION = HERE / "narration.json"

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
NODE = shutil.which("node") or "node"

WIDTH, HEIGHT, FPS = 1920, 1080, 30
#: Where the 1440×900 screencast sits on the 1920×1080 plate. It is drawn at its
#: native size — no resampling at all, which is the crispest the UI type can be —
#: and must match the rounded rectangle in media/cards/05-frame.html.
SCREEN = {"x": 240, "y": 10, "w": 1440, "h": 900}
#: The 3:2 still Devpost and YouTube want.
THUMBNAIL = (1920, 1280)
#: Hard ceiling from docs/VIDEO.md; the hackathon rejects anything longer.
MAX_SECONDS = 300.0
#: A caption longer than this is split; two lines of Inter 42px is the limit.
CAPTION_CHARS = 112


class AssemblyError(RuntimeError):
    """Something the pipeline needs is missing or ffmpeg refused a step."""


# --------------------------------------------------------------------------------------
# Shell helpers
# --------------------------------------------------------------------------------------


def run(cmd: list[str], what: str) -> None:
    """Run a command, raising with its stderr if it fails."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = "\n".join((result.stderr or result.stdout).strip().splitlines()[-12:])
        raise AssemblyError(f"{what} failed:\n{tail}")


def ffmpeg(args: list[str], what: str) -> None:
    """Run ffmpeg quietly."""
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], what)


def probe_size(path: Path) -> tuple[int, int]:
    """Pixel dimensions of a video's first stream."""
    result = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    width, _, height = result.stdout.strip().partition("x")
    return (int(width), int(height)) if width and height else (0, 0)


def probe_duration(path: Path) -> float:
    """Seconds in a media file."""
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssemblyError(f"ffprobe could not read {path}")
    return float(result.stdout.strip())


def clock(seconds: float) -> str:
    """m:ss.s, the way a running order is written."""
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}:{rest:04.1f}"


# --------------------------------------------------------------------------------------
# Captions
# --------------------------------------------------------------------------------------


def _split_long(line: str, limit: int) -> list[str]:
    """Break one over-long sentence at the punctuation nearest its middle."""
    if len(line) <= limit:
        return [line]
    breaks = [m.end() for m in re.finditer(r"(?:,|;|:|—|–)\s+", line)]
    if not breaks:
        breaks = [m.end() for m in re.finditer(r"\s+", line)]
    if not breaks:
        return [line]
    middle = len(line) / 2
    cut = min(breaks, key=lambda index: abs(index - middle))
    left, right = line[:cut].strip(), line[cut:].strip()
    if not left or not right:
        return [line]
    return _split_long(left, limit) + _split_long(right, limit)


def split_captions(text: str, limit: int = CAPTION_CHARS) -> list[str]:
    """One caption per sentence, with long sentences broken in half."""
    flat = " ".join(text.split())
    out: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", flat):
        if sentence.strip():
            out.extend(_split_long(sentence.strip(), limit))
    return out


@dataclass
class Caption:
    """One line of burned-in text and the window it is on screen for."""

    text: str
    start: float
    end: float
    png: Path


def time_captions(lines: list[str], speech: float, folder: Path, shot_id: str) -> list[Caption]:
    """Spread ``lines`` across ``speech`` seconds, weighted by how much there is to say."""
    if not lines:
        return []
    # A short line still needs a beat to land, hence the constant.
    weights = [len(line) + 14 for line in lines]
    total = sum(weights)
    captions: list[Caption] = []
    at = 0.0
    for index, (line, weight) in enumerate(zip(lines, weights, strict=True)):
        span = speech * weight / total
        end = speech if index == len(lines) - 1 else at + span
        captions.append(Caption(line, round(at, 3), round(end, 3), folder / f"{shot_id}-{index:02d}.png"))
        at = end
    return captions


def render_captions(captions: list[Caption], folder: Path) -> None:
    """Draw every caption PNG in one Playwright pass."""
    if not captions:
        return
    folder.mkdir(parents=True, exist_ok=True)
    jobs = [{"file": str(caption.png), "text": caption.text} for caption in captions]
    jobs_path = folder / "jobs.json"
    jobs_path.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
    result = subprocess.run(
        [NODE, str(HERE / "captions.mjs"), str(jobs_path)], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise AssemblyError(f"caption rendering failed:\n{result.stderr.strip()}")
    for line in result.stdout.strip().splitlines():
        print(line)


# --------------------------------------------------------------------------------------
# Shots
# --------------------------------------------------------------------------------------


@dataclass
class Shot:
    """One entry in the running order, resolved to real files and real seconds."""

    id: str
    kind: str
    text: str
    speech: float
    duration: float
    picture: Path
    trim: float = 0.0
    ken: dict[str, float] = field(default_factory=dict)
    captions: list[Caption] = field(default_factory=list)


def ken_burns(shot: Shot, frames: int) -> str:
    """A slow push on a still, always downscaling out of the 2× render.

    The card PNGs are 3840×2160, so zoom 1 already shows the whole card at a
    2:1 downscale and zoom 1.08 still has 3.5k pixels of width to draw 1920
    from. The move never has to invent detail — it only spends some of the
    supersampling it started with.
    """
    start = shot.ken.get("from", 1.0)
    end = shot.ken.get("to", 1.07)
    focus_x = shot.ken.get("x", 0.5)
    focus_y = shot.ken.get("y", 0.5)
    span = max(frames - 1, 1)
    zoom = f"{start}+({end}-{start})*min(on/{span},1)"
    return (
        f"zoompan=z='{zoom}':x='(iw-iw/zoom)*{focus_x}':y='(ih-ih/zoom)*{focus_y}'"
        f":d=1:fps={FPS}:s={WIDTH}x{HEIGHT},setsar=1"
    )


def build_shot(shot: Shot, out: Path) -> Path:
    """Render one shot to its own MP4 — picture, motion, captions, no audio."""
    target = out / "shots" / f"{shot.id}.mp4"
    target.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, round(shot.duration * FPS))

    inputs: list[str] = []
    steps: list[str] = []

    if shot.kind == "clip":
        plate = out / "cards" / "05-frame.png"
        if not plate.exists():
            raise AssemblyError(f"{plate} is missing — run `node media/render-cards.mjs` first")
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{shot.duration:.3f}", "-i", str(plate)]
        inputs += ["-i", str(shot.picture)]
        steps.append(f"[0:v]scale={WIDTH}:{HEIGHT}:flags=lanczos,setsar=1,fps={FPS}[bg]")
        # The recording is 1440×900 and so is its window on the plate, so the
        # scaler only ever runs if one of the two is changed.
        native = probe_size(shot.picture)
        scaled = f"scale={SCREEN['w']}:{SCREEN['h']}:flags=lanczos,"
        resize = "" if native == (SCREEN["w"], SCREEN["h"]) else scaled
        # trim → scale → freeze the last frame forever → cut to length. That
        # order means a clip that ran short holds on what it ended on, and a clip
        # that ran long simply stops; neither case needs a second pass.
        steps.append(
            f"[1:v]fps={FPS},trim=start={shot.trim:.3f},setpts=PTS-STARTPTS,"
            f"{resize}setsar=1,"
            f"tpad=stop_mode=clone:stop_duration=600,"
            f"trim=duration={shot.duration:.3f},setpts=PTS-STARTPTS[ui]"
        )
        steps.append(f"[bg][ui]overlay={SCREEN['x']}:{SCREEN['y']}[v0]")
        next_input = 2
    else:
        inputs += [
            "-loop", "1", "-framerate", str(FPS), "-t", f"{shot.duration:.3f}", "-i", str(shot.picture),
        ]  # fmt: skip
        steps.append(f"[0:v]{ken_burns(shot, frames)}[v0]")
        next_input = 1

    label = "[v0]"
    for index, caption in enumerate(shot.captions):
        inputs += ["-i", str(caption.png)]
        nxt = f"[vc{index}]"
        steps.append(
            f"{label}[{next_input + index}:v]"
            f"overlay=0:0:enable='between(t,{caption.start:.3f},{caption.end:.3f})'{nxt}"
        )
        label = nxt

    steps.append(f"{label}format=yuv420p[out]")

    ffmpeg(
        [
            *inputs,
            "-filter_complex",
            ";".join(steps),
            "-map",
            "[out]",
            "-frames:v",
            str(frames),
            "-r",
            str(FPS),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-profile:v",
            "high",
            "-level",
            "4.1",
            "-x264-params",
            "keyint=60:min-keyint=30:scenecut=0",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(target),
        ],  # fmt: skip
        f"shot {shot.id}",
    )
    return target


# --------------------------------------------------------------------------------------
# Sound
# --------------------------------------------------------------------------------------


def build_audio(shots: list[Shot], out: Path) -> Path:
    """Lay the voiceover onto the running order, normalized to −16 LUFS."""
    voice = out / "vo"
    target = out / "voiceover.wav"
    inputs: list[str] = []
    chain: list[str] = []
    for index, shot in enumerate(shots):
        wav = voice / f"{shot.id}.wav"
        if not wav.exists():
            raise AssemblyError(f"{wav} is missing — run `python media/tts.py` first")
        inputs += ["-i", str(wav)]
        # Pad each line out to its shot's length, so the picture and the words
        # can never slide apart no matter what happens upstream.
        chain.append(
            f"[{index}:a]aresample=48000,apad,atrim=duration={shot.duration:.3f},asetpts=N/SR/TB[a{index}]"
        )
    joined = "".join(f"[a{index}]" for index in range(len(shots)))
    total = sum(shot.duration for shot in shots)
    chain.append(f"{joined}concat=n={len(shots)}:v=0:a=1[cat]")
    chain.append(
        "[cat]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,"
        f"afade=t=in:st=0:d=0.7,afade=t=out:st={max(total - 1.2, 0):.3f}:d=1.2[out]"
    )
    ffmpeg(
        [
            *inputs,
            "-filter_complex",
            ";".join(chain),
            "-map",
            "[out]",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(target),
        ],  # fmt: skip
        "voiceover mix",
    )
    return target


# --------------------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------------------


def resolve_shots(narration: dict[str, Any], out: Path) -> list[Shot]:
    """Turn narration.json into shots with real files, real durations, real captions."""
    durations_path = out / "vo" / "durations.json"
    if not durations_path.exists():
        raise AssemblyError(f"{durations_path} is missing — run `python media/tts.py` first")
    measured = json.loads(durations_path.read_text(encoding="utf-8"))

    clips_path = out / "clips.json"
    clips: dict[str, dict[str, Any]] = {}
    if clips_path.exists():
        clips = {row["id"]: row for row in json.loads(clips_path.read_text(encoding="utf-8"))}

    tail = float(narration.get("tail_seconds", 0.6))
    captions_dir = out / "captions"
    shots: list[Shot] = []
    for entry in narration["shots"]:
        shot_id = entry["id"]
        kind = entry["kind"]
        speech = float(measured["shots"][shot_id]["seconds"])
        duration = round(speech + tail, 3)

        if kind == "clip":
            row = clips.get(shot_id)
            if row is None:
                raise AssemblyError(f"no recording for {shot_id} — run `node media/record.mjs` first")
            picture = out / row["file"]
            trim = float(row.get("trim", 0.0))
        elif kind == "code":
            picture, trim = out / "code" / f"{shot_id}.png", 0.0
        else:
            picture, trim = out / "cards" / f"{entry['card']}.png", 0.0
        if not picture.exists():
            raise AssemblyError(f"{picture} is missing")

        shot = Shot(
            id=shot_id,
            kind=kind,
            text=entry["text"],
            speech=speech,
            duration=duration,
            picture=picture,
            trim=trim,
            ken=entry.get("ken", {}),
        )
        shot.captions = time_captions(split_captions(shot.text), speech, captions_dir, shot_id)
        shots.append(shot)
    return shots


def main(argv: list[str] | None = None) -> int:
    """Assemble the film; return 0 if it is under the time limit."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="", help="output root (default media/out)")
    parser.add_argument("--name", default="porchlight-demo.mp4", help="output file name")
    args = parser.parse_args(argv)

    out = Path(args.out or HERE / "out")
    narration = json.loads(NARRATION.read_text(encoding="utf-8"))
    shots = resolve_shots(narration, out)

    render_captions([caption for shot in shots for caption in shot.captions], out / "captions")

    print("\n  running order")
    at = 0.0
    parts: list[Path] = []
    for shot in shots:
        parts.append(build_shot(shot, out))
        print(
            f"  {clock(at):>6}  {shot.id:<16} {shot.kind:<5} {shot.duration:5.1f}s"
            f"  {len(shot.captions)} caption(s)"
        )
        at += shot.duration

    listing = out / "shots" / "concat.txt"
    listing.write_text("".join(f"file '{path.name}'\n" for path in parts), encoding="utf-8")
    silent = out / "picture.mp4"
    # -c copy: every shot was already encoded to the delivery settings, so the
    # film is encoded exactly once and the concat is a remux.
    ffmpeg(
        ["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(silent)],
        "concatenating the shots",
    )

    voiceover = build_audio(shots, out)

    final = out / args.name
    ffmpeg(
        [
            "-i",
            str(silent),
            "-i",
            str(voiceover),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            "-shortest",
            str(final),
        ],  # fmt: skip
        "muxing the voiceover",
    )

    thumbnail = out / "thumbnail.png"
    ffmpeg(
        [
            "-i",
            str(out / "cards" / "06-thumbnail.png"),
            "-vf",
            f"scale={THUMBNAIL[0]}:{THUMBNAIL[1]}:flags=lanczos",
            "-frames:v",
            "1",
            str(thumbnail),
        ],  # fmt: skip
        "thumbnail",
    )

    length = probe_duration(final)
    size_mb = final.stat().st_size / 1_000_000
    print(f"\n  {final}")
    print(f"  {clock(length)}  ({length:.1f}s)  {size_mb:.1f} MB  {WIDTH}×{HEIGHT} {FPS}fps h264+aac")
    print(f"  {thumbnail}  {THUMBNAIL[0]}×{THUMBNAIL[1]}")

    if length > MAX_SECONDS:
        over = length - MAX_SECONDS
        print(f"\nFAIL: {clock(length)} is {over:.1f}s over the {clock(MAX_SECONDS)} limit", file=sys.stderr)
        return 1
    print(f"  under the {clock(MAX_SECONDS)} limit by {MAX_SECONDS - length:.1f}s")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssemblyError as error:
        print(f"\n{error}", file=sys.stderr)
        sys.exit(1)
