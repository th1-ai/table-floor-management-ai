# Instructions for Claude

You are working inside **Table / Floor Management AI** ("The Maître d'") — Optimises the restaurant floor (seating plan, covers pacing, turn times, no-show prediction, walk-in vs reservation balance) and syncs with concierge bookings..

You are the hotel's Claude Code session. The person you are talking to runs a
hotel; they are not a developer. Your job is to get this agent working for their
property and then help them run it.

**Read `README.md` first.** It is written for them, it explains what this agent
does, and it is the map for everything below.

---

## How this repo is built: WAT

Three layers, and keeping them separate is what makes the agent reliable.

**Workflows** (`workflows/*.md`) are the standard operating procedures. Plain
markdown, written the way you would brief a colleague. Read the relevant one
before you act.

**You** are the decision-maker. You read the workflow, run the tools in order,
handle what goes wrong, and ask when you are genuinely stuck. You do not do the
work by hand that a tool already does.

**Tools** (`tools/*.py`) do the actual work. They are deterministic Python with
`--help` on every one. They are tested. They are fast. Prefer them.

Why it matters: if you did every step yourself and each step was 90% right, five
steps would land at 59%. Handing execution to tested code keeps the accuracy
where it belongs and leaves you to make the judgement calls.

The workflows in this repo:

| File | When |
|---|---|
| `workflows/00-setup.md` | First run. Config, credentials, knowledge, doctor, demo. |
| `workflows/10-*.md` | The agent's main job, step by step. |
| `workflows/80-review.md` | Working the review queue. |
| `workflows/90-go-live.md` | The shadow to live checklist. |
| `workflows/99-troubleshooting.md` | When something breaks. |

---

## The rules

**1. Never send anything in shadow mode.** `mode: shadow` in `config/hotel.yaml`
means the agent drafts and queues, nothing more. Do not work around it. Do not
suggest working around it. If a command is blocked, that is the system doing its
job — read the message, it says what to do. Approving an item in shadow is recorded, not sent; the go-live checklist clears the shadow-era queue with `python3 tools/review.py stale`.

**2. Ask before going live.** Switching `mode` to `live` is the hotel's decision,
never yours. Before you even raise it, `workflows/90-go-live.md` has to have been
worked through: real drafts reviewed, the review queue exercised, `make doctor`
clean. When you do raise it, say plainly what will change.

**3. Ask before anything irreversible.** Sending a guest an email, writing to the
PMS, taking a payment, publishing a review reply. Even in live mode, even when it
is approved, say what you are about to do before you do it.

**4. Look for a tool before writing code.** `ls tools/` and read the `--help`.
Almost everything you need is already there. If you do need something new, write
it as a tool with an argparse CLI, so it can be re-run and tested.

**5. Do not rewrite a workflow without asking.** Refine, correct, add what you
learned. Do not replace. These are the hotel's instructions, not scratch paper.

**6. Secrets live in `.env` and nowhere else.** Never paste a key into a config
file, a prompt, a commit or a chat message. Never print one.

**7. Everything in `data/` is disposable.** The database, the logs, the exports.
Deliverables that the hotel needs to see belong in `data/exports/` (or a Google
Sheet, if that is configured) and get mentioned by name when you finish.

---

## The interactive provider: how you answer the agent's questions

If `llm.provider` is `interactive` in `config/hotel.yaml`, the agent does not
call a model at all. It asks **you**.

When a run needs a decision it writes the prompt to
`data/pending/<id>.prompt.md`, writes the JSON schema for the answer to
`data/pending/<id>.schema.json`, prints what it is waiting for, and exits with
code 3. That exit code is not an error.

What you do:

1. Read `data/pending/<id>.prompt.md`. It contains the property facts, the task,
   and the item.
2. Work out the answer.
3. Write it as JSON to `data/pending/<id>.answer.json`, matching the schema
   exactly. Nothing else in the file, no prose, no code fence.
4. Run the same command again. The agent picks up your answer, deletes the
   prompt, and carries on.

If there are several pending prompts, answer them all and re-run once.

This mode costs the hotel nothing extra — it uses the Claude Code session they
are already paying for — and it is the best way for them to see how the agent
thinks. Suggest they start here.

---

## Working style

**Explain in their language.** They run a hotel. "The agent could not reach your
mailbox because the password in `.env` is not an app password" is useful.
A stack trace is not.

**Show the command, then the result.** They should be able to re-run anything you
did.

**When something fails, read the whole error.** The tools in this repo are
written to tell you what to fix. Fix the cause, re-run, then note in the relevant
workflow what you learned so the next person does not hit it.

**When you are not sure, stop and ask.** A wrong guess that reaches a guest costs
the hotel far more than a question costs you.

---

## Quick reference

```bash
make setup      # virtualenv, dependencies, config files
make doctor     # is everything configured and reachable?
make demo       # one full cycle on sample data, no credentials needed
make run        # one real pass
make review     # what is waiting for a human
make test       # the test suite
make schedule   # cron / launchd / systemd snippet for this machine
make report     # what the agent did, and what it cost
```

Paths worth knowing:

```
config/hotel.yaml     the property, the systems, the mode
config/agent.yaml     this agent's own settings
knowledge/            what the agent knows about the property
prompts/              how it is asked to think - editable
data/agent.db         everything it has seen and decided
data/logs/*.jsonl     every decision, with a run id
data/pending/         parked prompts, when provider is interactive
docs/safety.md        the guardrails, in full
```

---

## Agent specifics

**Nothing here talks to a guest.** This agent reads a floor and a book,
proposes a seating plan, and (once approved) notifies staff. There is no
guest inbox, no guest-facing text, and no AI-disclosure line to add
(`docs/safety.md`). `knowledge/property.md`/`faq.md`/`signature.md` ship as
the generic scaffold and are not read by anything here -
`knowledge/dining-policy.md` is the one file worth filling in.

**This agent does not use `systems.pms.adapter`.** A restaurant cover
(time, party size, dietary, occasion) does not fit the shared `Reservation`
dataclass every room-facing agent in this family reads through. The floor
and the book load through `tools/covers_book.py` instead - CSV in
`data/imports/` for a real property, the bundled fixtures for the demo.
`make doctor` still pings a PMS adapter (every repo shares the same
`core/adapters` registry) and it will show PASS against an empty fixture -
that is expected, not a sign the PMS is connected.

**A rule toggle and a walk-in are both fresh plans, never edits.**
`tools/run.py --set-rule <key>=on|off` changes the live rule state and
exits without planning; `tools/run.py --once --walk-in "Name,Size,HH:MM"`
inserts a real booking and re-plans the whole service from scratch. Either
one produces a brand-new item to review - the plan a host already looked at
is never silently changed underneath them (`docs/how-it-works.md`
"Idempotency"). If a user asks why their approved plan didn't pick up a
walk-in, that is why: re-run and review the new one.

**A plan always needs a human**, whatever `mode` is set to - there is no
autonomy setting that skips review for the seating plan itself
(`tools/run.py:_needs_human` forces `needs_human` for an unseated booking or
a hidden nut allergy; everything else is `pending_review`). Going live only
changes whether an *approved* plan actually reaches
`messaging.notify_staff()` / `sheets.append()` - never suggest a config
that removes the review step.

**The narrative note can pend without losing the plan.** With
`llm.provider: interactive`, the plan is computed and cached
(`item.payload["_plan"]`) before the pre-service-note prompt is even
written. If `tools/run.py` exits 3, the plan already exists - answer the
prompt and re-run; it resumes the same item at the narrate stage, it does
not recompute the plan or start a new one.

**`--dry-run` really writes nothing** - not an item row, not an LLM usage
event. Safe to suggest freely when a user wants to see what a rule or
constant change would do before it does anything real.

**Every recurring job is one entry in `config/agent.yaml: schedule:`.**
`python3 tools/schedule.py --all` reads that block and prints one snippet
per job (`plan_lunch`, `plan_dinner`) - never hand-write a cron line for a
job that is not listed there; add it to `schedule:` first.
