# Workflow: first-run setup

Objective: get Table / Floor Management AI from a fresh clone to a working
demo, then to the restaurant's real floor and book, in one sitting.

## Steps

1. **Install and check.**
   ```bash
   make setup
   make doctor
   ```
   `make setup` creates the virtualenv, installs `requirements.txt`, and
   copies `.env.example` -> `.env` and every `config/*.example.yaml` ->
   `config/*.yaml` (only if those files do not exist yet). `make doctor` will
   show a `FAIL` on "hotel identity" right after setup - that is expected, it
   means the property name is still the shipped placeholder. Everything else
   should be `ok` or `warn`.

2. **Run the demo.** No credentials needed.
   ```bash
   make demo
   ```
   Expect to see tonight's book seated (including a 40-guest corporate group
   that needs the private-dining composite), a walk-in six-top slotted into
   the second turn, then a contrast pass with table joins turned off, ending
   with `DEMO OK — 3 items processed, 3 drafted, 0 sent (shadow)`. If you do
   not see that, stop and read `workflows/99-troubleshooting.md`.

3. **Fill in the property and the restaurant.** Edit `config/hotel.yaml`
   (name, address, contact, languages) and `config/agent.yaml`'s
   `restaurant:` block (name, venue, `hold_zones` - your own floor's zone
   names for an occasion hold). Then copy the one knowledge file this agent
   actually reads:
   ```bash
   cp knowledge/dining-policy.example.md knowledge/dining-policy.md
   ```
   `dining-policy.md` is where you write *why* the private room's banquet
   bonus, the server-balance cap and `hold_zones` are set where they are -
   see `knowledge/README.md`. `property.md`/`faq.md`/`signature.md` are the
   generic scaffold shared by every agent in this family and are not read by
   this one (there is no guest inbox here) - leave them as the shipped
   example unless another agent on this property needs them.

4. **Load the real floor and book.** This agent does not use
   `systems.pms.adapter` - see `docs/how-it-works.md` "Design decisions" #6.
   Instead:
   - Export the real table geometry to `data/imports/floor_tables.csv`
     (`id, zone, seats, joinable_with, x, y, w, h`).
   - Export (or hand-key) tonight's reservations to `data/imports/covers.csv`
     (`id, day_offset, service, time, party_name, party_size, dietary,
     occasion, is_group, notes, source`).
   `docs/integrations.md` has the exact headers. Until those files exist, the
   agent plans against the shipped fixtures (`fixtures/restaurant/`,
   `fixtures/inbound/`) - useful for learning the tool, not for a real
   service. Both CSVs are re-read on every `make run` / `make doctor` pass,
   so editing a row later (a table's seat count, tonight's party size) shows
   up on the very next run - no need to delete `data/agent.db` to pick up an
   edit. `make demo` never reads either file, whatever you have connected -
   it always plans the same fixture scenarios, on its own database.

5. **Pick how the agent thinks.** `config/hotel.yaml`'s `llm.provider` starts
   as `interactive` - it asks you, in this Claude Code session, to write the
   pre-service note instead of calling a model. That costs nothing extra.
   `docs/how-it-works.md` and `docs/safety.md` cover the other three
   providers (`mock`, `claude-code`, `anthropic`).

6. **Re-check.**
   ```bash
   make doctor
   ```
   Once the property name is real, "hotel identity" turns green. "floor
   book" and "floor book sources" tell you whether you are planning against
   your own CSV or the shipped fixtures. Move on to `workflows/10-seating.md`
   to plan a real service.
