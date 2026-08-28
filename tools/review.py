#!/usr/bin/env python3
"""tools/review.py - work the review queue: list / show / approve / edit / reject / send.

    python tools/review.py list [--status pending_review] [--kind floor_plan]
    python tools/review.py show <id>
    python tools/review.py approve <id> [--note "..."]
    python tools/review.py edit <id> --body-file note.txt [--note "..."]
    python tools/review.py reject <id> --reason "wrong tables"
    python tools/review.py retry <id>          # re-queue a failed send
    python tools/review.py send                # notify staff + export everything approved/edited
    python tools/review.py stale                # go-live step: clear the shadow-era backlog

Only this tool writes `approved` / `edited` / `rejected` (core/review.py). Only
`send` (here, mirroring tools/run.py's own pattern) writes `sending` / `sent`.
`send` never publishes a plan on its own initiative - it only acts on items a
human already approved or edited - and nothing here bypasses `mode: shadow`.
See docs/safety.md.

`--body-file` rewrites the pre-service note (`draft.narrative`), not the
seating plan itself - the plan is deterministic output from
tools/seating_engine.py and is not something a host edits by hand; to change
a plan, toggle a rule or simulate a walk-in (tools/run.py) and re-run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.adapters import get_messaging, get_sheets  # noqa: E402
from core.config import ConfigError, load_settings  # noqa: E402
from core.review import (WriteBlocked, approve, edit, list_queue, reject, retry,  # noqa: E402
                         show, stale_backlog)
from core.store import Store, StoreError  # noqa: E402


def _print_item_line(item) -> None:
    payload = item.payload or {}
    plan = payload.get("_plan") or {}
    summary = plan.get("summary") or {}
    label = f"day {payload.get('day_offset', '?')} {payload.get('service', '?')}"
    marker = "  [SAMPLE DATA]" if item.is_sample else ""
    print(f"  {item.id}  {item.review_status:<14} {label:<16} "
         f"seated={summary.get('seated', '-')}/{summary.get('parties', '-')} "
         f"warnings={summary.get('warning_count', '-')}{marker}")


def cmd_list(store, args) -> int:
    items = list_queue(store, status=args.status, kind=args.kind, limit=args.limit)
    if not items:
        print("Nothing is waiting for you.")
        return 0
    print(f"{len(items)} item(s) waiting:\n")
    for item in items:
        _print_item_line(item)
    if any(item.is_sample for item in items):
        print("\n[SAMPLE DATA] One or more plans above were built from the shipped "
             "sample fixtures, not your restaurant - systems.messaging.adapter is 'mock'. "
             "Connect your own systems (docs/integrations.md) before approving them.")
    print("\nRun `python3 tools/review.py show <id>` for the full plan.")
    return 0


def cmd_show(store, args) -> int:
    try:
        detail = show(store, args.id)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    payload = (detail.get("item") or {}).get("payload") or {}
    if payload.get("_sample"):
        print("[SAMPLE DATA] This plan was built from the shipped sample fixtures, not "
             "your restaurant - systems.messaging.adapter is 'mock'. Connect your own "
             "systems (docs/integrations.md) before approving it.\n")
    print(json.dumps(detail, indent=2, ensure_ascii=False, default=str))
    return 0


def cmd_approve(store, args) -> int:
    item = approve(store, args.id, note=args.note or "")
    print(f"approved {item.id} - now in the send queue")
    return 0


def cmd_edit(store, args) -> int:
    item = store.get_item(args.id)
    if item is None:
        print(f"error: no item {args.id}", file=sys.stderr)
        return 1
    text = Path(args.body_file).read_text(encoding="utf-8")
    new_draft = dict(item.draft or {})
    new_draft["narrative"] = text.strip()
    edit(store, args.id, new_draft, note=args.note or "")
    print(f"edited {item.id} - now in the send queue")
    return 0


def cmd_reject(store, args) -> int:
    item = reject(store, args.id, reason=args.reason or "")
    print(f"rejected {item.id}")
    return 0


def cmd_retry(store, args) -> int:
    item = retry(store, args.id)
    print(f"queued {item.id} for another send attempt")
    return 0


def _kitchen_rows(plan: dict) -> list[list]:
    return [[row.get("time", ""), row.get("party_name", ""),
            "+".join(row.get("table_ids", [])), row.get("covers", ""),
            ", ".join(row.get("dietary", []))]
           for row in (plan.get("kitchen_sheet") or [])]


def cmd_send(store, settings, args) -> int:
    claimed = store.claim_for_send(limit=args.limit)
    if not claimed:
        print("Nothing approved or edited is waiting to send.")
        return 0
    messaging = get_messaging(settings)
    sheets = get_sheets(settings)
    sent, failed = 0, 0
    for item in claimed:
        plan = (item.payload or {}).get("_plan") or {}
        draft = item.draft or {}
        summary = plan.get("summary") or {}
        note = draft.get("narrative") or "(no note)"
        text = (f"Seating plan - day {plan.get('day_offset')} {plan.get('service')}: "
               f"{summary.get('seated', 0)}/{summary.get('parties', 0)} parties seated, "
               f"{summary.get('warning_count', 0)} warning(s). {note}")
        try:
            result = messaging.notify_staff(text, item=item)
            kitchen_rows = _kitchen_rows(plan)
            if kitchen_rows:
                sheets.append("kitchen_sheet", kitchen_rows, item=item)
            sheets.append("floor_plans", [[item.id, plan.get("day_offset"), plan.get("service"),
                                           summary.get("seated"), summary.get("unseated"),
                                           summary.get("warning_count")]], item=item)
        except WriteBlocked as exc:
            # Not a failure: the mode blocked it. The approval stands for go-live.
            store.transition(item.id, "approved", "agent", {"blocked": str(exc)[:200]})
            print(f"blocked {item.id} (approval kept): {exc}")
            failed += 1
            continue
        except Exception as exc:  # noqa: BLE001 - record and move on, never crash the batch
            store.mark_send_failed(item.id, str(exc))
            print(f"failed {item.id}: {exc}")
            failed += 1
            continue
        message_id = result.get("message_id") if isinstance(result, dict) else None
        store.mark_sent(item.id, message_id)
        print(f"sent {item.id}")
        sent += 1
    print(f"\n{sent} sent, {failed} failed.")
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="what is waiting for a host")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--kind", default=None)
    p_list.add_argument("--limit", type=int, default=50)

    p_show = sub.add_parser("show", help="full detail for one plan")
    p_show.add_argument("id")

    p_approve = sub.add_parser("approve", help="approve the plan unchanged")
    p_approve.add_argument("id")
    p_approve.add_argument("--note", default="")

    p_edit = sub.add_parser("edit", help="rewrite the pre-service note, then queue it")
    p_edit.add_argument("id")
    p_edit.add_argument("--body-file", required=True)
    p_edit.add_argument("--note", default="")

    p_reject = sub.add_parser("reject", help="discard the plan")
    p_reject.add_argument("id")
    p_reject.add_argument("--reason", "--note", dest="reason", default="")

    p_retry = sub.add_parser("retry", help="re-queue a failed send")
    p_retry.add_argument("id")

    p_send = sub.add_parser("send", help="notify staff + export everything approved or edited")
    p_send.add_argument("--limit", type=int, default=20)

    sub.add_parser("stale", help="go-live step: mark everything still un-sent as stale "
                                 "(the shadow-era queue was never sent and is out of date)")

    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    store = Store(settings)
    try:
        if args.command == "list":
            return cmd_list(store, args)
        if args.command == "show":
            return cmd_show(store, args)
        if args.command == "approve":
            return cmd_approve(store, args)
        if args.command == "edit":
            return cmd_edit(store, args)
        if args.command == "reject":
            return cmd_reject(store, args)
        if args.command == "retry":
            return cmd_retry(store, args)
        if args.command == "send":
            return cmd_send(store, settings, args)
        if args.command == "stale":
            moved = stale_backlog(store)
            print(f"marked {len(moved)} item(s) stale. Nothing from before go-live will be sent.")
            return 0
        parser.error(f"unknown command {args.command}")
        return 2
    except StoreError as exc:
        print(f"cannot do that: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
