"""Bank email parsers for cc-spend."""

import re
import logging

logging.basicConfig(filename="parse_errors.log", level=logging.ERROR,
                    format="%(asctime)s %(levelname)s %(message)s")

_AMOUNT_RE = re.compile(r"SGD\s*([\d,]+\.\d{2})")


def _check_card_identifier(identifier: str | None, body: str, label: str) -> bool:
    """Return False (and log) if identifier is set but not found in body."""
    if identifier and identifier.lower() not in body.lower():
        logging.error(
            "%s: card identifier '%s' not found in email — skipping\n---\n%s\n---",
            label, identifier, body,
        )
        return False
    return True


def _parse_amount(text: str) -> float | None:
    """Extract the first SGD amount from text, or return None."""
    m = _AMOUNT_RE.search(text)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


class BankParser:
    """Parses transaction alert emails from a single bank sender."""

    def __init__(self, from_address: str, subject: str, merchant_re: str,
                 identifier: str | None = None):
        self.from_address = from_address
        self.subject = subject
        self._merchant_re = re.compile(merchant_re, re.IGNORECASE)
        self.identifier = identifier

    def __repr__(self) -> str:
        return f"BankParser(from_address={self.from_address!r})"

    def parse(self, body: str) -> tuple[str, float] | None:
        """Extract (merchant, amount) from email body, or return None on failure."""
        if not _check_card_identifier(self.identifier, body, self.from_address):
            return None
        m = self._merchant_re.search(body)
        amount = _parse_amount(body)
        if not m or amount is None:
            logging.error("BankParser(%s) failed\n---\n%s\n---", self.from_address, body)
            return None
        return m.group(1).strip(), amount
