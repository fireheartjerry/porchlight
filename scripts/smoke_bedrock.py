"""Prove a real AWS account can run Porchlight: models first, then the graph.

Run this once, immediately after credentials exist and before anything is deployed. It answers
the two questions a deploy cannot answer for you:

1. **Are the configured models actually available to this account in this region?**
   ``bedrock:ListFoundationModels`` for the inventory, then a one-token ``Converse`` call against
   each configured model id — the only check that proves model access was granted, not just that
   the model exists.
2. **Does the real graph work against real models?** One routine sample (expected: handled
   quietly) and one safety sample (expected: a Decision Card) through the actual Strands graph
   with ``PORCHLIGHT_MODEL_PROVIDER=bedrock`` and a throwaway SQLite store.

Usage::

    python scripts/smoke_bedrock.py                     # both halves
    python scripts/smoke_bedrock.py --skip-graph        # just model access (cheap)
    python scripts/smoke_bedrock.py --region us-east-1  # somewhere else

Exit codes: ``0`` all good, ``1`` a check failed, ``2`` no credentials, ``3`` Porchlight is not
importable. Every failure prints what to do about it.
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from typing import Any

COLUMNS = 96

ROUTINE_SAMPLE = "sm_dialysis_ride"
"""A sample that should be handled quietly, end to end, with no coordinator involvement."""

SAFETY_SAMPLE = "sm_child_home_alone"
"""A sample that must stop at a red Decision Card instead of doing outreach."""

PING = "Reply with the single word: ok"
"""The cheapest possible Converse prompt — one token in, one token out."""


# --------------------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------------------


def rule(title: str = "", char: str = "-") -> str:
    """A horizontal rule with an optional inline title."""
    if not title:
        return char * COLUMNS
    return f"{char * 2} {title} " + char * max(0, COLUMNS - len(title) - 4)


def ok(stream: Any, message: str) -> None:
    """Print a passing check."""
    stream.write(f"  [ ok ] {message}\n")
    stream.flush()


def warn(stream: Any, message: str) -> None:
    """Print a non-fatal problem."""
    stream.write(f"  [warn] {message}\n")
    stream.flush()


def bad(stream: Any, message: str, hint: str = "") -> None:
    """Print a failing check, plus what to do about it."""
    stream.write(f"  [FAIL] {message}\n")
    for line in textwrap.wrap(hint, width=COLUMNS - 9):
        stream.write(f"         {line}\n")
    stream.flush()


# --------------------------------------------------------------------------------------
# Model checks
# --------------------------------------------------------------------------------------


def base_model_id(model_id: str) -> str:
    """Strip a cross-region inference prefix (``global.``, ``us.``, ``eu.``, ``apac.``)."""
    for prefix in ("global.", "us.", "eu.", "apac.", "us-gov."):
        if model_id.startswith(prefix):
            return model_id[len(prefix) :]
    return model_id


def check_credentials(region: str, stream: Any) -> bool:
    """Confirm boto3 has credentials, and print who they belong to."""
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
    except ImportError as exc:  # pragma: no cover - boto3 is a hard dependency
        bad(stream, f"boto3 is not importable: {exc}", "Run: make install")
        return False
    try:
        identity = boto3.client("sts", region_name=region).get_caller_identity()
    except NoCredentialsError:
        bad(
            stream,
            "no AWS credentials found",
            "Configure them first: aws configure sso, or export AWS_ACCESS_KEY_ID / "
            "AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN.",
        )
        return False
    except (ClientError, BotoCoreError) as exc:
        bad(stream, f"sts:GetCallerIdentity failed: {exc}", "The credentials exist but are not usable.")
        return False
    ok(stream, f"credentials: account {identity['Account']} as {identity['Arn'].rsplit('/', 1)[-1]}")
    return True


def check_inventory(region: str, model_ids: list[str], stream: Any) -> bool:
    """List the foundation models this account can see and report on the configured ids."""
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        response = boto3.client("bedrock", region_name=region).list_foundation_models()
    except (ClientError, BotoCoreError) as exc:
        bad(
            stream,
            f"bedrock:ListFoundationModels failed in {region}: {exc}",
            "The role needs bedrock:ListFoundationModels, and Bedrock must be available in this region.",
        )
        return False

    available = {str(summary.get("modelId", "")) for summary in response.get("modelSummaries", [])}
    ok(stream, f"bedrock:ListFoundationModels — {len(available)} models visible in {region}")

    healthy = True
    for model_id in model_ids:
        base = base_model_id(model_id)
        if base in available or any(entry.startswith(base) for entry in available):
            ok(stream, f"{model_id} — base model {base} is in the catalogue")
        else:
            # A global/system inference profile is not a foundation model, so this is a hint,
            # not a verdict. The Converse call below is what actually decides.
            warn(stream, f"{model_id} — no catalogue entry for {base}; relying on the Converse check")
    return healthy


def check_converse(region: str, model_id: str, stream: Any) -> dict[str, int] | None:
    """Send a one-token Converse call and return its usage, or ``None`` when it failed."""
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    client = boto3.client("bedrock-runtime", region_name=region)
    try:
        response = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": PING}]}],
            inferenceConfig={"maxTokens": 1, "temperature": 0.0},
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        hints = {
            "AccessDeniedException": (
                f"Grant model access to {model_id} in the Bedrock console "
                f"(Model access, region {region}), and give this role bedrock:InvokeModel."
            ),
            "ValidationException": (
                f"{model_id} was rejected by {region}. Check PORCHLIGHT_MODEL_SONNET / "
                "PORCHLIGHT_MODEL_HAIKU — a cross-region inference profile id ('global.', 'us.') "
                "is usually what you want."
            ),
            "ResourceNotFoundException": f"{model_id} does not exist in {region}.",
            "ThrottlingException": "Bedrock throttled the smoke test; wait and re-run.",
        }
        bad(stream, f"Converse {model_id}: {code or 'ClientError'} — {exc}", hints.get(code, ""))
        return None
    except BotoCoreError as exc:
        bad(stream, f"Converse {model_id} failed: {exc}", "Check the region and network access.")
        return None

    usage = {key: int(value) for key, value in (response.get("usage") or {}).items() if value is not None}
    detail = f"{usage.get('inputTokens', 0)} in, {usage.get('outputTokens', 0)} out"
    ok(stream, f"Converse {model_id} — {usage.get('totalTokens', 0)} tokens ({detail})")
    return usage


# --------------------------------------------------------------------------------------
# Graph check
# --------------------------------------------------------------------------------------


class UsageMeter:
    """Collects trace events and the token usage the model hook reports.

    Strands reports *cumulative* usage per agent, so the highest number seen for an agent is
    that agent's total; summing across agents gives the run total.
    """

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.per_agent: dict[str, dict[str, int]] = {}

    def __call__(self, event: dict[str, Any]) -> None:
        """Trace sink: record the event and fold in any usage it carries."""
        self.events.append(event)
        detail = event.get("detail") or {}
        usage = detail.get("usage") if isinstance(detail, dict) else None
        if not isinstance(usage, dict) or not usage:
            return
        agent = str(event.get("agent") or "?")
        current = self.per_agent.setdefault(agent, {})
        for key, value in usage.items():
            if isinstance(value, int):
                current[key] = max(current.get(key, 0), value)

    def totals(self) -> dict[str, int]:
        """Token totals across every agent that reported usage."""
        totals: dict[str, int] = {}
        for usage in self.per_agent.values():
            for key, value in usage.items():
                totals[key] = totals.get(key, 0) + value
        return totals


def run_sample(ctx: Any, orchestrator: Any, sample: dict[str, Any], stream: Any) -> tuple[bool, str]:
    """Push one sample message through the graph and judge the outcome against its expectation."""
    from porchlight.intake_ingest import create_request_from_inbox

    stream.write("\n" + rule(f"{sample['label']}  (expects: {sample['expected']})") + "\n")
    request = create_request_from_inbox(ctx, sample["text"], sample["source"], sample.get("contact"))
    try:
        outcome = orchestrator.process_request(request.id)
    except Exception as exc:  # noqa: BLE001 - the point of a smoke test is to report the failure
        bad(stream, f"{sample['id']} raised {type(exc).__name__}: {exc}", "See the traceback above.")
        return False, f"{type(exc).__name__}"

    needed_a_person = bool(outcome.interrupted or outcome.decisions_created)
    verdict = "card" if needed_a_person else "quiet"
    titles = ", ".join(d.title for d in outcome.decisions_created) or "-"
    stream.write(f"  request  : {outcome.request_id}\n")
    stream.write(f"  status   : {outcome.status}\n")
    stream.write(f"  outcome  : {verdict} ({titles})\n")
    stream.write(f"  log rows : {outcome.log_events}\n")

    if verdict == sample["expected"]:
        ok(stream, f"{sample['id']} behaved as expected ({verdict})")
        return True, verdict
    bad(
        stream,
        f"{sample['id']} expected {sample['expected']!r} but got {verdict!r}",
        "The models are reachable but the graph disagreed with the fixture. Re-run with "
        "PORCHLIGHT_MODEL_PROVIDER=mock to see whether it is the model or the code.",
    )
    return False, verdict


def check_graph(args: argparse.Namespace, stream: Any) -> bool:
    """Run one routine and one safety sample through the real graph on Bedrock."""
    from porchlight.config import Settings, reset_settings
    from porchlight.context import build_context
    from porchlight.orchestrator import LocalOrchestrator, graph_available
    from porchlight.sim.fixtures import sample_by_id, seed_store

    os.environ["PORCHLIGHT_MODEL_PROVIDER"] = "bedrock"
    os.environ["PORCHLIGHT_STORE"] = "sqlite"
    os.environ["PORCHLIGHT_AWS_REGION"] = args.region
    reset_settings()

    if not graph_available():
        bad(stream, "porchlight.graph is not importable", "Run: make install")
        return False

    settings = Settings(
        mode="demo",
        store="sqlite",
        model_provider="bedrock",
        sqlite_path=args.db,
        session_dir=args.session_dir,
        aws_region=args.region,
    )
    meter = UsageMeter()
    ctx = build_context(settings, emit=meter)
    counts = seed_store(ctx.store, ctx.clock, ctx.settings)
    ok(stream, f"seeded {counts['volunteers']} volunteers into {args.db}")

    samples = []
    for sample_id in (args.routine_sample, args.safety_sample):
        sample = sample_by_id(sample_id)
        if sample is None:
            bad(stream, f"no sample message {sample_id!r}", "See porchlight/sim/fixtures.py.")
            return False
        samples.append(dict(sample))

    orchestrator = LocalOrchestrator(ctx)
    results = [run_sample(ctx, orchestrator, sample, stream) for sample in samples]

    totals = meter.totals()
    stream.write("\n" + rule("TOKENS", "=") + "\n")
    if totals:
        stream.write(
            f"  {totals.get('totalTokens', 0)} tokens total — "
            f"{totals.get('inputTokens', 0)} in, {totals.get('outputTokens', 0)} out, "
            f"across {len(meter.per_agent)} agents\n"
        )
        for agent, usage in sorted(meter.per_agent.items()):
            stream.write(f"    {agent:<12} {usage.get('totalTokens', 0):>7} tokens\n")
    else:
        warn(stream, "no token usage reported (the provider did not attach metrics)")
    stream.write(f"  {len(meter.events)} trace events\n")

    return all(passed for passed, _ in results)


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(
        prog="smoke_bedrock.py",
        description="Check Bedrock model access, then run two samples through the real graph.",
    )
    parser.add_argument("--region", default=None, help="AWS region (default: the configured one)")
    parser.add_argument("--sonnet", default=None, help="Override the judgement-tier model id")
    parser.add_argument("--haiku", default=None, help="Override the fast-tier model id")
    parser.add_argument("--db", default="data/local/smoke.db", help="Throwaway SQLite path")
    parser.add_argument("--session-dir", default="data/sessions-smoke", help="Throwaway session dir")
    parser.add_argument("--routine-sample", default=ROUTINE_SAMPLE, help="Sample expected to run quietly")
    parser.add_argument("--safety-sample", default=SAFETY_SAMPLE, help="Sample expected to raise a card")
    parser.add_argument("--skip-models", action="store_true", help="Skip the Bedrock model checks")
    parser.add_argument("--skip-graph", action="store_true", help="Skip the graph run (models only)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, stream: Any = sys.stdout) -> int:
    """Run the smoke test and return a process exit code."""
    args = parse_args(argv)

    try:
        from porchlight.config import get_settings
    except ImportError as exc:
        stream.write(f"Porchlight is not importable: {exc}\nRun: make install\n")
        return 3

    settings = get_settings()
    args.region = args.region or settings.aws_region
    model_ids = [args.sonnet or settings.model_sonnet, args.haiku or settings.model_haiku]

    stream.write(rule("PORCHLIGHT SMOKE TEST", "=") + "\n")
    stream.write(f"  region : {args.region}\n")
    stream.write(f"  models : {', '.join(model_ids)}\n\n")

    if not check_credentials(args.region, stream):
        return 2

    healthy = True
    if args.skip_models:
        warn(stream, "skipping the model checks (--skip-models)")
    else:
        stream.write("\n" + rule("MODEL ACCESS") + "\n")
        healthy &= check_inventory(args.region, model_ids, stream)
        for model_id in model_ids:
            healthy &= check_converse(args.region, model_id, stream) is not None

    if args.skip_graph:
        warn(stream, "skipping the graph run (--skip-graph)")
    elif not healthy:
        warn(stream, "skipping the graph run because the model checks failed")
    else:
        stream.write("\n" + rule("GRAPH ON BEDROCK") + "\n")
        healthy &= check_graph(args, stream)

    stream.write("\n" + rule("RESULT", "=") + "\n")
    if healthy:
        stream.write("  Everything passed. Deploy with: make deploy\n")
        return 0
    stream.write("  Something failed — see the [FAIL] lines above. Nothing was deployed.\n")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
