import logging
import signal
import sys
import threading

import config
import database
import imap_listener
import metrics
import telegram_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def _handle_sigterm(signum, frame):
    logger.info("Received SIGTERM, shutting down.")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_sigterm)
    metrics.start_metrics_server(config.METRICS_PORT)
    metrics.up_gauge.set(1)
    database.init_db()
    threading.Thread(target=telegram_client.run_summary_loop, daemon=True).start()
    imap_listener.run_loop()
