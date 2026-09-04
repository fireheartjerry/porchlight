"""Read what ``agentcore deploy`` recorded, and hand it to the app stack.

The AgentCore CLI writes ``agentcore/.cli/deployed-state.json`` after every deploy — that file
is committed on purpose, and it is the only place the runtime ARN and the memory id exist
without an AWS call. ``make deploy-runtime`` runs this to produce ``.env.deploy``; ``make
deploy`` reads the same values back as CDK context for ``infra/``.

Usage::

    python agentcore/deployed_state.py                    # KEY=VALUE lines
    python agentcore/deployed_state.py --write .env.deploy
    python agentcore/deployed_state.py --format cdk-context
    python agentcore/deployed_state.py --key PORCHLIGHT_AGENT_RUNTIME_ARN

Exits non-zero with a readable message when the project has not been deployed yet, so a
Makefile step fails loudly rather than writing an empty file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

STATE_PATH = Path(__file__).resolve().parent / ".cli" / "deployed-state.json"
DEFAULT_TARGET = "default"
RUNTIME_NAME = "Porchlight"
MEMORY_NAME = "PorchlightMemory"

RUNTIME_ARN_KEY = "PORCHLIGHT_AGENT_RUNTIME_ARN"
MEMORY_ID_KEY = "PORCHLIGHT_MEMORY_ID"

CDK_CONTEXT_KEYS = {RUNTIME_ARN_KEY: "runtimeArn", MEMORY_ID_KEY: "memoryId"}

__all__ = ["deployed_values", "main", "merge_dotenv", "read_state"]


def read_state(path: Path = STATE_PATH) -> dict[str, Any]:
    """Load ``deployed-state.json``.

    Args:
        path: Where the CLI keeps its state.

    Raises:
        SystemExit: When the file is missing or unreadable.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"{path} does not exist — run `make deploy-runtime` first") from None
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"could not read {path}: {error}") from error


def deployed_values(state: dict[str, Any], target: str = DEFAULT_TARGET) -> dict[str, str]:
    """Pull the runtime ARN and memory id for ``target`` out of the CLI's state.

    Args:
        state: The parsed ``deployed-state.json``.
        target: The deployment target name from ``agentcore/aws-targets.json``.

    Returns:
        ``{"PORCHLIGHT_AGENT_RUNTIME_ARN": ..., "PORCHLIGHT_MEMORY_ID": ...}``; the memory
        entry is omitted when no memory has been deployed.

    Raises:
        SystemExit: When the target has no deployed runtime.
    """
    targets = state.get("targets") or {}
    resources = (targets.get(target) or {}).get("resources") or {}
    runtime = (resources.get("runtimes") or {}).get(RUNTIME_NAME) or {}
    arn = runtime.get("runtimeArn")
    if not arn:
        raise SystemExit(
            f"no deployed runtime {RUNTIME_NAME!r} for target {target!r} in {STATE_PATH} — "
            "run `make deploy-runtime` first"
        )

    values = {RUNTIME_ARN_KEY: str(arn)}
    memory = (resources.get("memories") or {}).get(MEMORY_NAME) or {}
    memory_id = memory.get("memoryId") or next(iter(runtime.get("memoryIds") or []), None)
    if memory_id:
        values[MEMORY_ID_KEY] = str(memory_id)
    return values


def _render(values: dict[str, str], style: str) -> str:
    """Format the values as dotenv lines or as ``cdk`` context arguments."""
    if style == "cdk-context":
        return " ".join(f"-c {CDK_CONTEXT_KEYS[key]}={value}" for key, value in values.items())
    return "\n".join(f"{key}={value}" for key, value in values.items())


def merge_dotenv(path: Path, values: dict[str, str]) -> str:
    """Return ``path``'s contents with ``values`` replacing (or appended to) its own keys.

    ``.env.deploy`` is shared: this writes the two AgentCore lines, and ``make deploy-infra``
    writes the app stack's outputs into the same file. Neither may clobber the other.

    Args:
        path: The dotenv file, which need not exist yet.
        values: The keys this module owns.

    Returns:
        The full new contents, newline-terminated.
    """
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    kept = [line for line in existing if line.split("=", 1)[0].strip() not in values]
    lines = [*kept, *(f"{key}={value}" for key, value in values.items())]
    return "\n".join(line for line in lines if line.strip()) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Print (or write) the deployed runtime ARN and memory id."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--target", default=DEFAULT_TARGET, help="deployment target name")
    parser.add_argument("--format", default="dotenv", choices=("dotenv", "cdk-context"))
    parser.add_argument("--key", help=f"print one value only ({RUNTIME_ARN_KEY} or {MEMORY_ID_KEY})")
    parser.add_argument("--write", type=Path, help="write the dotenv lines to this file too")
    args = parser.parse_args(argv)

    values = deployed_values(read_state(), args.target)
    if args.key:
        if args.key not in values:
            raise SystemExit(f"{args.key} is not in the deployed state")
        print(values[args.key])
        return 0

    rendered = _render(values, args.format)
    if args.write:
        args.write.write_text(merge_dotenv(args.write, values), encoding="utf-8")
        print(f"wrote {args.write}", file=sys.stderr)
    print(rendered)
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())
