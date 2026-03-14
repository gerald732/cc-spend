import os
from dataclasses import dataclass
from dotenv import load_dotenv
import yaml

load_dotenv()

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SUMMARY_INTERVAL_SECONDS = int(os.getenv("SUMMARY_INTERVAL_SECONDS", str(6 * 3600)))

CITI_STATEMENT_DATE = int(os.getenv("CITI_STATEMENT_DATE", "25"))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "10800"))

DB_PATH = os.getenv("DB_PATH", "transactions.db")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

METRICS_PORT = int(os.getenv("METRICS_PORT", "9090"))

CARDS_FILE = os.getenv("CARDS_FILE", "cards.yml")


@dataclass
class CardConfig:
    bank: str             # CITI, DBS, or UOB — maps to a parser class
    label: str            # full Gmail label, e.g. [Gmail]/Labels/Citibank
    identifier: str | None  # substring that must appear in email body; None = accept all
    card_type: str        # label used throughout the app, e.g. CITI_REWARDS
    online_bypass: bool   # if True, skip merchant categorization and record as ONLINE


def _load_cards(path: str) -> list[CardConfig]:
    with open(path) as f:
        data = yaml.safe_load(f)
    cards = []
    for entry in data.get("cards", []):
        cards.append(CardConfig(
            bank=str(entry["bank"]).upper(),
            label=f"[Gmail]/Labels/{entry['gmail_label']}",
            identifier=str(entry["identifier"]) if entry.get("identifier") else None,
            card_type=str(entry["card_type"]),
            online_bypass=bool(entry.get("online_bypass", False)),
        ))
    return cards


CARDS: list[CardConfig] = _load_cards(CARDS_FILE)
