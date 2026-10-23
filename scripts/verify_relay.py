#!/usr/bin/env python3
"""Offline freshness validator for a GitHub-published UZI read-only snapshot."""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None
    except ValueError:
        return None


def verify(payload: dict[str, Any], now: datetime | None = None, max_age_minutes: float = 15.0) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    errors: list[str] = []
    warnings: list[str] = []
    if payload.get("schema") != "uzi-market-relay/v1":
        errors.append("unknown_schema")
    if payload.get("symbol") != "SOXLUSDT":
        errors.append("wrong_symbol")
    if payload.get("source_host") != "fapi.binance.com":
        errors.append("unverified_source_host")
    if payload.get("realtime_at_publication") is not True:
        errors.append("publication_not_verified_fresh")
    timestamps = payload.get("required_quote_times")
    if not isinstance(timestamps, dict):
        timestamps = {}
    ages: dict[str, float | None] = {}
    for name in ("last_price_utc", "mark_price_utc"):
        dt = parse_utc(timestamps.get(name))
        age = (now - dt).total_seconds()/60 if dt else None
        ages[name] = round(age, 3) if age is not None else None
        if age is None or age < -2 or age > max_age_minutes:
            errors.append(name + "_missing_or_stale")
    gen_at = parse_utc(payload.get("generated_at_utc"))
    generation_age_minutes = (now - gen_at).total_seconds()/60 if gen_at is not None else None
    if generation_age_minutes is None or generation_age_minutes < -2 or generation_age_minutes > max_age_minutes:
        errors.append("publication_missing_or_stale")
    analysis = payload.get("analysis") or {}
    market = analysis.get("market") or {}
    for key in ("last_price", "mark_price"):
        value = market.get(key)
        if isinstance(value, bool):
            errors.append(key + "_invalid")
            continue
        try:
            v = float(value)
        except (ValueError, TypeError):
            v = 0
        if not math.isfinite(v) or v <= 0:
            errors.append(key + "_invalid")
    tech = analysis.get("technical") or {}
    for tf, duration_min in (("1d", 1440), ("4h", 240)):
        rec = tech.get(tf) or {}
        if rec.get("status") != "ok":
            warnings.append(tf + "_unverified_or_incomplete")
        close = parse_utc(rec.get("last_closed_candle_close_time_utc"))
        candle_age = (now - close).total_seconds()/60 if close else None
        if candle_age is None or candle_age < -2 or candle_age > duration_min + 30:
            warnings.append(tf + "_candle_stale")
    if payload.get("status_at_publication") != "complete":
        warnings.append("publication_partial")
    ready = not errors and not warnings
    return {
        "status": "fresh_ready" if ready else ("invalid_or_stale" if errors else "fresh_but_incomplete"),
        "usable_for_current_1d_4h_analysis": ready,
        "symbol": payload.get("symbol"),
        "now_utc": now.isoformat(timespec="seconds"),
        "quote_age_minutes": ages,
        "publication_age_minutes": round(generation_age_minutes, 3) if generation_age_minutes is not None else None,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    args = parser.parse_args()
    try:
        content = args.file.read_text(encoding="utf-8")
        if len(content) > 1_000_000:
            raise ValueError("File too large")
        payload = json.loads(content)
        if not isinstance(payload, dict):
            raise ValueError("Expected object")
        result = verify(payload)
    except (OSError, ValueError) as exc:
        result = {"status": "invalid_file", "usable_for_current_1d_4h_analysis": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["usable_for_current_1d_4h_analysis"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
