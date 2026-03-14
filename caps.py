from datetime import datetime, date
import database

UOB_GROCERIES_CAP = 750.0
DBS_CAP = 1000.0
CITI_CAP = 1000.0


def get_period_start(card_type: str, citi_statement_date: int) -> datetime:
    today = date.today()
    if card_type in ("DBS_WWMC", "UOB_LADY"):
        return datetime(today.year, today.month, 1)
    # CITI_REWARDS: billing period starts on citi_statement_date
    if today.day >= citi_statement_date:
        return datetime(today.year, today.month, citi_statement_date)
    # Before statement date — period started last month
    if today.month == 1:
        return datetime(today.year - 1, 12, citi_statement_date)
    return datetime(today.year, today.month - 1, citi_statement_date)


def apply_cap(card_type: str, category: str, citi_statement_date: int) -> str:
    period_start = get_period_start(card_type, citi_statement_date)

    if card_type == "UOB_LADY" and category == "GROCERIES":
        total = database.get_monthly_category_total("UOB_LADY", "GROCERIES", period_start)
        if total >= UOB_GROCERIES_CAP:
            return "EXCEEDED"

    elif card_type == "DBS_WWMC":
        total = database.get_period_total("DBS_WWMC", period_start)
        if total >= DBS_CAP:
            return "EXCEEDED"

    elif card_type == "CITI_REWARDS":
        total = database.get_period_total("CITI_REWARDS", period_start)
        if total >= CITI_CAP:
            return "EXCEEDED"

    return category
