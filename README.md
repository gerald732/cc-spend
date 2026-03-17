# cc-spend

Monitors Singapore credit card transaction alert emails via IMAP and sends per-transaction alerts and spending summaries via Telegram.

## Local development

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 2. Install dependencies (includes dev tools: pylint, flake8, pytest)
pip install -r requirements-dev.txt

# 3. Copy the example configs and fill in your values (see Setup below)
cp .env.example .env
cp cards.example.yml cards.yml

# 4. Run the tests (no live credentials needed)
python -m pytest test_cc_spend.py -v

# 5. Run the service locally
python main.py
```

Four endpoints are available on `METRICS_PORT` (default 9090) once the service is running:

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | Returns `200 OK` while the process is alive — used by Docker health checks and uptime monitors |
| `GET /metrics` | Prometheus scrape endpoint |
| `GET /status` | JSON spend summary — current period totals vs caps for all cards |
| `GET /categories` | Browser UI — view and override the merchant→category cache |
| `POST /categories` | Submit a category override from the `/categories` form |

To verify the service is running and the DB is populated correctly (e.g. after seeding):
```bash
curl http://localhost:9090/status
```
```json
{
  "UOB_LADY": {
    "period_start": "2026-03-01",
    "categories": {
      "FAMILY": {"spent": 179.22, "cap": 750.0, "remaining": 570.78},
      "DINING": {"spent": 432.77, "cap": 750.0, "remaining": 317.23}
    }
  },
  "DBS_WWMC": {
    "period_start": "2026-03-01",
    "spent": 194.08, "cap": 1000.0, "remaining": 805.92
  },
  "CITI_REWARDS": {
    "period_start": "2026-02-15",
    "spent": 142.92, "cap": 1000.0, "remaining": 857.08
  }
}
```

## How it works

1. Polls Gmail (IMAP) on a configurable interval for unseen transaction alert emails
2. Parses merchant name and amount from configured bank alert emails
3. Categorizes merchants (FAMILY, DINING, TRANSPORT, etc.) using fuzzy matching against a known list; for unknowns, checks the merchant cache in SQLite, then falls back to Gemini API (if `GEMINI_API_KEY` is set) or Claude API (if `ANTHROPIC_API_KEY` is set)
4. Claude results and manual overrides are stored in a `merchant_categories` table so repeated transactions from the same merchant never re-query the API
5. Tracks per-card spending caps and marks transactions as `EXCEEDED` when the cap is hit
6. Stores every transaction in a SQLite database
7. Sends per-transaction alerts and 6-hourly (configurable) summaries to a Telegram bot

## Supported cards

Cards are configured via `cards.yml`. Both banks and cards are fully config-driven — no code changes are needed to add a new card or a new bank.

- **New card from an existing bank**: add an entry under `cards:` referencing an existing `banks:` key.
- **New bank**: add an entry under `banks:` with the sender address and a merchant-name regex, then add cards referencing it.

The three banks in `cards.example.yml` (`CITI`, `DBS`, `UOB`) are examples — you can define any bank entirely in config.

Each card entry has an `online_bypass` flag. Cards with `online_bypass: true` skip merchant categorisation and are recorded as `ONLINE`.

## Setup

### Prerequisites

- Python 3.11+
- Gmail account with **IMAP enabled** and an **App Password** (2FA required)
- Gmail labels set up as filters for bank alert emails matching the `label` values in your `cards.yml` (e.g. `[Gmail]/Labels/Citibank`, `[Gmail]/Labels/iBank`)
- Telegram bot (token + chat ID)

### Install dependencies

```bash
pip install -r requirements-dev.txt   # local dev (includes pylint, flake8, pytest)
# or
pip install -r requirements.txt       # prod only
```

### Configure `.env`

Copy `.env.example` to `.env` and fill in your values:

```ini
# Gmail IMAP
GMAIL_USER=you@gmail.com
GMAIL_APP_PASSWORD=your_app_password_here
IMAP_SERVER=imap.gmail.com

# Telegram bot (for per-transaction alerts and 6-hourly summaries)
# Create a bot via @BotFather, add it to your group, then get the chat ID.
TELEGRAM_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# How often to send a spend summary (seconds, default: 6 hours)
SUMMARY_INTERVAL_SECONDS=21600

# Citi billing period reset day (1-28)
CITI_STATEMENT_DATE=25

# Poll interval in seconds (default: 3 hours)
POLL_INTERVAL_SECONDS=10800

# SQLite database path (override in Docker to point at the mounted volume)
DB_PATH=/data/transactions.db

# LLM fallback for merchant categorization.
# Gemini 2.5 Flash Lite takes precedence when GEMINI_API_KEY is set.
# Claude (paid, separate from Claude.ai Pro) is used if only ANTHROPIC_API_KEY is set.
# If neither is set, unknown merchants are recorded as OTHER.
GEMINI_API_KEY=
ANTHROPIC_API_KEY=

# Prometheus metrics + healthcheck port (default: 9090)
METRICS_PORT=9090

# Timezone for billing period boundary calculations.
# Must match your local timezone — period resets are computed using the system clock.
TZ=Asia/Singapore
```

Card configuration lives in `cards.yml` (see `cards.example.yml` for the format) — not in `.env`.

### Run

```bash
python main.py
```

### Run with Docker

The image is not published to a registry. Build it on the Docker host first, then start the stack:

```bash
# Build (re-run this after any code change)
docker build -t cc-spend:latest .

# Start
docker compose up -d
```

When deploying via Portainer, copy the contents of `docker-compose.yml` into a new stack — Portainer will use the `cc-spend:latest` image already present on the host.

All runtime config and data lives under `/docker/cc-spend/` on the host. Create the directory and copy your configs there before starting the container:

```bash
mkdir -p /docker/cc-spend
cp .env.example /docker/cc-spend/.env        # then fill in your values
cp cards.example.yml /docker/cc-spend/cards.yml  # then fill in your cards
```

## Prefilling historical spend (mid-month setup)

If you start the service mid-billing-period, the DB will have no prior transactions and cap logic will behave as if you have spent $0. Use `seed_db.py` to inject your actual spend from earlier in the month so cap thresholds are accurate from the first real transaction.

**This is a one-off manual step — never run it more than once against the same database. The script will refuse to run if the DB already has rows, but the underlying data would still be wrong.**

`seed_db.py` is already baked into the container image (`COPY *.py .`), so you do not need to open a shell or copy files. The script reads `DB_PATH` from the environment, which points at the same `/data/transactions.db` volume the service uses.

### Step 1 — edit the seed data

On the Docker host, open `seed_db.py` from your local checkout and edit the `SEED` list to match your actual transactions for the current billing period. The `category` field should be the value that `apply_cap` would have assigned at the time — e.g. `FAMILY`, `DINING`, `OTHER`. Only use `EXCEEDED` if the cap was already blown before that row.

### Step 2 — rebuild the image

```bash
docker build -t cc-spend:latest .
```

### Step 3 — dry-run (preview only, no writes)

```bash
docker run --rm --env-file /docker/cc-spend/.env -v /docker/cc-spend/data:/data -v /docker/cc-spend/cards.yml:/app/cards.yml:ro cc-spend:latest python seed_db.py --dry-run
```

### Step 4 — insert

```bash
docker run --rm --env-file /docker/cc-spend/.env -v /docker/cc-spend/data:/data -v /docker/cc-spend/cards.yml:/app/cards.yml:ro cc-spend:latest python seed_db.py
```

The script prints post-seed totals per card on completion. Verify the numbers, then start the service normally.

### Step 5 — start the service

```bash
docker compose up -d
```

> If the service is already running and you need to reseed, stop it first (`docker compose down`) to avoid concurrent writes to the SQLite file, then repeat from Step 2.

## Running tests

No live credentials needed — the test suite mocks all I/O.

```bash
python -m pytest test_cc_spend.py -v
# or
python -m unittest test_cc_spend -v
```

Tests cover: email parsers (Citi/DBS/UOB), merchant categorizer, Gemini and Claude LLM fallbacks, cap logic, and database queries.

## Telegram notifications

Two types of messages are sent to the configured chat:

**Per-transaction** (sent immediately after each new transaction):
```
💳 COLD STORAGE VIVOCITY
SGD 55.30 · UOB Lady · Family

UOB Lady Family: SGD 123 / 750  ▓▓░░░░░░░░  16%
UOB Lady Dining: SGD 80 / 750   ▓░░░░░░░░░  11%
```

**6-hourly summary** (sent every `SUMMARY_INTERVAL_SECONDS`):
```
📊 Spend Summary

UOB Lady  (resets 1 Apr)
  Family: SGD 123 / 750  ▓▓░░░░░░░░  SGD 627 left
  Dining: SGD 80 / 750   ▓░░░░░░░░░  SGD 670 left

DBS WWMC  (resets 1 Apr)
  Total: SGD 200 / 1000  ▓▓░░░░░░░░  SGD 800 left

Citi Rewards  (resets 25 Mar)
  Total: SGD 150 / 1000  ▓░░░░░░░░░  SGD 850 left
```

### Setting up the Telegram bot

1. Message `@BotFather` on Telegram and create a new bot — it will give you a token.
2. Add the bot to your group chat (or start a private chat with it).
3. Get your chat ID: send a message to the bot/group, then visit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and read `result[0].message.chat.id`.
4. Set `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` in your `.env`.

## Adding a new card

Add an entry to `cards.yml` — no code changes needed:

```yaml
cards:
  - bank: CITI
    label: "[Gmail]/Labels/Citibank"
    identifier: "Citi Prestige"
    card_type: CITI_PRESTIGE
    online_bypass: false
```

## Adding a new merchant

**Option 1 — Browser UI (recommended for one-off corrections):**

Open `http://localhost:9090/categories` in a browser. Use the "Add / Override" form at the bottom to map any merchant name to the correct category. Manual overrides take precedence over Claude on future transactions.

**Option 2 — Code (for well-known merchants you want matched without any API call):**

Edit `MERCHANT_MCC` in `categorizer.py`, mapping the merchant name (uppercase) to its MCC code:

```python
"NEW MERCHANT": 5411,  # Family (supermarket)
"ANOTHER SHOP": 5641,  # Family (children's wear)
```

If no MCC mapping or cache entry exists for a merchant, an LLM classifies it into `FAMILY`, `DINING`, or `OTHER`. Gemini is tried first (`gemini-2.5-flash-lite`); Claude is used as a secondary fallback. The result is stored in the cache so the API is only called once per new merchant.

> **Note:** `GEMINI_API_KEY` and `ANTHROPIC_API_KEY` are independent of Claude.ai Pro subscriptions — they are separate API products. If neither key is configured, unknown merchants fall back to `OTHER`. Failures are counted in the `cc_spend_claude_failures_total` metric.

## Logging

All log output goes to stdout at `INFO` level with UTC timestamps. Each module uses its own named logger so you can filter by source (e.g. `categorizer`, `imap_listener`).

Key log events:
- `categorizer` — merchant name sent to Gemini/Claude, raw API response, cache hits, and fallback-to-OTHER with reason
- `imap_listener` — poll start/end, IMAP failures, and per-transaction processing
- `metrics` — manual category overrides submitted via `/categories`

Failed email parses are also written to `parse_errors.log` with the raw email body for debugging.
