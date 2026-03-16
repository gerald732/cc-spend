"""
Prometheus metrics and health endpoint for cc-spend.

Starts a background HTTP server on METRICS_PORT (default 9090) serving:
  GET /metrics  — Prometheus text format
  GET /healthz  — 200 OK while the process is alive
  GET /status   — JSON spend summary (current period totals vs caps)
"""

import json
import threading
from http.server import HTTPServer
import logging

from prometheus_client import Counter, Gauge
from prometheus_client.exposition import MetricsHandler

import caps
import config
import database

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

def _build_status() -> dict:
    """Query the DB and return current period spend vs caps for all cards."""
    result = {}
    for card_type in ("UOB_LADY", "DBS_WWMC", "CITI_REWARDS"):
        period_start = caps.get_period_start(card_type, config.CITI_STATEMENT_DATE)
        period_start_str = period_start.date().isoformat()

        if card_type == "UOB_LADY":
            card_cap = caps.UOB_LADY_CAP
            categories = {}
            for cat in ("FAMILY", "DINING"):
                spent = database.get_monthly_category_total(card_type, cat, period_start)
                categories[cat] = {
                    "spent": round(spent, 2),
                    "cap": card_cap,
                    "remaining": round(max(card_cap - spent, 0), 2),
                }
            result[card_type] = {"period_start": period_start_str, "categories": categories}
        else:
            card_cap = caps.DBS_CAP if card_type == "DBS_WWMC" else caps.CITI_CAP
            spent = database.get_period_total(card_type, period_start)
            result[card_type] = {
                "period_start": period_start_str,
                "spent": round(spent, 2),
                "cap": card_cap,
                "remaining": round(max(card_cap - spent, 0), 2),
            }
    return result


class _Handler(MetricsHandler):
    """HTTP handler serving /healthz, /status, and the Prometheus /metrics endpoint."""

    def do_GET(self):
        """Route GET requests to the appropriate handler."""
        if self.path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        elif self.path == "/status":
            try:
                body = json.dumps(_build_status(), indent=2).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                logger.exception("Failed to build /status response")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(exc).encode())
        else:
            super().do_GET()

    def log_message(self, *args):  # silence per-request access logs
        pass


def start_metrics_server(port: int) -> None:
    """Start the HTTP metrics/health server on a daemon thread."""
    server = HTTPServer(("", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Metrics server started on :%d (/metrics, /healthz, /status)", port)
