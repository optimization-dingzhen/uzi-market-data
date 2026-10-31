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
- Fetch schedule: GitHub Actions has a **best-effort once-hourly backup** at UTC minute 53. The hourly ChatGPT analysis must actively refresh on demand, then independently check last/mark quote and generation timestamps at read time (max 15 minutes). Neither cron nor a stored age is real-time proof
- If any required quote is missing, stale, a wrong instrument or an API access restriction applies, publication fails rather than emitting a false live signal.
- Funded accounts, trade secrets, order execution, and user balances are never used.

## ChatGPT Web / UZI SKILL project instruction

Paste this text into your ChatGPT project's instructions to prioritize the new source:

> For each scheduled hourly SOXL analysis, trigger one OKX refresh with the connected GitHub app using the `data/refresh-request.txt` SHA-checked push path, even if the last cached snapshot was recently generated; never trigger more than once in the same analysis. Match the resulting Actions run by request commit SHA, require success, then re-read `data/OKX-SOXL-USDT-SWAP.json` and confirm `generated_at_utc` is later than the request, `exchange=OKX`, `symbol=SOXL-USDT-SWAP`, verified source, and both quote timestamps are <=15 minutes old at read time. If refresh cannot be confirmed, clearly report the failure; do not claim an old cache was newly fetched. The OKX contract is not Binance SOXLUSDT or SOXL ETF. Base primary trend on confirmed UTC 1d and structure/overbought-oversold on confirmed 4h, with EMA20/EMA50, RSI14, ATR14 and Bollinger bands. Attribute OI/funding to OKX; keep unavailable changes null. Use delayed Binance history only as explicitly historical context, never as current Binance/OKX quotes; verify SOXL ETF and US options separately.

## On-demand refresh from ChatGPT Web

The **primary refresh trigger is each hourly ChatGPT analysis**. The GitHub Actions hourly cron (UTC :53) is optional backup, best-effort only, and cannot guarantee quotes at the next analysis time. A one-shot push-based trigger is supported by `.github/workflows/publish-okx.yml`:

1. Read `data/OKX-SOXL-USDT-SWAP.json` with the connected GitHub app and check current UTC against both quote timestamps.
2. For **each hourly analysis**, if repository write access is authorized, update `data/refresh-request.txt` with a unique `request_utc=<current UTC ISO-8601>` line via GitHub update_file (preserving the current file SHA), **even if the previously cached quotes are under 15 minutes old**. This invokes the OKX publisher's **push** workflow. Limit to one request per analysis; if unsupported, note that the refresh was not performed.
3. Match the Actions run by this request's **commit SHA** and `event=push`; do not substitute the latest successful unrelated run. Require `conclusion=success`.
4. Re-read the JSON, check `generated_at_utc` is after the request, and independently check its generation and both market quote timestamps against current UTC. If any is older than 15 minutes, unavailable or provenance-mismatched, fail closed and use delayed Binance history only.

Each request causes a small GitHub commit. This is a *user-initiated near-live refresh*, NOT streaming tick data and not a guarantee of bounded API latency. Never edit broker/OKX accounts or place orders.

To use this without manually opening Codex or GitHub, include this supplemental ChatGPT project instruction:

> At the start of every hourly OKX SOXL-USDT-SWAP analysis, request a fresh snapshot once via the connected GitHub connector: SHA-check and update `data/refresh-request.txt`, find the matching push-commit Actions run and require success, then re-read the OKX JSON and independently verify the new generation time and last/mark quote timestamps are no older than 15 minutes. If unavailable or delayed, label the result limited/historical; do not claim cache data was fetched this run. Analyse confirmed 1d first, then confirmed 4h, including RSI overbought/oversold, EMA20/50, ATR and Bollinger. Do not mix Binance or the US-listed ETF with OKX.

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
`python scripts/verify_okx.py --file data/OKX-SOXL-USDT-SWAP.json`.
Exit code 0 means OKX quote/mark provenance, snapshot generation time, and
confirmed 1d/4h candle recency passed. Exit code 2 means **not usable as a
current market signal**. Published `last_quote_age_minutes` values are not
read-time ages, and `status: live_verified_quotes` is not perpetual freshness.

In ChatGPT, re-read the file after any refresh. The exact exchange timestamps
must all pass the 15-minute quote/generation checks at the moment of analysis.
Analysis order: **1d trend first, then 4h structure and overbought/oversold
conditions**. Use EMA20/EMA50, RSI14, Bollinger bands and ATR; do not infer a
Binance price, mark, OI, or funding rate from OKX. Missing OKX OI 4h/1d changes
must remain `null` with explanation, not interpolation presented as truth.

The on-demand path is:
1. Read the prior snapshot as cache; record this analysis request start UTC.
2. At each hourly analysis, if authorized, update `data/refresh-request.txt` with a distinct timestamp
   using its current blob SHA. This causes a `push` event on main.
3. Identify the resulting workflow run by **triggering commit SHA** and
   `event=push`, not merely "latest successful run." Poll the run to completion.
4. Require success, then fetch the JSON again, ensure `generated_at_utc` is
   after the request start, and recompute last/mark/generation ages against
   the current UTC. Do not assume a push commit itself generated fresh data.
5. On timeout, missing or failed run, quote staleness, missing provenance, or
   stale confirmed candles: fail closed and present historical information only.

This on-demand trigger involves GitHub runner availability, fetching OKX,
committing the result, and connector read latency. It has **no bounded
completion time** and cannot guarantee real-time execution.

OI changes use a nearest historical sample within +/-20 minutes of the
target time. `derivatives.oi_change_diagnostics` now reports the reference
timestamp, temporal distance, and unavailable reason for each horizon. The
publisher stores only its own observations, not an official OKX historical OI
series. A reliable near-continuous OI history requires a separately authorized
persistent sampler/data vendor; do not loosen tolerance simply to fill nulls.

## Acceptance checks

- `python -m unittest discover -s tests -v` passes offline.
- `python scripts/verify_okx.py --file data/OKX-SOXL-USDT-SWAP.json`
  returns 2 on a stale repository snapshot, even if the snapshot's stored
  `last_quote_age_minutes` equals zero.
- Wrong venue, symbol, source, or 1d/4h candle data is rejected.
- A successful freshly generated snapshot passes verification in its run.
- Missing OI changes remain null; diagnostics explain nearest timestamp gap.
- A refresh-request push produces a matching, completed, successful workflow
  and a **newer** generated_at_utc; else ChatGPT clearly reports failure.
- Do not assess hourly ChatGPT analytics using 288 five-minute cron slots/day. Evaluate
  **one matching on-demand refresh per completed hourly analysis** and a successful
  re-read timestamp gate. The optional 24-slots/day hourly GitHub schedule remains
  best-effort, not an availability or timeliness SLA.
