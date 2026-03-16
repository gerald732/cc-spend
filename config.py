"""Configuration loader: env vars and cards.yml."""

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
class BankConfig:
    """Email routing and parsing config shared by all cards from one bank."""

    from_address: str   # sender email used to route messages to this bank
    subject: str        # expected email subject (informational)
    merchant_re: str    # regex pattern (one capture group) to extract merchant name


@dataclass
class CardConfig:
    """Per-card configuration: which bank, which Gmail label, and spend tracking settings."""
    bank: str             # must match a key in BANKS
    label: str            # full IMAP label path, e.g. [Gmail]/Labels/Citibank
    identifier: str | None  # substring that must appear in email body; None = accept all
    card_type: str        # label used throughout the app, e.g. CITI_REWARDS
    online_bypass: bool   # if True, skip merchant categorization and record as ONLINE


def _load_config(path: str) -> tuple[dict[str, BankConfig], list[CardConfig]]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    banks = {
        key.upper(): BankConfig(
            from_address=str(entry["from_address"]),
            subject=str(entry["subject"]),
            merchant_re=str(entry["merchant_re"]),
        )
        for key, entry in data.get("banks", {}).items()
    }
    cards = [
        CardConfig(
            bank=str(entry["bank"]).upper(),
            label=str(entry["label"]),
            identifier=str(entry["identifier"]) if entry.get("identifier") else None,
            card_type=str(entry["card_type"]),
            online_bypass=bool(entry.get("online_bypass", False)),
        )
        for entry in data.get("cards", [])
    ]
    return banks, cards


BANKS: dict[str, BankConfig]
CARDS: list[CardConfig]
BANKS, CARDS = _load_config(CARDS_FILE)
