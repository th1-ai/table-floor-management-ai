"""Tests for tools/covers_book.py - seeding, the walk-in, rule toggles and
the book fingerprint. Uses the shared `settings_and_store` fixture
(tests/conftest.py) so a real property's own config/*.yaml can never affect
this suite.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import Settings
from core.store import Store
from tools import covers_book

FLOOR_CSV_HEADER = "id,zone,seats,joinable_with,x,y,w,h\n"
COVERS_CSV_HEADER = ("id,day_offset,service,time,party_name,party_size,dietary,occasion,"
                     "is_group,notes,source\n")


def test_ensure_seeded_loads_fixtures(settings_and_store):
    settings, store = settings_and_store
    tables = covers_book.get_tables(store)
    covers = covers_book.get_covers(store)
    rules = covers_book.get_rules(store)
    assert len(tables) == 16
    assert len(covers) == 11
    assert set(rules) == {"turn-time", "join-tables", "vip-window", "server-balance",
                          "allergy-flag"}
    assert all(rules.values())  # the shipped config seeds every rule on


def test_ensure_seeded_is_idempotent(settings_and_store):
    settings, store = settings_and_store
    before = len(covers_book.get_covers(store))
    # calling it again must not duplicate - it re-imports (covering-window
    # replace), not accumulates
    covers_book.ensure_seeded(settings, store, demo=True)
    covers_book.ensure_seeded(settings, store, demo=True)
    assert len(covers_book.get_covers(store)) == before


def test_insert_walkin_appears_in_next_get_covers(settings_and_store):
    settings, store = settings_and_store
    before = len(covers_book.get_covers(store, day_offset=1, service="dinner"))
    covers_book.insert_walkin(store, day_offset=1, service="dinner", party_name="Six-top",
                              party_size=6, time="20:15")
    after = covers_book.get_covers(store, day_offset=1, service="dinner")
    assert len(after) == before + 1
    walkin = next(c for c in after if c.party_name == "Six-top")
    assert walkin.party_size == 6 and walkin.time == "20:15" and walkin.source == "walk_in"


def test_set_rule_unknown_key_raises(settings_and_store):
    settings, store = settings_and_store
    with pytest.raises(covers_book.CoversBookError, match="unknown dining rule"):
        covers_book.set_rule(store, "not-a-real-rule", False)


def test_set_rule_changes_get_rules(settings_and_store):
    settings, store = settings_and_store
    covers_book.set_rule(store, "join-tables", False)
    assert covers_book.get_rules(store)["join-tables"] is False
    covers_book.set_rule(store, "join-tables", True)
    assert covers_book.get_rules(store)["join-tables"] is True


def test_book_fingerprint_changes_on_walkin_and_rule_toggle(settings_and_store):
    settings, store = settings_and_store
    tables = covers_book.get_tables(store)
    covers = covers_book.get_covers(store, day_offset=1, service="dinner")
    rules = covers_book.get_rules(store)
    fp0 = covers_book.book_fingerprint(tables, covers, rules)

    covers_book.insert_walkin(store, day_offset=1, service="dinner", party_name="Six-top",
                              party_size=6, time="20:15")
    fp1 = covers_book.book_fingerprint(
        tables, covers_book.get_covers(store, day_offset=1, service="dinner"), rules)
    assert fp1 != fp0

    covers_book.set_rule(store, "join-tables", False)
    fp2 = covers_book.book_fingerprint(
        tables, covers_book.get_covers(store, day_offset=1, service="dinner"),
        covers_book.get_rules(store))
    assert fp2 != fp1

    # same inputs -> same fingerprint, every time
    fp1_again = covers_book.book_fingerprint(
        tables, covers_book.get_covers(store, day_offset=1, service="dinner"), rules)
    assert fp1_again == fp1


# --------------------------------------------------------------------------
# BLOCKER #1 (SIMULATION.md finding #1) - `make demo` must be immune to a
# real property's own data/imports/*.csv, even when the real data/agent.db
# has already been seeded from it. AGENT_REPO_ROOT isolates each test to its
# own tmp_path, standing in for a property's repo - never this repo's own.
# --------------------------------------------------------------------------
def test_demo_immune_to_decoy_csvs_and_a_seeded_real_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_REPO_ROOT", str(tmp_path))
    shutil.copytree(REPO_ROOT / "fixtures", tmp_path / "fixtures")
    imports = tmp_path / "data" / "imports"
    imports.mkdir(parents=True)
    (imports / "floor_tables.csv").write_text(FLOOR_CSV_HEADER + "DECOY1,Main,99,,0,0,0,0\n",
                                               encoding="utf-8")
    (imports / "covers.csv").write_text(
        COVERS_CSV_HEADER + "decoy-1,2,dinner,19:00,Decoy Party,2,,,false,,seed\n",
        encoding="utf-8")
    settings = Settings(agent={})

    # the "real run" seeds data/agent.db from the decoy CSV, exactly as a
    # property that already connected their own data would
    real_store = Store(settings, path=tmp_path / "real.db")
    real_counts = covers_book.ensure_seeded(settings, real_store, demo=False)
    assert real_counts == {"floor_tables": 1, "restaurant_covers": 1}
    real_store.close()

    # make demo must still see only the shipped fixtures, on its own db
    demo_store = Store(settings, path=tmp_path / "demo.db")
    demo_counts = covers_book.ensure_seeded(settings, demo_store, demo=True)
    assert demo_counts == {"floor_tables": 16, "restaurant_covers": 11}
    demo_store.close()


# --------------------------------------------------------------------------
# BLOCKER #2 (SIMULATION.md finding #2) - an edited data/imports/*.csv row
# must show up on the very next re-import, and a live walk-in must survive
# untouched.
# --------------------------------------------------------------------------
def test_edited_csv_row_reflected_on_next_reimport_walkin_survives(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_REPO_ROOT", str(tmp_path))
    imports = tmp_path / "data" / "imports"
    imports.mkdir(parents=True)
    (imports / "floor_tables.csv").write_text(FLOOR_CSV_HEADER + "T1,Main,4,,0,0,0,0\n",
                                               encoding="utf-8")
    (imports / "covers.csv").write_text(
        COVERS_CSV_HEADER + "cov-1,1,dinner,19:00,Original Party,2,,,false,,seed\n",
        encoding="utf-8")
    settings = Settings(agent={})
    store = Store(settings, path=tmp_path / "t.db")

    covers_book.ensure_seeded(settings, store, demo=False)
    before = {c.party_name: c for c in covers_book.get_covers(store, day_offset=1,
                                                               service="dinner")}
    assert before["Original Party"].party_size == 2

    covers_book.insert_walkin(store, day_offset=1, service="dinner", party_name="Walk-in Two",
                              party_size=4, time="20:00")

    (imports / "covers.csv").write_text(
        COVERS_CSV_HEADER + "cov-1,1,dinner,19:00,Original Party,5,,,false,,seed\n",
        encoding="utf-8")  # the property edits tonight's party size

    covers_book.ensure_seeded(settings, store, demo=False)  # what `make run`/`make doctor` do next
    after = {c.party_name: c for c in covers_book.get_covers(store, day_offset=1,
                                                              service="dinner")}
    assert after["Original Party"].party_size == 5  # the edit shows up
    assert after["Walk-in Two"].party_size == 4  # the walk-in survived, untouched
    store.close()
