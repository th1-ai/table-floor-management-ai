"""Tests for tools/doctor.py - specifically that "floor book" reports the
exact counts the run loop would use (BLOCKER #2, SIMULATION.md finding #2)
without ever touching the real data/agent.db, and that "hold zones" warns
when a property's own zones do not match config/agent.yaml: hold_zones
(BLOCKER #3, SIMULATION.md finding #3).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import Settings  # noqa: E402
from core.doctor import PASS, WARN  # noqa: E402
from tools import doctor  # noqa: E402

FLOOR_CSV_HEADER = "id,zone,seats,joinable_with,x,y,w,h\n"
COVERS_CSV_HEADER = ("id,day_offset,service,time,party_name,party_size,dietary,occasion,"
                     "is_group,notes,source\n")


def _write_imports(tmp_path: Path, floor_rows: str, cover_rows: str) -> Path:
    imports = tmp_path / "data" / "imports"
    imports.mkdir(parents=True, exist_ok=True)
    (imports / "floor_tables.csv").write_text(FLOOR_CSV_HEADER + floor_rows, encoding="utf-8")
    (imports / "covers.csv").write_text(COVERS_CSV_HEADER + cover_rows, encoding="utf-8")
    return imports


def test_check_seeded_state_matches_what_run_loop_would_load_and_touches_no_real_db(
        tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_REPO_ROOT", str(tmp_path))
    imports = _write_imports(
        tmp_path,
        "T1,Main,4,,0,0,0,0\nT2,Main,4,,0,0,0,0\n",
        "cov-1,1,dinner,19:00,Party,2,,,false,,seed\n")
    settings = Settings(agent={})

    check = doctor.check_seeded_state(settings)
    assert check.status == PASS
    assert "2 table(s), 1 booking(s)" in check.detail
    assert not (tmp_path / "data" / "agent.db").exists()  # never the real db

    # edit the CSV - doctor's next call must reflect it immediately, exactly
    # like `make run` would on its own next pass - no `rm data/agent.db`
    # workaround needed (that was the bug).
    (imports / "floor_tables.csv").write_text(FLOOR_CSV_HEADER + "T1,Main,4,,0,0,0,0\n",
                                               encoding="utf-8")
    check2 = doctor.check_seeded_state(settings)
    assert "1 table(s), 1 booking(s)" in check2.detail
    assert not (tmp_path / "data" / "agent.db").exists()


def test_check_hold_zones_warns_when_no_real_zone_matches(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_REPO_ROOT", str(tmp_path))
    _write_imports(tmp_path, "S1,Sala,4,,0,0,0,0\nG1,Giardino,4,,0,0,0,0\n",
                   "cov-1,1,dinner,19:00,Party,2,,,false,,seed\n")
    settings = Settings(agent={})  # default hold_zones: Window, Terrace - matches nothing here

    check = doctor.check_hold_zones(settings)
    assert check.status == WARN
    assert "none of your floor's zones match" in check.detail

    settings_configured = Settings(agent={"hold_zones": ["Sala", "giardino"]})
    check2 = doctor.check_hold_zones(settings_configured)
    assert check2.status == PASS
