"""Synthesize the demo voiceover, one WAV per shot, and report the durations.

    python media/tts.py                    # macOS `say`, no credentials, no network
    python media/tts.py --engine polly     # Amazon Polly, when AWS credentials exist

Reads ``media/narration.json`` and writes ``media/out/vo/<shot>.wav`` (48 kHz mono
PCM, what ffmpeg wants) plus ``media/out/vo/durations.json``. That durations file
is the clock the rest of the pipeline runs on: ``media/record.mjs`` paces the
screen recordings against it, and ``media/assemble.py`` cuts every shot to it.

Two backends, one interface. ``say`` is the default because the pipeline has to
work on a laptop with no AWS credentials at all; ``polly`` is a drop-in for the
real thing — neural or long-form ``Matthew``, the voice docs/VIDEO.md asks for —
and is selected purely by ``--engine polly``. Nothing else in the pipeline knows
or cares which one spoke.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
NARRATION = HERE / "narration.json"

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"

#: Everything downstream is mixed at this rate; resampling once here keeps the
#: concat in assemble.py from having to think about it.
SAMPLE_RATE = 48_000


class SynthesisError(RuntimeError):
    """A backend could not produce audio for a line."""


@dataclass(frozen=True)
class Voice:
    """Which voice, how fast, from whom."""

    engine: str
    name: str
    rate: int
    polly_engine: str
    polly_fallback: str


# --------------------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------------------


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SynthesisError(f"{cmd[0]} failed: {result.stderr.strip() or result.stdout.strip()}")


def _to_wav(source: Path, target: Path) -> None:
    """Transcode whatever the backend produced into 48 kHz mono PCM."""
    _run(
        [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source),
            "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le",
            str(target),
        ]
    )  # fmt: skip


def synth_say(text: str, target: Path, voice: Voice) -> None:
    """macOS ``say`` → AIFF → WAV. No network, no credentials, no account."""
    if shutil.which("say") is None:
        raise SynthesisError("`say` is not on PATH — this backend is macOS only (try --engine polly)")
    aiff = target.with_suffix(".aiff")
    script = target.with_suffix(".txt")
    # `say -f` rather than an argv string: the narration has apostrophes and em
    # dashes in it, and a file never has to be quoted.
    script.write_text(text, encoding="utf-8")
    try:
        _run(["say", "-v", voice.name, "-r", str(voice.rate), "-f", str(script), "-o", str(aiff)])
        _to_wav(aiff, target)
    finally:
        aiff.unlink(missing_ok=True)
        script.unlink(missing_ok=True)


def synth_polly(text: str, target: Path, voice: Voice) -> None:
    """Amazon Polly → MP3 → WAV. Long-form if the voice supports it, else neural.

    This is the path docs/VIDEO.md describes for a machine that has AWS
    credentials. It is never taken by default, and the rest of the pipeline is
    identical either way.
    """
    try:
        import boto3  # noqa: PLC0415 - optional dependency, only for this backend
    except ImportError as error:  # pragma: no cover - depends on the machine
        raise SynthesisError("boto3 is not installed — `pip install boto3` for --engine polly") from error

    client = boto3.client("polly")
    mp3 = target.with_suffix(".mp3")
    last: Exception | None = None
    for engine in (voice.polly_engine, voice.polly_fallback):
        try:
            answer = client.synthesize_speech(
                Text=text,
                TextType="text",
                VoiceId=voice.name,
                Engine=engine,
                OutputFormat="mp3",
            )
            mp3.write_bytes(answer["AudioStream"].read())
            break
        except Exception as error:  # pragma: no cover - depends on the account
            last = error
    else:  # pragma: no cover - depends on the account
        raise SynthesisError(f"Polly refused every engine: {last}")

    try:
        _to_wav(mp3, target)
    finally:
        mp3.unlink(missing_ok=True)


BACKENDS = {"say": synth_say, "polly": synth_polly}


# --------------------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------------------


def duration_of(path: Path) -> float:
    """Seconds of audio in ``path``, from ffprobe."""
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SynthesisError(f"ffprobe could not read {path.name}: {result.stderr.strip()}")
    return round(float(result.stdout.strip()), 3)


def voice_for(narration: dict[str, Any], args: argparse.Namespace) -> Voice:
    """Merge narration.json's defaults with whatever the command line overrode."""
    say = narration.get("voice", {}).get("say", {})
    polly = narration.get("voice", {}).get("polly", {})
    default_name = polly.get("voice", "Matthew") if args.engine == "polly" else say.get("voice", "Samantha")
    return Voice(
        engine=args.engine,
        name=args.voice or default_name,
        rate=args.rate or int(say.get("rate", 175)),
        polly_engine=polly.get("engine", "long-form"),
        polly_fallback=polly.get("fallback_engine", "neural"),
    )


def main(argv: list[str] | None = None) -> int:
    """Synthesize every shot; return 0 on success."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine", choices=sorted(BACKENDS), default="say", help="which voice backend")
    parser.add_argument("--voice", default="", help="override the voice name")
    parser.add_argument("--rate", type=int, default=0, help="override words per minute (say only)")
    parser.add_argument("--out", default="", help="output root (default media/out)")
    parser.add_argument("--only", default="", help="synthesize a single shot id")
    args = parser.parse_args(argv)

    narration = json.loads(NARRATION.read_text(encoding="utf-8"))
    voice = voice_for(narration, args)
    out = Path(args.out or HERE / "out") / "vo"
    out.mkdir(parents=True, exist_ok=True)

    shots: dict[str, Any] = {}
    total = 0.0
    synth = BACKENDS[voice.engine]
    for shot in narration["shots"]:
        if args.only and shot["id"] != args.only:
            continue
        text = " ".join(shot["text"].split())
        target = out / f"{shot['id']}.wav"
        synth(text, target, voice)
        seconds = duration_of(target)
        total += seconds
        shots[shot["id"]] = {
            "seconds": seconds,
            "words": len(text.split()),
            "file": f"vo/{shot['id']}.wav",
        }
        print(f"  vo    {shot['id']}  {seconds:6.2f}s  {len(text.split()):3d} words")

    tail = float(narration.get("tail_seconds", 0.6))
    report = {
        "engine": voice.engine,
        "voice": voice.name,
        "rate": voice.rate if voice.engine == "say" else None,
        "sample_rate": SAMPLE_RATE,
        "tail_seconds": tail,
        "shots": shots,
        "speech_seconds": round(total, 2),
        "programme_seconds": round(total + tail * len(shots), 2),
    }
    (out / "durations.json").write_text(f"{json.dumps(report, indent=2)}\n", encoding="utf-8")
    minutes, seconds = divmod(report["programme_seconds"], 60)
    clock = f"{int(minutes)}:{seconds:04.1f}"
    print(f"{len(shots)} lines · {report['speech_seconds']}s of speech · programme {clock}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
