"""tools/seating_engine.py - the whole seating-plan decision engine. Pure functions.

PURE: no I/O, no clock, no randomness. Feed :func:`run_seating_plan` the same
tables, the same book and the same rules and it returns the same plan every
time. Every number in a step's ``detail`` traces back to a row you gave it -
table ids, party names and sizes are never invented. This mirrors the header
comment on the source engine this module was built from.

Deterministic decisioning, LLM for language (ARCHITECTURE.md section 1):
nothing in this file calls a model. The only LLM call in this agent writes a
short narrative about a plan this module already finished
(``prompts/dining_note.md``, driven from ``tools/run.py``).

Two design decisions worth knowing before you read the placement functions
(full list in ``docs/how-it-works.md``):

- The **private-dining composite** (a group too big for a single table or a
  joined pair) is only attempted when ``join-tables`` is on. The source demo
  demonstrates this explicitly: turning table joins off drops a previously
  seated large group into the unseated list, which only makes sense if the
  composite itself depends on joining tables together.
- A **joined-table party's zone**, for every purpose downstream (occasion
  holds, server-balance, the kitchen sheet), is its *first* table's zone -
  where "first" means lowest table id, not seating/arrival order.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any

LATE_CUTOFF_DEFAULT = "20:15"
BANQUET_FACTOR_DEFAULT = 1.15
ZONE_COVER_CAP_DEFAULT = 24
GROUP_SIZE_THRESHOLD = 8


def _fold(text: str) -> str:
    """Casefold + strip accents: ``"Alergía"``, ``"ALLERGIA"`` and
    ``"allergie"`` all fold to a plain, comparable string. Every
    dietary/occasion keyword match in this module goes through this first -
    a hotel's own languages are not always ASCII (docs/safety.md)."""
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).casefold().strip()


# Occasions that trigger vip-window's queue-jump + hold-zone preference.
# One word per hotel.languages this family ships examples for (en, es, fr,
# de, it, pt) - accent-folded and compared as a whole occasion string, e.g.
# "anniversario" (it, double-n) or "aniversário" (pt, single-n), not a
# substring match.
OCCASION_WORDS = {
    "anniversary", "honeymoon", "birthday", "engagement", "proposal", "wedding",
    "aniversario", "luna de miel", "cumpleaños", "compromiso",
    "propuesta de matrimonio", "boda",
    "anniversaire", "lune de miel", "fiançailles", "demande en mariage", "mariage",
    "jahrestag", "flitterwochen", "geburtstag", "verlobung", "heiratsantrag", "hochzeit",
    "anniversario", "luna di miele", "compleanno", "fidanzamento",
    "proposta di matrimonio", "matrimonio", "nozze",
    "aniversário", "lua de mel", "casamento", "noivado", "pedido de casamento",
}
_OCCASION_WORDS_FOLDED = {_fold(w) for w in OCCASION_WORDS}

# Nut-allergy phrases, one stem per language - substring match against the
# folded dietary text, so "allergia alle noci" (it), "Nussallergie" (de) and
# "alergia a los frutos secos" (es) all flag the same as "nut allergy" (en).
_NUT_ALLERGY_STEMS = {
    "nut", "frutos secos", "fruto seco", "nuez", "nueces", "mani", "cacahuete",
    "cacahuates", "fruits a coque", "fruit a coque", "noix", "arachide",
    "cacahouete", "nuss", "noci", "nocciola", "nocciole", "arachidi", "noz",
    "nozes", "amendoim",
}

# A word from any of these families means "this dietary note names SOME
# allergy" even when it does not match a specific stem above - the common,
# accent-folded substring across allergy/allergie/alergia/allergisch/
# allergico/anafilassi/intolleranza etc. Used only as the fallback in
# Cover.has_allergy_signal, so an allergen this repo does not have a keyword
# for still raises a flag instead of vanishing (docs/safety.md).
_ALLERGY_SIGNAL_STEMS = ("lerg", "anafil", "anaphyla", "intoleran")

HOLD_ZONES = ("Window", "Terrace")  # default only - a real property's own
                                    # zone names come from config/agent.yaml
                                    # (dining.hold_zones) via tools/run.py;
                                    # matched case-insensitively below.
PRIVATE_ZONE = "Private"
BAR_ZONE = "Bar"


# --------------------------------------------------------------------------
# plain data
# --------------------------------------------------------------------------
@dataclass
class Table:
    """One row of ``floor_tables``."""

    id: str
    zone: str
    seats: int
    joinable_with: list[str] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0


@dataclass
class Cover:
    """One row of ``restaurant_covers`` - one booking for one service."""

    id: str
    day_offset: int
    service: str
    time: str
    party_name: str
    party_size: int
    dietary: list[str] = field(default_factory=list)
    occasion: str = ""
    is_group: bool = False
    notes: str = ""
    source: str = "seed"

    @property
    def is_celebration(self) -> bool:
        return _fold(self.occasion) in _OCCASION_WORDS_FOLDED

    @property
    def has_nut_allergy(self) -> bool:
        return any(stem in _fold(d) for d in self.dietary for stem in _NUT_ALLERGY_STEMS)

    @property
    def has_allergy_signal(self) -> bool:
        """A dietary note that reads like it names some allergy, in any of
        this module's language families, but did not match a specific
        nut-allergy stem above - e.g. an allergen this repo has no keyword
        for, or a language it does not carry a word list for yet. Never true
        when :attr:`has_nut_allergy` already fired - see
        ``run_seating_plan``'s "ambiguous-allergy" step, which escalates
        this to a person instead of staying silent (docs/safety.md)."""
        if self.has_nut_allergy:
            return False
        return any(stem in _fold(d) for d in self.dietary for stem in _ALLERGY_SIGNAL_STEMS)


@dataclass
class Seated:
    """One booking the engine placed."""

    cover: Cover
    table_ids: list[str]
    turn: int
    zone: str
    flags: list[str] = field(default_factory=list)
    effective_seats: float = 0.0

    def as_dict(self) -> dict:
        return {"cover_id": self.cover.id, "party_name": self.cover.party_name,
                "party_size": self.cover.party_size, "time": self.cover.time,
                "table_ids": self.table_ids, "turn": self.turn, "zone": self.zone,
                "flags": self.flags, "effective_seats": self.effective_seats,
                "dietary": self.cover.dietary, "occasion": self.cover.occasion}


@dataclass
class Unseated:
    """One booking the engine could not place, and exactly why."""

    cover: Cover
    reason: str

    def as_dict(self) -> dict:
        return {"cover_id": self.cover.id, "party_name": self.cover.party_name,
                "party_size": self.cover.party_size, "time": self.cover.time,
                "reason": self.reason}


@dataclass
class SeatingPlan:
    day_offset: int
    service: str
    thinking_log: list[dict] = field(default_factory=list)
    seated: list[Seated] = field(default_factory=list)
    unseated: list[Unseated] = field(default_factory=list)
    kitchen_sheet: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "day_offset": self.day_offset, "service": self.service,
            "thinking_log": self.thinking_log,
            "seated": [s.as_dict() for s in self.seated],
            "unseated": [u.as_dict() for u in self.unseated],
            "kitchen_sheet": self.kitchen_sheet, "warnings": self.warnings,
            "summary": self.summary,
        }


# --------------------------------------------------------------------------
# queue ordering
# --------------------------------------------------------------------------
def _order_queue(covers: list[Cover], vip_on: bool) -> list[Cover]:
    """Big-first, with an occasion booking jumping to the front (vip-window)."""
    def key(c: Cover) -> tuple[int, int]:
        jump = 0 if (vip_on and c.is_celebration) else 1
        return (jump, -c.party_size)
    return sorted(covers, key=key)


# --------------------------------------------------------------------------
# table-finding helpers
# --------------------------------------------------------------------------
def _find_joinable_pair(size: int, tables: list[Table],
                        used: set[str]) -> tuple[Table, Table] | None:
    """The lowest-waste pair of linked tables that reaches ``size``, or None.

    Returned as ``(primary, secondary)`` sorted by table id - "primary" is
    what every other rule (occasion holds, server-balance, the kitchen sheet)
    means by "the joined party's table".
    """
    by_id = {t.id: t for t in tables}
    seen: set[tuple[str, str]] = set()
    best: tuple[tuple[int, str, str], tuple[Table, Table]] | None = None
    for t in tables:
        if t.id in used:
            continue
        for other_id in t.joinable_with:
            other = by_id.get(other_id)
            if other is None or other.id in used or other.id == t.id:
                continue
            pair_key = tuple(sorted((t.id, other.id)))
            if pair_key in seen:
                continue
            seen.add(pair_key)
            total = t.seats + other.seats
            if total < size:
                continue
            ordered = tuple(sorted((t, other), key=lambda tb: tb.id))
            rank = (total - size, ordered[0].id, ordered[1].id)
            if best is None or rank < best[0]:
                best = (rank, ordered)
    return best[1] if best else None


def _place_party(cover: Cover, tables: list[Table], used: set[str], join_on: bool,
                 vip_on: bool, hold_zones_folded: frozenset[str]) -> (
        tuple[list[str], list[str], float, str] | str):
    """An ordinary (non-group) party. Zone-preferred single table, then a pair.

    ``hold_zones_folded`` is the hotel's own configured zone names
    (case/accent-folded) that count as a window/terrace-style hold - see
    ``run_seating_plan``'s ``hold_zones`` parameter."""
    prefer_hold = vip_on and cover.is_celebration
    candidates = [t for t in tables if t.id not in used and t.seats >= cover.party_size]
    if prefer_hold:
        held = [t for t in candidates if _fold(t.zone) in hold_zones_folded]
        if held:
            candidates = held
    if candidates:
        best = min(candidates, key=lambda t: (t.seats, t.id))
        return [best.id], [], float(best.seats), best.zone
    if join_on:
        pair = _find_joinable_pair(cover.party_size, tables, used)
        if pair:
            t1, t2 = pair
            return [t1.id, t2.id], ["Joined tables"], float(t1.seats + t2.seats), t1.zone
    return f"No free table (or joined pair) seats a party of {cover.party_size} this turn."


def _place_group(cover: Cover, tables: list[Table], used: set[str], join_on: bool,
                 banquet_factor: float) -> tuple[list[str], list[str], float, str] | str:
    """party_size > 8 or is_group: single table (private preferred), joined
    pair, then a private-dining composite. See the module docstring for why
    the composite step is gated on ``join_on``."""
    size = cover.party_size
    candidates = [t for t in tables if t.id not in used and t.seats >= size]
    if candidates:
        best = min(candidates, key=lambda t: (t.zone != PRIVATE_ZONE, t.seats, t.id))
        return [best.id], ["Group"], float(best.seats), best.zone

    private_tables = sorted([t for t in tables if t.zone == PRIVATE_ZONE and t.id not in used],
                            key=lambda t: t.id)

    if not join_on:
        if private_tables:
            biggest = max(private_tables, key=lambda t: t.seats)
            return (f"Table joins are off: the private room's largest single table "
                    f"({biggest.id}, {biggest.seats} seats) is smaller than the party of {size}.")
        return f"No table seats a party of {size}, and table joins are off."

    pair = _find_joinable_pair(size, tables, used)
    if pair:
        t1, t2 = pair
        return [t1.id, t2.id], ["Group", "Joined tables"], float(t1.seats + t2.seats), t1.zone

    composite = list(private_tables)
    composite_seats = sum(t.seats for t in composite)
    has_private = bool(private_tables)
    remaining = sorted(
        [t for t in tables if t.id not in used and t.zone != BAR_ZONE and t not in composite],
        key=lambda t: (-t.seats, t.id))
    idx = 0
    factor = banquet_factor if has_private else 1.0
    while composite_seats * factor < size and idx < len(remaining):
        composite.append(remaining[idx])
        composite_seats += remaining[idx].seats
        idx += 1
    effective_seats = composite_seats * factor
    if composite and effective_seats >= size:
        flags = ["Group", "Private dining composite"]
        if has_private:
            flags.append("Set menu")
        return [t.id for t in composite], flags, effective_seats, composite[0].zone

    return f"No combination of tables reaches a party of {size}."


# --------------------------------------------------------------------------
# the whole plan
# --------------------------------------------------------------------------
def run_seating_plan(tables: list[Table], covers: list[Cover], rules: dict[str, bool], *,
                     day_offset: int, service: str,
                     late_cutoff: str = LATE_CUTOFF_DEFAULT,
                     banquet_factor: float = BANQUET_FACTOR_DEFAULT,
                     zone_cover_cap: int = ZONE_COVER_CAP_DEFAULT,
                     hold_zones: tuple[str, ...] = HOLD_ZONES) -> SeatingPlan:
    """Plan one service. See the module docstring - this function has no I/O.

    ``hold_zones`` names the zone(s) an occasion booking is held to when
    ``vip-window`` is on - matched case/accent-folded against
    ``floor_tables.zone``, so a property's own zone names
    (``Sala``/``Giardino``, not just ``Window``/``Terrace``) work without
    any code change. Configured in ``config/agent.yaml: dining.hold_zones``
    and threaded in from ``tools/run.py`` - the default here only matches
    the shipped demo fixtures.
    """
    hold_zones_folded = frozenset(_fold(z) for z in hold_zones)
    plan = SeatingPlan(day_offset=day_offset, service=service)
    book = [c for c in covers if c.day_offset == day_offset and c.service == service]
    total_covers = sum(c.party_size for c in book)
    largest = max(book, key=lambda c: c.party_size, default=None)
    plan.thinking_log.append({
        "step": "read-book",
        "text": f"Reading the book — {len(book)} booking(s), {total_covers} cover(s) at {service}.",
        "detail": {"bookings": len(book), "covers": total_covers, "tables": len(tables),
                   "seats": sum(t.seats for t in tables),
                   "largest_party": {"name": largest.party_name, "size": largest.party_size}
                                    if largest else None},
    })

    turn_time_on = bool(rules.get("turn-time", True))
    if turn_time_on:
        turns = [[c for c in book if c.time < late_cutoff],
                [c for c in book if c.time >= late_cutoff]]
        sittings = len(tables) * 2
        pacing_text = (f"Turn-time pacing is on: bookings before {late_cutoff} are the first "
                      f"turn, {late_cutoff} and later are the second — {sittings} sittings "
                      f"across {len(tables)} tables.")
    else:
        turns = [book]
        sittings = len(tables)
        pacing_text = ("Turn-time pacing is off: every table is held for one party all "
                      f"night — a hard ceiling of {sittings} sittings.")
        if len(book) > sittings:
            plan.warnings.append(
                f"Turn-time pacing is off and tonight has {len(book)} bookings for only "
                f"{sittings} tables — expect gaps or turned-away parties.")
    plan.thinking_log.append({"step": "pacing", "text": pacing_text,
                              "detail": {"turn_time": turn_time_on, "sittings": sittings}})

    join_on = bool(rules.get("join-tables", True))
    vip_on = bool(rules.get("vip-window", True))
    balance_on = bool(rules.get("server-balance", True))
    allergy_on = bool(rules.get("allergy-flag", True))

    used_by_turn: list[set[str]] = [set() for _ in turns]
    occasion_notes: list[str] = []
    zone_turn_covers: dict[tuple[int, str], int] = {}

    for turn_idx, turn_covers in enumerate(turns):
        for cover in _order_queue(turn_covers, vip_on):
            is_group = cover.is_group or cover.party_size > GROUP_SIZE_THRESHOLD
            result = (_place_group(cover, tables, used_by_turn[turn_idx], join_on, banquet_factor)
                     if is_group else
                     _place_party(cover, tables, used_by_turn[turn_idx], join_on, vip_on,
                                 hold_zones_folded))
            if isinstance(result, str):
                plan.unseated.append(Unseated(cover=cover, reason=result))
                continue
            table_ids, flags, effective_seats, zone = result
            used_by_turn[turn_idx].update(table_ids)
            seated = Seated(cover=cover, table_ids=table_ids, turn=turn_idx, zone=zone,
                            flags=list(flags), effective_seats=effective_seats)
            plan.seated.append(seated)
            zone_turn_covers[(turn_idx, zone)] = (zone_turn_covers.get((turn_idx, zone), 0)
                                                  + cover.party_size)
            if vip_on and cover.is_celebration and _fold(zone) in hold_zones_folded:
                seated.flags.append("Occasion hold")
                occasion_notes.append(
                    f"{cover.party_name} ({cover.occasion}, party of {cover.party_size}) -> "
                    f"{table_ids[0]} on the {zone.lower()}.")

    if vip_on and occasion_notes:
        zone_list = "/".join(sorted(hold_zones)) or "a hold zone"
        plan.thinking_log.append({
            "step": "occasion-holds",
            "text": f"{len(occasion_notes)} occasion booking(s) held a {zone_list} table.",
            "detail": {"notes": occasion_notes}})
    elif not vip_on:
        plan.thinking_log.append({
            "step": "occasion-holds",
            "text": "Occasion holds are off: celebrations are seated in plain booking order, "
                   "no reserved section.", "detail": {}})

    kitchen_flag_count = 0
    nut_allergy_names: list[str] = []
    ambiguous_allergy_names: list[str] = []
    for seated in plan.seated:
        if not seated.cover.dietary:
            continue
        kitchen_flag_count += 1
        if seated.cover.has_nut_allergy:
            nut_allergy_names.append(seated.cover.party_name)
        elif seated.cover.has_allergy_signal:
            ambiguous_allergy_names.append(seated.cover.party_name)
        if allergy_on:
            plan.kitchen_sheet.append({
                "table_ids": seated.table_ids, "party_name": seated.cover.party_name,
                "covers": seated.cover.party_size, "time": seated.cover.time,
                "dietary": seated.cover.dietary})
    if allergy_on and nut_allergy_names:
        plan.thinking_log.append({
            "step": "nut-allergy",
            "text": (f"NUT ALLERGY at {', '.join(nut_allergy_names)}'s table — kitchen sheet "
                    "flagged, allergen brief goes to the pass, the section server and the "
                    "sommelier before service."),
            "detail": {"parties": nut_allergy_names}})
    elif nut_allergy_names:
        plan.warnings.append(
            f"{', '.join(nut_allergy_names)} has a nut allergy but allergy-flag is off — "
            "nothing is printed on the kitchen sheet.")
    if ambiguous_allergy_names:
        # Not a recognized nut-allergy phrase, but the note still names some
        # allergy - could be a real allergen this repo has no keyword for.
        # Never guess: always escalate to a person, whatever allergy-flag is
        # set to (docs/safety.md - a risk this module cannot classify must
        # still reach a person, not vanish).
        plan.thinking_log.append({
            "step": "ambiguous-allergy",
            "text": (f"{', '.join(ambiguous_allergy_names)}'s dietary note may describe an "
                    "allergy but does not match a known allergen keyword — needs a person "
                    "to check it by hand before service."),
            "detail": {"parties": ambiguous_allergy_names}})
        plan.warnings.append(
            f"{', '.join(ambiguous_allergy_names)} has a dietary note that may describe an "
            "allergy but did not match a known keyword — needs a person to check it by hand.")
    plan.thinking_log.append({
        "step": "kitchen-sheet",
        "text": (f"{kitchen_flag_count} seated part(y/ies) carry a dietary note."
                if allergy_on else
                f"Allergy flagging is off: {kitchen_flag_count} dietary note(s) counted, "
                "nothing printed to the kitchen sheet."),
        "detail": {"count": kitchen_flag_count}})

    if balance_on:
        for (turn_idx, zone), covers_ct in sorted(zone_turn_covers.items()):
            if covers_ct > zone_cover_cap:
                plan.warnings.append(
                    f"{zone} is carrying {covers_ct} covers in turn {turn_idx + 1} "
                    f"(cap {zone_cover_cap}) — split it across two server sections.")
        plan.thinking_log.append({
            "step": "server-balance",
            "text": f"Checked every zone against the {zone_cover_cap}-cover cap per turn.",
            "detail": {f"{zone} turn {t + 1}": n for (t, zone), n in zone_turn_covers.items()}})
    else:
        plan.thinking_log.append({
            "step": "server-balance",
            "text": "Server-balance checking is off: zone loads are shown, nothing is capped.",
            "detail": {f"{zone} turn {t + 1}": n for (t, zone), n in zone_turn_covers.items()}})

    for u in plan.unseated:
        plan.thinking_log.append({
            "step": "unseated",
            "text": f"{u.cover.party_name} (party of {u.cover.party_size}) could not be "
                   f"seated: {u.reason}",
            "detail": {"party": u.cover.party_name, "size": u.cover.party_size,
                      "reason": u.reason}})

    plan.seated.sort(key=lambda s: (s.turn, s.cover.time, -s.cover.party_size))

    composite = next((s for s in plan.seated if "Private dining composite" in s.flags), None)
    plan.summary = {
        "covers": total_covers, "parties": len(book),
        "seated": len(plan.seated), "unseated": len(plan.unseated),
        "tables_used": len({tid for s in plan.seated for tid in s.table_ids}),
        "tables_total": len(tables),
        "largest_party": ({"name": largest.party_name, "size": largest.party_size}
                          if largest else None),
        "composite": ({"party_name": composite.cover.party_name,
                      "table_ids": composite.table_ids} if composite else None),
        "warning_count": len(plan.warnings), "kitchen_flag_count": kitchen_flag_count,
    }
    plan.thinking_log.append({
        "step": "summary",
        "text": (f"{plan.summary['seated']} of {plan.summary['parties']} parties seated "
                f"({total_covers} covers), {plan.summary['tables_used']}/{len(tables)} "
                f"tables used, {len(plan.warnings)} warning(s)."),
        "detail": plan.summary})
    return plan
