# cc-spend

Monitors Singapore credit card transaction alert emails via IMAP and publishes spending totals to Home Assistant over MQTT.

## Local development

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy the example configs and fill in your values (see Setup below)
cp .env.example .env
cp cards.example.yml cards.yml

# 4. Run the tests (no live credentials needed)
python -m pytest test_cc_spend.py -v

# 5. Run the service locally
python main.py
```

Three endpoints are available on `METRICS_PORT` (default 9090) once the service is running:

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | Returns `200 OK` while the process is alive — used by Docker health checks and uptime monitors |
| `GET /metrics` | Prometheus scrape endpoint |
| `GET /status` | JSON spend summary — current period totals vs caps for all cards |

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
2. Parses merchant name and amount from Citi, DBS, and UOB alert emails
3. Categorizes merchants (FAMILY, DINING, TRANSPORT, etc.) using fuzzy matching; falls back to Claude API for unknowns
4. Tracks per-card spending caps and marks transactions as `EXCEEDED` when the cap is hit
5. Stores every transaction in a SQLite database
6. Sends per-transaction alerts and 6-hourly summaries to a Telegram bot

## Supported cards

Cards are configured entirely via the `CARDS` env var — no code changes needed to add a new card.

| Bank key | Sender address             | Notes                        |
|----------|----------------------------|------------------------------|
| `CITI`   | alerts@citibank.com.sg     | Any Citi card                |
| `DBS`    | ibanking.alert@dbs.com     | Any DBS card                 |
| `UOB`    | unialerts@uobgroup.com     | Any UOB card                 |

Each card entry in `CARDS` sets its own `ONLINE_BYPASS` flag. Cards with `true` skip merchant categorisation and are recorded as `ONLINE`.

## Setup

### Prerequisites

- Python 3.11+
- Gmail account with **IMAP enabled** and an **App Password** (2FA required)
- Two Gmail labels set up as filters for bank alert emails:
  - `[Gmail]/Citibank` — for Citi alert emails
  - `[Gmail]/iBank` — for DBS and UOB alert emails
- Home Assistant with an MQTT broker (e.g. Mosquitto)

### Install dependencies

```bash
pip install -r requirements.txt
```

### Configure `.env`

Copy `.env` and fill in your values:

```ini
# Gmail IMAP
GMAIL_USER=you@gmail.com
GMAIL_APP_PASSWORD=your_app_password_here
IMAP_SERVER=imap.gmail.com

# Telegram bot
TELEGRAM_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
SUMMARY_INTERVAL_SECONDS=21600

# Citi billing period reset day (1-28)
CITI_STATEMENT_DATE=15

# Poll interval in seconds (default: 3 hours)
POLL_INTERVAL_SECONDS=10800

# SQLite database path
DB_PATH=transactions.db

# Card definitions (BANK_KEY|GMAIL_LABEL_SUFFIX|IDENTIFIER|CARD_TYPE|ONLINE_BYPASS)
CARDS=CITI|Citibank|Citi Rewards|CITI_REWARDS|true,DBS|iBank|1798|DBS_WWMC|true,UOB|iBank|8631|UOB_LADY|false

# Optional: Claude API key for unknown merchant fallback
ANTHROPIC_API_KEY=sk-ant-...
```

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

**This is a one-off manual step — never run it more than once against the same database, as it will double-insert every row.**

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

Tests cover: email parsers (Citi/DBS/UOB), merchant categorizer, Claude fallback, cap logic, and database queries.

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
    gmail_label: Citibank
    identifier: "Citi Prestige"
    card_type: CITI_PRESTIGE
    online_bypass: false
```

## Adding a new merchant

Edit `MERCHANT_MCC` in `categorizer.py`, mapping the merchant name (uppercase) to its MCC code:

```python
"NEW MERCHANT": 5411,  # Family (supermarket)
"ANOTHER SHOP": 5641,  # Family (children's wear)
```

If no MCC mapping exists for a merchant, the Claude fallback classifies it into `FAMILY`, `DINING`, or `OTHER` (requires `ANTHROPIC_API_KEY`).

## Parse errors

Failed parses are logged to `parse_errors.log` with the raw email body for debugging.
