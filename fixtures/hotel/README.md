# Why this folder is (deliberately) almost empty

This agent does not use `systems.pms.adapter` - see
`docs/how-it-works.md` "Design decisions" #6 and `docs/integrations.md`.
The restaurant's own book (tables, covers, dining rules) lives in
`fixtures/restaurant/` and `fixtures/inbound/` instead.

`reservations.json` here is an empty array so `core/adapters/pms_mock.py`'s
`ping()` reports a harmless PASS instead of a misleading FAIL in `make
doctor` - every repo in this family shares the same `core/adapters` registry,
so `make doctor` always pings a PMS adapter even when an agent has no use
for one. Nothing in this repo reads this file.
