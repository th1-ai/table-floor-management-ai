# Connecting your systems

Every connector in this repo is one of three things, and the table says which.
We will not tell you an integration exists when it does not.

| Badge | Means |
|---|---|
| **built** | Written against the real API and tested against it. |
| **universal** | Works with any system through a common protocol: IMAP/SMTP, CSV, a webhook. |
| **stub** | Interface only. Calling it raises a clear error with a recipe for adding it. |

Check what is actually working on your machine at any time:

```bash
make doctor
```

## The floor book - not the PMS adapter

`floor_tables` and `restaurant_covers` (tonight's bookings) do not go
through `systems.pms.adapter` - see `docs/how-it-works.md` "Design decisions"
#6. A restaurant cover (time, party size, dietary, occasion) does not fit the
room-PMS `Reservation` dataclass every other agent in this family reads
through, so this agent reads its own book directly (`tools/covers_book.py`),
in the same universal, always-works spirit as `core/adapters/pms_csv.py`:

| Source | Status | Needs | Notes |
|---|---|---|---|
| `fixtures/restaurant/floor_tables.json` + `fixtures/inbound/*.json` | universal | nothing | What `make demo` uses. |
| `data/imports/floor_tables.csv` + `data/imports/covers.csv` | universal | CSV exports | **Start here for a real property.** |

CSV wins over fixtures automatically the moment either file exists
(`tools/covers_book.py:source_for`) - **except for `make demo`**, which
always plans the three shipped fixture scenarios on its own database
(`data/demo/demo.db`), never `data/imports/`, whatever a property has
already connected (`tools/demo.py`, `load_settings(demo=True)`).

Once loaded, both live in this agent's own `data/agent.db` tables
(`floor_tables`, `restaurant_covers`, `dining_rules`). **Both CSVs are
re-imported on every `make run` / `make doctor` pass** - a covering-window
replace, not a one-time seed: `floor_tables` and the imported slice of
`restaurant_covers` are reloaded fresh from the file every time, so an
edited row (a table's seat count, tonight's party size) shows up on the very
next run, never stuck on whatever was true the first time the file was
read. A walk-in (`tools/run.py --walk-in`) is a live row this agent inserted
directly, not an import, so re-importing a CSV can never touch or lose one.
A rule toggle (`tools/run.py --set-rule`) is separate state again and is
never affected by a re-import either.

**`data/imports/floor_tables.csv`** - `id, zone, seats, joinable_with, x, y,
w, h`. `joinable_with` is a `|`-separated list of table ids (e.g.
`M2|M3`). `zone` is free text - `Private` and `Bar` are the two values the
engine always treats specially (private-dining composites, and composites
never include a bar table). A window/terrace-style occasion hold is
**configured**, not hardcoded: `config/agent.yaml: hold_zones` names which
of *your own* zone values count (default ships as `["Window", "Terrace"]`,
matching the demo fixtures) - matched case- and accent-insensitively, so
`Sala`/`sala`/`SALA` all match. `make doctor`'s "hold zones" check warns if
none of your real zones match what is configured. `x, y, w, h` are only used
if you build your own floor-plan rendering; the engine ignores them.

**`data/imports/covers.csv`** - `id, day_offset, service, time, party_name,
party_size, dietary, occasion, is_group, notes, source`. `day_offset` is
whole days from today (`0` = today, `1` = tomorrow). `dietary` is a
`|`-separated list, matched case- and accent-insensitively in English,
Spanish, French, German, Italian and Portuguese (`tools/seating_engine.py`
`_NUT_ALLERGY_STEMS` - "allergia alle noci", "Nussallergie" and "nut
allergy" all flag the same). A dietary note that clearly names *some*
allergy in one of those languages but does not match a specific stem still
escalates to `needs_human` rather than staying silent - it is never simply
dropped. `occasion` matches `anniversary`, `honeymoon`, `birthday`,
`engagement`, `proposal`, `wedding` and their Spanish/French/German/Italian/
Portuguese equivalents (`OCCASION_WORDS`, same case/accent folding) to
trigger vip-window's queue-jump and occasion hold. `is_group` is
`true`/`false` (also implied automatically once `party_size` exceeds 8).
`source` is free text - `concierge` is the honest version of "syncs with
concierge bookings" this repo has (`docs/how-it-works.md` design decision
#2): tag a booking that way and it is planned exactly like any other. Never
set `source` to `walk_in` yourself - that value is reserved for
`tools/run.py --walk-in`, so a re-import can tell your own rows apart from
a live walk-in and never touches the walk-in.

Headers are matched loosely (`checkIn`, `check_in`, `Check In` all work) and
extra columns are kept. Dates/times use `YYYY-MM-DD` and 24-hour `HH:MM`.

### `pms` and `email` - shipped, unused by this agent

Every repo in this family shares the same `core/adapters` registry, so
`make doctor` always pings a PMS and an email adapter even when an agent has
no use for one. `fixtures/hotel/reservations.json` is an empty array so the
PMS ping reports a harmless PASS rather than a misleading FAIL - see
`fixtures/hotel/README.md`. Nothing in this repo calls `core.adapters.get_pms()`
or `core.adapters.get_email()`. If you also run a room-facing agent from this
family (Front Desk AI, Concierge AI...), its own PMS/email connection is
entirely separate from this one.

## Messaging - `systems.messaging.adapter`

Used for `notify_staff`: the pre-service note and the seated/unseated
summary, to whoever the floor and kitchen team actually watch.

| Adapter | Status | Needs | Notes |
|---|---|---|---|
| `mock` | universal | nothing | No-op; what `make demo` uses. |
| `unipile` | built | your own UniPile account | WhatsApp on your own number. |
| `webhook` | universal | any URL | POST to Zapier, Make, n8n, or your own endpoint. |

**`unipile`.** You create the account, you connect your number by QR code,
you own the credentials: `UNIPILE_DSN`, `UNIPILE_API_KEY`,
`UNIPILE_ACCOUNT_ID`, `UNIPILE_STAFF_CHAT_ID`.

**`webhook`.** The simplest possible outbound: set `MESSAGING_WEBHOOK_URL`
and the agent POSTs `{chat_id, text, kind, hotel, sent_at}`. Point it at a
Slack/Teams channel via your automation tool of choice.

## Sheets - `systems.sheets.adapter`

Used to export the kitchen sheet and a floor-plan log row, once a plan is
approved and sent (`tools/review.py send`).

| Adapter | Status | Needs | Notes |
|---|---|---|---|
| `csv` | universal | nothing | Writes `data/exports/kitchen_sheet.csv` + `data/exports/floor_plans.csv`. |
| `google` | built | service account JSON | A live shared spreadsheet the kitchen can pull up. |

For `google`: enable the Sheets API, create a service account and a JSON
key, save it as `service_account.json`, and share your spreadsheet with the
service account's email address as an Editor. Set
`systems.sheets.spreadsheet_id` to the long id from the sheet's URL.

## Everything else

`pos`, `accounting`, `reviews`, `calendar`, `payments`, `procurement` and
`locks` are **stubs**: the interface exists, nothing is implemented. This
agent does not call any of them today. If a property wants, say, a POS
integration to pull real check totals per table, use the recipe below.

## Implement your own

<a id="implement-your-own"></a>

The interface is small on purpose, and your Claude Code session can do this
with you in an afternoon. Open `claude` in this folder and paste:

> Read `docs/integrations.md#implement-your-own` and `core/adapters/base.py`.
> I need a messaging adapter for **<your system>**. Its API docs are at
> **<url>** and I have credentials in `.env` as `<VAR names>`. Copy
> `core/adapters/messaging_webhook.py` as the shape, implement `ping`,
> `capabilities` and `notify_staff` first, register it in
> `core/adapters/__init__.py`, and stop before anything else so I can check
> it with `make doctor`.

### The five steps

**1. Copy the closest existing adapter.** `core/adapters/pms_csv.py` for a
CSV-style import (also the template `tools/covers_book.py` itself follows),
`messaging_webhook.py` for a chat channel, `sheets_csv.py` for an export
target.

**2. Implement `ping()` and `capabilities()` first.**

```python
def ping(self) -> HealthCheck:
    """Never raises. Returns ok=False with a fix_hint a host can act on."""

def capabilities(self) -> set[str]:
    """The method names that actually do something on this adapter."""
```

`make doctor` reads both. Getting them right first means the rest of the
work has a feedback loop.

**3. Implement the reads.** Map the vendor's fields onto the dataclasses in
`core/adapters/base.py`, or - for the floor book specifically - onto
`tools/seating_engine.py`'s `Table`/`Cover` dataclasses. Put anything you do
not map into `.extra` rather than dropping it.

**4. Implement the writes, each with the guard.**

```python
from core.adapters.base import guarded_write

@guarded_write("send_message")
def notify_staff(self, text: str) -> dict:
    ...
```

The decorator is not optional. Without it your adapter can write while the
agent is in shadow mode, which defeats the entire safety model.

**5. Register it.** One line in `core/adapters/__init__.py`:

```python
REGISTRY["messaging"]["yoursystem"] = "core.adapters.messaging_yoursystem:YourSystemMessaging"
```

Then set `systems.messaging.adapter: yoursystem` in `config/hotel.yaml` and
run `make doctor`.

### Rules that matter

- **`ping()` never raises.** It returns `HealthCheck(ok=False, ...)` with a
  hint. A broken adapter must still produce a readable doctor table.
- **Every write is decorated.** No exceptions.
- **Rate limits belong in the adapter.** Use `core/adapters/_http.py:RateLimiter`.
  Retry 429 and 5xx with backoff; never retry a 4xx.
- **Never log a credential.** `core/log.py` masks anything whose key looks
  like a secret, but do not rely on it.
- **Write a test.** Copy `tests/test_covers_book.py`'s shape: feed your
  parser a small fixture, check the dataclass that comes out. No network.

### `core/` is shared

`core/` is identical in all 28 agents in this family. If you change
something in `core/`, keep it generic - a restaurant-specific tweak belongs
in `tools/` or in your own adapter file, not in the shared runtime.
