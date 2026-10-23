import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from publish_snapshot import make_publication, atomic_save


class TestRelay(unittest.TestCase):
    def snapshot(self, minutes_ago=0):
        now = datetime.now(timezone.utc)
        now_ms = int(now.timestamp() * 1000)
        t = now_ms - minutes_ago * 60_000
        def candles(period_ms):
            out = []
            last_open = (now_ms // period_ms) * period_ms - period_ms
            for n in range(150):
                candle_ms = last_open - (149-n) * period_ms
                val = 100 + n * 0.12
                out.append([candle_ms, str(val), str(val + 0.2), str(val - 0.2), str(val + 0.1), "100", candle_ms + period_ms - 1])
            return out
        return {
            "symbol": "SOXLUSDT",
            "fetched_at_utc": now.isoformat(),
            "data_source": "Binance USD-M Futures public REST API (fapi.binance.com)",
            "ticker_24h": {"symbol": "SOXLUSDT", "lastPrice": "120", "closeTime": t,
                          "highPrice": "121", "lowPrice": "116", "quoteVolume": "100000"},
            "premium_index": {"symbol": "SOXLUSDT", "markPrice": "120", "indexPrice": "119.9",
                              "lastFundingRate": "0.0001", "time": t},
            "klines": {"1d": candles(86_400_000), "4h": candles(14_400_000)},
            "open_interest": {"symbol": "SOXLUSDT", "openInterest": "12345"},
            "errors": [],
        }

    def test_fresh_report(self):
        p = make_publication(self.snapshot(), "SOXLUSDT")
        self.assertEqual(p["schema"], "uzi-market-relay/v1")
        self.assertEqual(p["status_at_publication"], "complete")
        self.assertTrue(p["realtime_at_publication"])
        self.assertIn("1d", p["analysis"]["technical"])
        self.assertIn("4h", p["analysis"]["technical"])
        self.assertNotIn("klines", p)
        self.assertLess(len(json.dumps(p)), 9000)

    def test_refuse_stale_snapshot(self):
        with self.assertRaises(ValueError):
            make_publication(self.snapshot(minutes_ago=120), "SOXLUSDT")

    def test_refuse_wrong_symbol(self):
        with self.assertRaises(ValueError):
            make_publication(self.snapshot(), "BTCUSDT")

    def test_refuse_non_binance_provenance(self):
        s = self.snapshot()
        s["data_source"] = "unverified website"
        with self.assertRaises(ValueError):
            make_publication(s, "SOXLUSDT")

    def test_partial_when_4h_missing(self):
        s = self.snapshot()
        s["klines"].pop("4h")
        p = make_publication(s, "SOXLUSDT")
        self.assertEqual(p["status_at_publication"], "partial")
        self.assertEqual(p["analysis"]["higher_timeframe_context"]["alignment"], "insufficient_verified_klines")

    def test_atomic_file(self):
        with tempfile.TemporaryDirectory() as dirname:
            f = Path(dirname) / "data" / "SOXLUSDT.json"
            p = make_publication(self.snapshot(), "SOXLUSDT")
            atomic_save(f, p)
            self.assertEqual(json.loads(f.read_text(encoding="utf-8"))["schema"], "uzi-market-relay/v1")


if __name__ == "__main__":
    unittest.main()

class TestVerification(unittest.TestCase):
    def test_report_freshness_and_stale(self):
        from verify_relay import verify
        report = make_publication(TestRelay().snapshot(), "SOXLUSDT")
        good = verify(report)
        self.assertEqual(good["status"], "fresh_ready")
        self.assertTrue(good["usable_for_current_1d_4h_analysis"])
        later = datetime.now(timezone.utc) + timedelta(minutes=16)
        old = verify(report, now=later)
        self.assertFalse(old["usable_for_current_1d_4h_analysis"])
        self.assertIn("last_price_utc_missing_or_stale", old["errors"])

    def test_fake_host_rejected(self):
        from verify_relay import verify
        report = make_publication(TestRelay().snapshot(), "SOXLUSDT")
        report["source_host"] = "other.example"
        self.assertFalse(verify(report)["usable_for_current_1d_4h_analysis"])

    def test_late_candles_cannot_be_current_signals(self):
        from verify_relay import verify
        report = make_publication(TestRelay().snapshot(), "SOXLUSDT")
        report["analysis"]["technical"]["4h"]["last_closed_candle_close_time_utc"] = "2026-01-01T00:00:00+00:00"
        res = verify(report)
        self.assertFalse(res["usable_for_current_1d_4h_analysis"])
        self.assertIn("4h_candle_stale", res["warnings"])
