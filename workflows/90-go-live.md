# Workflow: shadow to live

Objective: decide, together with the restaurant, whether Table / Floor
Management AI is ready to notify the floor/kitchen and log its plans on its
own instead of only drafting them - and make the change safely if so.

This is the restaurant's decision, never the agent's. Do not suggest it until
the checklist below is genuinely true, and when you do raise it, say plainly
what changes: **the seating plan itself never becomes automatic** - a human
host reviews every plan either way (`docs/how-it-works.md` "Nothing seats a
walk-in or changes a plan without a person"). Going live only changes what
happens to a plan a host has already approved.

## Checklist

- [ ] `make doctor` is clean (no `FAIL` lines). `warn` on `mode` is expected
      until you flip it.
- [ ] `config/hotel.yaml` has the real property name and details, and
      `config/agent.yaml`'s `restaurant:` block names the real restaurant.
- [ ] The real floor and book are connected (`data/imports/floor_tables.csv`
      + `data/imports/covers.csv`) - going live on the shipped fixtures would
      only ever notify staff about a plan for an imagined room.
- [ ] At least a few real services have gone through `make run` and the
      review queue, not just the demo fixtures, and the host trusts the
      engine's placements for this room specifically.
- [ ] `late_cutoff`, `banquet_factor` and `zone_cover_cap` in
      `config/agent.yaml` have been checked against the real room, not left
      at the shipped defaults without a look (`docs/how-it-works.md` design
      decisions 3 and 5).
- [ ] `systems.messaging.adapter` (or `systems.sheets.adapter`) is connected
      to something the floor/kitchen team actually sees, and `make doctor`
      shows it healthy.
- [ ] Run `python3 tools/review.py stale` once, right before flipping the
      switch, to clear anything approved during shadow testing that is now
      out of date.

## Making the change

1. Edit `config/hotel.yaml`:
   ```yaml
   mode: live
   ```
2. `review.require_approval_for` in `config/agent.yaml` still lists
   `send_message`, `sheets_write` and `publish` by default - it should. Going
   live means **an approved plan actually notifies the floor**, not that the
   agent starts seating tables without a host looking first. There is no
   config that removes the human review step for the plan itself.
3. Run `make doctor` again to confirm.
4. Run one real pass and manually watch a send go through:
   ```bash
   make run
   python3 tools/review.py list
   python3 tools/review.py approve <id>
   python3 tools/review.py send
   ```
5. Tell the restaurant exactly what just changed: an approved plan now
   actually reaches the floor/kitchen the next time someone (or a scheduled
   job) runs `python3 tools/review.py send` - it is still never automatic
   before that approval, and every plan still waits for a host by default.

## Going back to shadow

```yaml
mode: shadow
```
in `config/hotel.yaml`, or `AGENT_MODE=shadow` in `.env` for one run. Either
stops every outbound notification and export on the next pass, mid-schedule,
with no other change required.
