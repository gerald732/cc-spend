import re
import logging

logging.basicConfig(filename="parse_errors.log", level=logging.ERROR,
                    format="%(asctime)s %(levelname)s %(message)s")

_AMOUNT_RE = re.compile(r"SGD\s*([\d,]+\.\d{2})")


def _check_card_identifier(identifier: str | None, body: str, parser_name: str) -> bool:
    """Return False (and log) if identifier is set but not found in body."""
    if identifier and identifier.lower() not in body.lower():
        logging.error(
            "%s: card identifier '%s' not found in email — skipping\n---\n%s\n---",
            parser_name, identifier, body,
        )
        return False
    return True


def _parse_amount(text: str) -> float | None:
    m = _AMOUNT_RE.search(text)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


class CitiParser:
    FROM = "alerts@citibank.com.sg"
    SUBJECT = "Citi Alerts - Credit Card/Ready Credit Transaction"
    _MERCHANT_RE = re.compile(r"Transaction\s+details\s*:\s*(.*)", re.IGNORECASE)

    def __init__(self, identifier: str | None = None):
        self.identifier = identifier

    def parse(self, body: str) -> tuple[str, float] | None:
        if not _check_card_identifier(self.identifier, body, "CitiParser"):
            return None
        m = self._MERCHANT_RE.search(body)
        amount = _parse_amount(body)
        if not m or amount is None:
            logging.error("CitiParser failed\n---\n%s\n---", body)
            return None
        return m.group(1).strip(), amount


class DBSParser:
    FROM = "ibanking.alert@dbs.com"
    SUBJECT = "Card Transaction Alert"
    _MERCHANT_RE = re.compile(r"To:\s*(.*)")

    def __init__(self, identifier: str | None = None):
        self.identifier = identifier

    def parse(self, body: str) -> tuple[str, float] | None:
        if not _check_card_identifier(self.identifier, body, "DBSParser"):
            return None
        m = self._MERCHANT_RE.search(body)
        amount = _parse_amount(body)
        if not m or amount is None:
            logging.error("DBSParser failed\n---\n%s\n---", body)
            return None
        return m.group(1).strip(), amount


class UOBParser:
    FROM = "unialerts@uobgroup.com"
    SUBJECT = "UOB - Transaction Alert"
    _MERCHANT_RE = re.compile(r"at\s+(.*?)\.\s+If\s+unauthorised,", re.IGNORECASE)

    def __init__(self, identifier: str | None = None):
        self.identifier = identifier

    def parse(self, body: str) -> tuple[str, float] | None:
        if not _check_card_identifier(self.identifier, body, "UOBParser"):
            return None
        m = self._MERCHANT_RE.search(body)
        amount = _parse_amount(body)
        if not m or amount is None:
            logging.error("UOBParser failed\n---\n%s\n---", body)
            return None
        return m.group(1).strip(), amount


BANK_PARSER_CLASSES = {
    "CITI": CitiParser,
    "DBS": DBSParser,
    "UOB": UOBParser,
}
