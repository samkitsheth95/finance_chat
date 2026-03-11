# Project Memory — india-markets MCP

This file captures architectural decisions, trade-offs discussed, and context
that should persist across all future development sessions.

---

## What This Project Is

A local-first **MCP server** that gives Claude live access to Indian financial
market data. The user chats with it inside Cursor or Claude Code — no separate
web UI. Claude decides which data tools to call based on the question asked.

## Why MCP (not a REST API or web app)

- User is a software engineer who works in Cursor daily
- MCP means no browser tab to open — chat lives inside the IDE
- Config travels with the repo (`.mcp.json` / `.cursor/mcp.json` symlink)
- Portable: anyone who clones the repo gets the MCP wiring automatically

## Why Zerodha Kite Connect

- Most reliable NSE data source for retail algo trading in India
- Low-latency, supports option chain + Greeks + historical tick data
- User already has a Zerodha account with Kite API access
- Limitation: access token expires daily, must be manually refreshed each morning

## Why Not Portfolio Tracking

- User has no holdings in Kite — pure market analysis use case
- Focus is on: indices, option chains, FII/DII flows, macro signals

## Layer 6 Design Notes (pre-build)

### Binary signals need graduated intensity
Current Layer 2 signals (`bullish` / `bearish` / `neutral`) lose magnitude information.
On 11 Mar 2026, FII index futures net was −187,070 contracts — 3.7× the ±50,000 threshold —
but the signal returned the same `bearish` string as a −55,000 position would.
Claude compensated by computing the ratio manually, but this should be part of the signal.

Layer 6 should replace binary flags with **scored intensity**, e.g.:
- `score: -0.87` on a −1.0 to +1.0 scale, derived from z-score vs recent history
- `magnitude: "extreme"` alongside the directional label (extreme / strong / moderate / mild)
- Thresholds should be **dynamic** (percentile of last 20 trading days), not hardcoded constants

### The Signal Weighting Framework (Layer 6)

All data layers feed into a scoring system before Claude synthesizes:
- Each signal → directional score (+1 bullish / 0 neutral / -1 bearish)
- Weights shift based on: question type + time horizon + market regime
- Regime overrides trump all weights (e.g., VIX > 20 → FII flows dominate)
- Conflicts are flagged explicitly (e.g., FII cash buying + FII futures short)
- Claude gets a pre-digested brief, not raw numbers

## Data Sources Decided

| Source | Library | Auth | Cost |
|--------|---------|------|------|
| NSE/BSE live quotes, option chain, historical | `kiteconnect` | API key + daily token | ₹2000/month |
| FII/DII flows, participant OI | `nsepython` | None (public scrape) | Free |
| Global markets, crude, DXY | `yfinance` | None | Free |
| US bond yields / macro | `yfinance` (^TNX, ^FVX) | None | Free |
| News sentiment | `feedparser` + RSS feeds + `gnews` (Google News) | None | Free |

## Build Order (Layers)

1. ✅ Layer 1 — Kite: live quotes, indices, historical OHLC
2. ✅ Layer 2 — NSE: FII/DII cash flows, participant-wise F&O OI
3. ✅ Layer 3 — Kite: option chain, Greeks, PCR, Max Pain, India VIX
4. ✅ Layer 4 — yfinance/FRED: global indices, crude, DXY, USD/INR, US 10Y yield
5. ✅ Layer 5 — RSS/Google News: market news, geopolitical sentiment scoring
6. ✅ Layer 6 — signal_scorer.py + signal_tools.py: scored brief with regime detection

## Sharing / Portability

Each collaborator needs their own:
- Zerodha account + Kite Connect API subscription
- `KITE_API_KEY` and `KITE_ACCESS_TOKEN` in `.env`
- Python 3.13 + `pip install -r requirements.txt`

NSE public data (Layers 2–3 partial) works without Kite — good for testing.

## Layer 3 Implementation Notes

- **Option chain** — `tools/derivatives_tools.get_option_chain(underlying, expiry)`
  - Loads NFO instruments via `core/kite_client.get_instruments("NFO")` (cached after first call, ~2s)
  - Filters by `name == underlying` and `instrument_type in ("CE", "PE")` for the target expiry
  - Lot size read from instrument data (fallback to hardcoded `_LOT_SIZE_FALLBACK` dict)
  - Fetches quotes in batches of 500 (Kite API limit); returns `greeks` (iv, delta, theta, gamma, vega)
    when exchange-computed Greeks are available (NSE provides them for index options)
  - Greeks are `None` when not published by NSE (e.g. deep ITM/OTM, stock options)
  - Returns: `pcr`, `max_pain`, `call_oi_wall`, `put_oi_wall`, `top_call/put_strikes`, `atm_chain` (±10)

- **PCR signal** — contrarian interpretation:
  - PCR ≥ 1.3 → `strongly_bullish` (extreme put loading = oversold, writers expect bounce)
  - PCR 1.0–1.3 → `bullish`; 0.7–1.0 → `neutral`
  - PCR 0.5–0.7 → `bearish`; < 0.5 → `strongly_bearish` (call complacency)

- **Max Pain calculation** — O(n²) over all strikes; fast enough for index chains (~100–150 strikes)
  - Formula: for each candidate expiry X, sum (X − K) × CE_OI for K < X, plus (K − X) × PE_OI for K > X
  - Returns the strike minimising total payout to option buyers

- **India VIX** — `tools/derivatives_tools.get_vix()`
  - Wraps `kite.quote(["NSE:INDIA VIX"])` with regime classification and strategy guidance
  - Weekly 1σ expected move = VIX / √52 (%)
  - Six regimes: very_low (<12), low (12–16), normal (16–20), elevated (20–25), high (25–30), extreme (>30)

- **Two MCP tools exposed**: `option_chain(underlying, expiry)` and `vix()`
  - Claude is instructed to call both together for derivatives questions
  - `vix()` is separate from `indices()` to give richer context (regime + strategy guidance)

## Layer 4 Implementation Notes

- **Two MCP tools exposed**: `global_markets()` and `macro_snapshot()`
  - `global_markets()` — equity indices only (S&P 500, Nasdaq, Nikkei, Hang Seng, FTSE)
  - `macro_snapshot()` — everything: indices + WTI/Brent crude + Gold + DXY + USD/INR
    + US 10Y & 5Y yields + yield curve steepness (10Y−5Y) (10Y − 2Y)

- **yfinance** (`core/macro_client.yf_latest`) — single function wraps all yfinance tickers
  - Uses `fast_info` for minimal latency; falls back to `.history(period='5d')` when
    `fast_info` returns null (common outside trading hours for closed markets)
  - In-process cache: 60-second TTL per ticker, avoids hammering API on repeated calls
  - DXY: ticker `DX-Y.NYB` (ICE futures proxy); USD/INR: `USDINR=X`
  - US 10Y yield: `^TNX` — price IS the yield in %; change = change in %-points

- **No FRED API** — removed after realising FRED's `DGS10` is a daily series published
  with a one-business-day lag, making it *less* fresh than yfinance `^TNX` which is a
  live CBOE index. `^TNX` (10Y), `^FVX` (5Y) cover everything needed. No API key required.

- **India signal derivation** — per-factor signals in `tools/macro_tools.py`:
  - DXY rising → `bearish` (USD strength → EM outflows)
  - USD/INR rising → `bearish` (INR weakness → FII exit pressure)
  - Crude rising → `bearish` (import bill + inflation + CAD pressure)
  - S&P/Nasdaq rising → `bullish` (risk-on → FII inflows)
  - US 10Y rising above 4.5% → `bearish` (capital flows to US bonds)
  - Composite `india_macro_signal` = weighted average of all signals

- **Composite weighting** (equal in this version, differentiated in Layer 6):
  - DXY, US 10Y, crude, USD/INR → highest weight (structural FII drivers)
  - S&P 500, Nasdaq → medium weight
  - Nikkei, Hang Seng, FTSE → lower weight
  - Gold → informational only, not in composite

- **GIFT Nifty** — intentionally not implemented:
  - Requires NSE IFSC data feed; no reliable free yfinance ticker available
  - Kite Connect doesn't cover NSE IFSC instruments on standard subscriptions
  - Listed as a limitation in the MCP instructions; mark for future Layer 4 extension

## Layer 2 Implementation Notes

- **FII/DII cash flows** — `tools/nse_tools.get_fii_dii_activity()`
  - Hits `https://www.nseindia.com/api/fiidiiTradeReact` via nsepython (handles session cookie)
  - Returns today's buy/sell/net in ₹ crores for FII/FPI and DII
  - Includes derived `signal` field: strongly_bullish / bullish / neutral / bearish / strongly_bearish
  - Intraday values are provisional; final figures after 3:45 PM IST

- **nsepython not used at runtime** — `nsepython` is installed but its `nse_fiidii()` function
  has a bug: its `except` block calls `logger.info()` but `logger` is never imported, causing
  a `NameError` that swallows the real error. `core/nse_client.py` replicates the same
  cookie-priming approach using `requests.Session` directly. The package stays in
  `requirements.txt` as a reference for the `nsefetch` header pattern and future use.

## Layer 5 Implementation Notes

- **Three MCP tools exposed**: `market_news()`, `news_search(query, period)`, `news_topic(topic)`
  - `market_news()` — aggregates RSS headlines from 7 feeds (Indian financial + BBC)
  - `news_search(query)` — keyword search via Google News (gnews package)
  - `news_topic(topic)` — browse by topic (BUSINESS, WORLD, etc.) via Google News

- **RSS feeds** — `core/news_client.fetch_all_rss()` fetches from 7 sources:
  - Indian financial: ET Markets, ET Economy, Moneycontrol, Livemint Markets
  - BBC: World, Business, Asia (added for geopolitical + real-time event coverage)
  - HTTP via `requests` (so the global SSL bypass from kite_client applies)
  - Parsed with `feedparser`; cached in-process for 5 minutes per feed

- **Google News** — `core/news_client.gnews_search()` via `gnews` package
  - Wraps Google News RSS — free, no API key, real-time (no delay)
  - Country set to India (`country='IN'`), language English
  - Supports keyword search, top news, and topic-based browsing
  - Cached for 5 minutes per query/topic
  - **Replaced NewsAPI** — NewsAPI free tier had 100 req/day limit AND 24-hour
    article delay, making it useless for real-time market analysis

- **BBC RSS added** — user reads BBC regularly; BBC has real-time live feeds for
  conflicts and developing events. Three feeds: World, Business, Asia.

- **Category tagging** — `tools/news_tools._categorize(text)` applies keyword matching:
  - 9 categories: `rbi_policy`, `fii_flows`, `crude_energy`, `us_fed`, `geopolitical`,
    `earnings`, `ipo_listing`, `rupee_forex`, `nifty_market`
  - A headline can match multiple categories

- **Event risk detection** — `tools/news_tools._is_event_risk(text)`:
  - Flags headlines containing high-impact keywords: war, sanctions, crash, crisis,
    downgrade, recession, pandemic, circuit breaker, etc.
  - `event_risk_headlines` list in the response gives a quick scan

- **Sentiment scoring is Claude's job** — tools return structured headlines with
  categories and event_risk flags; Claude reads the text and scores sentiment.
  This is intentional: NLP sentiment models are unreliable on financial headlines,
  and Claude's contextual understanding (e.g., "crude crash" is bearish for crude
  but bullish for India) is superior.

- **Deduplication** — headlines from overlapping feeds are deduplicated by
  normalizing titles (lowercase, strip punctuation, collapse whitespace)

- **No API keys required** — all Layer 5 sources are free and unauthenticated.
  RSS feeds + Google News cover Indian financial news + global/geopolitical events.

- **Participant F&O OI** — `tools/nse_tools.get_participant_oi(date)`
  - Downloads CSV from `https://archives.nseindia.com/content/nsccl/fao_participant_oi_DDMMYYYY.csv`
  - Participants: FII, DII, Client (retail), Pro (proprietary)
  - Returns per-participant long/short/net for index futures, stock futures, index & stock options
  - Published by NSE after market close (~6 PM IST); "latest" auto-detects most recent day
  - Key signal: `fii_index_futures_signal` based on FII net index futures position

## Layer 6 Implementation Notes

- **Architecture decision: Hybrid approach** — Python scores signals + detects regimes,
  Claude handles question-specific weighting using its own reasoning.
  - Rejected: hard-coded weight matrix (fragile, can't handle nuance)
  - Rejected: two-pass LLM (extra latency/cost for marginal benefit)
  - Chosen: Claude is already reasoning about the question — give it well-structured
    scored data and let it weight based on context. System prompt has weighting rules.

- **One MCP tool exposed**: `market_brief()`
  - Calls all 5 data layers in parallel via `ThreadPoolExecutor(max_workers=7)`
  - Returns: regime, scored signals, conflicts, default composite, data issues
  - Always fetches NIFTY data; for BankNifty etc., use individual tools

- **Signal normalization** — all signals scored -1.0 (bearish) → 0.0 → +1.0 (bullish)
  - Piecewise linear interpolation over breakpoints (`_lerp`)
  - Magnitude labels: extreme (≥0.75), strong (≥0.5), moderate (≥0.25), mild (>0.05)
  - Fixes the binary threshold problem: FII -187k contracts → -0.96 (extreme), not just "bearish"

- **Scorers implemented** (all in `core/signal_scorer.py`):
  - Derivatives: PCR (contrarian), max pain distance (±2% → ±1.0), VIX (fear gauge), OI walls
  - Flows: FII cash net (₹ Cr), DII cash net (₹ Cr), FII index futures net (contracts)
  - Macro: converts existing string signals (bullish/bearish) to scored values; extracts
    key India-relevant factors: DXY, crude, US 10Y, USD/INR, S&P 500
  - News: event risk headline density as a fear signal

- **Regime detection** — priority-ordered from live data:
  1. EXTREME FEAR: VIX > 30
  2. FII EXODUS: FII cash net < -₹5,000 Cr (single day)
  3. FEAR: VIX > 22
  4. EXPIRY: days_to_expiry ≤ 1
  5. GREED: VIX < 13 AND PCR < 0.6
  6. SIDEWAYS: VIX 14–20 AND Nifty day range < 0.8%
  7. NORMAL: default

- **Default weight profiles** (regime-aware):
  - Normal: derivatives 30%, flows 30%, macro 25%, news 15%
  - Fear/extreme_fear: flows 50–55% dominant
  - Exodus: macro 55% dominant
  - Greed/sideways: derivatives 55% dominant
  - Expiry: derivatives 60% dominant
  - Claude adjusts these based on question type + time horizon (rules in system prompt)

- **Conflict detection** — four checks:
  1. FII cash vs FII futures (hedged/cautious vs rotation)
  2. FII vs DII (institutional divergence)
  3. Macro vs FII flows (global vs local disconnect)
  4. PCR vs VIX (put writers vs market fear)

- **Phase 1 limitations** (planned for Phase 2):
  - No multi-day lookback (5-day FII trend, 10-day range for sideways)
  - No 200 DMA for FEAR regime refinement
  - No event calendar (RBI meeting day, Budget day, F&O expiry week auto-detect)
  - No per-stock brief (always Nifty); BankNifty brief would need separate tool or param
