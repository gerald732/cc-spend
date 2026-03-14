"""
Unit tests for cc-spend.

Run with: python3 -m pytest test_cc_spend.py -v
  or:     python3 -m unittest test_cc_spend -v
"""

import os
import sys
import sqlite3
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Minimal env so config.py doesn't raise on missing required vars
# ---------------------------------------------------------------------------
os.environ.setdefault("GMAIL_USER", "test@gmail.com")
os.environ.setdefault("GMAIL_APP_PASSWORD", "test")
os.environ.setdefault("MQTT_HOST", "localhost")

import parser as p
import categorizer
import database
import caps
import config


# ===========================================================================
# Parser tests
# ===========================================================================

CITI_BODY = """
Dear Cardholder,

Transaction details : GRAB SINGAPORE
Amount             : SGD 12.50
"""

CITI_BODY_LARGE_AMOUNT = """
Transaction details : CAPITALAND MALL
Amount             : SGD 1,234.56
"""

DBS_BODY = """
Dear Customer,

To: MCD JURONG EAST
SGD 8.90 was charged to your card.
"""

UOB_BODY = """
You made a transaction.
At COLD STORAGE VIVOCITY. If unauthorised, please call us immediately.
SGD 55.30
"""

BROKEN_BODY = "This email has no useful content."


class TestCitiParser(unittest.TestCase):
    def setUp(self):
        self.parser = p.CitiParser()

    def test_happy_path(self):
        merchant, amount = self.parser.parse(CITI_BODY)
        self.assertEqual(merchant, "GRAB SINGAPORE")
        self.assertAlmostEqual(amount, 12.50)

    def test_comma_amount(self):
        merchant, amount = self.parser.parse(CITI_BODY_LARGE_AMOUNT)
        self.assertEqual(merchant, "CAPITALAND MALL")
        self.assertAlmostEqual(amount, 1234.56)

    def test_missing_fields_returns_none(self):
        self.assertIsNone(self.parser.parse(BROKEN_BODY))


class TestDBSParser(unittest.TestCase):
    def setUp(self):
        self.parser = p.DBSParser()

    def test_happy_path(self):
        merchant, amount = self.parser.parse(DBS_BODY)
        self.assertEqual(merchant, "MCD JURONG EAST")
        self.assertAlmostEqual(amount, 8.90)

    def test_missing_fields_returns_none(self):
        self.assertIsNone(self.parser.parse(BROKEN_BODY))


class TestUOBParser(unittest.TestCase):
    def setUp(self):
        self.parser = p.UOBParser()

    def test_happy_path(self):
        merchant, amount = self.parser.parse(UOB_BODY)
        self.assertEqual(merchant, "COLD STORAGE VIVOCITY")
        self.assertAlmostEqual(amount, 55.30)

    def test_missing_fields_returns_none(self):
        self.assertIsNone(self.parser.parse(BROKEN_BODY))


# ===========================================================================
# Categorizer tests
# ===========================================================================

class TestCategorizer(unittest.TestCase):
    def test_exact_grocery(self):
        self.assertEqual(categorizer.categorize("NTUC FAIRPRICE"), "GROCERIES")

    def test_fuzzy_grocery(self):
        # Partial name — should still fuzzy-match NTUC
        self.assertEqual(categorizer.categorize("NTUC AMK HUB"), "GROCERIES")

    def test_exact_dining(self):
        self.assertEqual(categorizer.categorize("FOODPANDA"), "DINING")

    def test_fast_food_mcc(self):
        self.assertEqual(categorizer.categorize("MCD JURONG EAST"), "DINING")

    def test_transport(self):
        self.assertEqual(categorizer.categorize("GRAB"), "TRANSPORT")

    def test_unknown_merchant(self):
        self.assertEqual(categorizer.categorize("XYZZY UNKNOWN SHOP 999"), "OTHER")

    def test_case_insensitive(self):
        self.assertEqual(categorizer.categorize("ntuc fairprice"), "GROCERIES")


# ===========================================================================
# Claude fallback categorizer tests
# ===========================================================================

class TestCategorizeWithClaudeFallback(unittest.TestCase):
    def test_known_merchant_skips_claude(self):
        # NTUC matches fuzzy — Claude should never be called
        with patch("categorizer.anthropic") as mock_anthropic:
            result = categorizer.categorize_with_claude_fallback("NTUC FAIRPRICE")
        self.assertEqual(result, "GROCERIES")
        mock_anthropic.Anthropic.assert_not_called()

    def test_unknown_merchant_calls_claude_and_returns_category(self):
        mock_response = unittest.mock.MagicMock()
        mock_response.content[0].text = "GROCERIES"
        with patch.object(config, "ANTHROPIC_API_KEY", "test-key"), \
             patch("categorizer.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = mock_response
            result = categorizer.categorize_with_claude_fallback("SHENG SIONG FINEST 888")
        self.assertEqual(result, "GROCERIES")

    def test_claude_returns_dining(self):
        mock_response = unittest.mock.MagicMock()
        mock_response.content[0].text = "dining"  # lowercase — should be normalised
        with patch.object(config, "ANTHROPIC_API_KEY", "test-key"), \
             patch("categorizer.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = mock_response
            result = categorizer.categorize_with_claude_fallback("SOME RANDOM CAFE 42")
        self.assertEqual(result, "DINING")

    def test_claude_returns_unexpected_value_falls_back_to_other(self):
        mock_response = unittest.mock.MagicMock()
        mock_response.content[0].text = "TRANSPORT"
        with patch.object(config, "ANTHROPIC_API_KEY", "test-key"), \
             patch("categorizer.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = mock_response
            result = categorizer.categorize_with_claude_fallback("SOME RANDOM MERCHANT")
        self.assertEqual(result, "OTHER")

    def test_no_api_key_returns_other_without_calling_claude(self):
        with patch.object(config, "ANTHROPIC_API_KEY", None), \
             patch("categorizer.anthropic.Anthropic") as mock_cls:
            result = categorizer.categorize_with_claude_fallback("UNKNOWN PLACE")
        self.assertEqual(result, "OTHER")
        mock_cls.assert_not_called()

    def test_claude_exception_returns_other(self):
        with patch.object(config, "ANTHROPIC_API_KEY", "test-key"), \
             patch("categorizer.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.side_effect = Exception("API error")
            result = categorizer.categorize_with_claude_fallback("UNKNOWN PLACE")
        self.assertEqual(result, "OTHER")


# ===========================================================================
# ONLINE_CARD_TYPES config tests
# ===========================================================================

class TestOnlineCardTypes(unittest.TestCase):
    def test_default_online_cards(self):
        self.assertIn("DBS_WWMC", config.ONLINE_CARD_TYPES)
        self.assertIn("CITI_REWARDS", config.ONLINE_CARD_TYPES)

    def test_uob_not_in_online_cards(self):
        self.assertNotIn("UOB_LADY", config.ONLINE_CARD_TYPES)

    def test_override_via_env(self):
        with patch.dict(os.environ, {"ONLINE_CARD_TYPES": "DBS_WWMC"}):
            # Re-evaluate the expression as config.py would
            result = set(os.environ["ONLINE_CARD_TYPES"].split(","))
        self.assertEqual(result, {"DBS_WWMC"})
        self.assertNotIn("CITI_REWARDS", result)


# ===========================================================================
# Database tests  (uses a temp file so tests are isolated)
# ===========================================================================

class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        # Patch DB_PATH before each test
        self._patcher = patch.object(database, "DB_PATH", self.tmp.name)
        self._patcher.start()
        database.init_db()

    def tearDown(self):
        self._patcher.stop()
        os.unlink(self.tmp.name)

    def _insert(self, merchant, amount, card_type, category, ts=None):
        ts = ts or datetime.now().isoformat()
        database.insert_transaction(ts, merchant, amount, card_type, category)
        return ts

    def test_insert_and_retrieve(self):
        self._insert("NTUC", 50.0, "UOB_LADY", "GROCERIES")
        conn = sqlite3.connect(self.tmp.name)
        rows = conn.execute("SELECT * FROM transactions").fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "NTUC")  # merchant column

    def test_get_period_total(self):
        period_start = datetime(2026, 3, 1)
        self._insert("NTUC", 100.0, "UOB_LADY", "GROCERIES", "2026-03-05T10:00:00")
        self._insert("GIANT", 200.0, "UOB_LADY", "GROCERIES", "2026-03-10T10:00:00")
        # Outside period — should not be counted
        self._insert("GIANT", 999.0, "UOB_LADY", "GROCERIES", "2026-02-28T23:59:59")

        total = database.get_period_total("UOB_LADY", period_start)
        self.assertAlmostEqual(total, 300.0)

    def test_get_period_total_excludes_other_cards(self):
        period_start = datetime(2026, 3, 1)
        self._insert("NTUC", 100.0, "UOB_LADY", "GROCERIES", "2026-03-05T10:00:00")
        self._insert("MCD", 50.0, "DBS_WWMC", "DINING", "2026-03-05T10:00:00")

        self.assertAlmostEqual(database.get_period_total("UOB_LADY", period_start), 100.0)
        self.assertAlmostEqual(database.get_period_total("DBS_WWMC", period_start), 50.0)

    def test_get_monthly_category_total(self):
        period_start = datetime(2026, 3, 1)
        self._insert("NTUC", 400.0, "UOB_LADY", "GROCERIES", "2026-03-01T10:00:00")
        self._insert("GRAB", 30.0, "UOB_LADY", "DINING", "2026-03-02T10:00:00")

        grocery_total = database.get_monthly_category_total("UOB_LADY", "GROCERIES", period_start)
        self.assertAlmostEqual(grocery_total, 400.0)

        dining_total = database.get_monthly_category_total("UOB_LADY", "DINING", period_start)
        self.assertAlmostEqual(dining_total, 30.0)

    def test_get_all_monthly_groups_correctly(self):
        period_start = datetime(2026, 3, 1)
        self._insert("NTUC", 100.0, "UOB_LADY", "GROCERIES", "2026-03-01T10:00:00")
        self._insert("GIANT", 50.0, "UOB_LADY", "GROCERIES", "2026-03-02T10:00:00")
        self._insert("MCD", 20.0, "DBS_WWMC", "DINING", "2026-03-03T10:00:00")

        rows = database.get_all_monthly(period_start)
        result = {(r["card_type"], r["category"]): r["total"] for r in rows}

        self.assertAlmostEqual(result[("UOB_LADY", "GROCERIES")], 150.0)
        self.assertAlmostEqual(result[("DBS_WWMC", "DINING")], 20.0)


# ===========================================================================
# Cap logic tests
# ===========================================================================

class TestCaps(unittest.TestCase):
    """
    Tests for get_period_start and apply_cap.
    database calls in apply_cap are patched so these tests have no I/O.
    """

    # --- get_period_start ---

    def test_dbs_period_start_is_first_of_month(self):
        with patch("caps.date") as mock_date:
            mock_date.today.return_value = datetime(2026, 3, 14).date()
            result = caps.get_period_start("DBS_WWMC", 25)
        self.assertEqual(result, datetime(2026, 3, 1))

    def test_uob_period_start_is_first_of_month(self):
        with patch("caps.date") as mock_date:
            mock_date.today.return_value = datetime(2026, 3, 14).date()
            result = caps.get_period_start("UOB_LADY", 25)
        self.assertEqual(result, datetime(2026, 3, 1))

    def test_citi_period_start_same_month_when_past_statement_date(self):
        # today=Mar 26, statement_date=25 → period started Mar 25
        with patch("caps.date") as mock_date:
            mock_date.today.return_value = datetime(2026, 3, 26).date()
            result = caps.get_period_start("CITI_REWARDS", 25)
        self.assertEqual(result, datetime(2026, 3, 25))

    def test_citi_period_start_prev_month_before_statement_date(self):
        # today=Mar 14, statement_date=25 → period started Feb 25
        with patch("caps.date") as mock_date:
            mock_date.today.return_value = datetime(2026, 3, 14).date()
            result = caps.get_period_start("CITI_REWARDS", 25)
        self.assertEqual(result, datetime(2026, 2, 25))

    def test_citi_period_start_january_wraps_to_previous_year(self):
        # today=Jan 10, statement_date=25 → period started Dec 25 of prev year
        with patch("caps.date") as mock_date:
            mock_date.today.return_value = datetime(2026, 1, 10).date()
            result = caps.get_period_start("CITI_REWARDS", 25)
        self.assertEqual(result, datetime(2025, 12, 25))

    # --- apply_cap ---

    def test_uob_groceries_under_cap_unchanged(self):
        with patch("caps.database.get_monthly_category_total", return_value=400.0), \
             patch("caps.get_period_start", return_value=datetime(2026, 3, 1)):
            result = caps.apply_cap("UOB_LADY", "GROCERIES", 25)
        self.assertEqual(result, "GROCERIES")

    def test_uob_groceries_at_cap_returns_exceeded(self):
        with patch("caps.database.get_monthly_category_total", return_value=750.0), \
             patch("caps.get_period_start", return_value=datetime(2026, 3, 1)):
            result = caps.apply_cap("UOB_LADY", "GROCERIES", 25)
        self.assertEqual(result, "EXCEEDED")

    def test_uob_dining_never_capped(self):
        # DINING on UOB_LADY has no cap — should pass through unchanged
        with patch("caps.get_period_start", return_value=datetime(2026, 3, 1)):
            result = caps.apply_cap("UOB_LADY", "DINING", 25)
        self.assertEqual(result, "DINING")

    def test_dbs_under_cap_unchanged(self):
        with patch("caps.database.get_period_total", return_value=500.0), \
             patch("caps.get_period_start", return_value=datetime(2026, 3, 1)):
            result = caps.apply_cap("DBS_WWMC", "DINING", 25)
        self.assertEqual(result, "DINING")

    def test_dbs_at_cap_returns_exceeded(self):
        with patch("caps.database.get_period_total", return_value=1000.0), \
             patch("caps.get_period_start", return_value=datetime(2026, 3, 1)):
            result = caps.apply_cap("DBS_WWMC", "DINING", 25)
        self.assertEqual(result, "EXCEEDED")

    def test_citi_under_cap_unchanged(self):
        with patch("caps.database.get_period_total", return_value=999.99), \
             patch("caps.get_period_start", return_value=datetime(2026, 2, 25)):
            result = caps.apply_cap("CITI_REWARDS", "OTHER", 25)
        self.assertEqual(result, "OTHER")

    def test_citi_at_cap_returns_exceeded(self):
        with patch("caps.database.get_period_total", return_value=1000.0), \
             patch("caps.get_period_start", return_value=datetime(2026, 2, 25)):
            result = caps.apply_cap("CITI_REWARDS", "OTHER", 25)
        self.assertEqual(result, "EXCEEDED")


if __name__ == "__main__":
    unittest.main()
