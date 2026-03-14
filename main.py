import logging
import signal
import sys

import database
import imap_listener

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
    database.init_db()
    imap_listener.run_loop()
