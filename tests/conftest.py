"""Shared pytest fixtures.

`test_seating_*.py` and `test_covers_book.py` must never read this repo's own
`config/hotel.yaml` / `config/agent.yaml` - those are the hotel's own edits,
and a real property filling them in must never be able to turn `make test`
red (factory/workflows/build-repo.md section 5, "Tests never read the live
config"). `settings_and_store` points `load_settings()` at a throwaway copy
of the shipped `.example.yaml` files instead; `load_settings(demo=True)`
still forces `mock` provider, `shadow` mode and `mock` adapters regardless of
file content.

`test_core_*.py` (synced byte-identical from `factory/core/` - never edited
here) manage their own isolation per test and do not use this fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import load_settings  # noqa: E402
from core.store import Store  # noqa: E402
from tools import covers_book  # noqa: E402


@pytest.fixture
def settings_and_store(tmp_path, monkeypatch):
    monkeypatch.chdir(REPO_ROOT)
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "hotel.yaml").write_text(
        (REPO_ROOT / "config" / "hotel.example.yaml").read_text(encoding="utf-8"),
        encoding="utf-8")
    (cfg_dir / "agent.yaml").write_text(
        (REPO_ROOT / "config" / "agent.example.yaml").read_text(encoding="utf-8"),
        encoding="utf-8")
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(cfg_dir))
    monkeypatch.delenv("AGENT_MODE", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_EFFORT", raising=False)
    settings = load_settings(demo=True)
    store = Store(settings, path=tmp_path / "test.db")
    # demo=True pins covers_book to the bundled fixtures, never
    # data/imports/*.csv - so this suite can never pick up a real property's
    # own CSV if one happens to sit in this repo's data/imports/ on the
    # machine running `make test` (factory/workflows/build-repo.md section 5,
    # "Tests never read the live config").
    covers_book.ensure_seeded(settings, store, demo=True)
    yield settings, store
    store.close()
