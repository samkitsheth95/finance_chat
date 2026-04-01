# Portfolio Doctor — Design Spec

**Date:** 2026-04-01
**Status:** Approved
**Approach:** Hybrid — new MCP sharing code with india-markets via `shared/` package

## Overview

A new MCP server ("portfolio-doctor") that analyzes a client's trading history
(equities + mutual funds, Indian markets) to identify behavioral patterns,
quantify the cost of mistakes, compare against passive alternatives, and generate
actionable recommendations. Built for financial advisors analyzing client portfolios.

### What it answers

- "What behavioral patterns are hurting this client's returns?"
- "How much did panic selling actually cost them?"
- "Would they have been better off with a simple index SIP?"
- "What should they start/stop doing today?"

### What it does NOT do

- Live market analysis (that's india-markets MCP)
- Portfolio tracking or position management
- Trade execution or order placement
- Tax filing or compliance reporting

---

## 1. Codebase Reorganization

### Current structure (single MCP)

```
finance_chat/
├── core/           ← Everything mixed: shared yfinance + india-markets-specific
├── tools/          ← India-markets tools
├── server/app.py   ← India-markets MCP
├── scripts/
├── data/daily/
```

### Proposed structure (two MCPs, shared code)

```
finance_chat/
├── shared/                           ← NEW: Extracted shared utilities
│   ├── __init__.py
│   ├── yf_client.py                  ← Extracted from core/macro_client.py
│   ├── price_history.py              ← NEW: batch historical OHLC via yfinance
│   ├── mf_client.py                  ← NEW: MF NAV history via mftool
│   └── nse_utils.py                  ← Extracted from core/fundamentals_client.py
│
├── core/                             ← India-markets core (slimmed)
│   ├── kite_client.py                ← Unchanged
│   ├── nse_client.py                 ← Unchanged
│   ├── macro_client.py               ← Thin wrapper, imports from shared/yf_client
│   ├── fundamentals_client.py        ← Imports from shared/nse_utils
│   ├── signal_scorer.py              ← Unchanged
│   ├── stock_scorer.py               ← Unchanged
│   ├── daily_store.py                ← Unchanged
│   └── news_client.py                ← Unchanged
│
├── tools/                            ← India-markets tools (unchanged)
├── server/app.py                     ← India-markets MCP (unchanged)
│
├── portfolio_doctor/                 ← NEW: Portfolio analysis MCP
│   ├── core/                         ← Analysis engines
│   │   ├── __init__.py
│   │   ├── csv_parser.py
│   │   ├── portfolio_engine.py
│   │   ├── behavioral_engine.py
│   │   └── alternatives_engine.py
│   ├── tools/                        ← Business logic tools
│   │   ├── __init__.py
│   │   ├── portfolio_tools.py
│   │   ├── behavioral_tools.py
│   │   ├── alternative_tools.py
│   │   └── report_tools.py
│   └── server/
│       ├── __init__.py
│       └── app.py                    ← Portfolio Doctor MCP
│
├── data/
│   ├── daily/                        ← Existing india-markets snapshots
│   └── portfolios/                   ← NEW: Client portfolio data
│
├── .mcp.json                         ← Updated: both MCPs
├── scripts/
└── requirements.txt
```

### What gets extracted into shared/

| File | Source | What it contains |
|------|--------|-----------------|
| `yf_client.py` | Extracted from `core/macro_client.py` | yfinance session management, SSL bypass, caching layer, `yf_latest()` helper |
| `nse_utils.py` | Extracted from `core/fundamentals_client.py` | `nse_to_yf()` symbol mapping, symbol normalization |
| `price_history.py` | New | Fetch daily OHLC for any NSE stock/index via yfinance, up to 20+ years |
| `mf_client.py` | New | MF NAV history via `mftool`, AMFI scheme code lookup/validation |

### Impact on existing code

Only 2 files need import updates:
- `core/macro_client.py` — imports yf session from `shared/yf_client` instead of defining inline
- `core/fundamentals_client.py` — imports `nse_to_yf` from `shared/nse_utils` instead of defining inline

All 22 existing india-markets tools continue working identically.

### Run commands

- India-markets: `python -m server.app` (unchanged)
- Portfolio-doctor: `python -m portfolio_doctor.server.app`
- Both use `-m` flag → repo root on `sys.path` → `shared/`, `core/`, `portfolio_doctor/` all importable

---

## 2. CSV Schema & Data Ingestion

### Standardized CSV format

Unified format supporting both equities and mutual funds:

| Column | Type | Required | Equity Example | MF Example |
|--------|------|----------|----------------|------------|
| `date` | YYYY-MM-DD | Yes | 2019-03-15 | 2019-03-15 |
| `instrument_type` | EQUITY/MF | Yes | EQUITY | MF |
| `symbol` | String | Yes | RELIANCE | 119551 |
| `scheme_name` | String | No | | Parag Parikh Flexi Cap Fund - Direct Growth |
| `action` | BUY/SELL/SIP/SWP/SWITCH_IN/SWITCH_OUT | Yes | BUY | SIP |
| `quantity` | Float | Yes | 50 | 124.873 |
| `price` | Float | Yes | 1245.60 | 56.2340 |
| `amount` | Float | No | 62280.00 | 7023.45 |
| `brokerage` | Float | No | 20.00 | 0 |
| `notes` | String | No | | Monthly SIP |

### Key MF-specific considerations

- **AMFI scheme codes** are the canonical MF identifier (e.g., 119551)
- **SIP vs lump sum** captured via `action` field — matters for behavioral analysis
- **Direct vs Regular** plans encoded in scheme code, flagged in analysis
- **Units are fractional** — MF quantities can be 124.873

### Historical data sources

- Equities: `shared/price_history.py` using yfinance (`.NS` tickers, 20+ years)
- Mutual funds: `shared/mf_client.py` using `mftool` library (AMFI public NAV data, goes back to fund inception)

### Ingestion pipeline (portfolio_doctor/core/csv_parser.py)

1. **Parse & validate** — read CSV, split into equity trades and MF transactions
2. **Symbol resolution** — equity: map to yfinance `.NS` ticker; MF: validate AMFI scheme code, cross-check `scheme_name` if provided
3. **Trade ledger construction** — per-instrument position history; equity uses FIFO for cost basis; MF uses per-lot NAV (each purchase lot tracked separately for LTCG/STCG tax treatment)
4. **Cash flow timeline** — unified inflow/outflow sequence across equity and MF for total portfolio XIRR and alternative scenario modeling
5. **SIP detection** — identify regular monthly patterns (same scheme, similar amount, monthly cadence), tag as systematic vs ad-hoc
6. **Storage** — save processed data to `data/portfolios/{client_name}/trades.json`, `positions.json`, `cashflows.json`, `sip_patterns.json`

### Validation rules

- Can't sell more shares/units than currently held
- Dates should be valid trading days (warn but don't reject weekends)
- Equity symbols must resolve to valid NSE tickers via yfinance
- MF scheme codes must exist in AMFI database
- Duplicate rows (same date/symbol/action/qty/price) trigger a warning

---

## 3. Analysis Engines

Three engines in `portfolio_doctor/core/`. Each does one thing well, returns
structured data consumed by the tools layer.

### Engine 1: Portfolio Engine (portfolio_engine.py)

The math layer — computes returns, positions, metrics. No opinions.

| Function | Computes |
|----------|----------|
| `compute_holdings(trades, as_of_date)` | Current/historical holdings at any point. Running quantity, avg cost (FIFO for equity, per-lot for MF), invested amount per position |
| `compute_returns(trades, price_data)` | Per-position returns (absolute, %), total portfolio XIRR, time-weighted return, annualized return. Handles partial sells |
| `compute_portfolio_value_series(trades, price_data)` | Daily portfolio value curve from first trade to today. Powers the equity curve chart |
| `compute_sector_allocation(holdings)` | Maps equity to sector (yfinance `.info`), MFs tagged by type (equity MF, debt MF, hybrid) |
| `compute_cash_flows(trades)` | Net cash deployed over time — cumulative investment curve. Used by alternatives engine |
| `compute_turnover(trades, avg_portfolio_value)` | Annual portfolio turnover ratio (total sells / avg value). High = overtrading signal |
| `compute_tax_drag(trades, price_data)` | Estimated STCG (15%) and LTCG (10% above ₹1L) on realized gains. Equity-oriented vs debt-oriented MF treatment |

Design choices:
- FIFO cost basis for equity (standard in India)
- Per-lot tracking for MF (LTCG grandfathering — pre Jan 31, 2018 purchases)
- XIRR via `scipy.optimize.brentq`
- All calculations use actual trade dates and prices

### Engine 2: Behavioral Engine (behavioral_engine.py)

The psychology layer — detects patterns, scores them, quantifies cost.

| Detector | Catches | Method |
|----------|---------|--------|
| `detect_panic_selling` | Selling during crashes | Sells when Nifty >10% below recent peak. Score by drawdown depth + post-sell recovery |
| `detect_fomo_buying` | Buying at peaks | Buys when stock >20% above 200 DMA or Nifty near ATH. Score by subsequent drawdown |
| `detect_disposition_effect` | Selling winners early, holding losers | Compare avg holding period of winners vs losers |
| `detect_concentration_risk` | Over-allocation | Max single-stock weight, top-5 concentration, sector concentration over time |
| `detect_overtrading` | Churning returns | Monthly trade count, round-trips within 30 days, churn cost as % of returns |
| `detect_herd_behavior` | Following the crowd | Buys in stocks that ran 30%+ in prior month |
| `detect_anchoring_bias` | Anchored to buy price | Repeated sells at breakeven (±2% of cost) |
| `detect_sip_discipline` | MF: SIP consistency | SIPs maintained during crashes? Stoppages during drawdowns? |
| `detect_regular_plan_waste` | MF: commission leak | Regular plan holdings where direct plan exists, cumulative expense ratio drag |

Each detector returns:
```python
{
    "pattern": "panic_selling",
    "score": -0.7,           # -1.0 (severe) to +1.0 (excellent)
    "severity": "high",      # low / medium / high
    "instances": [...],      # specific triggering trades
    "cost_estimate": 45000,  # estimated INR cost
    "evidence_summary": "Sold HDFCBANK at ₹842 during March 2020 crash..."
}
```

Composite behavioral score weights:
- Timing biases (panic + FOMO): 25%
- Disposition effect: 20%
- Overtrading: 20%
- Concentration risk: 15%
- Herd + anchoring: 10%
- SIP discipline: 10% (redistributed if no MF trades)

### Engine 3: Alternatives Engine (alternatives_engine.py)

The "what if" layer — same cash flows, different strategies.

| Scenario | Logic |
|----------|-------|
| Nifty 50 SIP | Same cash inflows on same dates, buy Nifty 50 TRI (total return index including dividends) |
| Popular MF SIPs | Same cash flows into: UTI Nifty 50 Index, Parag Parikh Flexi Cap, HDFC Balanced Advantage, HDFC Short Term Debt. NAV from `mftool` |
| Model portfolios | 100% equity (Nifty TRI), 70/30 equity-debt, 50/50. Debt = liquid fund NAV |
| Buy-and-hold same stocks | Same stocks, same buy timing, but never sell. Current value if held |
| Same stocks, no re-entry | For stocks bought → sold → bought again: what if held from first buy? Isolates cost of "trading around" a position |

Each scenario returns:
```python
{
    "scenario": "nifty_50_sip",
    "total_invested": 1500000,
    "final_value": 2340000,
    "xirr": 0.148,
    "absolute_return_pct": 56.0,
    "annualized_return_pct": 14.8,
    "max_drawdown_pct": -35.2,
    "vs_actual": {
        "return_difference_pct": +3.2,
        "value_difference": +48000,
        "interpretation": "A simple Nifty 50 SIP would have earned ₹48,000 more"
    }
}
```

Fair comparison rules:
- Same dates, same amounts — only the vehicle changes
- Account for transaction costs in actual portfolio, not in SIP alternatives
- Use TRI (Total Return Index) for Nifty, not price index
- Use actual historical NAVs for MF alternatives

---

## 4. MCP Tools

6 tools following the conversation flow: ingest → explore → diagnose → compare → recommend → present.

| # | MCP Tool | Function | File |
|---|----------|----------|------|
| 1 | `ingest_trades` | `ingest_client_trades(csv_path, client_name)` | `portfolio_tools.py` |
| 2 | `portfolio_overview` | `get_portfolio_overview(client_name)` | `portfolio_tools.py` |
| 3 | `behavioral_audit` | `get_behavioral_audit(client_name)` | `behavioral_tools.py` |
| 4 | `compare_alternatives` | `get_alternative_scenarios(client_name)` | `alternative_tools.py` |
| 5 | `action_plan` | `get_action_plan(client_name)` | `report_tools.py` |
| 6 | `full_report_data` | `get_full_report_data(client_name)` | `report_tools.py` |

### Tool details

**ingest_trades(csv_path, client_name)**
- Parse and validate the standardized CSV
- Returns: validation summary, trade count, date range, unique symbols, capital deployed, instrument mix

**portfolio_overview(client_name)**
- Requires: ingest_trades called first
- Returns: current holdings, total returns (XIRR, absolute, annualized), sector allocation, equity curve summary, turnover ratio, tax drag estimate

**behavioral_audit(client_name)**
- Requires: ingest_trades called first
- Calls portfolio_engine internally for position/return data
- Returns: all 9 detector results, composite behavioral score, top 3 costliest behaviors with evidence

**compare_alternatives(client_name)**
- Requires: ingest_trades called first
- Calls portfolio_engine for cash flow timeline
- Returns: 5 scenario comparisons, side-by-side returns table, value difference vs actual

**action_plan(client_name)**
- Requires: behavioral_audit + compare_alternatives results (calls them if not cached)
- Returns: prioritized recommendations in Start/Stop/Keep framework, personalized, quantified in rupees

**full_report_data(client_name)**
- Aggregates ALL analysis into a single structured JSON
- Calls any tools not yet called
- Returns: complete data blob optimized for canvas rendering

### Data caching between tools

After `ingest_trades`, processed data lives in `data/portfolios/{client_name}/`.
Each tool reads from there and writes results back. Tools can be called individually
or `full_report_data` fetches everything at once.

### System prompt

```
You are a portfolio behavioral analyst for Indian retail investors and traders.
You help financial advisors analyze their clients' trading history to identify
behavioral patterns, quantify the cost of mistakes, and provide actionable
improvement recommendations.

AVAILABLE TOOLS:

  ingest_trades(csv_path, client_name)
    → START HERE. Always call this first when given a new client CSV.

  portfolio_overview(client_name)
    → "How has this client done?" — holdings, returns, allocation, turnover.

  behavioral_audit(client_name)
    → "What mistakes is this client making?" — 9 behavioral detectors,
      each scored -1.0 to +1.0 with evidence and cost estimates.

  compare_alternatives(client_name)
    → "Would they have been better off with an index fund?" — 5 scenarios,
      same money, same dates, different vehicles.

  action_plan(client_name)
    → "What should this client change?" — Start/Stop/Keep framework,
      personalized, quantified in ₹.

  full_report_data(client_name)
    → "Give me everything" — aggregated JSON for canvas report.

CONVERSATION FLOW:
  1. Advisor provides CSV → ingest_trades()
  2. Quick look → portfolio_overview()
  3. Deep diagnosis → behavioral_audit()
  4. "What if" → compare_alternatives()
  5. Recommendations → action_plan()
  6. Full presentation → full_report_data() → render as canvas

RESPONSE GUIDELINES:
  • Present monetary values in ₹ with Indian commas (₹1,45,000)
  • Quantify behavioral costs in rupees — "panic selling cost ₹45,000"
  • Lead with differences, not absolutes: "₹48,000 more" not "14.8% XIRR"
  • Be empathetic, not judgmental — real people's money decisions
  • Flag regular-vs-direct MF savings opportunity
  • Frame recommendations as forward-looking actions, not past mistakes
```

### .mcp.json

```json
{
  "mcpServers": {
    "india-markets": {
      "command": ".venv/bin/python",
      "args": ["-m", "server.app"],
      "env": { "KITE_SSL_VERIFY": "false" }
    },
    "portfolio-doctor": {
      "command": ".venv/bin/python",
      "args": ["-m", "portfolio_doctor.server.app"],
      "env": {}
    }
  }
}
```

---

## 5. Interactive Canvas Report

`full_report_data()` returns structured JSON. Claude renders it as an interactive
HTML canvas via cursor-ide-browser. Designed for advisor-to-client walkthroughs.

### Libraries (CDN)

- Chart.js — equity curves, bar comparisons, allocation pies
- D3.js — behavioral timeline markers on price charts, heatmaps
- Google Fonts — DM Sans (body) + DM Mono (numbers/money)

### Section A: Client Snapshot

Header bar with key metrics at a glance:
- Trading since / duration
- Total invested / current value
- XIRR
- Instrument count (stocks + MFs)
- Behavioral score (0-10 scale)
- Turnover ratio
- Tax drag estimate

### Section B: Equity Curve + Behavioral Markers

Chart.js line chart:
- Blue line: actual portfolio value over time
- Grey dashed: Nifty 50 (same cash flows)
- Red markers: panic sells (with tooltip showing trade detail)
- Orange markers: FOMO buys (with tooltip)
- Green markers: good decisions
- Vertical shaded bands for major market events (Covid Mar 2020, etc.)

Interactive: hover for tooltips, click markers for trade detail.

### Section C: Behavioral Audit — Radar + Detail Cards

Left: radar/spider chart showing all behavioral dimensions (0-10 each):
- Timing discipline, holding discipline, diversification,
  trading discipline, crowd independence, SIP consistency
- Second overlay: "ideal investor" at 8-9 for contrast

Right: scrollable cards for top 3 costliest behaviors, each with:
- Score, severity (color-coded: red/amber/green)
- Specific trade instances with dates, prices, opportunity cost
- Total estimated cost in ₹

### Section D: Alternative Scenarios — Bar Comparison

Horizontal grouped bar chart comparing final portfolio values:
- Actual portfolio
- Nifty 50 SIP
- Popular MF SIP
- 70/30 model portfolio
- Buy & hold same stocks

Each bar shows ₹ value + difference from actual. Callout box highlights
the single most impactful insight.

Below: table with XIRR, max drawdown, effort level per scenario.

### Section E: Allocation Analysis

Two side-by-side donut charts:
- Current sector allocation (shows concentration visually)
- Instrument type split (equity vs MF, direct vs regular)

Below: holdings table sorted by weight with per-position return and holding period.

### Section F: Action Plan — Start / Stop / Keep

Three columns:
- START DOING: new habits (index SIP, switch to direct plans, consolidate small positions)
- STOP DOING: costly behaviors with ₹ evidence (panic selling, FOMO buying, round-tripping)
- KEEP DOING: positive patterns to reinforce (SIP consistency, position sizing)

Each recommendation includes quantified cost/benefit in ₹.

---

## Dependencies

New dependencies to add to `requirements.txt`:
- `mftool` — AMFI NAV data for mutual funds
- `scipy` — XIRR calculation (brentq solver)

Existing dependencies already available:
- `yfinance` — historical equity prices
- `mcp` — FastMCP framework
- `python-dotenv` — env management

---

## Out of Scope (for now)

- Multiple broker CSV format parsers (Zerodha, Groww, etc.) — future enhancement
- CAMS/KFintech CAS statement parsing — future enhancement
- F&O / derivatives trade analysis — equity + MF only for v1
- Delivery volume analysis — planned for india-markets (B4), not portfolio-doctor
- Multi-currency / global stock support — India NSE/BSE only
- Automated report email/PDF export — canvas HTML for now
