"""IMAP polling loop: fetches unseen bank alert emails and processes transactions."""

import imaplib
import email
import logging
import random
import time
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

import config
import database
import categorizer
import caps
import metrics
import telegram_client
from email_parser import BankParser

logger = logging.getLogger(__name__)

_BACKOFF_BASE = 30       # seconds
_BACKOFF_MAX = 1800      # 30 minutes
_BACKOFF_FACTOR = 2
_BACKOFF_JITTER = 0.2    # ±20%


def _build_label_parsers() -> dict[str, list[tuple[str, object]]]:
    label_parsers: dict[str, list] = {}
    for card in config.CARDS:
        bank_cfg = config.BANKS.get(card.bank)
        if bank_cfg is None:
            raise ValueError(
                f"Unknown bank key {card.bank!r} in cards config. "
                f"Valid keys: {list(config.BANKS)}"
            )
        parser = BankParser(
            from_address=bank_cfg.from_address,
            subject=bank_cfg.subject,
            merchant_re=bank_cfg.merchant_re,
            identifier=card.identifier,
        )
        label_parsers.setdefault(card.label, []).append((card.card_type, parser))
    return label_parsers


# Built at startup from cards.yml — no code change needed to add a card from an existing bank.
_LABEL_PARSERS: dict[str, list[tuple[str, object]]] = _build_label_parsers()

# card_type → online_bypass flag, for fast lookup in _process_message
_ONLINE_BYPASS: dict[str, bool] = {
    card.card_type: card.online_bypass for card in config.CARDS
}


def _connect() -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(config.IMAP_SERVER)
    conn.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
    return conn


def _fetch_unseen(conn: imaplib.IMAP4_SSL, label: str) -> list[tuple[bytes, str]]:
    """Return list of (uid, body) for unseen messages in label received in the last 24 hours."""
    conn.select(f'"{label}"', readonly=False)
    since = (datetime.now() - timedelta(hours=24)).strftime("%d-%b-%Y")
    _, data = conn.uid("search", None, f'(UNSEEN SINCE {since})')
    uids = data[0].split()
    results = []
    for uid in uids:
        _, msg_data = conn.uid("fetch", uid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        body = _extract_body(msg)
        results.append((uid, body))
    return results


class _HTMLTextExtractor(HTMLParser):
    """Strip HTML tags and CSS/script blocks, returning visible text."""
    def __init__(self):
        super().__init__()
        self._lines: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):  # pylint: disable=unused-argument
        if tag in ("style", "script"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self._lines.append(stripped)

    def get_text(self) -> str:
        """Return the accumulated visible text lines joined by newlines."""
        return "\n".join(self._lines)


def _html_to_text(html: str) -> str:
    """Strip HTML tags from an email body and return plain text."""
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def _extract_body(msg: email.message.Message) -> str:
    plain = html = None
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            if ct == "text/plain" and plain is None:
                plain = payload.decode(errors="replace")
            elif ct == "text/html" and html is None:
                html = payload.decode(errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            plain = payload.decode(errors="replace")

    if plain:
        return plain
    if html:
        return _html_to_text(html)
    return ""


def _mark_seen(conn: imaplib.IMAP4_SSL, uid: bytes):
    conn.uid("store", uid, "+FLAGS", "\\Seen")


def _get_sender(conn: imaplib.IMAP4_SSL, uid: bytes) -> str:
    _, msg_data = conn.uid("fetch", uid, "(BODY[HEADER.FIELDS (FROM)])")
    raw = msg_data[0][1].decode(errors="replace")
    return raw.lower()


def _process_message(uid: bytes, body: str, card_type: str, parser, conn: imaplib.IMAP4_SSL):
    result = parser.parse(body)
    if result is None:
        logger.warning("Parse failed for %s uid=%s", card_type, uid)
        return

    merchant, amount = result
    if _ONLINE_BYPASS.get(card_type, False):
        category = "ONLINE"
    else:
        category = categorizer.categorize_with_claude_fallback(merchant)
    final_category = caps.apply_cap(card_type, category, config.CITI_STATEMENT_DATE)

    timestamp = datetime.now(timezone.utc).isoformat()
    database.insert_transaction(timestamp, merchant, amount, card_type, final_category)
    logger.info("Inserted: %s %.2f %s %s", merchant, amount, card_type, final_category)
    metrics.transactions_processed.labels(card_type=card_type, category=final_category).inc()

    _mark_seen(conn, uid)
    telegram_client.send_transaction(merchant, amount, card_type, final_category)


def poll_once() -> bool:
    """Poll all labels once. Returns True on success, False if IMAP connect failed."""
    try:
        conn = _connect()
    except Exception:
        logger.exception("IMAP connect failed")
        metrics.imap_failures.labels(reason="connect").inc()
        return False

    try:
        for label, parsers in _LABEL_PARSERS.items():
            try:
                messages = _fetch_unseen(conn, label)
            except Exception:
                logger.exception("Failed fetching label %s", label)
                metrics.imap_failures.labels(reason="fetch").inc()
                continue

            for uid, body in messages:
                for card_type, parser in parsers:
                    # Match by sender to route to the right parser
                    sender_header = _get_sender(conn, uid)
                    if parser.from_address.lower() in sender_header:
                        _process_message(uid, body, card_type, parser, conn)
                        break
    finally:
        conn.logout()
    return True


def run_loop():
    """Poll all Gmail labels on a fixed interval with exponential backoff on IMAP failure."""
    logger.info("Starting poll loop every %ds", config.POLL_INTERVAL_SECONDS)
    backoff = _BACKOFF_BASE
    while True:
        success = poll_once()
        if success:
            backoff = _BACKOFF_BASE  # reset on success
            time.sleep(config.POLL_INTERVAL_SECONDS)
        else:
            jitter = backoff * _BACKOFF_JITTER * (2 * random.random() - 1)
            sleep_time = min(backoff + jitter, _BACKOFF_MAX)
            logger.warning("Poll failed; retrying in %.0fs (backoff)", sleep_time)
            time.sleep(sleep_time)
            backoff = min(backoff * _BACKOFF_FACTOR, _BACKOFF_MAX)
