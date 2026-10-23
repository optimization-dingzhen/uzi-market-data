# OKX SOXL-USDT-SWAP live public data relay

This read-only relay uses OKX production public REST V5 endpoints. It is a **different derivative market from Binance SOXLUSDT**. Quotes, funding, OI, mark price and contract mechanics are exchange-specific. Do not label this data as Binance data or calculate an actionable Binance entry from the OKX mark price.

- Source venue: OKX
- Verified instrument: `SOXL-USDT-SWAP` (USDT-margined perpetual, contract must be `live`)
- Public API host for this GitHub-hosted runner: `https://us.okx.com`, in accordance with OKX's US/AU regional documentation
- Production public API; **no key, account, position or trading endpoints**
- GitHub snapshot: `data/OKX-SOXL-USDT-SWAP.json`
- Candle bars: `4H` and `1Dutc` (UTC daily boundary), confirmed only
- Indicators: EMA20, EMA50, RSI14 (Wilder), ATR14, Bollinger20, recent 20-bar high/low
- Other fields: last trade, mark, best bid/ask, spread, 24h high/low, current OI and funding
- OI changes over 4h and 1d are available only after local samples accumulate for those periods; missing stays `null`
- Fetch schedule: GitHub Actions attempts every 5 minutes, but it is **not a realtime stream**, and may be delayed/disabled; readers must re-check quote ages (max 15 min) at the time of every request
- If any required quote is missing, stale, a wrong instrument or an API access restriction applies, publication fails rather than emitting a false live signal.
- Funded accounts, trade secrets, order execution, and user balances are never used.

## ChatGPT Web / UZI SKILL project instruction

Paste this text into your ChatGPT project's instructions to prioritize the new source:

> For a request to analyze SOXLUSDT, first use the connected GitHub app to read `optimization-dingzhen/uzi-market-data` at `data/OKX-SOXL-USDT-SWAP.json`. This is an **OKX** SOXL-USDT-SWAP market snapshot, not Binance data. Verify `exchange`, `symbol`, `status`, last/mark quote times and age against current UTC. If either quote is older than 15 minutes, report it as stale and do not give precise live trade entry signals. Base primary trend on UTC 1d and swing structure on 4h using confirmed candles; show OKX OI/funding with their exchange attribution. If the live JSON is unavailable or stale, read `data/SOXLUSDT-historical.json` as explicitly delayed Binance history only, and do not label its close as current. US stock SOXL, US options max pain, and Binance funding/OI must be verified separately, with missing fields called out.

## On-demand refresh from ChatGPT Web

GitHub scheduled jobs are **best-effort**; this project cannot guarantee a new quote every five minutes. There is also a one-shot push-based trigger supported by `.github/workflows/publish-okx.yml`:

1. Read `data/OKX-SOXL-USDT-SWAP.json` with the connected GitHub app and check current UTC against both quote timestamps.
2. If either quote is older than 15 minutes **and repository write access is authorized**, update `data/refresh-request.txt` with a new `request_utc=<current UTC ISO-8601>` line via GitHub update_file (preserving the current file SHA). This causes the OKX publisher's **push** workflow to run.
3. Check the latest Actions run for the push commit; do not consider it successful until the run finishes with `conclusion=success`.
4. Re-read the JSON and re-check both market quote timestamps against the new current UTC. If still older than 15 minutes, unavailable or provenance is mismatched, fail closed and use delayed Binance history only.

Each request causes a small GitHub commit. This is a *user-initiated near-live refresh*, NOT streaming tick data and not a guarantee of bounded API latency. Never edit broker/OKX accounts or place orders.

To use this without manually opening Codex or GitHub, include this supplemental ChatGPT project instruction:

> When an OKX SOXL-USDT-SWAP GitHub snapshot is stale, use the connected GitHub connector (if authorized to write) to update `data/refresh-request.txt` with a new UTC timestamp, monitor the resulting `Publish verified OKX SOXL-USDT-SWAP public snapshot` run, and read the new `data/OKX-SOXL-USDT-SWAP.json` only after the action succeeds. Validate fresh last/mark timestamps again; if unavailable, declare stale and fall back to delayed Binance history. Do not claim that writing the refresh request itself made quotes fresh.

## Endpoint catalog

- `/api/v5/public/instruments?instType=SWAP&instId=SOXL-USDT-SWAP`
- `/api/v5/market/ticker?instId=SOXL-USDT-SWAP`
- `/api/v5/public/mark-price?instType=SWAP&instId=SOXL-USDT-SWAP`
- `/api/v5/public/open-interest?instType=SWAP&instId=SOXL-USDT-SWAP`
- `/api/v5/public/funding-rate?instId=SOXL-USDT-SWAP`
- `/api/v5/market/candles?instId=SOXL-USDT-SWAP&bar=4H&limit=120`
- `/api/v5/market/candles?instId=SOXL-USDT-SWAP&bar=1Dutc&limit=120`

OKX exchange announcement: https://www.okx.com/en-us/help/okx-to-list-perpetual-futures-for-soxl-nbis-qcom-and-csco-equities
OKX API guide: https://www.okx.com/docs-v5/en/

Only use the API when authorized for the jurisdiction of the executing environment and consistent with OKX data licensing/terms. Do not reroute requests around an explicit region-based service restriction.
