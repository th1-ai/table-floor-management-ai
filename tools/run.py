#!/usr/bin/env python3
"""tools/run.py - Table / Floor Management AI's main loop: load the book ->
plan the service -> queue for a host -> narrate.

    python tools/run.py --once
    python tools/run.py --once --day-offset 0 --service lunch
    python tools/run.py --once --dry-run
    python tools/run.py --once --provider mock
    python tools/run.py --once --walk-in "Six-top,6,20:15"
    python tools/run.py --set-rule join-tables=off
    python tools/run.py --watch

The seating plan (tools/seating_engine.py) never sends or writes anything
external on its own - it only proposes. workflows/80-review.md and
docs/safety.md cover the review queue; nothing here notifies staff or
exports a sheet until a host approves (tools/review.py send).

Exit codes: 0 ok, 3 waiting on an `interactive` narrative answer, 1 a real
error, 2 a bad --set-rule / --walk-in argument.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.adapters.base import AdapterError  # noqa: E402
from core.config import ConfigError, Settings, load_settings  # noqa: E402
from core.llm import LLMError, LLMPendingInteractive, complete  # noqa: E402
from core.log import Run, get_logger, summary_line  # noqa: E402
from core.store import Item, Store, StoreError  # noqa: E402
from core.templates import build_prompt  # noqa: E402

from tools import covers_book  # noqa: E402
from tools.covers_book import CoversBookError  # noqa: E402
from tools.seating_engine import run_seating_plan  # noqa: E402

log = get_logger("run")
SCHEMA_PATH = REPO_ROOT / "prompts" / "schemas" / "dining_note.json"


def _needs_human(plan_dict: dict, allergy_on: bool) -> bool:
    """A booking that could not be seated, a hidden nut allergy, or a
    dietary note that may describe an allergy this repo could not classify,
    always needs a person - see docs/how-it-works.md "Nothing seats a
    walk-in or changes a plan without a person" and docs/safety.md."""
    if plan_dict["unseated"]:
        return True
    warnings_lower = [w.lower() for w in plan_dict["warnings"]]
    if any("may describe an allergy" in w for w in warnings_lower):
        return True
    if not allergy_on:
        return any("nut allergy" in w for w in warnings_lower)
    return False


def _parse_walkin(spec: str) -> tuple[str, int, str]:
    parts = [p.strip() for p in spec.split(",", 2)]
    if len(parts) != 3:
        raise ValueError('expected "Name,PartySize,HH:MM", e.g. "Six-top,6,20:15"')
    name, size_s, time_s = parts
    if not name:
        raise ValueError("party name cannot be blank")
    try:
        size = int(size_s)
    except ValueError:
        raise ValueError(f"party size must be a whole number, got {size_s!r}") from None
    if size < 1:
        raise ValueError(f"party size must be at least 1, got {size}")
    if not re.fullmatch(r"\d{1,2}:\d{2}", time_s):
        raise ValueError(f'time must be HH:MM (24-hour), got {time_s!r}')
    return name, size, time_s


def _parse_set_rule(spec: str) -> tuple[str, bool]:
    if "=" not in spec:
        raise ValueError('expected "<rule-key>=on" or "<rule-key>=off"')
    key, _, value = spec.partition("=")
    key, value = key.strip(), value.strip().lower()
    if value not in ("on", "off"):
        raise ValueError(f'value must be "on" or "off", got {value!r}')
    return key, value == "on"


def _compute_plan(settings: Settings, store: Store, *, day_offset: int,
                  service: str, demo: bool = False) -> tuple[list, list, dict, dict]:
    """Load the book and run the deterministic engine. No item is written here.

    ``demo=True`` (only ``tools/demo.py`` and the test fixtures pass it)
    pins the book to the bundled fixtures and never looks at
    ``data/imports/*.csv`` - see ``tools/covers_book.py``'s module docstring
    and docs/how-it-works.md "The loop, step by step" #1.
    """
    covers_book.ensure_seeded(settings, store, demo=demo)
    tables = covers_book.get_tables(store)
    covers = covers_book.get_covers(store, day_offset=day_offset, service=service)
    rules = covers_book.get_rules(store)
    cfg = settings.agent
    hold_zones = cfg.get("hold_zones") or ["Window", "Terrace"]
    result = run_seating_plan(
        tables, covers, rules, day_offset=day_offset, service=service,
        late_cutoff=str(cfg.get("late_cutoff", "20:15")),
        banquet_factor=float(cfg.get("banquet_factor", 1.15)),
        zone_cover_cap=int(cfg.get("zone_cover_cap", 24)),
        hold_zones=tuple(str(z) for z in hold_zones))
    return tables, covers, rules, result.as_dict()


def _get_or_create_item(store: Store, *, day_offset: int, service: str,
                        tables: list, covers: list, rules: dict, plan_dict: dict) -> Item:
    """Find (or start) the item for this exact book + rule state.

    Same fingerprint -> same item -> a retry after an interactive pause
    resumes it. A different fingerprint (a walk-in, a rule toggle) always
    starts a fresh item - see docs/how-it-works.md "Idempotency".
    """
    fingerprint = covers_book.book_fingerprint(tables, covers, rules)
    external_id = f"{day_offset}-{service}-{fingerprint}"
    item = store.upsert_item("seating", external_id, kind="floor_plan",
                             payload={"day_offset": day_offset, "service": service})
    if item.payload.get("_plan") is None:
        item = store.set_fields(item.id, payload={**item.payload, "_plan": plan_dict}) or item
    return item


def _narrate(settings: Settings, store: Store, item: Item, plan_dict: dict, *,
            provider: str | None) -> Item:
    """Best-effort: an LLMError never blocks a plan that already exists -
    see docs/how-it-works.md "Narration never blocks the plan". A pending
    interactive prompt is NOT an LLMError and propagates untouched."""
    if item.draft is not None and "narrative" in item.draft:
        return item  # already attempted (success or a graceful None)
    restaurant_name = settings.agent_get("restaurant.name", "the restaurant")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    note_item = {"summary": plan_dict["summary"], "warnings": plan_dict["warnings"],
                "kitchen_sheet": plan_dict["kitchen_sheet"], "unseated": plan_dict["unseated"]}
    # "dining-note-01" is the demo's own canned fixture
    # (fixtures/expected/dining_note/dining-note-01.json) - only meaningful for
    # the mock provider. Every other provider (interactive, above all) gets a
    # fixture_id derived from this item's own id: core.llm._pending_id() uses
    # fixture_id verbatim as the pending-prompt filename, so a hardcoded
    # constant here meant every pending dining_note prompt landed on the same
    # data/pending/dining_note-dining-note-01.* files - a second walk-in's
    # prompt silently overwrote the first one's before it was ever answered.
    # item.id is stable per item (core.store.upsert_item) and unique across
    # items, so two pending items now always get two separate files.
    effective_provider = provider or settings.llm.provider
    fixture_id = "dining-note-01" if effective_provider == "mock" else f"item-{item.id}"
    prompt = build_prompt("dining_note", settings=settings, item=note_item,
                          fixture_id=fixture_id, restaurant_name=restaurant_name)
    try:
        result = complete("dining_note", prompt, schema, settings=settings, provider=provider,
                          store=store, item_id=item.id, fixture_id=fixture_id)
        narrative = (result.data or {}).get("note")
    except LLMPendingInteractive:
        raise
    except LLMError as exc:
        log.warn("dining_note skipped", error=str(exc)[:200])
        narrative = None
    return store.set_fields(item.id, draft={"narrative": narrative}) or item


def _queue(store: Store, item: Item, plan_dict: dict, allergy_on: bool) -> Item:
    if item.review_status != "new":
        return item
    status = "needs_human" if _needs_human(plan_dict, allergy_on) else "pending_review"
    return store.transition(item.id, status, actor="agent", detail={
        "seated": plan_dict["summary"]["seated"], "unseated": plan_dict["summary"]["unseated"],
        "warnings": plan_dict["summary"]["warning_count"]})


def one_pass(settings: Settings, store: Store, *, day_offset: int, service: str,
            provider: str | None, demo: bool = False) -> tuple[int, dict]:
    """``demo=True`` (only ``tools/demo.py`` and the test fixtures pass it)
    pins the book to the bundled fixtures for this pass - see
    ``_compute_plan``."""
    stats = {"processed": 0, "drafted": 0, "needs_human": 0, "sent": 0}
    with Run("seating", settings, None if settings.dry_run else store) as run:
        tables, covers, rules, plan_dict = _compute_plan(
            settings, store, day_offset=day_offset, service=service, demo=demo)

        for line in plan_dict["thinking_log"]:
            print(f"  - {line['text']}")

        if settings.dry_run:
            stats["processed"] = 1
            stats["drafted"] = 1
            if _needs_human(plan_dict, rules.get("allergy-flag", True)):
                stats["needs_human"] = 1
            run.stats = dict(stats)
            print("\n--dry-run: nothing written - no item row, no LLM usage event, no "
                 "queue entry.\n")
            return 0, stats

        item = _get_or_create_item(store, day_offset=day_offset, service=service,
                                   tables=tables, covers=covers, rules=rules,
                                   plan_dict=plan_dict)
        try:
            item = _narrate(settings, store, item, plan_dict, provider=provider)
        except LLMPendingInteractive as exc:
            run.stats = dict(stats)
            print(str(exc))
            return 3, stats
        item = _queue(store, item, plan_dict, rules.get("allergy-flag", True))

        stats["processed"] = 1
        stats["drafted"] = 1
        if item.review_status == "needs_human":
            stats["needs_human"] = 1
        if item.draft and item.draft.get("narrative"):
            print(f"\nNote: {item.draft['narrative']}\n")
        log.info("queued", item_id=item.id, status=item.review_status,
                 seated=plan_dict["summary"]["seated"], unseated=plan_dict["summary"]["unseated"])
        reaped = store.reap_stuck_sending()
        if reaped:
            log.warn("reaped stuck sends", count=len(reaped))
        run.stats = dict(stats)
    return 0, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--once", action="store_true", help="plan one service (default)")
    mode_group.add_argument("--watch", action="store_true",
                            help="keep planning on the configured interval")
    parser.add_argument("--dry-run", action="store_true",
                        help="compute the plan, write nothing, even in live mode")
    parser.add_argument("--day-offset", type=int, default=1,
                        help="0 = today, 1 = tomorrow (default)")
    parser.add_argument("--service", default="dinner", choices=["lunch", "dinner"],
                        help="which service to plan (default: dinner)")
    parser.add_argument("--provider", default=None, help="override llm.provider for this run")
    parser.add_argument("--walk-in", default=None, metavar="NAME,SIZE,HH:MM",
                        help='insert a walk-in into the book and re-plan, e.g. '
                             '--walk-in "Six-top,6,20:15"')
    parser.add_argument("--set-rule", default=None, metavar="KEY=on|off",
                        help="toggle a dining rule (turn-time, join-tables, vip-window, "
                             "server-balance, allergy-flag), then exit without planning")
    parser.add_argument("--poll-seconds", type=int, default=None,
                        help="override the --watch interval (default: agent.yaml or 3600)")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(provider=args.provider, dry_run=args.dry_run)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    store = Store(settings)
    try:
        covers_book.ensure_seeded(settings, store)

        if args.set_rule:
            try:
                key, enabled = _parse_set_rule(args.set_rule)
                result = covers_book.set_rule(store, key, enabled)
            except (ValueError, CoversBookError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            print(f"{result['key']}: {'on' if result['enabled'] else 'off'}. Re-run `make run` "
                 "to see the new plan.")
            return 0

        if args.walk_in:
            try:
                name, size, time_s = _parse_walkin(args.walk_in)
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            if settings.dry_run:
                print(f"--dry-run: would book {name}, party of {size}, at {time_s}. "
                     "Nothing written.")
            else:
                cover = covers_book.insert_walkin(store, day_offset=args.day_offset,
                                                  service=args.service, party_name=name,
                                                  party_size=size, time=time_s)
                print(f"Walk-in booked: {cover.party_name}, party of {cover.party_size}, "
                     f"{cover.time}. Re-planning day_offset={args.day_offset} "
                     f"{args.service}...\n")

        if args.watch:
            poll_seconds = args.poll_seconds or int(settings.agent_get("poll_seconds", 3600))
            while True:
                code, stats = one_pass(settings, store, day_offset=args.day_offset,
                                       service=args.service, provider=args.provider)
                print(summary_line(stats, settings.mode))
                if code != 0:
                    return code
                time.sleep(poll_seconds)
        code, stats = one_pass(settings, store, day_offset=args.day_offset,
                               service=args.service, provider=args.provider)
        print(summary_line(stats, settings.mode))
        return code
    except AdapterError as exc:
        print(f"integration error: {exc}", file=sys.stderr)
        print("Run `make doctor` to see what is missing and how to fix it.", file=sys.stderr)
        return 1
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except StoreError as exc:
        print(f"store error: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
