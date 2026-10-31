#!/usr/bin/env python3
"""Read-time freshness and provenance gate for OKX SOXL-USDT-SWAP snapshots.

The freshness fields stored at publication are historical diagnostics; readers
must recompute age from the actual exchange timestamps at the time of access.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_SCHEMA = "uzi.okx.soxl.swap.v1"
EXPECTED_SYMBOL = "SOXL-USDT-SWAP"
EXPECTED_SOURCE = "https://us.okx.com"


def parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return timestamp.astimezone(timezone.utc) if timestamp.tzinfo is not None else None


def age_minutes(value: Any, now: datetime) -> float | None:
    timestamp = parse_utc(value)
    return (now - timestamp).total_seconds() / 60 if timestamp is not None else None


def positive(value: Any) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (float, int))
            and math.isfinite(value) and value > 0)


def verify(payload: dict[str, Any], now: datetime | None = None,
           max_age_minutes: float = 15.0) -> dict[str, Any]:
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    if not math.isfinite(max_age_minutes) or max_age_minutes <= 0:
        raise ValueError("max_age_minutes must be positive")
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(payload, dict):
        raise ValueError("Expected an object")
    if payload.get("schema") != EXPECTED_SCHEMA:
        errors.append("unknown_schema")
    if payload.get("exchange") != "OKX" or payload.get("symbol") != EXPECTED_SYMBOL:
        errors.append("wrong_exchange_or_symbol")
    if payload.get("status") != "live_verified_quotes":
        errors.append("unverified_publication")
    source = payload.get("source")
    if not isinstance(source, dict) or source.get("api_base") != EXPECTED_SOURCE or source.get("authenticated") is not False:
        errors.append("unverified_okx_source")
    if payload.get("instrument", {}).get("state") != "live":
        errors.append("instrument_not_live")

    ages: dict[str, float | None] = {}
    generated = age_minutes(payload.get("generated_at_utc"), now)
    ages["generated_at_utc"] = generated
    if generated is None or not -2 <= generated <= max_age_minutes:
        errors.append("generation_missing_future_or_stale")
    market = payload.get("market")
    if not isinstance(market, dict):
        market = {}
    for name, time_key, price_key in (
        ("last", "last_quote_time_utc", "last_price_usdt"),
        ("mark", "mark_quote_time_utc", "mark_price_usdt"),
    ):
        age = age_minutes(market.get(time_key), now)
        ages[name] = age
        if age is None or not -2 <= age <= max_age_minutes:
            errors.append(name + "_quote_missing_future_or_stale")
        if not positive(market.get(price_key)):
            errors.append(name + "_price_invalid")

    technical = payload.get("technical")
    if not isinstance(technical, dict):
        technical = {}
    candle_ages: dict[str, float | None] = {}
    for timeframe, maximum_minutes in (("1d", 1440 + 45), ("4h", 240 + 45)):
        item = technical.get(timeframe)
        if not isinstance(item, dict):
            item = {}
        age = age_minutes(item.get("last_closed_bar_end_utc"), now)
        candle_ages[timeframe] = age
        if item.get("timeframe") != timeframe or item.get("ohlc_source") != "OKX trade candles, confirmed closes only":
            errors.append(timeframe + "_source_or_timeframe_invalid")
        if age is None or not -2 <= age <= maximum_minutes:
            errors.append(timeframe + "_closed_candle_missing_future_or_stale")
        count = item.get("bar_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 51:
            errors.append(timeframe + "_insufficient_bars")
        for key in ("last_close", "ema20", "ema50", "atr14"):
            if not positive(item.get(key)):
                errors.append(timeframe + "_" + key + "_invalid")
        rsi = item.get("rsi14")
        if isinstance(rsi, bool) or not isinstance(rsi, (float, int)) or not math.isfinite(rsi) or not 0 <= rsi <= 100:
            errors.append(timeframe + "_rsi14_invalid")
        bands = item.get("bollinger20")
        if not isinstance(bands, dict) or not all(positive(bands.get(k)) for k in ("upper", "mid", "lower")) or not bands["upper"] >= bands["mid"] >= bands["lower"]:
            errors.append(timeframe + "_bollinger20_invalid")

    derivatives = payload.get("derivatives")
    if not isinstance(derivatives, dict):
        derivatives = {}
    oi_age = age_minutes(derivatives.get("oi_as_of_utc"), now)
    ages["oi"] = oi_age
    if oi_age is None or not -2 <= oi_age <= max_age_minutes or not positive(derivatives.get("oi_usd")):
        warnings.append("okx_oi_missing_or_stale")
    for name in ("oi_change_4h_pct", "oi_change_1d_pct"):
        value = derivatives.get(name)
        if value is None:
            warnings.append(name + "_unavailable")
        elif isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            warnings.append(name + "_invalid")
    if derivatives.get("funding_rate_pct") is None:
        warnings.append("okx_funding_unavailable")
    usable = not errors
    return {
        "status": "stale_or_invalid" if errors else ("fresh_with_warnings" if warnings else "fresh_ready"),
        "usable_for_current_1d_4h_analysis": usable,
        "exchange": payload.get("exchange"),
        "symbol": payload.get("symbol"),
        "now_utc": now.isoformat(timespec="seconds"),
        "max_quote_age_minutes": max_age_minutes,
        "age_minutes": {k: round(v, 3) if v is not None else None for k, v in ages.items()},
        "closed_candle_age_minutes": {k: round(v, 3) if v is not None else None for k, v in candle_ages.items()},
        "analysis_order": ["1d", "4h"],
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--max-age-minutes", type=float, default=15.0)
    args = parser.parse_args()
    try:
        raw = args.file.read_text(encoding="utf-8")
        if len(raw) > 1_000_000:
            raise ValueError("Snapshot is too large")
        result = verify(json.loads(raw), max_age_minutes=args.max_age_minutes)
    except (OSError, ValueError, TypeError) as exc:
        result = {"status": "invalid_file", "usable_for_current_1d_4h_analysis": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["usable_for_current_1d_4h_analysis"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
