# Workflow: working the review queue

Objective: turn a queued seating plan into a decision - approve, edit, or
reject - and, once approved, actually notify the floor and kitchen.

Nothing reaches the floor without going through this. `mode: shadow` blocks
`send_message` and `sheets_write` for everything except a plan you have
approved or edited; see `docs/safety.md` for the full guard.

## Steps

1. **See what is waiting.**
   ```bash
   make review
   ```
   Each line shows the item id, its status (`pending_review` or
   `needs_human`), which day/service it plans, and the seated/warning
   counts.

2. **Read one in full.**
   ```bash
   python3 tools/review.py show <id>
   ```
   Prints the whole plan: every seated party and its table(s), every
   unseated booking and why, the kitchen sheet, the warnings, the
   step-by-step reasoning log, and the pre-service note. Summarise it for
   the host in plain language - the headline numbers, the big group, any
   allergy, any overloaded section, any unseated booking - do not paste the
   raw JSON at them.

3. **Decide.**
   ```bash
   python3 tools/review.py approve <id>
   python3 tools/review.py edit <id> --body-file my-note.txt
   python3 tools/review.py reject <id> --reason "table plan needs a rework"
   ```
   `edit` here rewrites the pre-service note text (`draft.narrative`), not
   the seating plan itself - the plan is deterministic output from
   `tools/seating_engine.py`. To change the plan, toggle a rule or simulate a
   walk-in (`workflows/10-seating.md`) and re-run; that produces a fresh item
   to review, it never mutates the one you just looked at.

4. **Send what was approved.**
   ```bash
   python3 tools/review.py send
   ```
   Claims everything `approved`/`edited`, posts the pre-service note and
   summary to the floor/kitchen (`messaging.notify_staff`), and exports the
   kitchen sheet and a floor-plan log row (`sheets.append`). In `mode:
   shadow` this only ever works for zero items - shadow blocks the write
   regardless of approval (`core/review.py`); nothing is sent while shadow
   is on.

5. **A failed send.** `send` marks the item `failed` with the error
   attached.
   ```bash
   python3 tools/review.py retry <id>
   ```
   re-queues it for another attempt once you have fixed the cause (usually a
   messaging or sheets credential - `make doctor` will say which).

## Rules

- Only `tools/review.py` writes `approved` / `edited` / `rejected`.
- A booking that could not be seated always needs a human - never approve a
  plan with an unseated booking without deciding what happens to that party
  (a different table, a different time, or telling them there is no room).
- Confirm with the host before sending anything, even an approved plan, the
  first few times. `workflows/90-go-live.md` covers when to stop doing that.
