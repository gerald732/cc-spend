import json
import logging
from datetime import datetime
import paho.mqtt.client as mqtt
import config
import database
import caps

logger = logging.getLogger(__name__)

_TOPICS = {
    ("UOB_LADY", "GROCERIES"): ("tele/credit_cards/uob_lady_groceries/state", caps.UOB_GROCERIES_CAP),
    ("UOB_LADY", "DINING"):    ("tele/credit_cards/uob_lady_dining/state", None),
    ("DBS_WWMC", None):        ("tele/credit_cards/dbs_wwmc/state", caps.DBS_CAP),
    ("CITI_REWARDS", None):    ("tele/credit_cards/citi_rewards/state", caps.CITI_CAP),
}


def _make_client() -> mqtt.Client:
    client = mqtt.Client()
    if config.MQTT_USER:
        client.username_pw_set(config.MQTT_USER, config.MQTT_PASSWORD)
    client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
    return client


def publish_all():
    rows = database.get_all_monthly(_current_period_start())
    # Aggregate: card_type -> category -> total
    totals: dict[tuple, float] = {}
    card_totals: dict[str, float] = {}
    for row in rows:
        ct, cat, total = row["card_type"], row["category"], row["total"]
        totals[(ct, cat)] = totals.get((ct, cat), 0) + total
        card_totals[ct] = card_totals.get(ct, 0) + total

    client = _make_client()
    client.loop_start()

    # Per-category topics (UOB)
    for (ct, cat), topic_cap in _TOPICS.items():
        topic, cap = topic_cap
        if cat is not None:
            value = totals.get((ct, cat), 0.0)
        else:
            value = card_totals.get(ct, 0.0)
        payload: dict = {"value": round(value, 2)}
        if cap is not None:
            payload["cap"] = cap
            payload["remaining"] = round(max(cap - value, 0), 2)
        client.publish(topic, json.dumps(payload), retain=True)
        logger.info("MQTT publish %s → %s", topic, payload)

    client.loop_stop()
    client.disconnect()


def _current_period_start() -> datetime:
    # Use start of current calendar month as a reasonable default for aggregation
    today = datetime.today()
    return datetime(today.year, today.month, 1)
