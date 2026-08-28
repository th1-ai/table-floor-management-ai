# knowledge/

This folder is the agent's memory of your property. Most agents in this
family read these files before drafting anything a guest sees. **Table /
Floor Management AI is different: nothing here is read by a prompt.** This
agent produces no guest-facing text at all (`docs/safety.md` "No
guest-facing text, so no AI-disclosure line"), so `property.md`/`faq.md`/
`signature.md` below are the generic scaffold templates, shipped for
consistency across the family, and are optional for this repo specifically.
`dining-policy.md` is the one file that actually matters here - a
plain-language record of *why* `config/agent.yaml`'s numbers are what they
are, for the next person (including a future you) who has to change one.

## What to put here

| File | What it holds |
|---|---|
| `dining-policy.md` | **This agent's own.** Why the private room, the banquet bonus and the server-balance cap are set where they are. See `knowledge/dining-policy.example.md`. |
| `property.md` | Generic scaffold template. Not read by this agent. |
| `faq.md` | Generic scaffold template. Not read by this agent. |
| `signature.md` | Generic scaffold template. Not read by this agent - there is no outbound message to sign. |

Copy the file that actually matters here:

```bash
cp knowledge/dining-policy.example.md knowledge/dining-policy.md
```

`knowledge/*.md` is gitignored (the `.example.md` files are not), because
your property notes are yours.

## How to write `dining-policy.md`

**Write it the way you would brief the next duty manager.** Short
sentences, the real reasoning, no marketing language. Nobody but a human
ever reads this file.

**Say why, not just what.** `config/agent.yaml` already has the numbers;
this file is for the reasoning that does not fit in a YAML comment - why
the private room's banquet bonus is 1.15 and not 1.25, why the server-
balance cap is 24 covers on this floor and not 30.

**Keep it dated.** A constant with no date on it goes stale silently. Note
when you last checked each one against a real service.

## Keeping it current

Whenever you change a number in `config/agent.yaml`, update
`dining-policy.md` in the same sitting - the reasoning is worth as much as
the number. A good trigger: every time a plan raises the same warning twice
in a week, ask whether the setting behind it needs a look, and if you
change it, write down why here.
