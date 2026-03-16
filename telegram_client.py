import json
import logging
import time
import urllib.request
import urllib.error
from datetime import date

import caps
import config
import database

logger = logging.getLogger(__name__)

_CARD_LABELS = {
    "UOB_LADY": "UOB Lady",
    "DBS_WWMC": "DBS WWMC",
    "CITI_REWARDS": "Citi Rewards",
}

_CAT_LABELS = {
    "FAMILY": "Family",
    "DINING": "Dining",
    "ONLINE": "Online",
    "TRANSPORT": "Transport",
    "HEALTH": "Health",
    "TRAVEL": "Travel",
    "SHOPPING": "Shopping",
    "OTHER": "Other",
    "EXCEEDED": "⚠️ Cap Exceeded",
}


def _post(text: str) -> None:
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured; skipping message")
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    data = json.dumps({
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except urllib.error.URLError as exc:
        logger.error("Telegram send failed: %s", exc)


def _fmt_bar(spent: float, cap: float, width: int = 10) -> str:
    """Return a progress bar, e.g. ▓▓▓░░░░░░░"""
    filled = round(min(spent / cap, 1.0) * width)
    return "▓" * filled + "░" * (width - filled)


def _period_reset_date(card_type: str) -> str:
    """Return the next reset date as a short string, e.g. '1 Apr'."""
    today = date.today()
    if card_type in ("DBS_WWMC", "UOB_LADY"):
        if today.month == 12:
            reset = date(today.year + 1, 1, 1)
        else:
            reset = date(today.year, today.month + 1, 1)
    else:  # CITI_REWARDS
        sd = config.CITI_STATEMENT_DATE
        if today.day < sd:
            reset = date(today.year, today.month, sd)
        elif today.month == 12:
            reset = date(today.year + 1, 1, sd)
        else:
            reset = date(today.year, today.month + 1, sd)
    return reset.strftime("%-d %b")


def send_transaction(merchant: str, amount: float, card_type: str, category: str) -> None:
    card_label = _CARD_LABELS.get(card_type, card_type)
    cat_label = _CAT_LABELS.get(category, category)
    icon = "⚠️" if category == "EXCEEDED" else "💳"

    lines = [
        f"{icon} <b>{merchant}</b>",
        f"SGD {amount:.2f} · {card_label} · {cat_label}",
        "",
    ]

    period_start = caps.get_period_start(card_type, config.CITI_STATEMENT_DATE)

    if card_type == "UOB_LADY":
        for cat in ("FAMILY", "DINING"):
            total = database.get_monthly_category_total("UOB_LADY", cat, period_start)
            bar = _fmt_bar(total, caps.UOB_LADY_CAP)
            pct = int(total / caps.UOB_LADY_CAP * 100)
            lines.append(
                f"UOB Lady {cat.title()}: SGD {total:.0f} / {caps.UOB_LADY_CAP:.0f}"
                f"  {bar}  {pct}%"
            )
    elif card_type == "DBS_WWMC":
        total = database.get_period_total("DBS_WWMC", period_start)
        bar = _fmt_bar(total, caps.DBS_CAP)
        pct = int(total / caps.DBS_CAP * 100)
        lines.append(f"DBS WWMC: SGD {total:.0f} / {caps.DBS_CAP:.0f}  {bar}  {pct}%")
    elif card_type == "CITI_REWARDS":
        total = database.get_period_total("CITI_REWARDS", period_start)
        bar = _fmt_bar(total, caps.CITI_CAP)
        pct = int(total / caps.CITI_CAP * 100)
        lines.append(f"Citi Rewards: SGD {total:.0f} / {caps.CITI_CAP:.0f}  {bar}  {pct}%")

    _post("\n".join(lines))


def send_summary() -> None:
    lines = ["📊 <b>Spend Summary</b>", ""]

    for card_type, card_label in _CARD_LABELS.items():
        period_start = caps.get_period_start(card_type, config.CITI_STATEMENT_DATE)
        reset = _period_reset_date(card_type)

        lines.append(f"<b>{card_label}</b>  (resets {reset})")
        if card_type == "UOB_LADY":
            for cat in ("FAMILY", "DINING"):
                total = database.get_monthly_category_total("UOB_LADY", cat, period_start)
                bar = _fmt_bar(total, caps.UOB_LADY_CAP)
                remaining = max(caps.UOB_LADY_CAP - total, 0)
                lines.append(
                    f"  {cat.title()}: SGD {total:.0f} / {caps.UOB_LADY_CAP:.0f}"
                    f"  {bar}  SGD {remaining:.0f} left"
                )
        else:
            cap = caps.DBS_CAP if card_type == "DBS_WWMC" else caps.CITI_CAP
            total = database.get_period_total(card_type, period_start)
            bar = _fmt_bar(total, cap)
            remaining = max(cap - total, 0)
            lines.append(
                f"  Total: SGD {total:.0f} / {cap:.0f}  {bar}  SGD {remaining:.0f} left"
            )
        lines.append("")

    _post("\n".join(lines).rstrip())


def run_summary_loop() -> None:
    """Send a summary every SUMMARY_INTERVAL_SECONDS, skipping if no new transactions."""
    last_count = database.get_transaction_count()
    while True:
        time.sleep(config.SUMMARY_INTERVAL_SECONDS)
        try:
            current_count = database.get_transaction_count()
            if current_count == last_count:
                logger.info("No new transactions since last summary — skipping")
                continue
            last_count = current_count
            send_summary()
        except Exception:
            logger.exception("Summary send failed")


