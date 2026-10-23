import io
import csv
import sys
import unittest
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publish_archive as a

class TestArchive(unittest.TestCase):
    def test_urls(self):
        self.assertIn('/futures/um/daily/klines/SOXLUSDT/4h/', a.daily_url('SOXLUSDT','4h',date(2026,10,21)))
    def test_months(self):
        self.assertEqual(a.previous_n_months(date(2026,1,5),2),['2025-11','2025-12'])
    def test_parse_zip_header(self):
        b=io.BytesIO()
        with zipfile.ZipFile(b, 'w') as z:
            z.writestr('SOXLUSDT-1d.csv','open_time,open,high,low,close,volume,close_time\n1792627200000,10,11,9,10.5,100,1792713599999\n')
        parsed=a.parse_zip(b.getvalue(), '1d')
        self.assertEqual(len(parsed),1)
        self.assertEqual(parsed[0][4],10.5)
    def test_metrics_small(self):
        now=int(datetime.now(timezone.utc).timestamp()*1000)
        bars=[]
        for x in range(100):
            t=now-((105-x)*86400*1000)
            v=100+x/10
            bars.append([t,v,v+1,v-1,v,20,t+86400*1000-1])
        m=a.metrics(bars,'1d')
        self.assertEqual(m['trend'],'up')
        self.assertEqual(m['bars'],100)
        self.assertIsNotNone(m['rsi14'])
        self.assertFalse('funding_rate' in m)
    def test_unpublished(self):
        self.assertGreater(len(a.monthly_url('SOXLUSDT','4h','2026-09')),15)

if __name__ == '__main__': unittest.main()
