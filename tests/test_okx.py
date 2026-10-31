import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from publish_okx import build_snapshot, parse_bars, oi_changes, oi_sample_diagnostics, SYMBOL

class TestOKX(unittest.TestCase):
    def sample(self):
        now = int(datetime.now(timezone.utc).timestamp()*1000)
        now4 = (now // 14400000)*14400000
        nowd = (now // 86400000)*86400000
        def bars(start, unit):
            rows=[]
            for i in range(120):
                ts = start-(119-i)*unit
                px = 40+i*0.5
                rows.append([str(ts), str(px), str(px+1), str(px-1), str(px+0.3),"100","100","1000","1" if i<119 else "0"])
            return list(reversed(rows))
        t={"instId": SYMBOL, "last":"99.0", "bidPx":"98.9", "askPx":"99.1", "ts":str(now),"high24h":"102","low24h":"93","vol24h":"10000"}
        return now, {
            "instrument":[{"instId":SYMBOL,"instType":"SWAP","state":"live","settleCcy":"USDT", "ctVal":"0.01", "ctValCcy":"SOXL"}],
            "ticker":[t],
            "mark_price":[{"instId":SYMBOL,"markPx":"99.05","ts":str(now)}],
            "open_interest":[{"instId":SYMBOL,"oi":"1000","oiUsd":"500000","oiCcy":"5000","ts":str(now)}],
            "funding_rate":[{"instId":SYMBOL,"fundingRate":"0.0001", "fundingTime":str(now+3600000)}],
            "candles_4h":bars(now4,14400000),
            "candles_1d":bars(nowd,86400000),
            "errors":[], "endpoints":{},
        }
    def test_quote_and_technical(self):
        now, snap = self.sample()
        result = build_snapshot(snap,now_ms=now)
        self.assertEqual(result["exchange"], "OKX")
        self.assertEqual(result["symbol"], SYMBOL)
        self.assertEqual(result["status"], "live_verified_quotes")
        self.assertGreater(result["technical"]["4h"]["bar_count"],50)
        self.assertGreater(result["technical"]["1d"]["bar_count"],50)
        self.assertEqual(result["derivatives"]["funding_rate_pct"],0.01)
        self.assertIsNone(result["derivatives"]["oi_change_4h_pct"])
    def test_unconfirmed_bar_ignored(self):
        now, snap=self.sample()
        result=build_snapshot(snap,now_ms=now)
        self.assertEqual(result["technical"]["1d"]["bar_count"],119)
        self.assertEqual(result["technical"]["4h"]["bar_count"],119)
    def test_reject_stale_quote(self):
        now, snap=self.sample()
        snap["mark_price"][0]["ts"]=str(now-45*60000)
        with self.assertRaisesRegex(ValueError,"stale"):
            build_snapshot(snap,now_ms=now)
    def test_reject_wrong_instrument(self):
        now,snap=self.sample()
        snap["ticker"][0]["instId"]="BTC-USDT-SWAP"
        with self.assertRaisesRegex(ValueError,"Unexpected instrument"):
            build_snapshot(snap,now_ms=now)
    def test_reject_inactive(self):
        now,snap=self.sample()
        snap["instrument"][0]["state"]="suspend"
        with self.assertRaisesRegex(ValueError,"not a live"):
            build_snapshot(snap,now_ms=now)
    def test_oi_4h_1d_changes(self):
        now,snap=self.sample()
        prev={"exchange":"OKX","symbol":SYMBOL,"oi_history":[
            {"ts_ms":now-4*3600000,"oi_usd":400000},
            {"ts_ms":now-24*3600000,"oi_usd":250000}]}
        result=build_snapshot(snap,previous=prev,now_ms=now)
        self.assertEqual(result["derivatives"]["oi_change_4h_pct"],25.0)
        self.assertEqual(result["derivatives"]["oi_change_1d_pct"],100.0)
    def test_reject_cross_exchange_oi_history(self):
        now,snap=self.sample()
        result=build_snapshot(snap,previous={"exchange":"Binance","symbol":SYMBOL,"oi_history":[{"ts_ms":now-4*3600000,"oi_usd":400000}]},now_ms=now)
        self.assertIsNone(result["derivatives"]["oi_change_4h_pct"])
    def test_oi_reference_gap_is_reported(self):
        now, snap = self.sample()
        prev = {"exchange": "OKX", "symbol": SYMBOL, "oi_history": [
            {"ts_ms": now-4*3600000+26*60000, "oi_usd": 400000},
            {"ts_ms": now-24*3600000-75*60000, "oi_usd": 300000},
        ]}
        result = build_snapshot(snap, previous=prev, now_ms=now)
        diagnostics = result["derivatives"]["oi_change_diagnostics"]
        self.assertIsNone(result["derivatives"]["oi_change_4h_pct"])
        self.assertIsNone(result["derivatives"]["oi_change_1d_pct"])
        self.assertEqual(diagnostics["4h"]["reason_if_unavailable"], "reference_outside_20m_tolerance")
        self.assertEqual(diagnostics["1d"]["reason_if_unavailable"], "reference_outside_20m_tolerance")

    def test_funding_missing_visible(self):
        now,snap=self.sample()
        snap.pop("funding_rate")
        result=build_snapshot(snap,now_ms=now)
        self.assertIsNone(result["derivatives"]["funding_rate_pct"])
        self.assertIn("OKX funding rate unavailable",result["warnings"])

if __name__=="__main__":
    unittest.main()
