---
name: table-floor-management-ai
description: Run Table / Floor Management AI ("The Maître d'") — Optimises the restaurant floor (seating plan, covers pacing, turn times, no-show prediction, walk-in vs reservation balance) and syncs with concierge bookings.. Use when the user asks to run the agent, check what is waiting for review, approve or reject a draft, or asks how the agent is doing. Trigger phrases: "run The Maître d'", "/table-floor-management-ai", "check the queue", "what is waiting for me", "approve that draft".
---

# Table / Floor Management AI

Plans a service's seating and works the review queue. Everything happens
from the repo root; every command below exists and works.

## Before anything else

Read `README.md` if you have not this session, and `workflows/10-seating.md`
for the main loop. If the user has never run this agent, start at
`workflows/00-setup.md` instead and walk them through it.

## The loop

**1. Check the agent is healthy.**

```bash
make doctor
```

Any `FAIL` line has a fix hint. Fix it before going further. `WARN` lines
are worth mentioning but do not stop the run.

**2. Plan a service.**

```bash
make run                                          # tomorrow, dinner (the defaults)
make run ARGS="--day-offset 0 --service lunch"    # today's lunch
make run ARGS="--dry-run"                         # compute the plan, write nothing
```

If `llm.provider` is `interactive`, the run will stop with exit code 3 and
park the pre-service-note prompt in `data/pending/`. That is expected. Read
the `*.prompt.md`, write your answer as JSON to the matching `*.answer.json`
(a single `note` field), then run the same command again - it resumes the
same plan, it does not recompute it.

**3. Show what is waiting.**

```bash
make review
python3 tools/review.py show <id>
```

Summarise it for the user in plain language: the headline numbers, the big
group and its tables, any allergy, any overloaded section, any unseated
booking. Do not paste raw JSON at them.

**4. Act on their decision.**

```bash
python3 tools/review.py approve <id>
python3 tools/review.py edit <id> --body-file <path>
python3 tools/review.py reject <id> --reason "<why>"
```

`edit` rewrites the pre-service note text, not the seating plan itself - the
plan is deterministic output from `tools/seating_engine.py`. To change the
plan, use a walk-in or a rule toggle (below) and review the fresh plan that
produces.

**5. A walk-in or a rule change.**

```bash
make run ARGS='--walk-in "Six-top,6,20:15"'      # insert a booking, then re-plan
make run ARGS="--set-rule join-tables=off"       # toggle a rule, then run again to see it
```

Either one produces a brand-new plan to review - the one the user already
saw is untouched.

**6. Report.**

```bash
make report
```

## Rules

- **Never send in shadow mode**, and never work around a blocked write. The
  error message says what to do.
- **Going live is the restaurant's decision.** Only raise it after
  `workflows/90-go-live.md` has been worked through.
- **A plan always needs a human before it reaches the floor** - even in
  live mode, even an auto-eligible one; there is no config that skips this.
  Confirm before sending anything, the first few times.
- **Never print or paste a credential.**
- If a run fails, read the whole error, fix the cause, re-run, and note
  what you learned in `workflows/99-troubleshooting.md`.
