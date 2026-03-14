import imaplib
import email
import logging
import time
from datetime import datetime, timezone

import config
import database
import categorizer
import caps
import mqtt_client
from parser import PARSERS

logger = logging.getLogger(__name__)

# Map Gmail label → list of (card_type, parser) pairs
_LABEL_PARSERS: dict[str, list[tuple[str, object]]] = {
    "[Gmail]/Citibank": [("CITI_REWARDS", PARSERS["CITI_REWARDS"])],
    "[Gmail]/iBank": [
        ("DBS_WWMC", PARSERS["DBS_WWMC"]),
        ("UOB_LADY", PARSERS["UOB_LADY"]),
    ],
}


def _connect() -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(config.IMAP_SERVER)
    conn.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
    return conn


def _fetch_unseen(conn: imaplib.IMAP4_SSL, label: str) -> list[tuple[bytes, str]]:
    """Return list of (uid, body) for unseen messages in label."""
    conn.select(f'"{label}"', readonly=False)
    _, data = conn.uid("search", None, "UNSEEN")
    uids = data[0].split()
    results = []
    for uid in uids:
        _, msg_data = conn.uid("fetch", uid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        body = _extract_body(msg)
        results.append((uid, body))
    return results


def _extract_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode(errors="replace")
    return msg.get_payload(decode=True).decode(errors="replace")


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
    if card_type in config.ONLINE_CARD_TYPES:
        category = "ONLINE"
    else:
        category = categorizer.categorize_with_claude_fallback(merchant)
    final_category = caps.apply_cap(card_type, category, config.CITI_STATEMENT_DATE)

    timestamp = datetime.now(timezone.utc).isoformat()
    database.insert_transaction(timestamp, merchant, amount, card_type, final_category)
    logger.info("Inserted: %s %.2f %s %s", merchant, amount, card_type, final_category)

    _mark_seen(conn, uid)
    mqtt_client.publish_all()


def poll_once():
    try:
        conn = _connect()
    except Exception:
        logger.exception("IMAP connect failed")
        return

    for label, parsers in _LABEL_PARSERS.items():
        try:
            messages = _fetch_unseen(conn, label)
        except Exception:
            logger.exception("Failed fetching label %s", label)
            continue

        for uid, body in messages:
            for card_type, parser in parsers:
                # Match by sender to route to the right parser
                sender_header = _get_sender(conn, uid)
                if parser.FROM.lower() in sender_header:
                    _process_message(uid, body, card_type, parser, conn)
                    break

    conn.logout()


def run_loop():
    logger.info("Starting poll loop every %ds", config.POLL_INTERVAL_SECONDS)
    while True:
        poll_once()
        time.sleep(config.POLL_INTERVAL_SECONDS)
