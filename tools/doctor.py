#!/usr/bin/env python3
"""tools/doctor.py - is Table / Floor Management AI configured and reachable
right now?

    make doctor
    python tools/doctor.py

Runs the generic core.doctor checks (python, deps, config, .env, hotel
identity, mode, llm provider, every adapter, the store, knowledge) plus this
agent's own: the five dining rules, the prompt files, and where the floor
book (floor_tables / covers) is actually being read from - a CSV you
supplied, or the demo fixtures. "floor book" runs the *same*
`covers_book.ensure_seeded` re-import `tools/run.py` calls before every
pass, against a throwaway in-memory store - never the real `data/agent.db` -
so the counts printed are exactly what the next `make run` would load, not
a stale snapshot from whenever the database first got seeded. Exits 0 when
everything passed, 1 when a FAIL line needs fixing. Never a traceback.
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import ConfigError, Settings, load_settings  # noqa: E402
from core.doctor import Check, FAIL, PASS, WARN, print_table, run_checks  # noqa: E402
from core.store import Store  # noqa: E402

from tools import covers_book  # noqa: E402

EXPECTED_RULES = {"turn-time", "join-tables", "vip-window", "server-balance", "allergy-flag"}


def check_dining_rules(settings: Settings) -> Check:
    configured = settings.agent_get("dining_rules", {}) or {}
    missing = EXPECTED_RULES - set(configured)
    if missing:
        return Check("dining rules", FAIL,
                     f"config/agent.yaml is missing: {', '.join(sorted(missing))}",
                     "Copy config/agent.example.yaml to config/agent.yaml - it ships with "
                     "all five rules seeded on.")
    off = [k for k, v in configured.items()
          if isinstance(v, dict) and not v.get("enabled", True)]
    return Check("dining rules", PASS,
                 f"{len(configured)} rule(s) configured" + (f", off: {', '.join(off)}" if off
                                                             else ", all on"))


def check_book_sources() -> Check:
    sources = covers_book.sources_used()
    none_configured = [k for k, v in sources.items() if v == "none configured"]
    detail = "; ".join(f"{k}: {v}" for k, v in sources.items())
    if none_configured:
        return Check("floor book sources", WARN, detail,
                     "No data/imports/*.csv and no fixtures/inbound/*.json for "
                     f"{', '.join(none_configured)} - see docs/integrations.md.")
    return Check("floor book sources", PASS, detail)


def _probe_store() -> Store:
    """A throwaway, in-memory store - never the hotel's own `data/agent.db` -
    so doctor can run the exact re-import `tools/run.py` calls before every
    pass without touching real state."""
    return Store(None, path=":memory:")


def check_seeded_state(settings: Settings) -> Check:
    try:
        with _probe_store() as probe:
            counts = covers_book.ensure_seeded(settings, probe)
            n_tables = counts["floor_tables"]
            n_covers = counts["restaurant_covers"]
    except Exception as exc:  # noqa: BLE001 - doctor must always print a table
        return Check("floor book", FAIL, f"could not load the floor book: {exc}"[:160],
                     "Check data/imports/floor_tables.csv / covers.csv for bad rows - "
                     "see docs/integrations.md.")
    if not n_tables:
        return Check("floor book", FAIL, "no floor_tables rows",
                     "Add fixtures/restaurant/floor_tables.json (ships with the repo) or "
                     "data/imports/floor_tables.csv.")
    return Check("floor book", PASS,
                 f"{n_tables} table(s), {n_covers} booking(s) - the exact counts the next "
                 "`make run` will load")


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).casefold().strip()


def check_hold_zones(settings: Settings) -> Check:
    """`vip-window`'s occasion hold only ever fires on a zone name in
    `config/agent.yaml: hold_zones` - a property whose zones (`Sala`,
    `Giardino`...) do not match any of them gets the rule on with no hold
    ever happening, silently. This flags that mismatch before it is a
    surprise on a real service (see tools/seating_engine.py "hold_zones")."""
    hold_zones = settings.agent_get("hold_zones", ["Window", "Terrace"]) or []
    if not hold_zones:
        return Check("hold zones", WARN, "hold_zones is empty in config/agent.yaml",
                     "Occasion bookings will never get a held table. Set hold_zones to your "
                     "own floor_tables.csv zone names.")
    try:
        with _probe_store() as probe:
            covers_book.ensure_seeded(settings, probe)
            zones = sorted({r["zone"] for r in
                           probe.db.execute("SELECT DISTINCT zone FROM floor_tables").fetchall()})
    except Exception as exc:  # noqa: BLE001 - doctor must always print a table
        return Check("hold zones", WARN, f"could not check: {exc}"[:160], "")
    folded_hold = {_fold(z) for z in hold_zones}
    matches = [z for z in zones if _fold(z) in folded_hold]
    if not matches:
        return Check("hold zones", WARN,
                     f"configured {hold_zones}, but none of your floor's zones match "
                     f"({zones})",
                     "Occasion holds (vip-window) will never fire. Set hold_zones in "
                     "config/agent.yaml to match your own floor_tables.csv zone names.")
    return Check("hold zones", PASS, f"{', '.join(matches)} match {hold_zones}")


def check_prompts() -> Check:
    missing = [p for p in ("prompts/dining_note.md", "prompts/schemas/dining_note.json")
              if not (REPO_ROOT / p).is_file()]
    if missing:
        return Check("prompts", FAIL, f"missing {', '.join(missing)}",
                     "These ship with the repo - restore them from git.")
    return Check("prompts", PASS, "dining_note.md + schema present")


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        checks = run_checks(None) + [Check("config", FAIL, str(exc),
                                           "Fix config/hotel.yaml or config/agent.yaml.")]
        return print_table(checks, title="Table / Floor Management AI - doctor")

    checks = run_checks(settings, extra=[check_dining_rules, check_seeded_state])
    checks.append(check_book_sources())
    checks.append(check_hold_zones(settings))
    checks.append(check_prompts())
    return print_table(checks, title="Table / Floor Management AI - doctor")


if __name__ == "__main__":
    raise SystemExit(main())
