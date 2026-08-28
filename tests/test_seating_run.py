"""Integration tests: the bundled fixtures, through tools/run.py's real
functions, with provider=mock and a throwaway store. No network, no
credentials - the same path `make demo` and a real scheduled run both take.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.adapters import get_messaging, get_sheets
from core.review import WriteBlocked, approve
from core.store import Store
from tools import covers_book
from tools.run import _needs_human, one_pass

DAY_OFFSET, SERVICE = 1, "dinner"


def test_one_pass_mock_provider_queues_a_pending_review_item(settings_and_store):
    settings, store = settings_and_store
    code, stats = one_pass(settings, store, day_offset=DAY_OFFSET, service=SERVICE,
                           provider="mock", demo=True)
    assert code == 0
    assert stats["processed"] == 1 and stats["drafted"] == 1
    items = store.list_items(status=["pending_review", "needs_human"], kind="floor_plan")
    assert len(items) == 1
    item = items[0]
    assert item.payload["_plan"]["summary"]["seated"] == 9
    assert item.draft["narrative"]  # the mock fixture note was attached


def test_dry_run_writes_no_item_row(settings_and_store):
    settings, store = settings_and_store
    settings.dry_run = True
    code, stats = one_pass(settings, store, day_offset=DAY_OFFSET, service=SERVICE,
                           provider="mock", demo=True)
    assert code == 0
    assert stats["processed"] == 1
    assert store.list_items(kind="floor_plan") == []


def test_rerun_with_unchanged_book_reuses_the_same_item(settings_and_store):
    settings, store = settings_and_store
    one_pass(settings, store, day_offset=DAY_OFFSET, service=SERVICE, provider="mock", demo=True)
    first = store.list_items(kind="floor_plan")
    assert len(first) == 1
    one_pass(settings, store, day_offset=DAY_OFFSET, service=SERVICE, provider="mock", demo=True)
    second = store.list_items(kind="floor_plan")
    assert len(second) == 1
    assert second[0].id == first[0].id


def test_walkin_creates_a_fresh_item_not_a_mutation(settings_and_store):
    settings, store = settings_and_store
    one_pass(settings, store, day_offset=DAY_OFFSET, service=SERVICE, provider="mock", demo=True)
    before_ids = {i.id for i in store.list_items(kind="floor_plan")}
    covers_book.insert_walkin(store, day_offset=DAY_OFFSET, service=SERVICE,
                              party_name="Six-top", party_size=6, time="20:15")
    one_pass(settings, store, day_offset=DAY_OFFSET, service=SERVICE, provider="mock", demo=True)
    after = store.list_items(kind="floor_plan")
    after_ids = {i.id for i in after}
    assert len(after) == 2
    assert before_ids < after_ids  # the old plan is still there, untouched


def test_unseated_booking_needs_a_human(settings_and_store):
    settings, store = settings_and_store
    covers_book.set_rule(store, "join-tables", False)
    code, stats = one_pass(settings, store, day_offset=DAY_OFFSET, service=SERVICE,
                           provider="mock", demo=True)
    assert code == 0
    assert stats["needs_human"] == 1
    item = store.list_items(kind="floor_plan")[0]
    assert item.review_status == "needs_human"
    assert item.payload["_plan"]["unseated"]


def test_retry_after_interactive_pending_resumes_narrative_only(settings_and_store):
    """A trap the family has hit before: a later LLM call (narrate) can pend
    AFTER an earlier stage (the plan) already succeeded. The retry must
    resume the SAME item at the narrate stage, not recompute the plan into a
    new item and not skip narration - see docs/how-it-works.md "Resumable
    stages"."""
    settings, store = settings_and_store
    code, _ = one_pass(settings, store, day_offset=DAY_OFFSET, service=SERVICE,
                       provider="interactive", demo=True)
    assert code == 3
    items = store.list_items(kind="floor_plan")
    assert len(items) == 1
    pending_item = items[0]
    assert pending_item.review_status == "new"  # not queued - narration has not finished
    assert pending_item.payload["_plan"]["summary"]["seated"] == 9  # the plan IS cached
    assert pending_item.draft is None

    pending_dir = REPO_ROOT / "data" / "pending"
    prompt_files = list(pending_dir.glob("dining_note-*.prompt.md"))
    assert len(prompt_files) == 1
    pid = prompt_files[0].name[: -len(".prompt.md")]
    answer_path = pending_dir / f"{pid}.answer.json"
    try:
        answer_path.write_text(json.dumps({"note": "Test note from the retry."}),
                               encoding="utf-8")
        code2, _ = one_pass(settings, store, day_offset=DAY_OFFSET, service=SERVICE,
                            provider="interactive", demo=True)
    finally:
        for p in pending_dir.glob(f"{pid}.*"):
            p.unlink(missing_ok=True)

    assert code2 == 0
    items2 = store.list_items(kind="floor_plan")
    assert len(items2) == 1
    assert items2[0].id == pending_item.id  # the SAME item, resumed
    assert items2[0].draft["narrative"] == "Test note from the retry."
    assert items2[0].review_status in ("pending_review", "needs_human")


def test_shadow_mode_blocks_send_even_when_approved(settings_and_store):
    settings, store = settings_and_store
    one_pass(settings, store, day_offset=DAY_OFFSET, service=SERVICE, provider="mock", demo=True)
    item = store.list_items(kind="floor_plan")[0]
    approve(store, item.id)
    claimed = store.claim_for_send(limit=5)
    assert len(claimed) == 1
    messaging = get_messaging(settings)
    blocked = False
    try:
        messaging.notify_staff("test note", item=claimed[0])
    except WriteBlocked:
        blocked = True
    assert blocked, "mode: shadow must block notify_staff even on an approved item"


def test_two_pending_items_get_separate_prompt_files(settings_and_store):
    """MAJOR #4 regression (SIMULATION.md finding #4): a second walk-in
    queued before the first item's interactive dining_note prompt was ever
    answered must get its OWN pending prompt file, never silently overwrite
    the first one's (that was `fixture_id="dining-note-01"`, a hardcoded
    constant, for every item)."""
    settings, store = settings_and_store
    pending_dir = REPO_ROOT / "data" / "pending"
    code_a, _ = one_pass(settings, store, day_offset=DAY_OFFSET, service=SERVICE,
                         provider="interactive", demo=True)
    assert code_a == 3
    item_a = store.list_items(kind="floor_plan")[0]
    pid_a = f"dining_note-item-{item_a.id}"

    covers_book.insert_walkin(store, day_offset=DAY_OFFSET, service=SERVICE,
                              party_name="Second Walk-in", party_size=4, time="20:30")
    code_b, _ = one_pass(settings, store, day_offset=DAY_OFFSET, service=SERVICE,
                         provider="interactive", demo=True)
    assert code_b == 3
    items = store.list_items(kind="floor_plan")
    assert len(items) == 2
    item_b = next(i for i in items if i.id != item_a.id)
    pid_b = f"dining_note-item-{item_b.id}"
    assert pid_a != pid_b

    try:
        assert (pending_dir / f"{pid_a}.prompt.md").exists(), \
            "item A's prompt must still exist - item B must never overwrite it"
        assert (pending_dir / f"{pid_b}.prompt.md").exists()
        # neither item was queued - the pend happens before _queue ever runs
        assert item_a.review_status == "new"
        assert next(i for i in items if i.id == item_b.id).review_status == "new"
    finally:
        for pid in (pid_a, pid_b):
            for p in pending_dir.glob(f"{pid}.*"):
                p.unlink(missing_ok=True)


def test_needs_human_escalates_on_ambiguous_allergy_warning():
    """BLOCKER #3 regression, the run.py side: an ambiguous-allergy warning
    from tools/seating_engine.py must force needs_human, whatever
    allergy-flag is set to - docs/safety.md."""
    plan_dict = {"unseated": [], "warnings": [
        "Guest has a dietary note that may describe an allergy but did not "
        "match a known keyword — needs a person to check it by hand."]}
    assert _needs_human(plan_dict, allergy_on=True) is True
    assert _needs_human(plan_dict, allergy_on=False) is True


def test_needs_human_false_with_no_warnings():
    assert _needs_human({"unseated": [], "warnings": []}, allergy_on=True) is False
