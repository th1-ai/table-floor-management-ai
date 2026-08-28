"""tools/covers_book.py - the restaurant's own booking book.

``floor_tables``, ``restaurant_covers`` and ``dining_rules`` live in this
agent's own SQLite tables (``core.store.migrate``), not through
``core.adapters.get_pms()`` - see ``docs/how-it-works.md`` "Design decisions"
#6. A restaurant cover (time, party size, dietary, occasion) does not fit the
room-PMS ``Reservation`` dataclass, so this module reads its own book
directly: ``fixtures/restaurant/*.json`` for the demo (what `make demo`
uses), or ``data/imports/floor_tables.csv`` + ``data/imports/covers.csv`` for
a real property - the universal, always-works path, in the same spirit as
``core/adapters/pms_csv.py`` but for a table book instead of a room book. See
``docs/integrations.md`` for the exact headers.

:func:`ensure_seeded` runs its full covering-window replace on *every* call
(``make run``, ``make doctor``, every pass) - never gated on "table is
empty". `floor_tables` and the imported/seeded slice of `restaurant_covers`
are deleted and reloaded fresh from whatever source is live right now, so an
edited row in `data/imports/floor_tables.csv` / `covers.csv` shows up on the
very next run, not just the first one. A walk-in (:func:`insert_walkin`,
``source='walk_in'``) is never part of that replace - it is a live row this
agent inserted directly, not an import, so re-importing can never lose one.
A rule toggle (:func:`set_rule`) is untouched too; `dining_rules` still only
seeds once, since it is a host's own live state, not an import.

Every loader below takes an explicit ``demo`` flag. ``demo=True`` (only
``tools/demo.py`` and the test fixtures pass it) pins the source to
``fixtures/restaurant/*.json`` + ``fixtures/inbound/*.json`` and never even
looks at ``data/imports/`` - so `make demo` reads the same three fixture
scenarios every time, on its own database, whatever a real property has
already connected. ``demo=False`` (the default, what `make run` / `make
doctor` use) prefers `data/imports/*.csv` and falls back to the fixtures
only when no CSV exists yet.
"""

from __future__ import annotations

import csv
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from core.config import Settings, repo_root, sub_data_dir
from core.store import Store, utcnow

from tools.seating_engine import Cover, Table

SCHEMA = """
CREATE TABLE IF NOT EXISTS floor_tables (
  id             TEXT PRIMARY KEY,
  zone           TEXT NOT NULL,
  seats          INTEGER NOT NULL,
  joinable_with  TEXT NOT NULL DEFAULT '[]',
  x REAL NOT NULL DEFAULT 0, y REAL NOT NULL DEFAULT 0,
  w REAL NOT NULL DEFAULT 0, h REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS restaurant_covers (
  id           TEXT PRIMARY KEY,
  day_offset   INTEGER NOT NULL,
  service      TEXT NOT NULL,
  time         TEXT NOT NULL,
  party_name   TEXT NOT NULL,
  party_size   INTEGER NOT NULL,
  dietary      TEXT NOT NULL DEFAULT '[]',
  occasion     TEXT NOT NULL DEFAULT '',
  is_group     INTEGER NOT NULL DEFAULT 0,
  notes        TEXT NOT NULL DEFAULT '',
  source       TEXT NOT NULL DEFAULT 'seed',
  created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_covers_service ON restaurant_covers (day_offset, service);

CREATE TABLE IF NOT EXISTS dining_rules (
  key         TEXT PRIMARY KEY,
  label       TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  enabled     INTEGER NOT NULL DEFAULT 1,
  sort_order  INTEGER NOT NULL DEFAULT 0
);
"""


class CoversBookError(RuntimeError):
    """Raised for an unknown rule key. Message names every valid one."""


def migrate(store: Store) -> None:
    store.migrate(SCHEMA)


def _imports_dir() -> Path:
    return sub_data_dir("imports")


def _fixtures_dir() -> Path:
    return repo_root() / "fixtures" / "restaurant"


def _inbound_dir() -> Path:
    return repo_root() / "fixtures" / "inbound"


def _load_json_array(name: str) -> list[dict]:
    """``fixtures/restaurant/<name>.json`` - one array, static property data."""
    path = _fixtures_dir() / f"{name}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [d for d in data if isinstance(d, dict)]


def _load_inbound_covers() -> list[dict]:
    """``fixtures/inbound/*.json`` - one booking per file, like every other
    agent's inbound fixtures (ARCHITECTURE.md section 3, ``fixtures/inbound/``:
    "sample emails / messages / bookings / invoices")."""
    if not _inbound_dir().is_dir():
        return []
    out = []
    for path in sorted(_inbound_dir().glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            out.append(data)
    return out


def _load_csv(name: str, *, demo: bool = False) -> list[dict]:
    """``data/imports/<name>.csv`` - never consulted when ``demo=True``, so a
    real property's own import can never leak into `make demo`."""
    if demo:
        return []
    path = _imports_dir() / f"{name}.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def source_for(name: str) -> str:
    """Where `name` (``floor_tables`` | ``covers``) is read from right now."""
    if (_imports_dir() / f"{name}.csv").exists():
        return f"csv: data/imports/{name}.csv"
    if name == "covers" and list(_inbound_dir().glob("*.json")):
        return "fixtures: fixtures/inbound/*.json"
    if name != "covers" and (_fixtures_dir() / f"{name}.json").exists():
        return f"fixtures: fixtures/restaurant/{name}.json"
    return "none configured"


def sources_used() -> dict[str, str]:
    return {"floor_tables": source_for("floor_tables"), "covers": source_for("covers")}


def _bool(v: Any) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y")


def _list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    if v in (None, "", "[]"):
        return []
    return [s.strip() for s in str(v).split("|") if s.strip()]


# --------------------------------------------------------------------------
# seeding / re-import (covering-window replace, every call - see module
# docstring)
# --------------------------------------------------------------------------
def ensure_seeded(settings: Settings, store: Store, *, demo: bool = False) -> dict[str, int]:
    """Load floor_tables / restaurant_covers / dining_rules for the pass about
    to run.

    Safe (and required) to call on every run: `floor_tables` and the
    imported slice of `restaurant_covers` are replaced from the live source
    every time (never gated on "table is empty" - that was the bug, see
    docs/how-it-works.md), so an edited CSV row shows up on the very next
    call. `dining_rules` still only seeds once - it is a host's own live
    toggle state, not an import. Returns ``{"floor_tables": n, "restaurant_covers": n}``,
    the exact counts this pass will plan against - `tools/doctor.py` reports
    these directly rather than a stale snapshot.
    """
    migrate(store)
    n_tables = _reimport_tables(store, demo=demo)
    n_covers = _reimport_covers(store, demo=demo)
    _seed_rules(store, settings)
    return {"floor_tables": n_tables, "restaurant_covers": n_covers}


def _reimport_tables(store: Store, *, demo: bool = False) -> int:
    """Full replace: nothing else in this agent ever writes `floor_tables`,
    so it is always safe to drop and reload it from the live source."""
    rows = _load_csv("floor_tables", demo=demo) or _load_json_array("floor_tables")
    store.db.execute("DELETE FROM floor_tables")
    for raw in rows:
        store.db.execute(
            "INSERT OR REPLACE INTO floor_tables (id, zone, seats, joinable_with, x, y, w, h) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (str(raw.get("id")), str(raw.get("zone") or "Main"),
             int(float(raw.get("seats") or 2)), json.dumps(_list(raw.get("joinable_with"))),
             float(raw.get("x") or 0), float(raw.get("y") or 0),
             float(raw.get("w") or 0), float(raw.get("h") or 0)))
    return len(rows)


def _reimport_covers(store: Store, *, demo: bool = False) -> int:
    """Covering-window replace of the imported/seeded covers only - any
    `source='walk_in'` row (:func:`insert_walkin`) is a live booking this
    agent took directly, never an import, so it is excluded from the delete
    and survives every re-import untouched."""
    rows = _load_csv("covers", demo=demo) or _load_inbound_covers()
    store.db.execute("DELETE FROM restaurant_covers WHERE source != 'walk_in'")
    now = utcnow()
    for raw in rows:
        store.db.execute(
            "INSERT OR REPLACE INTO restaurant_covers (id, day_offset, service, time, "
            "party_name, party_size, dietary, occasion, is_group, notes, source, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(raw.get("id") or uuid.uuid4().hex[:8]), int(float(raw.get("day_offset") or 0)),
             str(raw.get("service") or "dinner"), str(raw.get("time") or "19:00"),
             str(raw.get("party_name") or ""), int(float(raw.get("party_size") or 2)),
             json.dumps(_list(raw.get("dietary"))), str(raw.get("occasion") or ""),
             1 if _bool(raw.get("is_group")) else 0, str(raw.get("notes") or ""),
             str(raw.get("source") or "seed"), now))
    return len(rows)


def _seed_rules(store: Store, settings: Settings) -> None:
    if store.db.execute("SELECT COUNT(*) AS n FROM dining_rules").fetchone()["n"]:
        return
    configured = settings.agent_get("dining_rules", {}) or {}
    for i, (key, cfg) in enumerate(configured.items()):
        cfg = cfg if isinstance(cfg, dict) else {}
        store.db.execute(
            "INSERT OR IGNORE INTO dining_rules (key, label, description, enabled, sort_order) "
            "VALUES (?,?,?,?,?)",
            (str(key), str(cfg.get("label") or key), str(cfg.get("description") or ""),
             1 if cfg.get("enabled", True) else 0, i))


# --------------------------------------------------------------------------
# reads, for the engine
# --------------------------------------------------------------------------
def get_tables(store: Store) -> list[Table]:
    rows = store.db.execute("SELECT * FROM floor_tables ORDER BY id").fetchall()
    return [Table(id=r["id"], zone=r["zone"], seats=r["seats"],
                 joinable_with=json.loads(r["joinable_with"] or "[]"),
                 x=r["x"], y=r["y"], w=r["w"], h=r["h"]) for r in rows]


def get_covers(store: Store, *, day_offset: int | None = None,
              service: str | None = None) -> list[Cover]:
    sql = "SELECT * FROM restaurant_covers"
    where, params = [], []
    if day_offset is not None:
        where.append("day_offset=?")
        params.append(day_offset)
    if service is not None:
        where.append("service=?")
        params.append(service)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY time"
    rows = store.db.execute(sql, params).fetchall()
    return [Cover(id=r["id"], day_offset=r["day_offset"], service=r["service"], time=r["time"],
                 party_name=r["party_name"], party_size=r["party_size"],
                 dietary=json.loads(r["dietary"] or "[]"), occasion=r["occasion"] or "",
                 is_group=bool(r["is_group"]), notes=r["notes"] or "",
                 source=r["source"] or "seed") for r in rows]


def get_rules(store: Store) -> dict[str, bool]:
    rows = store.db.execute(
        "SELECT key, enabled FROM dining_rules ORDER BY sort_order").fetchall()
    return {r["key"]: bool(r["enabled"]) for r in rows}


def list_rules(store: Store) -> list[dict]:
    rows = store.db.execute("SELECT * FROM dining_rules ORDER BY sort_order").fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# writes - internal ops state, not a guarded outbound action (nothing here
# leaves this machine; see docs/how-it-works.md "Nothing seats a walk-in or
# changes a plan without a person" for what IS guarded)
# --------------------------------------------------------------------------
def set_rule(store: Store, key: str, enabled: bool) -> dict:
    row = store.db.execute("SELECT 1 FROM dining_rules WHERE key=?", (key,)).fetchone()
    if row is None:
        known = ", ".join(r["key"] for r in store.db.execute(
            "SELECT key FROM dining_rules ORDER BY sort_order").fetchall())
        raise CoversBookError(
            f"unknown dining rule '{key}'. Known: {known or '(none seeded yet - run make demo '
                                                          'or make run once first)'}")
    store.db.execute("UPDATE dining_rules SET enabled=? WHERE key=?", (1 if enabled else 0, key))
    return {"key": key, "enabled": enabled}


def insert_walkin(store: Store, *, day_offset: int, service: str, party_name: str,
                  party_size: int, time: str, notes: str = "demo walk-in",
                  source: str = "walk_in") -> Cover:
    """Insert a real ``restaurant_covers`` row. The next plan re-run sees it."""
    cover_id = f"walkin-{uuid.uuid4().hex[:8]}"
    store.db.execute(
        "INSERT INTO restaurant_covers (id, day_offset, service, time, party_name, "
        "party_size, dietary, occasion, is_group, notes, source, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (cover_id, day_offset, service, time, party_name, party_size, "[]", "", 0, notes,
         source, utcnow()))
    return Cover(id=cover_id, day_offset=day_offset, service=service, time=time,
                party_name=party_name, party_size=party_size, notes=notes, source=source)


def book_fingerprint(tables: list[Table], covers: list[Cover], rules: dict[str, bool]) -> str:
    """A short, stable hash of everything that can change a plan's outcome.

    Part of a floor_plan item's external_id (docs/how-it-works.md
    "Idempotency"): the same fingerprint means the same inputs, so a retry
    after an interactive pause resumes the same item. A walk-in or a rule
    toggle changes the fingerprint, so the next plan is a fresh item, never a
    silent overwrite of what a host already reviewed.
    """
    payload = {
        "tables": sorted([(t.id, t.zone, t.seats, sorted(t.joinable_with)) for t in tables]),
        "covers": sorted([(c.id, c.time, c.party_name, c.party_size, sorted(c.dietary),
                          c.occasion, c.is_group) for c in covers]),
        "rules": sorted(rules.items()),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return digest[:12]
