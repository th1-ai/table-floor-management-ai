#!/usr/bin/env python3
"""tools/report.py - what the agent did, and what it cost.

    make report
    python tools/report.py --json

Everything here is computed from `data/agent.db` - nothing phoned home. See
docs/benefits.md for what each number means and its honest caveats.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import ConfigError, load_settings  # noqa: E402
from core.review import queue_summary  # noqa: E402
from core.store import Store, StoreError  # noqa: E402


def build_report(store: Store) -> dict:
    counts = store.counts()
    queue = queue_summary(store)
    usage = store.usage_totals()
    total_plans = sum(counts.values())
    sent = counts.get("sent", 0) + counts.get("auto_sent", 0)
    rejected = counts.get("rejected", 0)

    seated_total, parties_total, covers_total, warnings_total = 0, 0, 0, 0
    rows = store.db.execute(
        "SELECT payload_json FROM items WHERE kind='floor_plan'").fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            continue
        summary = ((payload.get("_plan") or {}).get("summary")) or {}
        seated_total += summary.get("seated", 0)
        parties_total += summary.get("parties", 0)
        covers_total += summary.get("covers", 0)
        warnings_total += summary.get("warning_count", 0)
    seat_rate = round(100 * seated_total / parties_total, 1) if parties_total else 0.0

    return {
        "total_plans": total_plans, "by_status": counts,
        "waiting_on_human": queue["waiting_on_human"], "sent": sent, "rejected": rejected,
        "parties_seen": parties_total, "parties_seated": seated_total,
        "seated_pct": seat_rate, "covers_planned": covers_total,
        "warnings_raised": warnings_total,
        "llm_calls": usage["calls"], "llm_cost_usd": round(usage["cost_usd"], 4),
    }


def print_human(report: dict, mode: str) -> None:
    print("Table / Floor Management AI - report\n")
    print(f"Mode: {mode}")
    print(f"Plans generated: {report['total_plans']}")
    print(f"Waiting for a host: {report['waiting_on_human']}")
    print(f"Sent to the floor/kitchen: {report['sent']}")
    print(f"Rejected: {report['rejected']}")
    print()
    print(f"Parties planned: {report['parties_seen']} "
         f"({report['parties_seated']} seated, {report['seated_pct']}%)")
    print(f"Covers planned: {report['covers_planned']}")
    print(f"Warnings raised across all plans: {report['warnings_raised']}")
    print()
    print(f"LLM calls: {report['llm_calls']} (the pre-service note only - the model never "
         f"seats a table) - cost so far: ${report['llm_cost_usd']}")
    if mode == "shadow":
        print("\nNote: mode is shadow, so 'sent' counts what actually reached the floor/kitchen "
             "- which is zero until you go live. See docs/benefits.md.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    try:
        store = Store(settings)
    except StoreError as exc:
        print(f"store error: {exc}", file=sys.stderr)
        return 1
    try:
        report = build_report(store)
    finally:
        store.close()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_human(report, settings.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
