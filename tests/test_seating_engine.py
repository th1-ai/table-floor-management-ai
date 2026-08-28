"""Tests for tools/seating_engine.py - the pure decision engine.

No store, no settings, no fixtures on disk: every test builds its own small
Table/Cover list so the formulas, thresholds and ordering are pinned down
precisely. No network, no credentials.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.seating_engine import Cover, Table, run_seating_plan

ALL_ON = {"turn-time": True, "join-tables": True, "vip-window": True,
         "server-balance": True, "allergy-flag": True}


def _tables() -> list[Table]:
    return [
        Table(id="P1", zone="Private", seats=10, joinable_with=["P2"]),
        Table(id="P2", zone="Private", seats=8, joinable_with=["P1"]),
        Table(id="M1", zone="Main", seats=8),
        Table(id="M2", zone="Main", seats=6),
        Table(id="W1", zone="Window", seats=2, joinable_with=["W2"]),
        Table(id="W2", zone="Window", seats=2, joinable_with=["W1"]),
        Table(id="T1", zone="Terrace", seats=4),
        Table(id="B1", zone="Bar", seats=2),
    ]


def _cover(**kw) -> Cover:
    base = dict(id="c", day_offset=1, service="dinner", time="19:00",
               party_name="Party", party_size=2)
    base.update(kw)
    return Cover(**base)


def test_composite_uses_private_tables_first_then_largest_non_bar():
    tables = _tables()
    covers = [_cover(id="big", party_name="Big Co", party_size=26, is_group=True)]
    plan = run_seating_plan(tables, covers, ALL_ON, day_offset=1, service="dinner")
    assert plan.unseated == []
    seated = plan.seated[0]
    # P1(10) + P2(8) = 18 raw, x1.15 = 20.7 < 26 -> add M1(8): 26 raw, x1.15 = 29.9 >= 26
    assert seated.table_ids == ["P1", "P2", "M1"]
    assert "Private dining composite" in seated.flags
    assert "Set menu" in seated.flags
    assert seated.effective_seats == (10 + 8 + 8) * 1.15


def test_banquet_factor_not_applied_without_a_private_table():
    tables = [t for t in _tables() if t.zone != "Private"]  # no private room at all
    covers = [_cover(id="big", party_name="Big Co", party_size=16, is_group=True)]
    plan = run_seating_plan(tables, covers, ALL_ON, day_offset=1, service="dinner")
    seated = plan.seated[0]
    # M1(8) + M2(6) + T1(4) = 18 raw, no bonus since no private table used
    assert seated.effective_seats == 18.0
    assert "Set menu" not in seated.flags


def test_group_unseated_when_joins_off_names_largest_private_table():
    tables = _tables()
    rules = {**ALL_ON, "join-tables": False}
    covers = [_cover(id="big", party_name="Big Co", party_size=26, is_group=True)]
    plan = run_seating_plan(tables, covers, rules, day_offset=1, service="dinner")
    assert plan.seated == []
    assert len(plan.unseated) == 1
    reason = plan.unseated[0].reason
    assert "P1" in reason and "10 seats" in reason and "party of 26" in reason


def test_ordinary_party_unseated_when_nothing_free():
    tables = [Table(id="B1", zone="Bar", seats=2)]
    rules = {**ALL_ON, "join-tables": False}
    covers = [_cover(id="a", party_size=2, time="19:00"),
             _cover(id="b", party_name="Second", party_size=2, time="19:05")]
    plan = run_seating_plan(tables, covers, rules, day_offset=1, service="dinner")
    assert len(plan.seated) == 1
    assert len(plan.unseated) == 1
    assert "No free table" in plan.unseated[0].reason


def test_occasion_booking_jumps_queue_and_prefers_hold_zone():
    tables = [Table(id="M1", zone="Main", seats=8), Table(id="W1", zone="Window", seats=2)]
    covers = [_cover(id="big", party_name="Big Co", party_size=8, time="19:00"),
             _cover(id="anniv1", party_name="Farrow", party_size=2, time="19:01",
                   occasion="anniversary")]
    plan = run_seating_plan(tables, covers, ALL_ON, day_offset=1, service="dinner")
    farrow = next(s for s in plan.seated if s.cover.party_name == "Farrow")
    assert farrow.table_ids == ["W1"]
    assert "Occasion hold" in farrow.flags
    # Big Co (size 8) needed M1, and got it - Farrow (occasion) didn't steal it
    assert next(s for s in plan.seated if s.cover.party_name == "Big Co").table_ids == ["M1"]


def test_vip_window_off_no_occasion_hold_and_no_zone_preference():
    tables = [Table(id="M1", zone="Main", seats=2), Table(id="W1", zone="Window", seats=2)]
    covers = [_cover(id="anniv1", party_name="Farrow", party_size=2, occasion="anniversary")]
    rules = {**ALL_ON, "vip-window": False}
    plan = run_seating_plan(tables, covers, rules, day_offset=1, service="dinner")
    farrow = plan.seated[0]
    assert "Occasion hold" not in farrow.flags
    assert any(s["step"] == "occasion-holds" and "off" in s["text"] for s in plan.thinking_log)


def test_server_balance_warns_over_cap():
    tables = [Table(id="M1", zone="Main", seats=20), Table(id="M2", zone="Main", seats=10)]
    covers = [_cover(id="a", party_size=20, time="19:00"),
             _cover(id="b", party_name="Second", party_size=10, time="19:05")]
    plan = run_seating_plan(tables, covers, ALL_ON, day_offset=1, service="dinner",
                            zone_cover_cap=24)
    assert any("Main is carrying 30 covers" in w for w in plan.warnings)


def test_server_balance_off_no_warning_even_over_cap():
    tables = [Table(id="M1", zone="Main", seats=20), Table(id="M2", zone="Main", seats=10)]
    covers = [_cover(id="a", party_size=20, time="19:00"),
             _cover(id="b", party_name="Second", party_size=10, time="19:05")]
    rules = {**ALL_ON, "server-balance": False}
    plan = run_seating_plan(tables, covers, rules, day_offset=1, service="dinner",
                            zone_cover_cap=24)
    assert plan.warnings == []


def test_allergy_flag_on_headlines_nut_allergy_and_fills_kitchen_sheet():
    tables = [Table(id="M1", zone="Main", seats=4)]
    covers = [_cover(id="a", party_name="Okafor", party_size=2, dietary=["nut allergy"])]
    plan = run_seating_plan(tables, covers, ALL_ON, day_offset=1, service="dinner")
    assert len(plan.kitchen_sheet) == 1
    assert plan.kitchen_sheet[0]["party_name"] == "Okafor"
    assert any(s["step"] == "nut-allergy" for s in plan.thinking_log)
    assert plan.summary["kitchen_flag_count"] == 1


def test_allergy_flag_off_hides_kitchen_sheet_but_still_warns_on_nut_allergy():
    tables = [Table(id="M1", zone="Main", seats=4)]
    covers = [_cover(id="a", party_name="Okafor", party_size=2, dietary=["nut allergy"])]
    rules = {**ALL_ON, "allergy-flag": False}
    plan = run_seating_plan(tables, covers, rules, day_offset=1, service="dinner")
    assert plan.kitchen_sheet == []
    assert any("nut allergy" in w.lower() and "nothing is printed" in w for w in plan.warnings)


def test_turn_time_off_single_turn_and_capacity_warning():
    tables = [Table(id="M1", zone="Main", seats=4)]
    rules = {**ALL_ON, "turn-time": False}
    covers = [_cover(id="a", party_size=2, time="19:00"),
             _cover(id="b", party_name="Second", party_size=2, time="21:00")]
    plan = run_seating_plan(tables, covers, rules, day_offset=1, service="dinner")
    assert plan.summary["seated"] == 1
    assert plan.summary["unseated"] == 1
    assert any("expect gaps or turned-away parties" in w for w in plan.warnings)
    assert any("hard ceiling of 1 sittings" in s["text"] for s in plan.thinking_log)


def test_joined_pair_zone_is_the_lowest_id_table():
    tables = [Table(id="W2", zone="Window", seats=2, joinable_with=["W1"]),
             Table(id="W1", zone="Terrace", seats=2, joinable_with=["W2"])]
    covers = [_cover(id="a", party_size=4)]
    plan = run_seating_plan(tables, covers, ALL_ON, day_offset=1, service="dinner")
    seated = plan.seated[0]
    assert seated.table_ids == ["W1", "W2"]
    assert seated.zone == "Terrace"  # W1's zone, W1 < W2 by id
    assert "Joined tables" in seated.flags


def test_deterministic_replay_same_inputs_same_plan():
    tables, covers = _tables(), [_cover(id="a", party_size=6, time="19:00")]
    plan1 = run_seating_plan(tables, covers, ALL_ON, day_offset=1, service="dinner")
    plan2 = run_seating_plan(tables, covers, ALL_ON, day_offset=1, service="dinner")
    assert plan1.as_dict() == plan2.as_dict()


# --------------------------------------------------------------------------
# BLOCKER #3 (SIMULATION.md finding #3) - dietary/occasion/zone detection
# must work in the hotel's own languages, accent-folded, and zones must be
# the hotel's own configured names, not hardcoded English ones.
# --------------------------------------------------------------------------
NUT_ALLERGY_PHRASES = {
    "en": "nut allergy", "es": "alergia a los frutos secos", "fr": "allergie aux noix",
    "de": "Nussallergie", "it": "allergia alle noci", "pt": "alergia a nozes",
}


def test_nut_allergy_detected_across_hotel_languages():
    for lang, phrase in NUT_ALLERGY_PHRASES.items():
        cover = _cover(id=f"c-{lang}", dietary=[phrase])
        assert cover.has_nut_allergy, f"{lang}: {phrase!r} should flag a nut allergy"
        assert not cover.has_allergy_signal  # already classified - no ambiguity


OCCASION_PHRASES = {
    "en": "anniversary", "es": "aniversario", "fr": "anniversaire",
    "de": "Jahrestag", "it": "anniversario", "pt": "aniversário",
}


def test_occasion_detected_across_hotel_languages():
    for lang, phrase in OCCASION_PHRASES.items():
        cover = _cover(id=f"o-{lang}", occasion=phrase)
        assert cover.is_celebration, f"{lang}: {phrase!r} should read as a celebration"


def test_hold_zones_configurable_to_the_hotels_own_zone_names():
    """A property's own zones (Sala/Giardino, not Window/Terrace) must be
    able to hold an occasion booking - config, not a hardcoded constant."""
    tables = [Table(id="M1", zone="Main", seats=8), Table(id="S1", zone="Sala", seats=2)]
    covers = [_cover(id="big", party_name="Big Co", party_size=8, time="19:00"),
             _cover(id="anniv1", party_name="Farrow", party_size=2, time="19:01",
                   occasion="anniversario")]
    plan = run_seating_plan(tables, covers, ALL_ON, day_offset=1, service="dinner",
                            hold_zones=("sala",))  # case/accent-folded against "Sala"
    farrow = next(s for s in plan.seated if s.cover.party_name == "Farrow")
    assert farrow.table_ids == ["S1"]
    assert "Occasion hold" in farrow.flags


def test_default_hold_zones_window_terrace_still_work():
    """The shipped default (no hold_zones configured) must keep matching the
    demo fixtures' own Window/Terrace zones - no regression for a property
    that never sets hold_zones."""
    tables = _tables()
    covers = [_cover(id="anniv1", party_name="Farrow", party_size=2, occasion="honeymoon")]
    plan = run_seating_plan(tables, covers, ALL_ON, day_offset=1, service="dinner")
    farrow = plan.seated[0]
    assert "Occasion hold" in farrow.flags
    assert farrow.zone in ("Window", "Terrace")


def test_ambiguous_allergy_note_escalates_without_a_specific_keyword():
    """A dietary note that clearly names some allergy, in a language this
    module carries a word list for, but does not match a specific nut
    phrase, must never be silently dropped - docs/safety.md."""
    tables = [Table(id="M1", zone="Main", seats=4)]
    covers = [_cover(id="a", party_name="Guest", party_size=2,
                     dietary=["allergic to shellfish"])]
    plan = run_seating_plan(tables, covers, ALL_ON, day_offset=1, service="dinner")
    assert plan.kitchen_sheet  # still reaches the kitchen sheet
    assert any(s["step"] == "ambiguous-allergy" for s in plan.thinking_log)
    assert any("may describe an allergy" in w for w in plan.warnings)


def test_ambiguous_allergy_note_in_another_language_also_escalates():
    tables = [Table(id="M1", zone="Main", seats=4)]
    covers = [_cover(id="a", party_name="Guest", party_size=2,
                     dietary=["allergique aux crustacés"])]  # French: shellfish allergy
    plan = run_seating_plan(tables, covers, ALL_ON, day_offset=1, service="dinner")
    assert any("may describe an allergy" in w for w in plan.warnings)


def test_plain_dietary_note_with_no_allergy_signal_does_not_escalate():
    tables = [Table(id="M1", zone="Main", seats=4)]
    covers = [_cover(id="a", party_name="Guest", party_size=2, dietary=["vegetarian"])]
    plan = run_seating_plan(tables, covers, ALL_ON, day_offset=1, service="dinner")
    assert plan.kitchen_sheet  # still on the kitchen sheet, just not escalated
    assert not any(s["step"] == "ambiguous-allergy" for s in plan.thinking_log)
    assert not any("may describe an allergy" in w for w in plan.warnings)
