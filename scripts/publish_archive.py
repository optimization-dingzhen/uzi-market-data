#!/usr/bin/env python3
"""Publish delayed Binance Vision USD-M SOXLUSDT futures OHLCV (read-only).

Not a real-time data source: archive ZIPs are published after the trading day.
No attempt is made to access georestricted Binance Futures REST endpoints.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import statistics
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = "https://data.binance.vision/data/futures/um"
UA = "UZI-Research-Historical-Archive/1.0"
MARKET = "Binance USD-M Futures"
INTERVAL_SECONDS = {"4h": 4 * 3600, "1d": 24 * 3600}


def monthly_url(symbol: str, interval: str, year_month: str) -> str:
    return f"{ROOT}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{year_month}.zip"


def daily_url(symbol: str, interval: str, day: date) -> str:
    dt = day.isoformat()
    return f"{ROOT}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{dt}.zip"


def http_zip(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Unexpected status {resp.status}: {url}")
            if (resp.headers.get("Content-Length") or "0").isdigit() and int(resp.headers.get("Content-Length") or "0") > 5_000_000:
                raise RuntimeError(f"Archive exceeds size limit: {url}")
            data = resp.read(5_000_001)
            if len(data) > 5_000_000:
                raise RuntimeError(f"Archive exceeds size limit: {url}")
            return data
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise RuntimeError(f"Archive fetch denied HTTP {e.code}: {url}") from e


def parse_zip(data: bytes, interval: str) -> list[list[Any]]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        members = [s for s in z.namelist() if s.endswith(".csv") and not s.startswith("__MACOSX")]
        if len(members) != 1:
            raise ValueError("Archive should contain exactly one CSV")
        content = z.read(members[0])
    raw = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    rows: list[list[Any]] = []
    for a in raw:
        if len(a) < 7:
            continue
        try:
            t = int(a[0]); o, h, l, c, v = map(float, a[1:6]); ct = int(a[6])
        except (ValueError, TypeError):
            continue  # Header row, if any
        if t > 10**14:  # Guard against accidental microsecond timestamp
            t //= 1000
        if ct > 10**14:
            ct //= 1000
        if not all(map(math.isfinite, (o, h, l, c, v))) or l <= 0 or v < 0:
            continue
        if h < max(o, l, c) or l > min(o, c):
            continue
        dur_ms = INTERVAL_SECONDS[interval] * 1000
        if abs((ct - t) - (dur_ms - 1)) > 5000:
            continue
        rows.append([t, o, h, l, c, v, ct])
    return rows


def ema(values: list[float], n: int) -> float | None:
    if len(values) < n:
        return None
    smoothed = sum(values[:n]) / n
    alpha = 2 / (n + 1)
    for x in values[n:]:
        smoothed = smoothed * (1 - alpha) + x * alpha
    return smoothed


def rsi(values: list[float], n: int = 14) -> float | None:
    if len(values) <= n:
        return None
    diff = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    gains = sum(max(x, 0) for x in diff[:n]) / n
    losses = sum(max(-x, 0) for x in diff[:n]) / n
    for d in diff[n:]:
        gains = (gains * (n - 1) + max(d, 0)) / n
        losses = (losses * (n - 1) + max(-d, 0)) / n
    return (100.0 if gains > 0 else 50.0) if losses == 0 else 100 - 100 / (1 + gains / losses)


def atr(rows: list[list[Any]], n: int = 14) -> float | None:
    if len(rows) <= n:
        return None
    tr = []
    for a, b in zip(rows[:-1], rows[1:]):
        tr.append(max(b[2] - b[3], abs(b[2] - a[4]), abs(b[3] - a[4])))
    value = sum(tr[:n]) / n
    for x in tr[n:]:
        value = (value * (n - 1) + x) / n
    return value


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def metrics(rows: list[list[Any]], interval: str) -> dict[str, Any]:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    unique = {row[0]: row for row in rows if row[6] <= now_ms}
    bars = [unique[k] for k in sorted(unique)]
    if not bars:
        return {"available": False, "bars": 0}
    close = [x[4] for x in bars]
    e20, e50 = ema(close, 20), ema(close, 50)
    last = bars[-1]
    trend = "unavailable" if e50 is None else ("up" if last[4] > e20 > e50 else "down" if last[4] < e20 < e50 else "mixed")
    since = datetime.now(timezone.utc) - datetime.fromtimestamp(last[6] / 1000, tz=timezone.utc)
    return {
        "available": True, "interval": interval, "bars": len(bars),
        "last_closed_bar_open_utc": iso(last[0]),
        "last_closed_bar_end_utc": iso(last[6]),
        "last_close_usdt": round(last[4], 5),
        "last_bar_high_usdt": round(last[2], 5),
        "last_bar_low_usdt": round(last[3], 5),
        "ema20": round(e20, 5) if e20 is not None else None,
        "ema50": round(e50, 5) if e50 is not None else None,
        "rsi14": round(rsi(close), 2) if rsi(close) is not None else None,
        "atr14": round(atr(bars), 5) if atr(bars) is not None else None,
        "recent20_high_usdt": max(x[2] for x in bars[-20:]),
        "recent20_low_usdt": min(x[3] for x in bars[-20:]),
        "trend": trend,
        "age_minutes": round(since.total_seconds() / 60, 2),
    }


def previous_n_months(as_of: date, n: int) -> list[str]:
    y, m = as_of.year, as_of.month
    result = []
    for _ in range(n):
        if m == 1:
            y -= 1
            m = 12
        else:
            m -= 1
        result.append(f"{y:04d}-{m:02d}")
    return sorted(result)


def month_start(as_of: date) -> date:
    return as_of.replace(day=1)


def fetch_history(symbol: str, interval: str, as_of: date, lookback_months: int = 2) -> tuple[list[list[Any]],list[str],list[str]]:
    urls: list[str] = []
    warnings: list[str] = []
    collected: list[list[Any]] = []
    for ym in previous_n_months(as_of, lookback_months):
        url = monthly_url(symbol, interval, ym)
        data = http_zip(url)
        if data is None:
            warnings.append(f"archive_not_published: {url}")
            continue
        collected.extend(parse_zip(data, interval))
        urls.append(url)
    day = month_start(as_of)
    while day < as_of:
        url = daily_url(symbol, interval, day)
        data = http_zip(url)
        if data is None:
            warnings.append(f"archive_not_yet_available: {day} ({interval})")
        else:
            collected.extend(parse_zip(data, interval))
            urls.append(url)
        day += timedelta(days=1)
    return collected, urls, warnings


def create_report(symbol: str, as_of: date) -> dict[str, Any]:
    fetched_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    analysis: dict[str, Any] = {}
    all_urls: list[str] = []
    warnings: list[str] = []
    for interval in ("1d", "4h"):
        bars, urls, w = fetch_history(symbol, interval, as_of)
        all_urls.extend(urls); warnings.extend(w)
        analysis[interval] = metrics(bars, interval)
    if not analysis["1d"]["available"] or not analysis["4h"]["available"]:
        raise RuntimeError("Missing 1d or 4h futures candles; refuse to publish an empty report")
    if analysis["1d"]["bars"] < 50 or analysis["4h"]["bars"] < 50:
        warnings.append("insufficient_50_bar_indicator_history")
    return {
        "schema": "uzi-market-archive-v1", "symbol": symbol,
        "product": MARKET, "source": "Binance Vision official futures UM historical Kline CSV archives",
        "source_archive_root": ROOT,
        "generated_at_utc": fetched_utc,
        "is_realtime": False,
        "is_archived_lagged_ohlcv": True,
        "status": "historical_only_no_trading_signal",
        "analysis": {"technical": analysis},
        "derivatives": {"current_open_interest": None, "funding_rate": None, "mark_price": None},
        "not_provided": ["live_last_price", "live_mark_price", "live_funding_rate", "current_OI", "options_max_pain"],
        "provenance": {"files_count": len(all_urls), "last_four_archive_urls": all_urls[-4:]},
        "warnings": warnings[:150],
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol", default="SOXLUSDT", choices=["SOXLUSDT"])
    p.add_argument("--output", type=Path, default=Path("data/SOXLUSDT-historical.json"))
    p.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(timezone.utc).date())
    a = p.parse_args()
    result = create_report(a.symbol, a.as_of)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=a.output.parent, delete=False) as tf:
        json.dump(result, tf, ensure_ascii=False, indent=2)
        tf.write("\n")
        tmp_path = Path(tf.name)
    tmp_path.replace(a.output)
    print(json.dumps({"status":result["status"],"output":str(a.output),"1d":result["analysis"]["technical"]["1d"],"4h":result["analysis"]["technical"]["4h"],"warnings_count":len(result["warnings"])},ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
