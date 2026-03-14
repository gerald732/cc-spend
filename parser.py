import re
import logging

logging.basicConfig(filename="parse_errors.log", level=logging.ERROR,
                    format="%(asctime)s %(levelname)s %(message)s")

_AMOUNT_RE = re.compile(r"SGD\s*([\d,]+\.\d{2})")


def _parse_amount(text: str) -> float | None:
    m = _AMOUNT_RE.search(text)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


class CitiParser:
    FROM = "alerts@citibank.com.sg"
    SUBJECT = "Citi Alerts - Credit Card/Ready Credit Transaction"
    _MERCHANT_RE = re.compile(r"Transaction details\s*:\s*(.*)")

    def parse(self, body: str) -> tuple[str, float] | None:
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

    def parse(self, body: str) -> tuple[str, float] | None:
        m = self._MERCHANT_RE.search(body)
        amount = _parse_amount(body)
        if not m or amount is None:
            logging.error("DBSParser failed\n---\n%s\n---", body)
            return None
        return m.group(1).strip(), amount


class UOBParser:
    FROM = "unialerts@uobgroup.com"
    SUBJECT = "UOB - Transaction Alert"
    _MERCHANT_RE = re.compile(r"At\s+(.*?)\.\s+If\s+unauthorised,")

    def parse(self, body: str) -> tuple[str, float] | None:
        m = self._MERCHANT_RE.search(body)
        amount = _parse_amount(body)
        if not m or amount is None:
            logging.error("UOBParser failed\n---\n%s\n---", body)
            return None
        return m.group(1).strip(), amount


PARSERS = {
    "CITI_REWARDS": CitiParser(),
    "DBS_WWMC": DBSParser(),
    "UOB_LADY": UOBParser(),
}
