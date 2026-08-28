#!/usr/bin/env python3
"""tools/demo.py - the whole loop on the bundled fixtures, zero credentials.

    make demo
    python tools/demo.py

Forces `llm.provider=mock` and `mode=shadow` regardless of config/hotel.yaml
(`load_settings(demo=True)`), so this always works on a fresh clone with a
blank .env. Runs against its own database (`data/demo/demo.db`) so running it
twice always shows the same picture and never touches `data/agent.db` (that
is `make run`'s file). Every `one_pass(..., demo=True)` call below also pins
`tools/covers_book.py` to the bundled fixtures only (never `data/imports/`),
so this stays immune to a real property's own floor and book, whatever they
have already connected - see `tools/covers_book.py`'s module docstring.
Walks through the same three moments the source demo shows: seat tonight's
book (a 40-guest corporate group with two nut allergies among the other
bookings), throw it a walk-in six-top, then contrast what happens with table
joins turned off.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import ConfigError, load_settings, sub_data_dir  # noqa: E402
from core.log import summary_line  # noqa: E402
from core.store import Store, StoreError  # noqa: E402

from tools import covers_book  # noqa: E402
from tools.run import one_pass  # noqa: E402

DAY_OFFSET = 1
SERVICE = "dinner"


def _accumulate(total: dict, stats: dict) -> None:
    for key in ("processed", "drafted", "needs_human", "sent"):
        total[key] = total.get(key, 0) + stats.get(key, 0)


def main() -> int:
    try:
        settings = load_settings(demo=True)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    demo_db = sub_data_dir("demo") / "demo.db"
    if demo_db.exists():
        demo_db.unlink()  # every `make demo` is a clean, repeatable run
    try:
        store = Store(settings, path=demo_db)
    except StoreError as exc:
        print(f"store error: {exc}", file=sys.stderr)
        return 1

    print("Table / Floor Management AI demo - The Birchwood Room, fixtures/restaurant "
         "+ fixtures/inbound\n")
    total = {"processed": 0, "drafted": 0, "needs_human": 0, "sent": 0}

    print(f"Plan tonight's seating (day_offset={DAY_OFFSET}, {SERVICE}):\n")
    code, stats = one_pass(settings, store, day_offset=DAY_OFFSET, service=SERVICE,
                           provider="mock", demo=True)
    if code != 0:
        print("demo: the seating pass did not finish cleanly", file=sys.stderr)
        store.close()
        return 1
    _accumulate(total, stats)

    print("\nSimulate a walk-in six-top (tools/run.py --walk-in \"Six-top,6,20:15\"):\n")
    covers_book.insert_walkin(store, day_offset=DAY_OFFSET, service=SERVICE,
                              party_name="Six-top", party_size=6, time="20:15")
    code, stats = one_pass(settings, store, day_offset=DAY_OFFSET, service=SERVICE,
                           provider="mock", demo=True)
    if code != 0:
        print("demo: the walk-in re-plan did not finish cleanly", file=sys.stderr)
        store.close()
        return 1
    _accumulate(total, stats)

    print("\nContrast: turn 'Allow table joins' off and re-plan "
         "(tools/run.py --set-rule join-tables=off):\n")
    covers_book.set_rule(store, "join-tables", False)
    code, stats = one_pass(settings, store, day_offset=DAY_OFFSET, service=SERVICE,
                           provider="mock", demo=True)
    covers_book.set_rule(store, "join-tables", True)  # leave the demo book as shipped
    if code != 0:
        print("demo: the rule-off pass did not finish cleanly", file=sys.stderr)
        store.close()
        return 1
    _accumulate(total, stats)

    counts = store.counts()
    waiting = sum(counts.get(s, 0) for s in ("pending_review", "needs_human"))
    print(f"\n{waiting} plan(s) waiting for a host to review - a floor plan always does, "
         "see docs/safety.md.")
    print("Nothing was sent: mode is shadow, and demo never calls notify_staff() or "
         "sheets.append() on anything.")
    print("Next: `make review` to see what is waiting, or read workflows/10-seating.md.\n")

    print(f"DEMO OK — {summary_line(total, settings.mode)}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
