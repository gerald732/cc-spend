import os
from dotenv import load_dotenv

load_dotenv()

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")

MQTT_HOST = os.environ["MQTT_HOST"]
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")

CITI_STATEMENT_DATE = int(os.getenv("CITI_STATEMENT_DATE", "25"))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "10800"))

DB_PATH = os.getenv("DB_PATH", "transactions.db")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Card types that bypass categorization — transactions are always recorded as ONLINE.
# Comma-separated. Default covers cards used primarily for online spend.
ONLINE_CARD_TYPES = set(os.getenv("ONLINE_CARD_TYPES", "DBS_WWMC,CITI_REWARDS").split(","))
