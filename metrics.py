"""
Prometheus metrics and health endpoint for cc-spend.

Starts a background HTTP server on METRICS_PORT (default 9090) serving:
  GET /metrics  — Prometheus text format
  GET /healthz  — 200 OK while the process is alive
"""

import threading
from http.server import HTTPServer
import logging

from prometheus_client import Counter, Gauge
from prometheus_client.exposition import MetricsHandler

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

imap_failures = Counter(
    "cc_spend_imap_failures_total",
    "IMAP connection/fetch failures",
    ["reason"],  # "connect" | "fetch"
)

claude_failures = Counter(
    "cc_spend_claude_failures_total",
    "Claude API calls that exhausted all retries",
)

transactions_processed = Counter(
    "cc_spend_transactions_processed_total",
    "Transactions successfully parsed, stored, and published",
    ["card_type", "category"],
)

up_gauge = Gauge(
    "cc_spend_up",
    "1 if the service process is running",
)


# ---------------------------------------------------------------------------
# HTTP server (metrics + healthcheck on the same port)
# ---------------------------------------------------------------------------

class _Handler(MetricsHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            super().do_GET()

    def log_message(self, fmt, *args):  # silence per-request access logs
        pass


def start_metrics_server(port: int) -> None:
    server = HTTPServer(("", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Metrics server started on :%d (/metrics, /healthz)", port)
