# Dining policy - The Birchwood Room

<!--
Copy this to knowledge/dining-policy.md and replace everything with your
own numbers and reasoning. Unlike knowledge/property.md and faq.md, nothing
in this file is read by a prompt - it exists so a human (you, or the next
person who inherits this floor) can see WHY config/agent.yaml's numbers are
what they are, in plain language, next to the config that encodes them.
Keep it current whenever you change a rule or a constant.
-->

## Why the private room's banquet bonus is 1.15

`config/agent.yaml: banquet_factor` gives a composite that uses a
private-zone table a 15% capacity bonus over its raw à-la-carte seat count,
reflecting that a set-menu, banquet-style room can pack chairs tighter than
a normal covered table. This is the number the source demo this repo was
built from ships with, not a benchmark we have measured - the first thing
to do with a real private room is watch three or four real group bookings
against the plan and see whether 1.15 over- or under-states what actually
fits.

## Why the server-balance cap is 24 covers

`config/agent.yaml: zone_cover_cap` is the same story - a house constant
from the source demo, not a citation to an industry number
(`docs/how-it-works.md` design decision #5). One section server on this
floor genuinely tops out around 24 covers in a turn before service slows
down; if your sections are staffed differently, change this number and
note the date and the reasoning here.

## Why `late_cutoff` is 20:15

`config/agent.yaml: late_cutoff` is the single line between the first and
second turn. 20:15 matches a roughly 90-minute first seating starting at
19:00 and gives the kitchen a clean break between the two - see
`docs/how-it-works.md` design decision #3 for why this is one fixed
cutoff and not a true per-table turn-time model yet. Move this earlier if
your dining room tends to run later, or later if your first turn is
usually still eating past 20:00.

## Group and private-dining house rules

Write down what you actually tell a corporate booker or a wedding party
here - minimum notice for a party that will need the private-dining
composite, whether you require a set menu above a certain size, deposit
policy, and anything about allergy handling for a banquet-style seating
that goes beyond the standard kitchen-sheet flag.

## What we have learned from real services

A running log is worth more here than a rewritten policy every time. Add a
line whenever a real service taught you something the engine's constants
did not predict - a walk-in six-top that should have gone to the terrace
instead of the bar, a private-dining night where the 1.15 bonus was too
generous, a server section that felt overloaded well under the 24-cover
cap because the room's layout makes it harder to work than the number
suggests.
