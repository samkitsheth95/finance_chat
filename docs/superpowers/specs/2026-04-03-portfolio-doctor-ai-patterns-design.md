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
  behavioral_engine → 9 detectors + composite
  alternatives_engine → 5 constant scenarios

New:
  pattern_engine → regime tags, sequences, loops, drift, calendar, drawdown responses
  scenario_engine → behavior-corrected replay, regime-aware, discipline-enforced, SIP-through-crash
  Claude → cross-pattern chains, unanticipated patterns, severity judgment, narrative
```

## Pattern Engine (`portfolio_doctor/core/pattern_engine.py`)

Deterministic enrichment of the trade history. All functions are pure
computation — no LLM calls, no network beyond what's passed in.

### Regime Tagging

`tag_trades_with_regime(trades, nifty_data, vix_data) → list[dict]`

Annotates each trade with market state at the time of execution.

Added fields per trade:
- `regime`: one of `crash`, `correction`, `recovery`, `bull`, `sideways`
- `nifty_drawdown_pct`: Nifty distance from 52-week peak (negative)
- `vix_level`: India VIX on trade date
- `nifty_vs_200dma_pct`: Nifty % above/below 200 DMA

Classification rules:

| Condition | Regime |
|---|---|
| Nifty >10% below 52w peak AND VIX >20 | `crash` |
| Nifty 5-10% below peak OR VIX 18-20 | `correction` |
| Was in crash/correction within last 60 days, now rising | `recovery` |
| Nifty <2% from 52w peak | `bull` |
| Everything else | `sideways` |

Inputs: `nifty_data` is `dict[str, float]` (date string → close).
`vix_data` is `dict[str, float]` (date string → VIX close). Both fetched by
the tools layer from Kite/yfinance.

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

### Temporal Drift

`compute_temporal_drift(trades, nifty_data, stock_price_data, window_months=12) → list[dict]`

Splits the client's full trading history into rolling windows (default 12
months, sliding by 6 months). Runs a subset of existing behavioral detectors
per window:
- `detect_overtrading` (trade frequency)
- `detect_panic_selling` (sell during drawdowns)
- `detect_fomo_buying` (buy near peaks)
- `detect_herd_behavior` (buy after rallies)

Returns per-window scores:
```python
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
}
```

Also computes trend metadata:
```python
{
    "trend_direction": "worsening" | "improving" | "stable",
    "worst_period": str,
    "best_period": str,
    "inflection_points": list,  # periods where score changed direction significantly
}
```

### Calendar Pattern Detection

`detect_calendar_patterns(trades) → list[dict]`

Groups trades by:
- Month of year
- Day of week
- Proximity to known events (budget: Feb 1, expiry: last Thu of month,
  quarter-end: Mar/Jun/Sep/Dec)

Uses chi-squared test against uniform distribution. Patterns with p < 0.05:

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

For every Nifty drawdown exceeding `threshold` during the client's history:

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

### Pattern Summary

`build_pattern_summary(trades, nifty_data, vix_data, stock_price_data, sip_patterns, behavioral_audit) → dict`

Orchestrates all of the above into a single output:

```python
{
    "client_name": str,
    "analysis_date": date,
    "trade_span_years": float,
    "regime_tagged_trades": list,   # all trades with regime annotations
    "sequences": list,
    "loops": list,
    "temporal_drift": {
        "windows": list,
        "trend": dict,
    },
    "calendar_patterns": list,
    "drawdown_responses": list,
    "costliest_loop": dict | None,
    "behavioral_evolution": str,    # "worsening" | "improving" | "stable"
}
```

Saved to `data/portfolios/{client}/pattern_summary.json`.

## Scenario Engine (`portfolio_doctor/core/scenario_engine.py`)

Builds personalized what-if scenarios based on pattern engine output.

### Behavior-Corrected Replay

`simulate_behavior_corrected(trades, pattern, current_prices, stock_price_data) → dict`

Replays the client's actual trade history but removes instances of a specific
behavioral pattern.

**How removal works per pattern type:**

| Pattern | What "remove" means |
|---|---|
| `panic_selling` | Delete the sell trade. Client holds the position instead. Value at current price. |
| `fomo_buying` | Delete the buy trade. Cash stays uninvested. Final value = remaining positions + saved cash. |
| `herd_behavior` | Delete herd-flagged buys. Same as FOMO removal. |
| `overtrading` | Remove round-trip pairs (buy+sell within 30 days). Hold from first buy. |
| `sell_then_rebuy_higher` | Remove both the sell and rebuy. Hold from original buy. |

Return shape matches `alternatives_engine` conventions:
```python
{
    "scenario": "behavior_corrected",
    "pattern_removed": str,
    "instances_removed": int,
    "total_invested": float,
    "final_value": float,
    "xirr": float,
    "vs_actual": {"value_difference": float, ...},
    "explanation": str,   # e.g. "Removed 5 panic sells, held positions instead"
}
```

### Regime-Aware Timing

`simulate_regime_aware_buying(cash_flows, nifty_data, vix_data, stock_price_data, target_regime="correction") → dict`

Same investment amounts as actual, but each buy is delayed until the next
window where the market enters `target_regime`. If no qualifying window within
90 calendar days, invest anyway (avoid cash drag distortion).

Buys go into a Nifty proxy (same as `simulate_nifty_sip`). The point isn't
stock selection — it's timing.

Return shape: same as above with `"scenario": "regime_aware_timing"`.

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

| Priority | Condition | Scenario |
|---|---|---|
| 1 (always) | Costliest loop or detector pattern | `behavior_corrected` targeting that pattern |
| 2 | FOMO or panic detected with score ≤ -0.3 | `regime_aware_timing` targeting `correction` |
| 3 (one of) | Overtrading score ≤ -0.3 | `discipline_enforced` with `max_trades_per_month=1` |
| 3 (one of) | Herd behavior score ≤ -0.3 | `discipline_enforced` with `only_below_200dma` |
| 3 (one of) | SIP discipline issues | `sip_through_crash` |

If multiple priority-3 candidates, pick by highest estimated cost.

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

Claude receives `pattern_summary.json` + `behavioral_audit.json` +
`dynamic_scenarios.json` and performs reasoning that cannot be pre-coded:

### Cross-Pattern Chain Reasoning

Connects separate detectors and sequences into behavioral narratives:
"You panic sell during crashes, sit in cash for 2-4 weeks, then FOMO buy back
at higher prices. This 3-step cycle has cost ₹X over N occurrences."

### Unanticipated Pattern Discovery

Examines regime-tagged trades, calendar patterns, and drawdown responses to
find patterns no detector was built for. Examples:
- "Your trade frequency triples in Jan and Sep"
- "You liquidate MFs to fund equity purchases on impulse"
- "You consistently dip-buy RELIANCE but hold only 45 days"

### Context-Aware Severity Judgment

Rules flag patterns; Claude judges whether they matter given full context.
A panic sell that was re-entered at lower levels isn't harmful. A panic sell
that missed a 40% recovery is devastating. Same flag, different judgment.

### Behavioral Evolution Narrative

From temporal drift data, generates the story of how behavior changed over
time: "Disciplined 2016-2018, deteriorated after 2020 crash, never recovered."

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

## Testing Strategy

- **pattern_engine tests**: synthetic trade lists with known sequences embedded.
  Verify regime tagging, sequence detection, loop counting, temporal drift.
- **scenario_engine tests**: replay known trade histories with removed patterns.
  Verify that holdings/values recalculate correctly.
- **Integration test**: full pipeline from CSV → pattern summary → dynamic
  scenarios with mocked market data.

## Future: Cross-Client Patterns (not built now)

The `pattern_summary.json` structure is designed to be aggregatable. Future
work could:
- Load summaries across multiple clients
- Identify common behavioral archetypes
- Build predictive models: "clients with pattern X in years 1-3 tend to do Y"
- Enable Claude to say: "You match the 'reactive trader' archetype — here's
  what usually helps clients like you"

This requires `>50` client datasets and is out of scope for this spec.
