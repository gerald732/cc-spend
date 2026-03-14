"""
One-off script to prefill the DB with estimated March 1–14 spend.
Edit the SEED list to match your actual transactions before running.

Usage:
    python seed_db.py [--dry-run]
"""

import sys
import database

database.init_db()

DRY_RUN = "--dry-run" in sys.argv

# fmt: (timestamp_iso, merchant, amount, card_type, category)
# - timestamp must be an ISO-8601 string (UTC or offset-aware)
# - category must be the value apply_cap *would have* assigned at that point in time
#   (i.e. the real merchant category, or "EXCEEDED" if cap was already blown by then)
# - amounts are in SGD
#
# Caps for reference:
#   UOB_LADY  FAMILY: $750  DINING: $750  (resets 1st of month)
#   DBS_WWMC  total:  $1000               (resets 1st of month)
#   CITI_REWARDS total: $1000             (resets on CITI_STATEMENT_DATE, default 25th)

SEED: list[tuple[str, str, float, str, str]] = [
    # ── UOB Lady ──────────────────────────────────────────────────────────
    # (EAT. @ TIONG BAHRU on 05 Mar excluded — amount cut off in source)
    ("2026-03-01T08:00:00+00:00", "KOPIFELLAS",         6.20, "UOB_LADY", "DINING"),
    ("2026-03-01T10:00:00+00:00", "SHENG SIONG",      103.44, "UOB_LADY", "FAMILY"),
    ("2026-03-02T10:00:00+00:00", "NTUC FAIRPRICE",     5.44, "UOB_LADY", "FAMILY"),
    ("2026-03-03T10:00:00+00:00", "NTUC FAIRPRICE",    25.56, "UOB_LADY", "FAMILY"),
    ("2026-03-04T10:00:00+00:00", "KRISPAY TONGUE TIP",26.20, "UOB_LADY", "DINING"),
    ("2026-03-04T12:00:00+00:00", "NTUC FAIRPRICE",     3.62, "UOB_LADY", "FAMILY"),
    ("2026-03-05T10:00:00+00:00", "GOKOKU BAKERY",      8.40, "UOB_LADY", "DINING"),
    ("2026-03-06T10:00:00+00:00", "BLUE LABEL PIZZA", 107.91, "UOB_LADY", "DINING"),
    ("2026-03-06T11:00:00+00:00", "KOPITIAM",            7.87, "UOB_LADY", "DINING"),
    ("2026-03-06T12:00:00+00:00", "GUARDIAN",            8.95, "UOB_LADY", "OTHER"),
    ("2026-03-06T13:00:00+00:00", "NTUC FAIRPRICE",    21.26, "UOB_LADY", "FAMILY"),
    ("2026-03-07T09:00:00+00:00", "YA KUN KAYA TOAST", 14.90, "UOB_LADY", "DINING"),
    ("2026-03-07T12:00:00+00:00", "PASTAGO",            20.00, "UOB_LADY", "DINING"),
    ("2026-03-07T19:00:00+00:00", "SHOCK BURGER",       12.49, "UOB_LADY", "DINING"),
    ("2026-03-08T09:00:00+00:00", "NTUC FAIRPRICE",     5.95, "UOB_LADY", "FAMILY"),
    ("2026-03-08T14:00:00+00:00", "WATSONS",            53.52, "UOB_LADY", "OTHER"),
    ("2026-03-08T19:00:00+00:00", "TASTE PARADISE",    229.15, "UOB_LADY", "DINING"),
    ("2026-03-09T09:00:00+00:00", "SHOCK BURGER",       11.90, "UOB_LADY", "DINING"),
    ("2026-03-09T10:00:00+00:00", "BJB TANJONG PAGAR",  5.90, "UOB_LADY", "DINING"),
    ("2026-03-09T11:00:00+00:00", "THE HAINAN STORY",   2.40, "UOB_LADY", "DINING"),
    ("2026-03-09T13:00:00+00:00", "NTUC FAIRPRICE",    13.95, "UOB_LADY", "FAMILY"),
    ("2026-03-09T19:00:00+00:00", "THE DAILY CUT",      9.45, "UOB_LADY", "DINING"),
    ("2026-03-10T12:00:00+00:00", "SMP BUGIS XIN YUAN JI", 13.10, "UOB_LADY", "DINING"),
    ("2026-03-11T10:00:00+00:00", "BJB TANJONG PAGAR",  5.90, "UOB_LADY", "DINING"),

    # ── DBS WWMC ──────────────────────────────────────────────────────────
    # (Shopee charges on 02–03 Mar fully offset by same-day refunds; net $0)
    ("2026-03-03T12:00:00+00:00", "GRAB",               6.72, "DBS_WWMC", "DINING"),
    ("2026-03-06T10:00:00+00:00", "AMZNPRIMESG",        4.99, "DBS_WWMC", "OTHER"),
    ("2026-03-08T11:00:00+00:00", "THE SOUP SPOON",    29.30, "DBS_WWMC", "DINING"),
    ("2026-03-08T14:00:00+00:00", "GRAB",              26.40, "DBS_WWMC", "TRANSPORT"),
    ("2026-03-09T10:00:00+00:00", "AXS PTE LTD",      71.60, "DBS_WWMC", "OTHER"),
    ("2026-03-10T10:00:00+00:00", "ZYM MOBILE",         7.77, "DBS_WWMC", "OTHER"),
    ("2026-03-12T12:00:00+00:00", "MOSBURGER",          9.10, "DBS_WWMC", "DINING"),
    ("2026-03-14T09:00:00+00:00", "CLAUDE.AI",         30.00, "DBS_WWMC", "OTHER"),
    ("2026-03-14T13:00:00+00:00", "MCDONALDS",          8.20, "DBS_WWMC", "DINING"),

    # ── CITI Rewards (period started 15 Feb) ──────────────────────────────
    ("2026-03-10T11:00:00+00:00", "ZYM MOBILE",       15.10, "CITI_REWARDS", "OTHER"),
    ("2026-03-14T15:00:00+00:00", "AMAZE ALPENGROUP",127.82, "CITI_REWARDS", "OTHER"),
    
]


def _print_totals():
    import caps, config

    period_starts = {
        ct: caps.get_period_start(ct, config.CITI_STATEMENT_DATE)
        for ct in ("UOB_LADY", "DBS_WWMC", "CITI_REWARDS")
    }
    print("\n  Post-seed totals:")
    for cat in ("FAMILY", "DINING"):
        t = database.get_monthly_category_total("UOB_LADY", cat, period_starts["UOB_LADY"])
        print(f"    UOB_LADY {cat}: SGD {t:.2f} / 750.00")
    for ct in ("DBS_WWMC", "CITI_REWARDS"):
        cap = 1000.0
        t = database.get_period_total(ct, period_starts[ct])
        print(f"    {ct}: SGD {t:.2f} / {cap:.2f}")


def main():
    import sqlite3, os
    if not DRY_RUN:
        conn = sqlite3.connect(os.environ.get("DB_PATH", "transactions.db"))
        count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        conn.close()
        if count > 0:
            print(f"ERROR: DB already has {count} rows. Refusing to seed again.")
            print("To reset: DELETE FROM transactions, then re-run seed_db.py")
            sys.exit(1)

    print(f"{'[DRY RUN] ' if DRY_RUN else ''}Seeding {len(SEED)} transactions...\n")
    for ts, merchant, amount, card_type, category in SEED:
        print(f"  {'(skip) ' if DRY_RUN else ''}  {merchant:30s}  {card_type:12s}  {category:10s}  SGD {amount:.2f}")
        if not DRY_RUN:
            database.insert_transaction(ts, merchant, amount, card_type, category)

    if not DRY_RUN:
        _print_totals()
    print("\nDone.")


if __name__ == "__main__":
    main()
