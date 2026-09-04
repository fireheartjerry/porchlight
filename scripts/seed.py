"""Seed the local Porchlight store with the Maple Street Mutual Aid fixtures.

Usage::

    python scripts/seed.py                       # seed the configured store
    python scripts/seed.py --db data/local/x.db  # seed a specific sqlite file
    python scripts/seed.py --frozen              # date the history from the demo epoch
"""

from __future__ import annotations

import argparse
import sys

from porchlight.clock import FrozenClock, SystemClock
from porchlight.config import Settings, get_settings
from porchlight.sim.fixtures import DEMO_EPOCH, seed_store
from porchlight.store import make_store


def main(argv: list[str] | None = None) -> int:
    """Seed the store and print what was written."""
    parser = argparse.ArgumentParser(description="Seed the Porchlight demo data.")
    parser.add_argument("--db", help="SQLite path to seed (overrides PORCHLIGHT_SQLITE_PATH)")
    parser.add_argument(
        "--frozen",
        action="store_true",
        help=f"Date the seeded history relative to the demo epoch ({DEMO_EPOCH.isoformat()})",
    )
    args = parser.parse_args(argv)

    settings: Settings = get_settings()
    if args.db:
        settings = settings.model_copy(update={"sqlite_path": args.db, "store": "sqlite"})

    store = make_store(settings)
    clock = FrozenClock(DEMO_EPOCH) if args.frozen else SystemClock()
    counts = seed_store(store, clock)

    target = args.db or (settings.sqlite_path if settings.store == "sqlite" else settings.dynamo_table)
    print(
        f"Seeded {counts['volunteers']} volunteers, {counts['requesters']} requesters, "
        f"{counts['requests']} past requests into {target}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
