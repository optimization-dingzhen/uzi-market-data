#!/usr/bin/env python3
"""Read-only UZI-style Binance USD-M perpetual diagnostics.

Uses only public, unsigned Binance endpoints and Python stdlib.
Network may be unavailable inside some ChatGPT runtimes; use --snapshot then.
Output is quantitative evidence, NOT the upstream UZI 66-person panel.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import socket
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = "https://fapi.binance.com"
# Strategic defaults: daily trend first; four-hour swing confirmation second.
# Shorter bars are opt-in only and must not override the 1d/4h direction.
PRIMARY_INTERVALS = ("1d", "4h")
OPTIONAL_INTERVALS = ("1h", "15m")
INTERVAL_DURATION_MS = {"1d": 86_400_000, "4h": 14_400_000, "1h": 3_600_000, "15m": 900_000}


def number(x: Any) -> float | None:
    try:
        if x is None or x == "":
            return None
        v = float(x)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def round_maybe(x: float | None, n: int = 5) -> float | None:
    return round(x, n) if x is not None and math.isfinite(x) else None


def percent_diff(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return (a - b) / b * 100


def _iso_ms(timestamp_ms: Any) -> str | None:
    n = number(timestamp_ms)
    if n is None:
        return None
    try:
        return datetime.fromtimestamp(n / 1000, tz=timezone.utc).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return None


def _get_json(route: str, params: dict[str, str | int]) -> Any:
    query = urllib.parse.urlencode(params)
    url = BASE + route + ("?" + query if query else "")
    req = urllib.request.Request(url, headers={"User-Agent": "UZI-Contract-Analyst/1.0"})
    with urllib.request.urlopen(req, timeout=7) as resp:
        data = resp.read(3_000_000)
    result = json.loads(data.decode("utf-8"))
    if isinstance(result, dict) and isinstance(result.get("code"), int) and result["code"] < 0:
        raise ValueError(f"Binance API error {result.get('code')}: {result.get('msg')}")
    return result


def diagnose_connectivity() -> dict[str, Any]:
    """Differentiate local DNS failure from Binance API denial without leaking IPs.

    This is a diagnostic, not a way around geo restrictions or network policy.
    """
    exchange_host = urllib.parse.urlsplit(BASE).hostname or "fapi.binance.com"
    control_host = "example.com"
    dns: dict[str, str] = {}
    for host in (exchange_host, control_host):
        try:
            socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            dns[host] = "resolved"
        except OSError as exc:
            dns[host] = f"failed ({type(exc).__name__})"

    out: dict[str, Any] = {"exchange": "Binance USD-M", "api_base": BASE, "dns": dns}
    if dns[exchange_host] != "resolved":
        if dns[control_host] != "resolved":
            out.update({
                "status": "environment_dns_unavailable",
                "action": "此运行环境无法解析币安与普通网站域名；切换联网执行环境或可信网页取数，不要伪称实时行情。",
            })
        else:
            out.update({
                "status": "binance_dns_unavailable",
                "action": "普通域名可解析，但币安域名不可解析；检查 DNS/网络策略或改用可信行情数据源。",
            })
        return out

    try:
        result = _get_json("/fapi/v1/time", {})
        server_time = _iso_ms(result.get("serverTime")) if isinstance(result, dict) else None
        if server_time is None:
            out.update({"status": "unexpected_response", "action": "返回内容不是币安标准服务器时间 JSON，请检查出口或代理。"})
        else:
            out.update({"status": "ok", "server_time_utc": server_time, "action": "API 连接正常；仍需查询实际交易对确认行情。"})
    except urllib.error.HTTPError as exc:
        label = {451: "restricted_location", 403: "access_forbidden", 418: "ip_banned", 429: "rate_limited"}.get(exc.code, "http_error")
        out.update({
            "status": label,
            "http_status": exc.code,
            "action": "币安拒绝了该网络出口的请求；应遵守其地区、权限和频率限制，不应绕过限制。" if label != "http_error" else "检查币安 HTTP 状态与维护公告。",
        })
    except (urllib.error.URLError, OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        out.update({
            "status": "connection_error",
            "error_type": type(exc).__name__,
            "action": "DNS 已解析但 HTTP 请求失败；检查执行环境防火墙、代理、TLS 或网络策略。",
        })
    return out


def fetch_snapshot(symbol: str, include_short_term: bool = False) -> dict[str, Any]:
    """Fetch public Binance Futures data; optional failures remain explicitly missing."""
    snap: dict[str, Any] = {
        "symbol": symbol,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_source": "Binance USD-M Futures public REST API (fapi.binance.com)",
        "endpoints": {},
        "errors": [],
        "klines": {},
        "primary_timeframes": list(PRIMARY_INTERVALS),
        "optional_short_term_requested": include_short_term,
    }
    requests: list[tuple[str, str, dict[str, str | int], bool]] = [
        ("ticker_24h", "/fapi/v1/ticker/24hr", {"symbol": symbol}, True),
        ("premium_index", "/fapi/v1/premiumIndex", {"symbol": symbol}, True),
        ("open_interest", "/fapi/v1/openInterest", {"symbol": symbol}, False),
        ("book_ticker", "/fapi/v1/ticker/bookTicker", {"symbol": symbol}, False),
        ("open_interest_hist_4h", "/futures/data/openInterestHist", {"symbol": symbol, "period": "4h", "limit": 3}, False),
        ("open_interest_hist_1d", "/futures/data/openInterestHist", {"symbol": symbol, "period": "1d", "limit": 3}, False),
        ("funding_history", "/fapi/v1/fundingRate", {"symbol": symbol, "limit": 8}, False),
    ]
    for key, route, args, required in requests:
        try:
            snap[key] = _get_json(route, args)
            snap["endpoints"][key] = BASE + route
        except Exception as exc:
            snap["errors"].append(f"{key}: {type(exc).__name__}: {exc}")
            if required:
                raise RuntimeError("无法获取必要行情数据；不输出实时结论。" + " | ".join(snap["errors"])) from exc
    for interval in PRIMARY_INTERVALS + (OPTIONAL_INTERVALS if include_short_term else ()):
        try:
            snap["klines"][interval] = _get_json("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": 150})
            snap["endpoints"]["klines_" + interval] = BASE + "/fapi/v1/klines"
        except Exception as exc:
            snap["errors"].append(f"klines_{interval}: {type(exc).__name__}: {exc}")
    for interval in PRIMARY_INTERVALS:
        if not snap["klines"].get(interval):
            snap["errors"].append(f"缺少关键 {interval} K 线：不能完整判断日线和四小时趋势。")
    return snap


def ema(values: list[float], n: int) -> float | None:
    if len(values) < n:
        return None
    current = sum(values[:n]) / n
    alpha = 2 / (n + 1)
    for x in values[n:]:
        current = alpha * x + (1 - alpha) * current
    return current


def rsi(values: list[float], n: int = 14) -> float | None:
    if len(values) < n + 1:
        return None
    delta = [b - a for a, b in zip(values[:-1], values[1:])]
    gain = sum(max(d, 0) for d in delta[:n]) / n
    loss = sum(max(-d, 0) for d in delta[:n]) / n
    for d in delta[n:]:
        gain = (gain * (n - 1) + max(d, 0)) / n
        loss = (loss * (n - 1) + max(-d, 0)) / n
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100 - 100 / (1 + gain / loss)


def atr(candles: list[dict[str, float]], n: int = 14) -> float | None:
    if len(candles) < n + 1:
        return None
    trs = []
    for prev, curr in zip(candles[:-1], candles[1:]):
        trs.append(max(curr["high"] - curr["low"], abs(curr["high"] - prev["close"]), abs(curr["low"] - prev["close"])))
    v = sum(trs[:n]) / n
    for tr in trs[n:]:
        v = (v * (n - 1) + tr) / n
    return v


def parse_candles(raw: Any) -> list[dict[str, float]]:
    if not isinstance(raw, list):
        return []
    out = []
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    for row in raw:
        if not isinstance(row, list) or len(row) < 6:
            continue
        # Binance's final candle is often still forming. Use only confirmed closes.
        if len(row) >= 7 and number(row[6]) is not None and float(row[6]) > now_ms:
            continue
        vals = [number(row[i]) for i in (1, 2, 3, 4, 5)]
        if any(x is None for x in vals):
            continue
        op, hi, lo, cl, vol = vals
        if lo <= 0 or hi < max(lo, op, cl) or lo > min(op, cl) or vol < 0:
            continue
        out.append({"open": op, "high": hi, "low": lo, "close": cl, "volume": vol, "time_ms": row[0]})
    return out


def indicators(raw: Any, interval: str) -> dict[str, Any]:
    bars = parse_candles(raw)
    if not bars:
        return {"status": "unavailable", "bars": 0}
    closes = [x["close"] for x in bars]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    value_rsi = rsi(closes)
    value_atr = atr(bars)
    bb = None
    if len(closes) >= 20:
        tail = closes[-20:]
        mean = statistics.fmean(tail)
        sd = statistics.pstdev(tail)
        bb = {"lower": round_maybe(mean - 2 * sd), "mid": round_maybe(mean), "upper": round_maybe(mean + 2 * sd)}
    hi = max(x["high"] for x in bars[-20:])
    lo = min(x["low"] for x in bars[-20:])
    trend = "insufficient_data"
    if e20 is not None and e50 is not None:
        if closes[-1] > e20 > e50:
            trend = "up"
        elif closes[-1] < e20 < e50:
            trend = "down"
        else:
            trend = "mixed"
    # K-line freshness is assessed separately from quote freshness. A live
    # lastPrice cannot make days-old 1d/4h chart analysis current.
    duration = INTERVAL_DURATION_MS.get(interval)
    last_open_ms = number(bars[-1]["time_ms"])
    last_close_ms = last_open_ms + duration - 1 if last_open_ms is not None and duration else None
    last_closed_age_hours = (datetime.now(timezone.utc).timestamp() * 1000 - last_close_ms) / 3_600_000 if last_close_ms is not None else None
    status = "ok" if len(bars) >= 50 else "limited_history"
    if last_closed_age_hours is None or last_closed_age_hours < -0.1 or (duration is not None and last_closed_age_hours > duration / 3_600_000 + 0.5):
        status = "stale"
    result: dict[str, Any] = {
        "status": status,
        "bars": len(bars),
        "last_closed_candle_open_time_utc": _iso_ms(bars[-1]["time_ms"]),
        "last_closed_candle_close_time_utc": _iso_ms(last_close_ms),
        "last_closed_candle_age_hours": round_maybe(last_closed_age_hours, 3),
        "last_candle_close": round_maybe(closes[-1]),
        "ema20": round_maybe(e20),
        "ema50": round_maybe(e50),
        "rsi14": round_maybe(value_rsi, 2),
        "atr14": round_maybe(value_atr),
        "bollinger20": bb,
        "recent_20_bar_high": round_maybe(hi),
        "recent_20_bar_low": round_maybe(lo),
        "trend": trend,
    }
    if interval == "15m" and len(bars) >= 2:
        # Rolling, 24-hour crypto/futures VWAP; NOT US equities session VWAP.
        tail = bars[-96:]
        den = sum(x["volume"] for x in tail)
        vwap = sum(((x["high"] + x["low"] + x["close"]) / 3) * x["volume"] for x in tail) / den if den else None
        result["rolling_24h_vwap_proxy"] = round_maybe(vwap)
    return result



def _oi_recent_change(history: Any) -> tuple[float | None, str | None]:
    """Use only the two most recent timestamped rows of a *known* period."""
    valid: list[tuple[float, float]] = []
    if isinstance(history, list):
        for item in history:
            if not isinstance(item, dict):
                continue
            ts = number(item.get("timestamp"))
            amount = number(item.get("sumOpenInterest"))
            if ts is not None and amount is not None:
                valid.append((ts, amount))
    valid.sort()
    change = percent_diff(valid[-1][1], valid[-2][1]) if len(valid) >= 2 else None
    at = _iso_ms(valid[-1][0]) if valid else None
    return round_maybe(change, 3), at


def _higher_timeframe_context(technical: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Daily leads; four-hour confirms or reveals a countertrend swing."""
    d1 = technical["1d"]
    h4 = technical["4h"]
    safe = d1.get("status") == "ok" and h4.get("status") == "ok"
    dt, ht = d1.get("trend"), h4.get("trend")
    table = {
        ("up", "up"): ("aligned_up", "日线和4小时趋势均偏强；仍需价格确认突破"),
        ("down", "down"): ("aligned_down", "日线和4小时趋势均偏弱；仍需价格确认失守"),
        ("up", "down"): ("daily_up_four_hour_pullback", "日线偏强但4小时回调，不把回调自动判为大级别反转"),
        ("down", "up"): ("daily_down_four_hour_rebound", "日线偏弱但4小时反弹，不把反弹自动判为大级别反转"),
    }
    label, explanation = table.get((dt, ht), ("mixed", "至少一个周期方向不明确，等待收盘确认")) if safe else (
        "insufficient_verified_klines", "缺少足够且及时的已收盘日线/4小时K线，不给当前方向判断"
    )
    return {
        "primary_timeframes": ["1d", "4h"],
        "daily_role": "primary_trend",
        "four_hour_role": "swing_confirmation",
        "daily_trend": dt if safe else None,
        "four_hour_trend": ht if safe else None,
        "alignment": label,
        "explanation": explanation,
        "requires_breakout_breakdown_confirmation": True,
    }


def analyze(snap: dict[str, Any], requested_symbol: str = "SOXLUSDT", stale_threshold_minutes: int = 15, include_short_term: bool = False) -> dict[str, Any]:
    symbol = str(snap.get("symbol", requested_symbol)).upper()
    if symbol != requested_symbol:
        raise ValueError(f"快照币对 {symbol} 与请求 {requested_symbol} 不一致")
    t = snap.get("ticker_24h") or {}
    p = snap.get("premium_index") or {}
    o = snap.get("open_interest") or {}
    b = snap.get("book_ticker") or {}
    for key, source in (("ticker_24h", t), ("premium_index", p), ("open_interest", o)):
        if isinstance(source, dict) and source.get("symbol") and source.get("symbol") != symbol:
            raise ValueError(f"{key} 的币对错误，不允许拼接不同交易对")
    ticker_price = number(t.get("lastPrice"))
    mark_price = number(p.get("markPrice"))
    index_price = number(p.get("indexPrice"))
    if ticker_price is None and mark_price is None:
        raise ValueError("缺少当前价格，禁止生成交易判断")
    # Validate *both* source timestamps: a fresh mark alone does not make a stale
    # last-trade/24h ticker live (or vice versa).
    current_ms = datetime.now(timezone.utc).timestamp() * 1000
    ticker_ms = number(t.get("closeTime"))
    mark_ms = number(p.get("time"))
    source_ms = min(ts for ts in (ticker_ms, mark_ms) if ts is not None) if (ticker_ms is not None or mark_ms is not None) else None
    age_minutes = ((current_ms - source_ms) / 60000) if source_ms is not None else None
    quote_age = ((current_ms - ticker_ms) / 60000) if ticker_ms is not None else None
    mark_age = ((current_ms - mark_ms) / 60000) if mark_ms is not None else None
    essential_ages = (quote_age, mark_age)
    realtime_verified = all(age is not None and -2 <= age <= stale_threshold_minutes for age in essential_ages)
    warnings = list(snap.get("errors") or [])
    if quote_age is None or mark_age is None:
        warnings.append("必要行情源的时间戳不完整；不能确认行情实时性")
    if any(age is not None and age < -2 for age in essential_ages):
        warnings.append("交易所时间戳在本地未来超过 2 分钟，请校准时钟")
    if any(age is not None and age > stale_threshold_minutes for age in essential_ages):
        warnings.append(f"必要行情源至少有一个滞后超过 {stale_threshold_minutes} 分钟，不应当作实时信号")
    last_funding = number(p.get("lastFundingRate"))
    oi_units = number(o.get("openInterest"))
    mark_basis = percent_diff(mark_price, index_price)
    best_bid = number(b.get("bidPrice"))
    best_ask = number(b.get("askPrice"))
    spread_bps = ((best_ask - best_bid) / ((best_bid + best_ask) / 2) * 10000) if best_bid and best_ask and best_ask >= best_bid else None

    oi_4h_pct, oi_4h_time = _oi_recent_change(snap.get("open_interest_hist_4h"))
    oi_1d_pct, oi_1d_time = _oi_recent_change(snap.get("open_interest_hist_1d"))
    # A legacy snapshot may contain 1h or unknown-period OI history.
    # Never label that movement "4h" without verified period metadata.
    legacy_oi_pct, legacy_oi_time = _oi_recent_change(snap.get("open_interest_hist"))

    funding_hist = snap.get("funding_history") or []
    regular_funding = []
    special_funding = 0
    if isinstance(funding_hist, list):
        for item in funding_hist:
            if not isinstance(item, dict):
                continue
            if item.get("rateType") == "Special":
                special_funding += 1
            elif item.get("rateType") in ("Regular", None):
                r = number(item.get("fundingRate"))
                if r is not None:
                    regular_funding.append(r * 100)
    if special_funding:
        warnings.append("历史费率含 Special 特别费用（如股息调整）；不要混进常规 funding 均值")

    active_intervals = PRIMARY_INTERVALS + (OPTIONAL_INTERVALS if include_short_term else ())
    technical = {interval: indicators((snap.get("klines") or {}).get(interval), interval) for interval in active_intervals}
    higher = _higher_timeframe_context(technical)
    if higher["alignment"] == "insufficient_verified_klines":
        warnings.append("日线/4小时已收盘K线不足或过期，不能给当前技术方向结论")
    if all(value.get("status") == "unavailable" for value in technical.values()):
        warnings.append("无可用 K 线；不能计算 EMA/RSI/ATR、支撑阻力")

    return {
        "product": "Binance USD-M perpetual (not SOXL ETF shares)",
        "symbol": symbol,
        "snapshot_fetched_utc": snap.get("fetched_at_utc"),
        "market_time_utc": _iso_ms(source_ms),
        "market_data_age_minutes": round_maybe(age_minutes, 2),
        "required_quote_times": {
            "last_price_utc": _iso_ms(ticker_ms),
            "mark_price_utc": _iso_ms(mark_ms),
            "last_price_age_minutes": round_maybe(quote_age, 2),
            "mark_price_age_minutes": round_maybe(mark_age, 2),
        },
        "realtime_verified": realtime_verified,
        "market": {
            "last_price": round_maybe(ticker_price),
            "mark_price": round_maybe(mark_price),
            "index_price": round_maybe(index_price),
            "mark_minus_index_pct": round_maybe(mark_basis, 4),
            "change_24h_pct": round_maybe(number(t.get("priceChangePercent")), 3),
            "high_24h": round_maybe(number(t.get("highPrice"))),
            "low_24h": round_maybe(number(t.get("lowPrice"))),
            "quote_volume_24h_usdt": round_maybe(number(t.get("quoteVolume")), 2),
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_bps": round_maybe(spread_bps, 2),
        },
        "derivatives": {
            "latest_funding_rate_pct": round_maybe(last_funding * 100 if last_funding is not None else None, 6),
            "next_funding_utc": _iso_ms(p.get("nextFundingTime")),
            "oi_contract_units": round_maybe(oi_units, 3),
            "oi_notional_usdt_approx": round_maybe(oi_units * mark_price, 2) if oi_units is not None and mark_price is not None else None,
            "oi_change_4h_pct": oi_4h_pct,
            "oi_4h_last_time_utc": oi_4h_time,
            "oi_change_1d_pct": oi_1d_pct,
            "oi_1d_last_time_utc": oi_1d_time,
            "legacy_oi_change_pct_unlabeled_period": legacy_oi_pct,
            "legacy_oi_last_time_utc": legacy_oi_time,
            "regular_funding_history_pct": [round(v, 6) for v in regular_funding],
            "special_funding_history_records": special_funding,
        },
        "technical": technical,
        "higher_timeframe_context": higher,
        "short_term_included": include_short_term,
        "evidence": {
            "data_source": snap.get("data_source", "user-provided JSON snapshot"),
            "endpoints": snap.get("endpoints", {}),
        },
        "warnings": warnings,
        "not_provided": [
            "SOXL ETF equity-market bid/ask and US market hours",
            "US SOXL listed-options chain / verified expiry-specific Max Pain",
            "cross-market basis adjusted for currency, market-hour and product terms",
        ],
        "scope": "read-only diagnostics; no backtest, no win probability, no order placement",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="SOXLUSDT", help="Binance USD-M perpetual symbol")
    parser.add_argument("--snapshot", type=Path, help="Raw Binance public API snapshot JSON (offline mode)")
    parser.add_argument("--output", type=Path, help="Write JSON report to file")
    parser.add_argument("--max-age-minutes", type=int, default=15)
    parser.add_argument("--include-short-term", action="store_true", help="可选：额外抓取1h/15m辅助入场，不改变1d/4h主判断")
    parser.add_argument("--diagnose", action="store_true", help="检查容器 DNS 和 Binance 公开 API 连通性，不需要交易账户")
    args = parser.parse_args(argv)
    symbol = args.symbol.upper()
    if not re.fullmatch(r"[A-Z0-9]{3,30}", symbol):
        parser.error("交易对格式无效")
    if args.diagnose:
        check = diagnose_connectivity()
        print(json.dumps(check, ensure_ascii=False, indent=2))
        return 0 if check["status"] == "ok" else 2
    try:
        snap = json.loads(args.snapshot.read_text(encoding="utf-8")) if args.snapshot else fetch_snapshot(symbol, include_short_term=args.include_short_term)
        report = analyze(snap, requested_symbol=symbol, stale_threshold_minutes=args.max_age_minutes, include_short_term=args.include_short_term)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        diagnostic = diagnose_connectivity() if not args.snapshot else None
        message: dict[str, Any] = {
            "status": "unavailable", "symbol": symbol, "error": str(exc),
            "hint": "无法获取行情时，使用可信实时网页并标注时间；或用 --snapshot 输入经核验的原始币安 JSON。",
        }
        if diagnostic is not None:
            message["connectivity"] = diagnostic
        print(json.dumps(message, ensure_ascii=False), file=sys.stderr)
        return 2
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
