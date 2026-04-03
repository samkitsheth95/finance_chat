# Portfolio Doctor — AI Pattern Recognition & Dynamic Scenarios

**Date:** 2026-04-03
**Status:** Design approved, pending implementation plan

## Problem

The current portfolio doctor is entirely rule-based. Nine behavioral detectors
check individual trades against fixed thresholds. Five what-if scenarios run
mechanical simulations. Claude wraps the results in natural language but does no
actual reasoning about the data.

With client data spanning 10-20 years, there are temporal patterns, behavioral
loops, and regime-dependent habits that point-in-time detectors cannot see. The
what-if scenarios are generic — the same five for every client regardless of
their specific behavioral weaknesses.

## Goals

1. **Temporal pattern detection** — identify multi-trade sequences, behavioral
   loops, drift over time, and calendar patterns within a single client's history
2. **AI-discovered patterns** — give Claude enriched structured data so it can
   find patterns we didn't pre-code detectors for
3. **Dynamic what-if scenarios** — generate 1-3 personalized scenarios per client
   based on their detected patterns, in addition to the 5 constant scenarios
4. **Architecture open for cross-client patterns** — design data structures that
   support future multi-client pattern matching (not built now)

## Architecture: Enrichment Layer

Two new engines layered on top of existing code. Nothing existing is rewritten.

```
Existing (unchanged):
  csv_parser → trades, cashflows, sip_patterns, positions
  portfolio_engine → holdings, returns, value_series, allocation
  behavioral_engine → 9 detectors + composite (known patterns, deterministic)
  alternatives_engine → 5 constant scenarios

New — Code (deterministic):
  pattern_engine:
    enrichment    → regime-tagged trades + enriched trade summary text
    known patterns → sequences, loops, calendar effects, drawdown responses
    temporal drift → multi-scale behavioral evolution (granular + phase + halves)
  scenario_engine → behavior-corrected replay, regime-aware, discipline-enforced, SIP-through-crash

New — AI (Claude at conversation time):
  receives: enriched trade summary (full history) + coded pattern results + scenarios
  discovers: patterns not pre-coded (cross-instrument flows, symbol habits, sizing shifts)
  synthesizes: cross-pattern chains, severity judgment, behavioral narrative
  selects: which insights to highlight, how to frame recommendations
```

## Shared Data Types

All market data inputs follow consistent shapes across both engines:

| Parameter | Type | Shape | Example |
|---|---|---|---|
| `nifty_data` | `dict[str, float]` | date string → Nifty close | `{"2024-01-15": 21743.5, ...}` |
| `vix_data` | `dict[str, float]` | date string → India VIX close | `{"2024-01-15": 14.2, ...}` |
| `stock_price_data` | `dict[str, dict[str, float]]` | symbol → (date string → close) | `{"RELIANCE": {"2024-01-15": 2500.0, ...}}` |
| `current_prices` | `dict[str, float]` | symbol → latest price/NAV | `{"RELIANCE": 1350.5, "119551": 103.88}` |
| `mf_nav` | `dict[str, float]` | date string → NAV | `{"2024-01-15": 45.23, ...}` |
| `actual_return` | `dict` | matches `alternatives_engine` | `{"final_value": float, "xirr": float, "total_invested": float}` |

`stock_price_data` uses the same shape for equities and indices. Index
tickers (e.g. `"NIFTY 50"`) use the same `symbol → dates → close` shape.
The tools layer is responsible for fetching and converting to these shapes.

When a date is missing from market data (weekend, holiday), functions use
nearest available date within a ±5 day window (via `_nearest_value` helper).
If no value found, the trade is skipped for that analysis with a warning.

## Pattern Engine (`portfolio_doctor/core/pattern_engine.py`)

Two responsibilities:
1. **Enrichment** — regime-tag every trade with market context so Claude can
   reason about them (deterministic, pure computation)
2. **Known pattern detection** — find sequences, loops, calendar effects, and
   drawdown responses using explicit rules (deterministic baseline)

Claude receives BOTH the enriched trades AND the coded pattern results. The
coded results are a starting point — Claude discovers additional patterns from
the enriched data that no rule anticipated. See "Claude's Role" section.

### Regime Tagging

`tag_trades_with_regime(trades, nifty_data, vix_data) → list[dict]`

Annotates each trade with market state at the time of execution.

Added fields per trade:
- `regime`: one of `crash`, `correction`, `recovery`, `bull`, `sideways`
- `nifty_drawdown_pct`: Nifty distance from 52-week peak (negative)
- `vix_level`: India VIX on trade date
- `nifty_vs_200dma_pct`: Nifty % above/below 200 DMA

Classification rules (evaluated in priority order — first match wins):

| Priority | Condition | Regime |
|---|---|---|
| 1 | Nifty >10% below running 52w peak AND VIX >20 | `crash` |
| 2 | Nifty 5-10% below running 52w peak, OR VIX 18-20 (and not crash) | `correction` |
| 3 | Prior regime (within last 60 days) was `crash` or `correction`, AND Nifty has risen >3% from the drawdown trough | `recovery` |
| 4 | Nifty <2% below running 52w peak | `bull` |
| 5 | Everything else | `sideways` |

Regime tagging is **stateful** — computed sequentially across the date range,
not per-trade in isolation. The function walks the full `nifty_data` series
chronologically, maintaining running peak, prior regime, and trough level.
Trades are then tagged by looking up the regime on their date.

When VIX data is unavailable for a date, VIX-dependent conditions are skipped
(crash requires drawdown >10% only; correction uses drawdown 5-10% only).

**Note**: a day with Nifty >10% below peak but VIX <18 (calm VIX during
structural decline) falls to `correction` via the drawdown-only path, not
`sideways`. The VIX condition is additive, not required.

**52-week peak**: rolling maximum of Nifty close over prior 252 trading days.
**200 DMA**: simple moving average of prior 200 trading-day closes, computed
from `nifty_data` directly (no external dependency).

### Sequence Detection

`detect_sequences(trades, nifty_data, stock_price_data) → list[dict]`

Finds multi-trade patterns that link cause and effect:

| Sequence type | Detection rule | Cost calculation |
|---|---|---|
| `sell_then_rebuy_higher` | SELL of symbol X, then BUY of X within 60 days at price > sell price | `(rebuy_price - sell_price) × quantity` |
| `panic_sell_miss_recovery` | SELL during `crash`/`correction` regime, no rebuy within 90 days, stock recovers >20% | `sell_quantity × recovery_price - sell_amount` |
| `fomo_buy_then_loss` | BUY during `bull` regime when stock >20% above 200 DMA, then position declines >10% within 60 days | `quantity × (buy_price - price_60d_later)` |
| `sip_stop_during_crash` | SIP active, then SIP stops within 30 days of a crash regime starting | Opportunity cost: missed SIPs × NAV at hypothetical dates |

Each sequence dict:
```python
{
    "type": str,          # sequence type name
    "trades": list,       # the linked trades
    "gap_days": int,      # days between first and last trade in sequence
    "cost": float,        # estimated rupee cost of this sequence
    "regime_at_start": str,
    "regime_at_end": str,
}
```

### Behavioral Loop Counting

`count_behavioral_loops(sequences) → list[dict]`

Groups sequences by type and symbol to identify repeating cycles:

```python
{
    "pattern": str,           # e.g. "sell_then_rebuy_higher"
    "occurrences": int,
    "total_cost": float,
    "symbols": list[str],     # which stocks this happened with
    "date_ranges": list,      # [{"start": date, "end": date}, ...]
    "avg_gap_days": float,
    "is_worsening": bool,     # cost per occurrence increasing over time?
}
```

A loop requires `occurrences >= 2`. `is_worsening` is true if the cost of the
most recent half of occurrences exceeds the earlier half.

### Temporal Drift (Multi-Scale)

`compute_temporal_drift(trades, nifty_data, stock_price_data) → dict`

Analyzes behavioral change at multiple time scales, adaptive to the client's
history length. Runs a subset of existing behavioral detectors per window:
- `detect_overtrading` (trade frequency)
- `detect_panic_selling` (sell during drawdowns)
- `detect_fomo_buying` (buy near peaks)
- `detect_herd_behavior` (buy after rallies)

**Three analysis scales:**

| Scale | Window size | Slide | Purpose | Min history |
|---|---|---|---|---|
| `granular` | 12 months | 6 months | Detect recent shifts | 18 months |
| `phase` | Split at major Nifty drawdowns (>10%) | Event-driven | Compare behavior across market cycles | 3 years + ≥1 drawdown |
| `halves` | First half vs second half of full history | — | Simple evolution check | 2 years |

`phase` windows are defined by major market events: split the timeline at
each Nifty drawdown >10% from peak. Each segment between drawdowns is one
phase, labeled by its date range. This naturally groups behavior by market
cycle rather than arbitrary calendar boundaries.

Returns a single dict:

```python
{
    "granular_windows": [
        {
            "period": "2020-H1",
            "start_date": date,
            "end_date": date,
            "trade_count": int,
            "scores": {
                "overtrading": float,
                "panic_selling": float,
                "fomo_buying": float,
                "herd_behavior": float,
            },
            "composite": float,
        },
        ...
    ],
    "phase_windows": [
        {
            "phase": "Pre-COVID (2018-01 to 2020-02)",
            "start_date": date,
            "end_date": date,
            "trade_count": int,
            "scores": {...},
            "composite": float,
            "triggering_drawdown_pct": float | None,
        },
        ...
    ],
    "halves": {
        "first_half": {"period": str, "scores": {...}, "composite": float},
        "second_half": {"period": str, "scores": {...}, "composite": float},
        "change": float,   # second_half.composite - first_half.composite
    },
    "trend": {
        "trend_direction": "worsening" | "improving" | "stable",
        "worst_period": str,
        "best_period": str,
        "inflection_points": list[str],
    },
}
```

The per-window `composite` is the simple average of the 4 detector scores
(not the full 9-detector weighted composite from `behavioral_engine`).

`trend` is computed from `granular_windows` if ≥3 exist, else from `halves`.
Direction: `worsening` if composite declined >0.15 over last 3+ windows,
`improving` if increased >0.15, else `stable`. Inflection points are windows
where composite changed direction by >0.2.

**Degraded mode by history length:**

| History | What runs |
|---|---|
| <18 months | `halves` only (full history = one window). `granular_windows` and `phase_windows` empty. `trend_direction` = `"stable"`. |
| 18 months – 3 years | `granular_windows` + `halves`. `phase_windows` empty unless a drawdown occurred. |
| 3+ years | All three scales. |

### Calendar Pattern Detection

`detect_calendar_patterns(trades) → list[dict]`

Groups trades by:
- Month of year
- Day of week
- Proximity to known events (budget: Feb 1, expiry: last Thu of month,
  quarter-end: Mar/Jun/Sep/Dec)

Uses chi-squared test against uniform distribution. Requires minimum 20 trades
total and expected frequency ≥ 5 per bin (standard chi-squared validity).
If trade count is too low, returns empty list. Patterns with p < 0.05:

```python
{
    "pattern": str,           # e.g. "sells_cluster_near_expiry"
    "description": str,
    "frequency": float,       # proportion of trades matching
    "expected_frequency": float,
    "p_value": float,
    "trades_matching": int,
}
```

### Drawdown Response Table

`build_drawdown_response_table(trades, nifty_data, threshold=0.05) → list[dict]`

For every distinct Nifty drawdown exceeding `threshold` during the client's
history. A drawdown episode starts when Nifty falls below `threshold` from
its running peak and ends when Nifty recovers to within 2% of the prior peak
(or a new peak is set). Minimum 10 trading days between episodes to avoid
counting the same correction multiple times.

```python
{
    "drawdown_start": date,
    "drawdown_trough": date,
    "drawdown_pct": float,        # e.g. -0.15
    "client_response": str,       # "sold" | "bought" | "held" | "mixed"
    "trades_during": list,
    "net_action": float,          # net buy(+) or sell(-) amount during drawdown
    "outcome_30d_pct": float,     # Nifty change 30 days after trough
    "outcome_90d_pct": float,     # Nifty change 90 days after trough
    "was_good_response": bool,    # bought or held AND market recovered
}
```

### Enriched Trade Summary (for Claude)

`build_enriched_trade_summary(regime_tagged_trades) → str`

Produces a compact, human-readable text representation of the full trade
history designed for Claude to scan and discover patterns. One line per trade:

```
2016-03-10 | BUY   | RELIANCE  | ₹45,000 | 20 shares @ ₹2,250 | bull    | Nifty -1% from peak | VIX 15
2016-09-05 | SIP   | 119551    | ₹5,000  | 48 units  @ ₹103.8 | sideways| Nifty -4% from peak | VIX 16
2020-03-23 | SELL  | RELIANCE  | ₹28,000 | 20 shares @ ₹1,400 | crash   | Nifty -35% from peak| VIX 72
2020-04-15 | BUY   | RELIANCE  | ₹33,000 | 20 shares @ ₹1,650 | recovery| Nifty -22% from peak| VIX 38
```

Format: `date | action | symbol | amount | qty @ price | regime | nifty_context | vix`

For clients with >500 trades, the summary is NOT truncated. A 2,000-trade
summary at ~100 chars/line is ~200K chars — within Claude's context window.
The full history is essential for pattern discovery.

This text is returned as part of the `deep_analysis` tool output so Claude
can reason about it at conversation time.

### Pattern Summary

`build_pattern_summary(trades, nifty_data, vix_data, stock_price_data, sip_patterns, behavioral_audit) → dict`

Orchestrates all of the above into a single output:

```python
{
    "client_name": str,
    "analysis_date": date,
    "trade_span_years": float,
    "enriched_trade_summary": str,   # compact text for Claude (see above)
    "regime_tagged_trades": list,    # all trades with regime annotations (structured)
    "sequences": list,
    "loops": list,
    "temporal_drift": dict,          # multi-scale: granular + phase + halves + trend
    "calendar_patterns": list,
    "drawdown_responses": list,
    "costliest_loop": dict | None,
    "behavioral_evolution": str,     # "worsening" | "improving" | "stable"
}
```

Saved to `data/portfolios/{client}/pattern_summary.json`.

**Note on `enriched_trade_summary`**: this is the key input for Claude's
AI-driven pattern discovery. The deterministic results (sequences, loops,
calendar patterns) serve as a baseline that Claude can confirm, override,
or augment with patterns it discovers from scanning the full enriched history.

## Scenario Engine (`portfolio_doctor/core/scenario_engine.py`)

Builds personalized what-if scenarios based on pattern engine output.

### Behavior-Corrected Replay

`simulate_behavior_corrected(trades, pattern, instances, current_prices, stock_price_data) → dict`

Replays the client's actual trade history but removes specific trade instances
that match a behavioral pattern, then rebuilds the portfolio from scratch.

**Inputs:**
- `trades`: full trade list
- `pattern`: pattern name (e.g. `"panic_selling"`)
- `instances`: list of trade dicts to remove — sourced from either
  `behavioral_audit["detectors"][pattern]["instances"]` or
  `pattern_summary["sequences"]` (for sequence-type patterns like
  `sell_then_rebuy_higher`). Each instance contains the trade(s) to remove,
  identified by `date` + `symbol` + `action` + `amount`.
- `current_prices`, `stock_price_data`: for valuation

**Replay pipeline:**

1. **Filter**: copy `trades` list, remove all trades matching instances
   (matched by `date` + `symbol` + `action` + `amount` for disambiguation
   when same-day duplicates exist)
2. **Rebuild ledger**: pass filtered trades through `build_position_ledger()`
   from `csv_parser` — this recomputes FIFO lots, avg cost, quantities
3. **Value positions**: multiply each position's quantity by `current_prices`
4. **Rebuild cash flows**: pass filtered trades through `build_cash_flows()`
5. **Compute XIRR**: call `compute_xirr()` with rebuilt cash flows +
   terminal value at today's date
6. **Compute totals**: `total_invested` = sum of all inflow amounts in
   filtered trades

**How removal works per pattern type:**

| Pattern | What "remove" means | Instances source |
|---|---|---|
| `panic_selling` | Delete the sell trade(s). Client holds instead. | `behavioral_audit["detectors"]["panic_selling"]["instances"]` |
| `fomo_buying` | Delete the buy trade(s). Cash stays uninvested. | `behavioral_audit["detectors"]["fomo_buying"]["instances"]` |
| `herd_behavior` | Delete herd-flagged buys. Same as FOMO. | `behavioral_audit["detectors"]["herd_behavior"]["instances"]` |
| `overtrading` | Remove both legs of round-trip pairs. Hold from first buy. | `behavioral_audit["detectors"]["overtrading"]["instances"]` |
| `sell_then_rebuy_higher` | Remove both the sell and rebuy trades. | `pattern_summary["sequences"]` filtered by type |

Return shape matches `alternatives_engine` conventions:
```python
{
    "scenario": "behavior_corrected",
    "pattern_removed": str,
    "instances_removed": int,
    "total_invested": float,
    "final_value": float,
    "xirr": float,
    "vs_actual": {
        "value_difference": float,
        "return_difference_pct": float,
        "interpretation": str,
    },
    "explanation": str,
}
```

### Regime-Aware Timing

`simulate_regime_aware_buying(cash_flows, nifty_data, vix_data, target_regime="correction") → dict`

Note: `stock_price_data` is not needed — all delayed buys route through the
Nifty proxy NAV. Regime classification uses `nifty_data` + `vix_data` only.

Same investment amounts as actual, but each buy is delayed until the next
window where the market enters `target_regime`. If no qualifying window within
90 calendar days, invest anyway (avoid cash drag distortion).

**Investment vehicle**: all delayed buys go into a Nifty 50 proxy NAV (same
as `simulate_nifty_sip`). The point is to measure the timing benefit, not
stock selection. This applies uniformly to both equity and MF cash flows.

**MF-only clients**: scenario still runs — all SIP/BUY flows are treated
the same. The comparison is "your actual timing vs correction-only timing"
regardless of instrument type.

Return shape: same as above with `"scenario": "regime_aware_timing"`,
plus `"buys_delayed": int`, `"avg_delay_days": float`.

### Discipline-Enforced

`simulate_discipline_enforced(trades, rule, current_prices, stock_price_data) → dict`

Replays trades but applies a constraint. Trades violating the rule are skipped.

**Rule types:**

| Rule | Config | Logic |
|---|---|---|
| `max_trades_per_month` | `{"type": "max_trades_per_month", "limit": 1}` | After `limit` trades in a calendar month, skip remaining |
| `only_below_200dma` | `{"type": "only_below_200dma"}` | Skip BUY if stock price > 200 DMA at trade date |
| `min_holding_days` | `{"type": "min_holding_days", "days": 180}` | Skip SELL if holding period < `days` |

Return shape: same convention with `"scenario": "discipline_enforced"`,
plus `"rule_applied"` and `"trades_skipped": int`.

### SIP Through Crash

`simulate_sip_through_crash(trades, sip_patterns, mf_nav, crash_dates) → dict`

For each SIP that stopped during a crash window (from `detect_sip_discipline`),
extend it through the crash at the same monthly amount and NAV.

Return shape: same convention with `"scenario": "sip_through_crash"`.

### Dynamic Scenario Selector

`select_dynamic_scenarios(pattern_summary, behavioral_audit) → list[dict]`

Returns an ordered list of up to 3 scenario specs to execute:

```python
[
    {
        "type": "behavior_corrected",
        "params": {"pattern": "panic_selling"},
        "reason": "Costliest pattern: 5 panic sells costing ₹1.2L",
        "priority": 1,
    },
    ...
]
```

**Selection priority:**

| Priority | Condition | Scenario | Instance source |
|---|---|---|---|
| 1 (always) | Costliest pattern by `cost_estimate` — checked in order: (a) `pattern_summary["costliest_loop"]` if exists, (b) highest-cost detector from `behavioral_audit["detectors"]` | `behavior_corrected` | Loop: `pattern_summary["sequences"]` filtered by loop type. Detector: `behavioral_audit["detectors"][pattern]["instances"]` |
| 2 | FOMO or panic score ≤ -0.3 in `behavioral_audit` | `regime_aware_timing` targeting `correction` | Uses `cash_flows` (no instances needed) |
| 3 (one of) | Overtrading score ≤ -0.3 | `discipline_enforced` with `max_trades_per_month=1` | Replays full `trades` with rule filter |
| 3 (one of) | Herd behavior score ≤ -0.3 | `discipline_enforced` with `only_below_200dma` | Replays full `trades` with rule filter |
| 3 (one of) | SIP discipline issues (score ≤ -0.3 or `sip_stop_during_crash` sequences exist) | `sip_through_crash` | Uses `sip_patterns` + crash dates |

If multiple priority-3 candidates, pick by highest `cost_estimate`.

**No-pattern fallback**: if `behavioral_audit` shows no pattern with score
≤ -0.3 and no loops exist, the selector returns 0 dynamic scenarios. The
5 constant scenarios are always shown regardless.

### Orchestrator

`run_dynamic_scenarios(trades, cashflows, sip_patterns, pattern_summary, behavioral_audit, actual_return, current_prices, nifty_data, vix_data, stock_price_data, mf_nav, crash_dates) → dict`

1. Calls `select_dynamic_scenarios`
2. Runs each selected scenario
3. Attaches `vs_actual` comparison
4. Returns `{"selected_scenarios": list, "results": list}`

Saved to `data/portfolios/{client}/dynamic_scenarios.json`.

## What-If Scenarios — Final Structure

### Always shown (5 constant, from `alternatives_engine`, unchanged)

| # | Scenario |
|---|---|
| 1 | Nifty 50 SIP |
| 2 | Popular MF SIP |
| 3 | 70/30 Model |
| 4 | Buy & Hold |
| 5 | No Re-entry |

### Personalized (1-3 dynamic, from `scenario_engine`)

Selected per client based on detected patterns. Each includes:
- The simulation result (invested, final value, XIRR, vs actual)
- `reason`: why this scenario was chosen for this client
- `explanation`: what was changed from actual behavior

### Report presentation

The HTML report shows constant scenarios first, then a labeled divider
"Personalized — based on your trading patterns", then dynamic scenarios with
the reason displayed below each row.

## Claude's Role at Conversation Time

Claude receives `pattern_summary` (including the `enriched_trade_summary`
text), `behavioral_audit`, and `dynamic_scenarios`. Claude does two things:
validates/interprets the deterministic results AND discovers new patterns
from the enriched trade data.

### What Claude receives

| Data | Format | Purpose |
|---|---|---|
| `enriched_trade_summary` | Text, one line per trade with regime context | **Primary input for AI pattern discovery** — Claude scans the full history |
| `sequences` + `loops` | Structured JSON | Deterministic baseline — Claude confirms, overrides, or augments |
| `temporal_drift` | Multi-scale windows with scores | Behavioral evolution data for narrative generation |
| `calendar_patterns` | Structured JSON | Statistical findings for Claude to interpret |
| `drawdown_responses` | Per-event response table | How client reacted to each market crisis |
| `behavioral_audit` | Existing 9 detector results | Point-in-time findings |
| `dynamic_scenarios` | Scenario results + reasons | Personalized what-if results |

### AI Pattern Discovery (from enriched trades)

Claude scans the `enriched_trade_summary` — the complete trade history with
regime annotations — and looks for patterns that no detector was coded for.

Examples of patterns only Claude can find:
- **Cross-instrument flows**: "You redeem MFs 3-5 days before equity buys —
  liquidating MFs to fund stock purchases on impulse"
- **Symbol-specific habits**: "You've bought RELIANCE 11 times, always within
  3 days of a >5% single-day drop, but hold only 45 days on average"
- **Regime-behavior mismatch**: "You buy aggressively in bull regimes but go
  completely silent during corrections — missing the best entry points"
- **Position sizing shifts**: "Your trade sizes doubled after 2020 — larger
  bets after early wins, classic overconfidence"
- **Timing clusters**: "80% of your sells happen on Mondays — possible
  weekend anxiety driving decisions"

These patterns emerge from Claude reading the full enriched history. They
are not pre-coded and will differ per client.

### Cross-Pattern Chain Reasoning

Connects separate detectors and sequences into behavioral narratives:
"You panic sell during crashes, sit in cash for 2-4 weeks, then FOMO buy back
at higher prices. This 3-step cycle has cost ₹X over N occurrences."

### Context-Aware Severity Judgment

Rules flag patterns; Claude judges whether they matter given full context.
A panic sell that was re-entered at lower levels isn't harmful. A panic sell
that missed a 40% recovery is devastating. Same flag, different judgment.

### Behavioral Evolution Narrative

From temporal drift data (especially `phase_windows` and `halves`), Claude
generates the story of how behavior changed across market cycles:
"You were disciplined during 2016-2019 (composite 7.2/10), but after the
COVID crash your trading frequency tripled and never came back down.
Your behavioral score has declined from 7.2 to 4.1 across two market cycles."

## MCP Integration

### New tool

`deep_analysis(client_name) → dict`

Runs pattern engine + scenario engine. Returns combined output. Cached.
Requires `ingest_trades` first.

### Updated tools

- `full_report_data` — includes `dynamic_scenarios` and `pattern_summary`
  sections if they exist (from prior `deep_analysis` call)
- `generate_report` — HTML template updated to render personalized scenario
  section and pattern insights

### System prompt additions

```
deep_analysis(client_name)
  → Use when asked "What are my patterns?", "Why do I keep losing money?",
    "Give me the deep analysis", "What would happen if I changed my behavior?"
  → START with behavioral_audit or full_report_data for basic questions.
    Use deep_analysis when the user wants AI-driven insights or personalized
    scenarios beyond the standard report.
  → Returns enriched_trade_summary (full trade history with market context),
    coded pattern results, and dynamic scenario simulations.
  → YOUR JOB after receiving deep_analysis results:
    1. Review the coded patterns (sequences, loops, calendar) — confirm or
       qualify them based on context
    2. Scan the enriched_trade_summary for patterns the detectors missed —
       look for cross-instrument flows, symbol-specific habits, timing
       clusters, position sizing shifts, regime-behavior mismatches
    3. Synthesize: connect coded + discovered patterns into a behavioral
       narrative — what is this client's core tendency and how has it
       evolved?
    4. Present dynamic scenarios with the behavioral context — "because
       you tend to X, we simulated what happens if you stopped"
```

## Data Requirements

| Data | Source | Already available? |
|---|---|---|
| Nifty daily close (10-20 years) | Kite OHLC or yfinance `^NSEI` | Yes via `shared/price_history.py` |
| India VIX daily | Kite or yfinance `^INDIAVIX` | Yes via `tools/derivatives_tools.py` |
| Per-stock daily close | Kite OHLC or yfinance | Yes via `shared/price_history.py` |
| Per-stock 200 DMA | Computed from close series | Yes via `tools/technicals_tools.py` |
| MF NAV history | mftool | Yes via `shared/mf_client.py` |

No new data sources required. All inputs come from existing infrastructure.

Portfolio-doctor tools fetch VIX data via `shared/price_history.py` using
yfinance `^INDIAVIX` (same infrastructure as india-markets but accessed
through the shared package, not through india-markets MCP tools).

## Edge Cases & Degraded Mode

| Condition | Behavior |
|---|---|
| **Short history (<1 year)** | Regime tagging works (uses available Nifty data). Sequences may be empty. Temporal drift produces 1 window, trend = `"stable"`. Calendar patterns skipped (<20 trades). Dynamic scenarios may return 0 results. |
| **MF-only client (no equities)** | Sequence types `sell_then_rebuy_higher` and `fomo_buy_then_loss` return empty (these require stock prices). `panic_sell_miss_recovery` still works for MF sells. `regime_aware_timing` and `sip_through_crash` work normally. `discipline_enforced` with `only_below_200dma` is skipped (no DMA for MFs). |
| **Very few trades (<5)** | Pattern engine runs but most outputs are empty lists. No loops (need ≥2 occurrences). Calendar patterns skipped. `build_pattern_summary` returns valid structure with empty fields. |
| **No patterns detected** | `select_dynamic_scenarios` returns empty list. Only the 5 constant scenarios are shown. Report omits the personalized section. |
| **Missing VIX data** | Regime tagging uses Nifty drawdown only (VIX conditions dropped). Recovery detection uses drawdown recovery only. |

## Testing Strategy

- **pattern_engine tests**: synthetic trade lists with known sequences embedded.
  Verify regime tagging, sequence detection, loop counting, temporal drift.
  Include edge cases: short history, MF-only, no trades in a window.
- **scenario_engine tests**: replay known trade histories with removed patterns.
  Behavior-corrected replay must use the same `build_position_ledger` and
  `compute_xirr` code paths as production — not hand-rolled totals. Verify
  that removing a panic sell correctly rebuilds FIFO lots and cash flows.
- **Scenario selector tests**: verify priority ordering, fallback to 0 dynamic
  scenarios when no patterns detected, correct instance source mapping.
- **Integration test**: full pipeline from CSV → pattern summary → dynamic
  scenarios with mocked market data. Verify JSON output shapes match spec.

## Future: Cross-Client Patterns (not built now)

The `pattern_summary.json` structure is designed to be aggregatable. Future
work could:
- Load summaries across multiple clients
- Identify common behavioral archetypes
- Build predictive models: "clients with pattern X in years 1-3 tend to do Y"
- Enable Claude to say: "You match the 'reactive trader' archetype — here's
  what usually helps clients like you"

This requires `>50` client datasets and is out of scope for this spec.
