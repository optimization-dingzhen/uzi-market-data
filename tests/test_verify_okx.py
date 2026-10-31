import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_okx import verify

NOW = datetime(2026, 10, 30, 23, 13, 30, tzinfo=timezone.utc)


def timestamp(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


def fixture():
    def candle(timeframe, age):
        return {
            "timeframe": timeframe,
            "ohlc_source": "OKX trade candles, confirmed closes only",
            "last_closed_bar_end_utc": timestamp(age),
            "bar_count": 119,
            "last_close": 80.0,
            "ema20": 84.0,
            "ema50": 90.0,
            "rsi14": 35.0,
            "atr14": 4.0,
            "bollinger20": {"mid": 86.0, "upper": 100.0, "lower": 72.0},
        }
    return {
        "schema": "uzi.okx.soxl.swap.v1",
        "exchange": "OKX",
        "symbol": "SOXL-USDT-SWAP",
        "generated_at_utc": timestamp(0),
        "status": "live_verified_quotes",
        "source": {"api_base": "https://us.okx.com", "authenticated": False},
        "instrument": {"state": "live"},
        "market": {
            "last_price_usdt": 78.0, "mark_price_usdt": 77.99,
            "last_quote_time_utc": timestamp(1),
            "mark_quote_time_utc": timestamp(1),
            "last_quote_age_minutes": 0.0,
        },
        "technical": {"1d": candle("1d", 1393), "4h": candle("4h", 193)},
        "derivatives": {
            "oi_usd": 1230000.0, "oi_as_of_utc": timestamp(1),
            "oi_change_4h_pct": None, "oi_change_1d_pct": None,
            "funding_rate_pct": 0.01,
        },
    }


class TestOKXReadTimeVerification(unittest.TestCase):
    def test_fresh_with_missing_oi_changes_is_usable_with_warnings(self):
        result = verify(fixture(), NOW)
        self.assertTrue(result["usable_for_current_1d_4h_analysis"])
        self.assertEqual(result["analysis_order"], ["1d", "4h"])
        self.assertIn("oi_change_4h_pct_unavailable", result["warnings"])

    def test_stored_quote_age_is_not_trusted(self):
        report = fixture()
        report["market"]["mark_quote_time_utc"] = timestamp(91)
        report["market"]["mark_quote_age_minutes"] = 0
        self.assertIn("mark_quote_missing_future_or_stale", verify(report, NOW)["errors"])

    def test_generation_stale_despite_fresh_quotes(self):
        report = fixture()
        report["generated_at_utc"] = timestamp(92)
        self.assertFalse(verify(report, NOW)["usable_for_current_1d_4h_analysis"])

    def test_reject_wrong_exchange(self):
        report = fixture()
        report["exchange"] = "Binance"
        self.assertIn("wrong_exchange_or_symbol", verify(report, NOW)["errors"])

    def test_reject_unverified_source(self):
        report = fixture()
        report["source"]["api_base"] = "https://fapi.binance.com"
        self.assertIn("unverified_okx_source", verify(report, NOW)["errors"])

    def test_reject_stale_4h_candle(self):
        report = fixture()
        report["technical"]["4h"]["last_closed_bar_end_utc"] = timestamp(800)
        self.assertIn("4h_closed_candle_missing_future_or_stale", verify(report, NOW)["errors"])

    def test_reject_missing_rsi(self):
        report = fixture()
        report["technical"]["1d"]["rsi14"] = None
        self.assertIn("1d_rsi14_invalid", verify(report, NOW)["errors"])

    def test_reject_future_timestamp(self):
        report = fixture()
        report["market"]["last_quote_time_utc"] = timestamp(-5)
        self.assertIn("last_quote_missing_future_or_stale", verify(report, NOW)["errors"])

    def test_null_oi_is_warning_not_fabricated(self):
        report = fixture()
        report["derivatives"]["oi_as_of_utc"] = None
        report["derivatives"]["oi_usd"] = None
        result = verify(report, NOW)
        self.assertTrue(result["usable_for_current_1d_4h_analysis"])
        self.assertIn("okx_oi_missing_or_stale", result["warnings"])


if __name__ == "__main__":
    unittest.main()
