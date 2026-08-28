# Guardrails and safety

This agent proposes a seating plan and, once a host approves it, notifies
your floor and kitchen team. It never talks to a guest and never writes to a
guest-facing system. Everything below is built in, not optional, and this
page explains what it does and what is left for you to decide.

## The two modes

| Mode | What happens |
|---|---|
| `shadow` (default) | The agent reads the book, plans, and queues. It **never** notifies staff and **never** exports a sheet. Approving, editing or rejecting a plan records your decision but sends nothing. At go-live, `python3 tools/review.py stale` clears that shadow-era queue so nothing old goes out by surprise. |
| `live` | Plans you approved are really sent to staff. Everything else still waits. |

`mode` lives in `config/hotel.yaml`. It is a global kill switch: flipping it
back to `shadow` stops every outbound action immediately, mid-schedule, with
no other change. `config/agent.yaml` can be stricter than `hotel.yaml`,
never looser.

Two more brakes:

- `make run ARGS="--dry-run"` computes the plan and writes nothing, even in
  live mode. Use it when you change `late_cutoff`, `banquet_factor` or
  `zone_cover_cap` and want to see the effect first.
- `review.require_approval_for` in `config/agent.yaml` lists the actions
  that need a human even in live mode. The defaults are `send_message`,
  `sheets_write`, `publish`. Shortening that list is how you hand the agent
  more rope, one action at a time - but see "What always needs a human"
  below for the part of this agent that never changes.

Every outbound action in the codebase goes through one function,
`core/review.py:assert_write_allowed`. There is no second path.

## The review queue

Nothing reaches the floor without passing through the queue.

```bash
make review                              # what is waiting
python3 tools/review.py show <id>         # the full plan and how it got there
python3 tools/review.py approve <id>
python3 tools/review.py edit <id> --body-file my-note.txt
python3 tools/review.py reject <id> --reason "table plan needs a rework"
```

A plan moves `new -> pending_review` (or `needs_human`) and then waits. Only
`tools/review.py` can write `approved`, `edited` or `rejected`; only
`tools/run.py`'s `send` command can write `sent`. A crash between "about to
send" and "sent" is picked up on the next pass and shown to you as failed
rather than silently retried.

## What the agent will not do

- **Override a human host's on-the-night judgement.** This is the roster's
  own promise. Concretely: the engine only ever proposes a plan; nothing in
  this codebase auto-seats a walk-in, auto-toggles a rule, or notifies staff
  without a host approving first - in `mode: live` and `mode: shadow` alike.
- Notify staff or export a sheet while `mode: shadow`.
- Send a plan a human has not approved, once the action needs approval.
- Drop a booking silently. Every unseated booking carries a specific reason
  (`tools/seating_engine.py`) - never "could not be placed", always why.
- Hide a nut allergy, whatever language it was written in. Nut-allergy
  detection (`tools/seating_engine.py:has_nut_allergy`) matches English,
  Spanish, French, German, Italian and Portuguese phrases, accent-folded
  ("allergia alle noci", "Nussallergie" and "nut allergy" all flag the
  same). If `allergy-flag` is off, the risk is still named in a warning
  ("...but nothing is printed on the kitchen sheet") rather than simply
  vanishing from the plan. A dietary note that names *some* allergy but
  matches none of those specific phrases is never dropped either - it
  escalates to `needs_human` instead of being guessed at (see "What always
  needs a human" below).
- Invent a guest, a table, a dish or a number in the pre-service note. The
  prompt (`prompts/dining_note.md`) is explicit: only facts from the
  finished plan, nothing else.
- Take a payment, issue a refund, or move money. Payment adapters are
  read-only by design and this agent never calls one.

## What always needs a human

Enforced in code (`tools/run.py:_needs_human`), not just in the prompt -
there is no config flag that relaxes either of these:

- **A booking that could not be seated at all.** A host must decide what
  happens to that party - a different table, a different time, or telling
  them there is no room tonight.
- **A nut allergy present in the book while `allergy-flag` is off.** The
  kitchen sheet has nothing printed, so a person must see it another way.
- **A dietary note that looks like it names an allergy, in any of this
  agent's language families, but does not match a specific nut-allergy
  phrase.** This repo cannot always tell what the allergen is - it never
  guesses. `Cover.has_allergy_signal` catches the common allergy/allergie/
  alergia/allergisch/allergico word family and always escalates, whatever
  `allergy-flag` is set to.

Every other plan is `pending_review` and still waits for a host to approve
before anything is sent - "always needs a human" above is about which plans
get flagged more urgently, not about which plans skip review. Nothing here
ever reaches `auto_sent`.

## Data handling

**What leaves your machine.** With `llm.provider: anthropic` or
`claude-code`, the pre-service-note prompt goes to Anthropic. That prompt
contains the finished plan's summary, warnings and kitchen sheet - party
names, sizes, times and dietary notes, not full guest profiles or contact
details. With `llm.provider: mock` or `interactive`, nothing leaves the
machine at all.

**What is stored, and where.** Everything lives in `data/` inside this
folder: `agent.db` (SQLite - the floor book, every plan, every decision),
`logs/*.jsonl`, `exports/`. `data/` is gitignored. There is no cloud service
behind this repo and no telemetry.

**Dietary and allergy notes are the sensitive data here**, not payment
cards. `core/redact.py`'s card/IBAN redaction still runs on every string
that flows through this agent (the same shared runtime as every repo in the
family), but it is not the meaningful protection for a restaurant floor plan
- keeping `data/agent.db` off a shared machine, and setting
`privacy.retention_days` to something short, is.

**Retention.** `privacy.retention_days` (default 365) is how long processed
plans stay in the database. Deleting `data/agent.db` deletes everything the
agent knows, including the live floor book - re-seed it from
`data/imports/*.csv` or the fixtures afterwards (`workflows/00-setup.md`).

## GDPR, in practice

If you are in the EU or handle EU guests' data, the short version:

- **You are the controller.** This software runs on your machine, under
  your control, on your data. TH1 does not receive it.
- **Your model provider is a processor**, only if you use `llm.provider:
  anthropic` or `claude-code`. Check their data processing terms and record
  them in your processing register.
- **Purpose and minimisation.** The engine sees party name, size, time,
  dietary notes and occasion - what it needs to seat the room. Do not put
  full guest contact details or payment information anywhere in this
  agent's book.
- **Right to erasure.** A guest asking to be forgotten means removing their
  rows from `data/agent.db` (`restaurant_covers` and any `items` referencing
  them) and any exported CSVs. Ask your Claude session: *"Delete every row
  in restaurant_covers and items whose payload mentions this guest's name,
  and tell me how many rows you removed."*
- **Retention.** Set `privacy.retention_days` to what your own policy says,
  not to the default.

This is a practical summary, not legal advice.

## No guest-facing text, so no AI-disclosure line

Unlike a guest-messaging agent in this family, this repo produces nothing a
guest ever reads - the pre-service note goes to your own floor and kitchen
team, who already know they are looking at an AI-assisted tool. The EU AI
Act Article 50 guest-disclosure pattern the rest of this family follows does
not apply here; there is no signature line to add and no guest language to
detect (`hotel.languages` is not read by anything in this agent).

## Subscription or API: an honest note

Two ways to pay for the reasoning behind the pre-service note - the plan
itself is free, deterministic code (`tools/seating_engine.py`), and never
touches a model:

**Your Claude Code subscription** (`llm.provider: claude-code` or
`interactive`). Flat monthly cost, no per-message billing. Genuinely the
cheapest way to run this agent for a small restaurant - a handful of notes a
day is exactly what a personal subscription is for.

The caveat, plainly: a personal Pro or Max subscription is intended for
interactive use, and Anthropic's usage policy and rate limits apply to
automated use of it. Read the terms and decide for yourself.

**The Anthropic API** (`llm.provider: anthropic`). Pay per token, no
ambiguity about automated use, proper rate limits, and usage you can
attribute. `make report` shows what you are spending - for this agent that
number should stay small, since there is exactly one model call per plan.

## If something goes wrong

1. `mode: shadow` in `config/hotel.yaml`, or `AGENT_MODE=shadow` in `.env`.
   Every outbound action stops on the next pass.
2. Remove the schedule (`crontab -e`, `launchctl unload`, or
   `systemctl disable --now <slug>-*.timer`).
3. `make doctor` to see what the agent thinks its state is.
4. `data/logs/*.jsonl` has every decision, with the run id, in order.
