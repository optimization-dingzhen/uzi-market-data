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


## Read-time verification (2026-10-31)

Before using an OKX snapshot for analysis, validate at the **current UTC**:
\`python scripts/verify_okx.py --file data/OKX-SOXL-USDT-SWAP.json\`.
Exit code 0 means OKX quote/mark provenance, snapshot generation time, and
confirmed 1d/4h candle recency passed. Exit code 2 means **not usable as a
current market signal**. Published \`last_quote_age_minutes\` values are not
read-time ages, and \`status: live_verified_quotes\` is not perpetual freshness.

In ChatGPT, re-read the file after any refresh. The exact exchange timestamps
must all pass the 15-minute quote/generation checks at the moment of analysis.
Analysis order: **1d trend first, then 4h structure and overbought/oversold
conditions**. Use EMA20/EMA50, RSI14, Bollinger bands and ATR; do not infer a
Binance price, mark, OI, or funding rate from OKX. Missing OKX OI 4h/1d changes
must remain \`null\` with explanation, not interpolation presented as truth.

The on-demand path is:
1. Read and reject stale snapshot; record request start UTC.
2. If authorized, update \`data/refresh-request.txt\` with a distinct timestamp
   using its current blob SHA. This causes a \`push\` event on main.
3. Identify the resulting workflow run by **triggering commit SHA** and
   \`event=push\`, not merely "latest successful run." Poll the run to completion.
4. Require success, then fetch the JSON again, ensure \`generated_at_utc\` is
   after the request start, and recompute last/mark/generation ages against
   the current UTC. Do not assume a push commit itself generated fresh data.
5. On timeout, missing or failed run, quote staleness, missing provenance, or
   stale confirmed candles: fail closed and present historical information only.

This trigger involves GitHub scheduling, runner availability, fetching OKX,
committing the result, and connector read latency. It has **no bounded
completion time** and cannot guarantee real-time execution.

OI changes use a nearest historical sample within +/-20 minutes of the
target time. \`derivatives.oi_change_diagnostics\` now reports the reference
timestamp, temporal distance, and unavailable reason for each horizon. The
publisher stores only its own observations, not an official OKX historical OI
series. A reliable near-continuous OI history requires a separately authorized
persistent sampler/data vendor; do not loosen tolerance simply to fill nulls.

## Acceptance checks

- \`python -m unittest discover -s tests -v\` passes offline.
- \`python scripts/verify_okx.py --file data/OKX-SOXL-USDT-SWAP.json\`
  returns 2 on a stale repository snapshot, even if the snapshot's stored
  \`last_quote_age_minutes\` equals zero.
- Wrong venue, symbol, source, or 1d/4h candle data is rejected.
- A successful freshly generated snapshot passes verification in its run.
- Missing OI changes remain null; diagnostics explain nearest timestamp gap.
- A refresh-request push produces a matching, completed, successful workflow
  and a **newer** generated_at_utc; else ChatGPT clearly reports failure.
- Observe actual schedule run creation over 24 hours; GitHub scheduled events
  are best-effort, not proof of a five-minute freshness SLA.
