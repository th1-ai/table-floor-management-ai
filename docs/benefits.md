# Measuring the benefit

## The business case

From the roster this repo is built from:

**Why it matters.** Better table turns and fewer gaps = more covers from the
same room.

**What to expect.** 5-15% more covers per service via tighter turns and
no-show backfill.

**ROI figure.** `+10%` covers per service (revenue).

That range is a property-level claim about a whole service, built up from
two mechanisms this repo actually implements (tighter turns via
`turn-time`, backfilling the gaps a no-show or a cancellation leaves via the
walk-in path) and is honest about what it does not yet implement (see
"What this repo cannot claim" below). Whether a specific room gets 5% or 15%
depends on how full the book already is, how many tables the private-dining
composite frees up on group nights, and how disciplined the floor has been
without this tool - there is no formula in this repo that outputs a
percentage, and it should not claim one.

## What to measure

```bash
make report
python3 tools/report.py --json
```

- **Parties seated vs. planned** (`seated_pct`) - the plainest signal that
  the room is being used well. Compare this against your own pre-agent
  baseline (a week of manual seating charts, or your reservation system's
  own no-show/turn-away log) - this repo has no baseline of its own to
  compare against.
- **Tables used per service** (`tables_used`/`tables_total` in a plan's
  `summary`) - low utilisation on a fully booked night usually means the
  private-dining composite or table joins are turned off, or the floor is
  smaller than the book needs.
- **Warnings raised** - a rising trend usually means `zone_cover_cap` or
  `banquet_factor` need recalibrating to the real room (`docs/how-it-works.md`
  design decision #5), not that the room is actually overloaded every night.
- **Unseated bookings** - the number that should trend toward zero as you
  connect the real floor and book and tune the rules. Every one has a
  reason attached (`tools/review.py show <id>`) - read them, do not just
  count them.
- **LLM calls and cost** - exactly one model call per plan (the pre-service
  note). This number should stay small; if it is not, something is
  re-planning the same service repeatedly.

## What this repo cannot claim

Honesty over a bigger number, per `docs/how-it-works.md`'s design decisions:

- **No-show prediction is not implemented.** The roster promises "which
  bookings look likely to not turn up"; this engine treats every booking as
  certain to arrive. The walk-in path (a host manually books a real walk-in
  into a gap) delivers the "no-show backfill" half of the roster promise;
  the "prediction" half does not exist yet. Do not tell a restaurant this
  agent forecasts no-shows.
- **Turn length is one fixed cutoff (`late_cutoff`), not a per-table
  model.** The roster promises tracking "how long each table really takes"
  as a variable, measured metric. This repo has a single early/late split
  for the whole room. `make report` cannot show a per-table turn-time
  trend because the engine does not compute one.
- **The banquet bonus and the server-balance cap are house constants**,
  ported from the source this repo was built from with no cited industry
  benchmark. Calibrate them to your own room before trusting the numbers
  they produce (`config/agent.yaml`).

## The counterfactual, honestly

The realistic comparison is not "AI vs. nothing" - most restaurants already
have a host or a manager building a seating chart by hand. The case for this
agent is: the same plan, built in seconds instead of during a busy pre-service
scramble, with every placement's reasoning written down (`show <id>`'s
`thinking_log`) so a new host can see *why* a table was used a certain way,
and a walk-in slotted into a genuine gap instead of turned away because
nobody had time to re-check the chart. It replaces the busywork of building
and re-building the chart, not the host's judgement about who actually sits
where tonight - see `docs/safety.md` "What the agent will not do".
