"""A real (not `make demo`) pass on a fresh clone must never let shipped
sample fixtures pass for the restaurant's own book.

`core.store.Store.upsert_item` tags an item `_sample: True` when its source
is read through a `mock` adapter outside `make demo`
(`core.adapters.is_sample_source`); `item.is_sample` reads that back. This
repo does not re-implement the tagging - it only has to *show* it, so
`tools/review.py list` and `show` print a `[SAMPLE DATA]` marker a host
cannot miss before approving a plan.

`config/agent.example.yaml: systems_used: [messaging]` narrows which
adapters count: this agent never calls `get_pms()` / `get_email()`, so their
shipped `mock` default is not a sample-data signal here.

Like `tests/conftest.py`'s `settings_and_store`, this module points
`AGENT_CONFIG_DIR` at throwaway copies of the shipped `.example.yaml` files -
a real property's own `config/*.yaml` must never turn `make test` red.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import load_settings  # noqa: E402
from core.store import Store  # noqa: E402
from tools.review import cmd_list, cmd_show  # noqa: E402

PLAN = {"day_offset": 1, "service": "dinner",
        "summary": {"parties": 3, "seated": 3, "unseated": 0, "warning_count": 0}}


def _sample_item(tmp_path, monkeypatch):
    """A real pass on a fresh clone: systems.messaging.adapter is still the
    shipped `mock` default, so anything it queues is sample data."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    for name in ("hotel", "agent"):
        shutil.copy(REPO_ROOT / "config" / f"{name}.example.yaml", cfg_dir / f"{name}.yaml")
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(cfg_dir))
    for var in ("AGENT_MODE", "LLM_PROVIDER", "LLM_MODEL", "LLM_EFFORT"):
        monkeypatch.delenv(var, raising=False)

    settings = load_settings()  # the real path, not load_settings(demo=True)
    assert settings.demo is False
    assert settings.systems.messaging.adapter == "mock"  # the shipped default

    store = Store(settings, path=tmp_path / "test.db")
    item = store.upsert_item("messaging", "1-dinner-abc123", kind="floor_plan",
                             payload={"day_offset": 1, "service": "dinner", "_plan": PLAN})
    item = store.transition(item.id, "pending_review", "agent") or item
    return store, item


def test_a_real_pass_on_the_mock_default_tags_its_item_sample(tmp_path, monkeypatch):
    store, item = _sample_item(tmp_path, monkeypatch)
    store.close()
    assert item.payload.get("_sample") is True
    assert item.is_sample is True


def test_review_list_shows_the_sample_marker(tmp_path, monkeypatch, capsys):
    store, _ = _sample_item(tmp_path, monkeypatch)
    capsys.readouterr()  # discard anything printed while setting up
    assert cmd_list(store, SimpleNamespace(status=None, kind="floor_plan", limit=50)) == 0
    store.close()
    out = capsys.readouterr().out
    assert "[SAMPLE DATA]" in out
    assert "not your restaurant" in out


def test_review_show_says_it_is_sample_data(tmp_path, monkeypatch, capsys):
    store, item = _sample_item(tmp_path, monkeypatch)
    capsys.readouterr()
    assert cmd_show(store, SimpleNamespace(id=item.id)) == 0
    store.close()
    out = capsys.readouterr().out
    assert "[SAMPLE DATA]" in out
