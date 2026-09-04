"""Run a day of neighbourhood requests through Porchlight, live, in the terminal.

Usage::

    python scripts/run_day.py --mock --reset            # a full Tuesday, no AWS
    python scripts/run_day.py --count 3                 # just the first three samples
    python scripts/run_day.py --sample-id sm_stove_child_alone   # one specific message

Prints a narrated trace while the graph works, then a summary of what was handled quietly and
what needed the coordinator.
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from typing import Any

COLUMNS = 100
"""Total width of the narration, so the trace stays readable in a demo recording."""

TYPE_LABELS: dict[str, str] = {
    "node_start": "node",
    "node_end": "node",
    "tool_call": "tool",
    "tool_result": "result",
    "model_call": "model",
    "message": "msg",
    "decision": "CARD",
    "log": "log",
    "policy": "policy",
    "demo_progress": "day",
}


def _label(event: dict[str, Any]) -> str:
    """Short column label for a trace event type."""
    return TYPE_LABELS.get(str(event.get("type")), str(event.get("type"))[:6])


class Narrator:
    """Prints trace events as aligned columns: ``agent | type | summary``."""

    def __init__(self, stream: Any = sys.stdout, verbose: bool = True) -> None:
        """Create a narrator writing to ``stream``."""
        self.stream = stream
        self.verbose = verbose
        self.events: list[dict[str, Any]] = []

    def __call__(self, event: dict[str, Any]) -> None:
        """Record and (optionally) print one trace event."""
        self.events.append(event)
        if not self.verbose:
            return
        agent = str(event.get("agent") or "-")[:10]
        kind = _label(event)[:6]
        summary = str(event.get("summary") or "")
        width = COLUMNS - 22
        wrapped = textwrap.wrap(summary, width=width) or [""]
        self.stream.write(f"  {agent:<10}  {kind:<6}  {wrapped[0]}\n")
        for line in wrapped[1:]:
            self.stream.write(f"  {'':<10}  {'':<6}  {line}\n")
        self.stream.flush()


def _rule(title: str = "", char: str = "-") -> str:
    """A horizontal rule with an optional inline title."""
    if not title:
        return char * COLUMNS
    return f"{char * 2} {title} " + char * max(0, COLUMNS - len(title) - 4)


def _build_settings(args: argparse.Namespace) -> Any:
    """Settings for this run, honouring ``--mock`` and ``--db``."""
    from porchlight.config import Settings, reset_settings

    if args.mock:
        os.environ["PORCHLIGHT_MODEL_PROVIDER"] = "mock"
        reset_settings()
    overrides: dict[str, Any] = {"mode": "demo", "store": "sqlite"}
    if args.mock:
        overrides["model_provider"] = "mock"
    if args.db:
        overrides["sqlite_path"] = args.db
    return Settings(**overrides)


def _pick_samples(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Choose which sample messages to run, in demo order."""
    from porchlight.sim.fixtures import SAMPLE_MESSAGES, demo_sequence, sample_by_id

    if args.sample_id:
        sample = sample_by_id(args.sample_id)
        if sample is None:
            ids = ", ".join(s["id"] for s in SAMPLE_MESSAGES)
            raise SystemExit(f"no sample {args.sample_id!r}. Available: {ids}")
        return [dict(sample)]
    return [dict(sample) for sample in demo_sequence(args.count)]


def _summary_table(rows: list[dict[str, Any]], stream: Any) -> None:
    """Print the per-request result table."""
    stream.write("\n" + _rule("SUMMARY", "=") + "\n")
    header = f"  {'request':<16}  {'sample':<26}  {'status':<14}  {'outcome'}\n"
    stream.write(header)
    stream.write("  " + "-" * (COLUMNS - 4) + "\n")
    for row in rows:
        stream.write(
            f"  {row['request_id']:<16}  {row['sample'][:26]:<26}  "
            f"{row['status'][:14]:<14}  {row['outcome']}\n"
        )


def _decision_table(decisions: list[Any], stream: Any) -> None:
    """Print every decision card the run produced."""
    if not decisions:
        stream.write("\n  No decision cards. Porchlight handled the whole day on its own.\n")
        return
    stream.write("\n" + _rule("NEEDS YOU", "=") + "\n")
    for decision in decisions:
        kind = str(getattr(decision, "kind", "policy"))
        title = str(getattr(decision, "title", "")) or "(untitled)"
        options = ", ".join(getattr(decision, "option_ids", list)() or []) or "-"
        stream.write(f"  [{kind:<9}] {title}\n")
        stream.write(f"  {'':<11} options: {options}\n")


def run(args: argparse.Namespace, stream: Any = sys.stdout) -> int:
    """Execute the day and return a process exit code."""
    try:
        from porchlight.context import build_context
        from porchlight.intake_ingest import create_request_from_inbox
        from porchlight.orchestrator import GraphUnavailableError, LocalOrchestrator, graph_available
        from porchlight.sim.fixtures import seed_store
    except ImportError as exc:  # pragma: no cover - broken checkout
        stream.write(f"Porchlight is not importable: {exc}\n")
        return 2

    settings = _build_settings(args)
    narrator = Narrator(stream=stream, verbose=not args.quiet)
    ctx = build_context(settings, emit=narrator)

    if args.reset or not ctx.store.list_volunteers():
        counts = seed_store(ctx.store, ctx.clock)
        stream.write(
            f"Seeded {counts['volunteers']} volunteers and {counts['requesters']} neighbours "
            f"into {settings.sqlite_path}.\n"
        )

    if not graph_available():
        stream.write(
            "\nporchlight.graph is not available yet, so there is nothing to run the requests\n"
            "through. The store, fixtures, and orchestrator are wired and ready; re-run this\n"
            "script once the graph module lands.\n"
        )
        return 3

    samples = _pick_samples(args)
    orchestrator = LocalOrchestrator(ctx)
    stream.write(
        f"\n{settings.group_name} — running {len(samples)} request(s) "
        f"with the {settings.model_provider} model provider.\n"
    )

    rows: list[dict[str, Any]] = []
    decisions: list[Any] = []
    quiet = 0
    needed = 0

    for index, sample in enumerate(samples, start=1):
        stream.write("\n" + _rule(f"{index}/{len(samples)}  {sample['label']}") + "\n")
        stream.write(f"  from {sample.get('contact') or 'unknown'} via {sample['source']}\n")
        for line in textwrap.wrap(sample["text"], width=COLUMNS - 6):
            stream.write(f"      {line}\n")
        stream.write("\n")

        request = create_request_from_inbox(ctx, sample["text"], sample["source"], sample.get("contact"))
        try:
            outcome = orchestrator.process_request(request.id)
        except GraphUnavailableError as exc:  # pragma: no cover - guarded above
            stream.write(f"  graph unavailable: {exc}\n")
            return 3
        except Exception as exc:  # noqa: BLE001 - one bad request must not stop the day
            stream.write(f"  run failed: {type(exc).__name__}: {exc}\n")
            rows.append(
                {
                    "request_id": request.id,
                    "sample": sample["label"],
                    "status": "error",
                    "outcome": f"{type(exc).__name__}: {exc}"[:40],
                }
            )
            continue

        if outcome.interrupted or outcome.decisions_created:
            needed += 1
            verdict = "needs you"
            titles = [d.title for d in outcome.decisions_created]
            detail = f"needs you — {titles[0]}" if titles else "needs you"
        else:
            quiet += 1
            verdict = "handled quietly"
            detail = verdict
        decisions.extend(outcome.decisions_created)
        rows.append(
            {
                "request_id": outcome.request_id,
                "sample": sample["label"],
                "status": str(outcome.status),
                "outcome": detail[:38],
            }
        )
        stream.write(f"  -> {verdict}\n")

    _summary_table(rows, stream)
    stream.write(
        f"\n  {quiet} handled quietly · {needed} needed the coordinator · "
        f"{len(narrator.events)} trace events\n"
    )
    _decision_table(decisions, stream)
    stream.write("\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Command-line interface for the demo runner."""
    parser = argparse.ArgumentParser(
        prog="run_day",
        description="Push sample neighbourhood requests through Porchlight and narrate the trace.",
    )
    parser.add_argument("--count", type=int, default=None, help="How many sample messages to run")
    parser.add_argument("--mock", action="store_true", help="Use the mock model provider (no AWS)")
    parser.add_argument("--sample-id", help="Run one specific sample message by id")
    parser.add_argument("--reset", action="store_true", help="Reseed the fixtures before running")
    parser.add_argument("--db", help="SQLite path to use (overrides PORCHLIGHT_SQLITE_PATH)")
    parser.add_argument("--quiet", action="store_true", help="Suppress the live trace narration")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the day."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
