#!/usr/bin/env python3
"""Publish a compact, read-only Binance USD-M market snapshot for GitHub connector.

No Binance keys, no trading endpoints, no open proxy, stdlib only.
Run from an environment legitimately permitted to access Binance Futures data.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from analyze_futures import analyze, fetch_snapshot

SCHEMA = "uzi-market-relay/v1"


def make_publication(snapshot: dict[str, Any], symbol: str) -> dict[str, Any]:
    """Derive a small report from an already-fetched official API snapshot."""
    if snapshot.get("data_source") != "Binance USD-M Futures public REST API (fapi.binance.com)":
        raise ValueError("Only direct Binance public REST snapshots may be published as official live data")
    report = analyze(snapshot, requested_symbol=symbol, stale_threshold_minutes=15)
    if not report["realtime_verified"]:
        raise ValueError("Required ticker/mark timestamps missing or stale: refusing to publish")
    if report["market"]["last_price"] is None or report["market"]["mark_price"] is None:
        raise ValueError("Missing latest traded/mark prices: refusing to publish")
    candles = report["technical"]
    readiness = all(candles.get(tf, {}).get("status") == "ok" for tf in ("1d", "4h"))
    warnings = list(report.get("warnings", []))
    if not readiness:
        warnings.append("核心1d或4h周期K线不足/过期；不得输出当前趋势判断")

    return {
        "schema": SCHEMA,
        "symbol": symbol,
        "source": "Binance USD-M Futures public REST API (read-only)",
        "source_host": "fapi.binance.com",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "upstream_market_time_utc": report["market_time_utc"],
        "required_quote_times": report["required_quote_times"],
        "status_at_publication": "complete" if readiness else "partial",
        "realtime_at_publication": report["realtime_verified"],
        "analysis": {
            "product": report["product"],
            "market": report["market"],
            "derivatives": report["derivatives"],
            "technical": {tf: candles.get(tf, {"status": "unavailable"}) for tf in ("1d", "4h")},
            "higher_timeframe_context": report["higher_timeframe_context"],
            "warnings": warnings,
        },
        "available_fields": ["1d", "4h", "funding", "OI", "mark", "last", "24h_ticker"],
        "not_included": ["account_keys", "orders", "trades", "SOXL listed-options chain", "Max Pain"],
        "freshness_rule": "Recalculate age when reading: time now UTC minus BOTH Binance ticker and mark timestamps; reject when either >15m or missing. Also inspect 1d/4h candle status.",
    }


def atomic_save(path: Path, content: dict[str, Any]) -> None:
    """Write atomically so readers never see half a JSON snapshot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), prefix=".tmp-", suffix=".json", delete=False) as handle:
            tmp = Path(handle.name)
            json.dump(content, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="SOXLUSDT", help="Only a fixed, allowlisted market symbol")
    parser.add_argument("--output", type=Path, default=Path("data/SOXLUSDT.json"))
    args = parser.parse_args(argv)
    symbol = args.symbol.upper()
    if not re.fullmatch(r"[A-Z0-9]{3,30}", symbol):
        parser.error("Invalid market symbol")
    if symbol != "SOXLUSDT":
        parser.error("This deployment is intentionally restricted to SOXLUSDT; audit before extending")
    try:
        raw = fetch_snapshot(symbol)
        publication = make_publication(raw, symbol)
        atomic_save(args.output, publication)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "unavailable", "symbol": symbol,
                          "error_type": type(exc).__name__, "message": str(exc)[:600],
                          "action": "No fake/live snapshot was published; check upstream API and regional eligibility."}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"status": publication["status_at_publication"],
                      "symbol": symbol, "output": str(args.output),
                      "generated_at_utc": publication["generated_at_utc"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
