# Workflow: troubleshooting

Read the whole error before doing anything - every tool here is written to
say what broke and what to do about it. If you fix something not covered
below, add it here.

## `make doctor` shows a FAIL

Each `FAIL` line has a `->` fix hint right under it. Common ones:

- **`hotel identity`: name is still 'Hotel Aurora'.** Expected on a fresh
  clone. Edit `config/hotel.yaml`.
- **`floor book`: no floor_tables rows.** `fixtures/restaurant/floor_tables.json`
  is missing, or `data/imports/floor_tables.csv` exists but is empty/malformed.
  Restore the fixture from git, or check the CSV headers against
  `docs/integrations.md`.
- **`llm provider`: claude-code selected but `claude` is not on PATH.**
  Install Claude Code, or switch `llm.provider` to `interactive` or
  `anthropic` in `config/hotel.yaml`.
- **`llm provider`: ANTHROPIC_API_KEY is not set.** Add it to `.env`, or
  switch `llm.provider` to `claude-code` or `interactive`.
- **`pms adapter` shows a FAIL.** This agent does not use the PMS adapter at
  all (`docs/how-it-works.md` "Design decisions" #6) - `fixtures/hotel/reservations.json`
  ships as an empty array purely so this line reports PASS instead of a
  misleading FAIL. If you see a FAIL here, that file was deleted; restore it
  from git.

## `make demo` does not print `DEMO OK`

- Make sure `make setup` ran first (`.venv` must exist).
- `tools/demo.py` forces `llm.provider=mock` and reads
  `fixtures/restaurant/floor_tables.json` + `fixtures/inbound/*.json` - if you
  deleted or renamed those, restore them from git.
- Read the traceback if there is one; `tools/demo.py` does not swallow
  errors on purpose, so a fixture problem shows up immediately.

## `make run` exits with code 3

Not an error. `llm.provider: interactive` parked the pre-service-note
prompt. Read `data/pending/*.prompt.md`, write your answer to the matching
`*.answer.json` (JSON only, a single `note` field, no prose, no code fence),
and run the same command again. The seating plan itself is not recomputed -
only the note.

## `make run --set-rule` or `--walk-in` prints an error and exits 2

The argument did not parse. `--set-rule` needs
`<turn-time|join-tables|vip-window|server-balance|allergy-flag>=on|off`.
`--walk-in` needs exactly `Name,PartySize,HH:MM`, e.g. `"Six-top,6,20:15"` -
note the size and the time are separate fields; a stray extra comma or a
12-hour time will fail to parse. The error message names exactly what was
expected.

## A booking always shows up unseated

Check `python3 tools/review.py show <id>` for the exact reason. Common
causes: `join-tables` is off and the party is bigger than any single table;
no table (or combination) reaches the party size at all; or `turn-time` is
off and there simply are not enough tables for the number of bookings
tonight. The reason names the specific constraint - fix the floor plan or
the rule, not the code.

## An item is stuck at `sending`

A process died between claiming an item and finishing the send.
`tools/run.py` calls `core.store.Store.reap_stuck_sending()` on every pass,
which moves anything stuck for more than 30 minutes to `failed` so you see
it in the queue instead of it vanishing. Use
`python3 tools/review.py retry <id>` once the cause is fixed.

## `python3 tools/*.py` says `ModuleNotFoundError: No module named 'core'`

You ran it with a Python that is not the repo's virtualenv, or from outside
the repo root. Use `make run` / `make doctor` / etc. (they call
`.venv/bin/python` for you), or run `.venv/bin/python tools/run.py` directly
from the repo root.

## Still stuck

`data/logs/*.jsonl` has every decision the agent made, in order, with a run
id. `python3 tools/review.py show <id>` has the full event trail for one
plan. If neither explains it, that is a real bug - describe exactly what you
ran and what you expected, and ask.
