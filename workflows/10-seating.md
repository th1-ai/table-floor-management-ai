# Workflow: plan tonight's seating

Objective: run the seating engine for one service and see the plan Table /
Floor Management AI proposes.

## Inputs

- The floor book (`workflows/00-setup.md` step 4 - real CSVs, or the shipped
  fixtures while you are still learning the tool).
- `config/agent.yaml`'s five `dining_rules`, `late_cutoff`, `banquet_factor`
  and `zone_cover_cap` - the defaults match the source this repo was built
  from; calibrate them to the real room once you have watched a few plans.

## Steps

1. **Plan one service.**
   ```bash
   make run                                          # tomorrow, dinner (the defaults)
   make run ARGS="--day-offset 0 --service lunch"    # today's lunch
   make run ARGS="--dry-run"                         # compute everything, write nothing
   ```
   Table / Floor Management AI reads the floor and the book, runs the
   deterministic engine (`tools/seating_engine.py`), prints its
   step-by-step reasoning, then asks the model for a short pre-service note
   (`prompts/dining_note.md`). Neither call ever seats a table - see
   `docs/how-it-works.md`.

2. **If `llm.provider` is `interactive`,** the run stops with exit code 3 and
   parks the note prompt in `data/pending/`. Read the `*.prompt.md`, write
   your answer as JSON to the matching `*.answer.json` (a single `note`
   field), and run the same command again - it resumes exactly where it
   stopped, it does not re-plan the whole service.

3. **See what happened.**
   ```bash
   make review
   ```
   Every plan is `pending_review` or `needs_human` - never sent
   automatically, whatever `mode` is set to (`docs/safety.md`).
   `needs_human` means a booking could not be seated at all, or a nut allergy
   exists while `allergy-flag` is off.

4. **Simulate a walk-in.** Inserts a real booking into tonight's book and
   plans the whole service again from scratch - a fresh item, not a change to
   the plan you already saw.
   ```bash
   make run ARGS='--walk-in "Six-top,6,20:15"'
   ```

5. **Toggle a rule.** Turns a dining rule on or off and exits without
   planning - run `make run` again afterwards to see the new plan.
   ```bash
   make run ARGS="--set-rule join-tables=off"
   ```
   Valid keys: `turn-time`, `join-tables`, `vip-window`, `server-balance`,
   `allergy-flag`.

6. **Work the queue.** `workflows/80-review.md` covers approve / edit /
   reject / send in full.

7. **Keep it running.**
   ```bash
   make watch
   ```
   Or schedule it - `make schedule ARGS="--all"` prints one snippet per job
   in `config/agent.yaml`'s `schedule:` block (`plan_lunch`, `plan_dinner`).

## Edge cases

- **A booking cannot be seated.** Never dropped silently - it lands in
  `unseated` with a specific reason (no table of that size, or table joins
  are off and the private room's largest single table is still too small),
  and the item is queued `needs_human`.
- **A re-run against an unchanged book.** Finds and resumes the same item
  instead of creating a duplicate - `docs/how-it-works.md` "Idempotency".
- **The pre-service note fails or is refused.** The plan itself is
  unaffected; the note is just missing (`draft.narrative: null`) -
  `docs/how-it-works.md` "Narration never blocks the plan".
