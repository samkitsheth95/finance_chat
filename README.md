# india-markets MCP

An MCP (Model Context Protocol) server that gives Claude live access to Indian
financial market data. Ask questions about NSE/BSE stocks, indices, options,
institutional flows, global macro, and news — directly inside Cursor or Claude Code.

## What you can ask

```
"How is the market doing today?"
"Should I be buying Nifty calls today or is it too risky?"
"What's the overall market setup? Give me the full picture."
"Are FIIs buying or selling? What's their derivatives positioning?"
"Show me the BankNifty option chain for this week's expiry."
"What is PCR and max pain for Nifty?"
"Is the macro setup supportive for India this month?"
"How do crude prices and DXY affect Indian markets right now?"
"Any event risk or market-moving news today?"
"Is it safe to go long today or should I wait?"
```

## Data Layers

| Layer | Data | Source | Status |
|-------|------|--------|--------|
| 1 — Market Foundation | Live quotes, indices, historical OHLC | Kite Connect | ✅ Done |
| 2 — Institutional Flows | FII/DII cash flows, F&O participant OI | NSE public | ✅ Done |
| 3 — Derivatives | Option chain, Greeks, PCR, Max Pain, VIX | Kite Connect | ✅ Done |
| 4 — Global Macro | S&P 500, DXY, crude, US 10Y, USD/INR | yfinance | ✅ Done |
| 5 — News & Sentiment | RSS feeds, Google News, event risk | feedparser + gnews | ✅ Done |
| 6 — Signal Scoring | Scored brief, regime detection, conflicts | All layers | ✅ Done (Phase 1) |

## Market Regimes

`market_brief()` automatically detects the current market regime from live data
and adjusts which signal layer matters most. Claude uses this to decide how much
weight to give derivatives vs flows vs macro vs news for any given question.

| Regime | Trigger | What's happening | Dominant layer |
|--------|---------|------------------|----------------|
| EXTREME FEAR | VIX > 30 | Panic / crash-like conditions | Flows (55%) — are FIIs done selling? |
| FEAR | VIX > 22 | Elevated anxiety, selloff underway | Flows (50%) — institutional direction decides |
| FII EXODUS | FII cash < -₹5,000 Cr/day | FIIs dumping aggressively | Macro (55%) — what's driving them out? |
| EXPIRY | ≤1 day to option expiry | Expiry day | Derivatives (60%) — theta + max pain gravity |
| GREED | VIX < 13 AND PCR < 0.6 | Low fear + call complacency | Derivatives (55%) — option writers control reversal |
| SIDEWAYS | VIX 14–20, range < 0.8% | Tight range, no direction | Derivatives (55%) — OI walls define the band |
| NORMAL | None of the above | Regular trading day | Balanced (30/30/25/15) |

Regimes are checked in priority order (top to bottom). If VIX is 35 *and* FII sold
₹8,000 Cr, the regime is EXTREME FEAR (not EXODUS) because VIX > 30 is checked first.

Default weights can be adjusted in `core/signal_scorer.py` → `_DEFAULT_WEIGHTS`.

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/your-username/finance_chat.git
cd finance_chat
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Get your Kite Connect credentials

1. Log in at [developers.kite.trade](https://developers.kite.trade)
2. Create an app → copy your **API Key** and **API Secret**
3. Each morning, generate a fresh **Access Token** via the Kite login URL:
   ```
   https://kite.trade/connect/login?api_key=YOUR_API_KEY&v=3
   ```
   After logging in, you'll be redirected to your redirect URL with a
   `request_token` in the query string. Exchange it for an access token:
   ```python
   from kiteconnect import KiteConnect
   kite = KiteConnect(api_key="YOUR_API_KEY")
   data = kite.generate_session("REQUEST_TOKEN_FROM_URL", api_secret="YOUR_SECRET")
   print(data["access_token"])  # paste this into .env
   ```

### 3. Configure your .env file

```bash
cp .env.example .env
```

Edit `.env`:
```
KITE_API_KEY=your_api_key_here
KITE_ACCESS_TOKEN=your_fresh_access_token_here
```

> **Note:** The access token expires at the end of each trading day.
> You need to regenerate it each morning before using the MCP server.

---

## Add to Cursor

The `.cursor/mcp.json` in this project is already configured. Cursor picks it
up automatically when you open this folder.

To verify it's running:
  1. Top menu → Cursor → Settings → Cursor Settings
  2. Look for the MCP section in the left sidebar
  3. `india-markets` should appear with a green dot

Alternatively: Cmd+Shift+P → type "MCP" → "Cursor: Open MCP Settings"

## Add to Claude Code

```bash
# From the project directory:
claude mcp add --scope project india-markets python -m server.app
```

Or add globally so it's available in all projects:
```bash
claude mcp add india-markets python -m server.app
```

---

## Sharing with others

Each person needs:
1. A Zerodha account with [Kite Connect API](https://kite.trade/pricing) access
2. Their own `KITE_API_KEY` and `KITE_ACCESS_TOKEN` in a `.env` file
3. Python 3.10+ and `pip install -r requirements.txt`

NSE public data (Layers 2, 4, 5) works without Kite — good for testing.

---

## Project structure

```
finance_chat/
├── server/
│   └── app.py                ← MCP server: tool registration + system prompt
├── tools/
│   ├── kite_tools.py         ← Layer 1: quotes, indices, historical OHLC
│   ├── nse_tools.py          ← Layer 2: FII/DII flows, participant OI
│   ├── derivatives_tools.py  ← Layer 3: option chain, PCR, max pain, VIX
│   ├── macro_tools.py        ← Layer 4: global indices, crude, DXY, yields
│   ├── news_tools.py         ← Layer 5: RSS, Google News, event risk
│   └── signal_tools.py       ← Layer 6: market_brief() aggregator
├── core/
│   ├── kite_client.py        ← Kite Connect session + instrument cache
│   ├── nse_client.py         ← NSE session (cookie-primed requests)
│   ├── macro_client.py       ← yfinance wrapper with in-process cache
│   ├── news_client.py        ← RSS + Google News fetcher with cache
│   └── signal_scorer.py      ← Signal normalization, regime detection, weights
├── scripts/
│   └── refresh_token.py      ← Token refresh utility
├── .mcp.json                 ← Cursor / Claude Code MCP config
├── .env.example              ← API key template
├── .env                      ← Your keys (gitignored)
└── requirements.txt
```
