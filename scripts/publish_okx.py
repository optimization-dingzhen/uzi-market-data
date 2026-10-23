#!/usr/bin/env python3
"""Publish a verified OKX SOXL-USDT-SWAP public-market snapshot (read only).

The exchange and instrument are deliberately explicit: OKX data must never be
presented as Binance SOXLUSDT data. No account key, trade or private endpoint.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API_BASE = "https://us.okx.com"
SYMBOL = "SOXL-USDT-SWAP"
TIMEFRAMES = {"4h": ("4H", 4 * 3600000), "1d": ("1Dutc", 24 * 3600000)}
API_ROUTES = {
    "instrument": ("/api/v5/public/instruments", {"instType": "SWAP", "instId": SYMBOL}),
    "ticker": ("/api/v5/market/ticker", {"instId": SYMBOL}),
    "mark_price": ("/api/v5/public/mark-price", {"instType": "SWAP", "instId": SYMBOL}),
    "open_interest": ("/api/v5/public/open-interest", {"instType": "SWAP", "instId": SYMBOL}),
    "funding_rate": ("/api/v5/public/funding-rate", {"instId": SYMBOL}),
    "candles_4h": ("/api/v5/market/candles", {"instId": SYMBOL, "bar": "4H", "limit": "120"}),
    "candles_1d": ("/api/v5/market/candles", {"instId": SYMBOL, "bar": "1Dutc", "limit": "120"}),
}


def numeric(v: Any) -> float | None:
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (ValueError, TypeError):
        return None


def round_value(v: float | None, digits: int = 5) -> float | None:
    return round(v, digits) if v is not None and math.isfinite(v) else None


def iso_ms(v: Any) -> str | None:
    f = numeric(v)
    if f is None:
        return None
    return datetime.fromtimestamp(f / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def elapsed_minutes(now_ms: float, timestamp_ms: Any) -> float | None:
    value = numeric(timestamp_ms)
    return (now_ms - value) / 60000.0 if value is not None else None


def get_json(route: str, query: dict[str, str]) -> dict[str, Any]:
    url = API_BASE + route + "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "UZI-readonly-OKX/1.0"})
    with urllib.request.urlopen(req, timeout=12) as response:
        body = response.read(2_000_000)
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict) or str(payload.get("code")) != "0" or not isinstance(payload.get("data"), list):
        raise ValueError(f"OKX API failure {route}: {str(payload)[:220]}")
    return payload


def fetch_all() -> dict[str, Any]:
    raw: dict[str, Any] = {"fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "errors": [], "endpoints": {}}
    required = {"instrument", "ticker", "mark_price", "candles_4h", "candles_1d"}
    for name, (route, args) in API_ROUTES.items():
        try:
            data = get_json(route, args)["data"]
            if not data:
                raise ValueError("No data")
            raw[name] = data
            raw["endpoints"][name] = API_BASE + route
        except Exception as exc:
            message = f"{name}: {type(exc).__name__}: {exc}"
            raw["errors"].append(message)
            if name in required:
                raise RuntimeError(message) from exc
    raw["fetched_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return raw


def first(raw: dict[str, Any], name: str, required: bool = False) -> dict[str, Any]:
    items = raw.get(name)
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        if required:
            raise ValueError("Missing required OKX data: " + name)
        return {}
    value = items[0]
    if value.get("instId") != SYMBOL:
        raise ValueError("Unexpected instrument for " + name)
    return value


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    alpha = 2 / (period + 1)
    for price in values[period:]:
        value = value + alpha * (price - value)
    return value


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    diffs = [b - a for a, b in zip(values[:-1], values[1:])]
    gain = sum(max(0, delta) for delta in diffs[:period]) / period
    loss = sum(max(0, -delta) for delta in diffs[:period]) / period
    for delta in diffs[period:]:
        gain = (gain * (period - 1) + max(0, delta)) / period
        loss = (loss * (period - 1) + max(0, -delta)) / period
    if loss == 0:
        return 100 if gain > 0 else 50
    return 100 - 100 / (1 + gain / loss)


def atr(bars: list[dict[str, float]], period: int = 14) -> float | None:
    if len(bars) < period + 1:
        return None
    tr = []
    for earlier, current in zip(bars[:-1], bars[1:]):
        tr.append(max(current["h"] - current["l"], abs(current["h"] - earlier["c"]), abs(current["l"] - earlier["c"])))
    value = sum(tr[:period]) / period
    for x in tr[period:]:
        value = (value * (period - 1) + x) / period
    return value


def parse_bars(rows: list[Any], duration_ms: int, now_ms: float) -> list[dict[str, float]]:
    valid: dict[int, dict[str, float]] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 9 or str(row[8]) != "1":
            continue
        ts = numeric(row[0])
        nums = [numeric(x) for x in row[1:5]]
        if ts is None or any(v is None for v in nums):
            continue
        o, h, l, c = nums
        if o <= 0 or c <= 0 or l <= 0 or h < max(o, c, l) or l > min(o, c):
            continue
        if ts + duration_ms > now_ms + 30000:
            continue
        valid[int(ts)] = {"ts": float(ts), "o": o, "h": h, "l": l, "c": c}
    return [valid[x] for x in sorted(valid)]


def calculate_technical(rows: list[Any], timeframe: str, now_ms: float) -> dict[str, Any]:
    duration = TIMEFRAMES[timeframe][1]
    bars = parse_bars(rows, duration, now_ms)
    if len(bars) < 51:
        raise ValueError(f"Insufficient closed {timeframe} bars for EMA50: {len(bars)}")
    closes = [b["c"] for b in bars]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    last = bars[-1]
    trend = "mixed"
    if last["c"] > e20 > e50:
        trend = "up"
    elif last["c"] < e20 < e50:
        trend = "down"
    recent = bars[-20:]
    bb_mid = statistics.fmean(closes[-20:])
    bb_std = statistics.pstdev(closes[-20:])
    return {
        "timeframe": timeframe,
        "ohlc_source": "OKX trade candles, confirmed closes only",
        "bar_timezone": "UTC",
        "bar_count": len(bars),
        "last_closed_bar_open_utc": iso_ms(last["ts"]),
        "last_closed_bar_end_utc": iso_ms(last["ts"] + duration - 1),
        "last_close": round_value(last["c"]),
        "ema20": round_value(e20),
        "ema50": round_value(e50),
        "rsi14": round_value(rsi(closes), 2),
        "atr14": round_value(atr(bars)),
        "bollinger20": {"mid": round_value(bb_mid), "upper": round_value(bb_mid+2*bb_std), "lower": round_value(bb_mid-2*bb_std)},
        "recent20_high": round_value(max(x["h"] for x in recent)),
        "recent20_low": round_value(min(x["l"] for x in recent)),
        "trend": trend,
        "bar_age_minutes": round_value((now_ms - (last["ts"] + duration)) / 60000, 2),
    }


def oi_changes(previous: dict[str, Any] | None, current_usd: float | None, current_ts: float | None, now_ms: float):
    samples = []
    if previous and previous.get("exchange") == "OKX" and previous.get("symbol") == SYMBOL:
        for sample in previous.get("oi_history", []):
            if not isinstance(sample, dict):
                continue
            ts, value = numeric(sample.get("ts_ms")), numeric(sample.get("oi_usd"))
            if ts is not None and value is not None and 0 < value and now_ms-3*86400000 <= ts <= now_ms+120000:
                samples.append({"ts_ms": int(ts), "oi_usd": round_value(value, 2)})
    if current_usd is not None and current_ts is not None and current_usd > 0:
        samples.append({"ts_ms": int(current_ts), "oi_usd": round_value(current_usd, 2)})
    unique = {s["ts_ms"]: s for s in samples}
    samples = [unique[k] for k in sorted(unique)][-900:]
    changes = {}
    for label, period in (("4h", 4*3600000), ("1d", 24*3600000)):
        target = (current_ts - period) if current_ts is not None else None
        reference = min(samples, key=lambda x: abs(x["ts_ms"]-target)) if target is not None and samples else None
        if current_usd is None or reference is None or abs(reference["ts_ms"]-target)>20*60000 or reference["oi_usd"] <= 0:
            changes[label] = None
        else:
            changes[label] = round_value((current_usd/reference["oi_usd"]-1)*100, 3)
    return samples, changes


def build_snapshot(raw: dict[str, Any], previous: dict[str, Any] | None = None,
                   now_ms: float | None = None, max_quote_age_minutes: float = 15) -> dict[str, Any]:
    if now_ms is None:
        now_ms = datetime.now(timezone.utc).timestamp()*1000
    info = first(raw, "instrument", True)
    ticker = first(raw, "ticker", True)
    mark = first(raw, "mark_price", True)
    if info.get("instType") != "SWAP" or info.get("state") != "live":
        raise ValueError("SOXL contract is not a live OKX SWAP")
    if info.get("settleCcy") not in ("USDT", None):
        raise ValueError("Unexpected OKX settlement currency")
    last = numeric(ticker.get("last"))
    mark_price = numeric(mark.get("markPx"))
    if last is None or mark_price is None or last <= 0 or mark_price <= 0:
        raise ValueError("Missing live last/mark price; no publish")
    last_age = elapsed_minutes(now_ms,ticker.get("ts"))
    mark_age = elapsed_minutes(now_ms,mark.get("ts"))
    if last_age is None or mark_age is None or not -2 <= last_age <= max_quote_age_minutes or not -2 <= mark_age <= max_quote_age_minutes:
        raise ValueError(f"OKX last/mark quote stale or invalid: {last_age=}, {mark_age=}")
    technical = {}
    for name in TIMEFRAMES:
        rows = raw.get("candles_"+name)
        if not isinstance(rows, list):
            raise ValueError("Missing confirmed K lines: " + name)
        technical[name] = calculate_technical(rows, name, now_ms)
    warning = list(raw.get("errors", []))
    for name,limit in (("4h",12*60),("1d",48*60)):
        if technical[name]["bar_age_minutes"] > limit:
            warning.append(f"{name} last confirmed candle unexpectedly stale")
    oi = first(raw, "open_interest")
    funding = first(raw, "funding_rate")
    oi_usd = numeric(oi.get("oiUsd"))
    oi_ts = numeric(oi.get("ts"))
    oi_age = elapsed_minutes(now_ms, oi_ts)
    if oi and (oi_age is None or not -2 <= oi_age <= max_quote_age_minutes):
        warning.append("OKX open-interest record is stale")
        oi_usd, oi_ts = None, None
    if not oi:
        warning.append("OKX open interest unavailable")
    if not funding:
        warning.append("OKX funding rate unavailable")
    samples, changes = oi_changes(previous, oi_usd, oi_ts, now_ms)
    bid, ask = numeric(ticker.get("bidPx")), numeric(ticker.get("askPx"))
    spread_bps = 10000*(ask-bid)/((ask+bid)/2) if bid and ask and ask>=bid else None
    rate = numeric(funding.get("fundingRate"))
    return {
        "schema": "uzi.okx.soxl.swap.v1",
        "exchange": "OKX",
        "symbol": SYMBOL,
        "market_type": "USDT-margined equity-linked perpetual SWAP, not Binance futures or SOXL ETF shares",
        "generated_at_utc": datetime.fromtimestamp(now_ms/1000, tz=timezone.utc).isoformat(timespec="seconds"),
        "status": "live_verified_quotes" if last_age is not None and mark_age is not None else "invalid",
        "source": {"api_base": API_BASE, "endpoints": raw.get("endpoints",{}), "api": "OKX public REST V5", "authenticated": False},
        "instrument": {"state": info.get("state"), "settleCcy": info.get("settleCcy"), "ctVal": info.get("ctVal"), "ctValCcy": info.get("ctValCcy")},
        "market": {
            "last_price_usdt": last, "mark_price_usdt": mark_price,
            "bid_usdt": bid, "ask_usdt": ask, "spread_bps": round_value(spread_bps,2),
            "last_quote_time_utc": iso_ms(ticker.get("ts")),
            "mark_quote_time_utc": iso_ms(mark.get("ts")),
            "last_quote_age_minutes": round_value(last_age,2),
            "mark_quote_age_minutes": round_value(mark_age,2),
            "high_24h": numeric(ticker.get("high24h")),
            "low_24h": numeric(ticker.get("low24h")),
            "base_volume_24h": numeric(ticker.get("volCcy24h")),
            "contracts_volume_24h": numeric(ticker.get("vol24h")),
        },
        "derivatives": {
            "oi_contracts": numeric(oi.get("oi")),
            "oi_base_equivalent": numeric(oi.get("oiCcy")),
            "oi_usd": oi_usd,
            "oi_as_of_utc": iso_ms(oi_ts),
            "oi_change_4h_pct": changes["4h"],
            "oi_change_1d_pct": changes["1d"],
            "funding_rate_pct": round_value(rate*100 if rate is not None else None, 6),
            "funding_api_record_utc": iso_ms(funding.get("ts")),
            "funding_time_utc": iso_ms(funding.get("fundingTime")),
            "next_funding_time_utc": iso_ms(funding.get("nextFundingTime")),
        },
        "technical": technical,
        "oi_history": samples,
        "warnings": warning,
        "not_provided": ["Binance SOXLUSDT live price/mark/funding/OI", "US-listed SOXL options chain/max pain", "live US SOXL ETF price"],
        "scope": "Read-only near-real-time OKX public quotes; may lag scheduled GitHub Actions. No trade signals without fresh validation."
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".okx_tmp_", delete=False) as handle:
        tmp = Path(handle.name)
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/OKX-SOXL-USDT-SWAP.json"))
    parser.add_argument("--max-age-minutes", type=float, default=15.0)
    args = parser.parse_args(argv)
    try:
        previous = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else None
        current = fetch_all()
        output = build_snapshot(current, previous=previous, max_quote_age_minutes=args.max_age_minutes)
        atomic_write(args.output, output)
        print(json.dumps({"status": "published", "exchange": output["exchange"], "symbol": output["symbol"], "generated_at_utc": output["generated_at_utc"], "last_age_min": output["market"]["last_quote_age_minutes"], "mark_age_min": output["market"]["mark_quote_age_minutes"], "bars_4h":output["technical"]["4h"]["bar_count"], "bars_1d":output["technical"]["1d"]["bar_count"]}))
        return 0
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status":"unavailable", "exchange":"OKX", "symbol": SYMBOL, "error":str(exc)[:300]}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
