# Portfolio Doctor — AI Patterns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add temporal pattern detection, behavioral loop analysis, multi-scale drift tracking, and personalized dynamic what-if scenarios to the portfolio doctor. Give Claude enriched trade data so it can discover patterns no detector anticipated.

**Architecture:** Two new engines (`pattern_engine.py`, `scenario_engine.py`) layered on existing code. No existing files are rewritten. Pattern engine produces deterministic enrichments; scenario engine builds personalized simulations; Claude discovers patterns from the enriched data at conversation time.

**Spec:** `docs/superpowers/specs/2026-04-03-portfolio-doctor-ai-patterns-design.md`

---

## File Structure

### New files

```
portfolio_doctor/core/
├── pattern_engine.py                    ← Regime tagging, sequences, loops, drift, calendar, drawdown, summary
└── scenario_engine.py                   ← Behavior-corrected, regime-aware, discipline-enforced, SIP-through-crash

portfolio_doctor/tools/
└── pattern_tools.py                     ← deep_analysis orchestration + data fetching

tests/portfolio_doctor/core/
├── test_pattern_engine.py               ← Pattern engine unit tests
└── test_scenario_engine.py              ← Scenario engine unit tests

tests/portfolio_doctor/tools/
└── test_pattern_tools.py                ← Pattern tools integration tests
```

### Modified files

| File | Change |
|------|--------|
| `portfolio_doctor/server/app.py` | Add `deep_analysis` + `generate_report` tools, update system prompt |
| `portfolio_doctor/tools/report_tools.py` | Include `pattern_summary` + `dynamic_scenarios` in `full_report_data` |
| `portfolio_doctor/report/template.html` | Add personalized scenarios section + pattern insights |
| `.cursor/rules/project-architecture.mdc` | Add Pattern Engine + Scenario Engine to component table |
| `.cursor/rules/portfolio-doctor-patterns.mdc` | Add new cached files, engine patterns |
| `.cursor/rules/portfolio-doctor-progress.mdc` | Replace with Phase 2 tracking |

---

## Task 1: Pattern Engine — Regime Tagging

**Files:**
- Create: `portfolio_doctor/core/pattern_engine.py`
- Create: `tests/portfolio_doctor/core/test_pattern_engine.py`

Foundation for all pattern detection. Annotates each trade with market context.

- [ ] **Step 1: Write tests for regime tagging**

Create `tests/portfolio_doctor/core/test_pattern_engine.py` with tests:
- `test_crash_regime` — Nifty >10% below peak + VIX >20 → `crash`
- `test_correction_regime` — Nifty 5-10% below peak → `correction`
- `test_recovery_regime` — after crash, Nifty risen >3% from trough → `recovery`
- `test_bull_regime` — Nifty <2% below peak → `bull`
- `test_sideways_regime` — everything else → `sideways`
- `test_stateful_regime_tracking` — verify sequential computation (crash→recovery transition)
- `test_missing_vix_degrades_gracefully` — VIX conditions skipped when VIX unavailable
- `test_200dma_computed_from_nifty_data` — verify DMA calculation

Use synthetic `nifty_data` and `vix_data` dicts with known drawdown patterns.

- [ ] **Step 2: Implement `tag_trades_with_regime()`**

Create `portfolio_doctor/core/pattern_engine.py`:
- Walk `nifty_data` chronologically, maintaining running 252-day peak, 200-day SMA, prior regime, trough level
- Classify each date using priority-ordered rules from spec
- Annotate each trade with: `regime`, `nifty_drawdown_pct`, `vix_level`, `nifty_vs_200dma_pct`
- Helper: `_compute_running_regime(nifty_data, vix_data) → dict[str, dict]` — date → regime info

- [ ] **Step 3: Run tests — verify pass**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/core/test_pattern_engine.py -v -k regime`
Expected: All regime tests PASSED

- [ ] **Step 4: Commit**

```bash
git add portfolio_doctor/core/pattern_engine.py tests/portfolio_doctor/core/test_pattern_engine.py
git commit -m "feat(pattern-engine): regime tagging with stateful classification"
```

---

## Task 2: Pattern Engine — Sequence Detection + Loop Counting

**Files:**
- Modify: `portfolio_doctor/core/pattern_engine.py`
- Modify: `tests/portfolio_doctor/core/test_pattern_engine.py`

Depends on: Task 1 (needs regime-tagged trades)

- [ ] **Step 1: Write tests for sequences**

Add to test file:
- `test_sell_then_rebuy_higher` — SELL then BUY same stock within 60 days at higher price
- `test_panic_sell_miss_recovery` — SELL during crash, no rebuy in 90 days, stock recovers >20%
- `test_fomo_buy_then_loss` — BUY during bull when stock >20% above 200 DMA, position declines >10%
- `test_sip_stop_during_crash` — SIP stops within 30 days of crash regime
- `test_no_sequences_in_clean_history` — verify empty list when no patterns match

- [ ] **Step 2: Write tests for loop counting**

Add to test file:
- `test_loop_requires_two_occurrences` — single sequence = no loop
- `test_loop_groups_by_type_and_symbol` — separate loops per pattern/symbol combo
- `test_is_worsening_flag` — recent costs > earlier costs
- `test_total_cost_aggregation`

- [ ] **Step 3: Implement `detect_sequences()`**

Add to `pattern_engine.py`:
- Iterate regime-tagged trades chronologically
- For each trade, look forward for matching pattern (sell→rebuy, panic→miss, fomo→loss, SIP stop)
- Each matched sequence returns: `type`, `trades`, `gap_days`, `cost`, `regime_at_start`, `regime_at_end`
- Use `stock_price_data` for post-trade price lookups (recovery %, decline %)

- [ ] **Step 4: Implement `count_behavioral_loops()`**

Add to `pattern_engine.py`:
- Group sequences by `(type, symbol)`
- Require `occurrences >= 2` to qualify as a loop
- Compute `is_worsening`: cost of recent half > cost of earlier half
- Return per-loop dict with `avg_gap_days`, `total_cost`, `date_ranges`

- [ ] **Step 5: Run tests — verify pass**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/core/test_pattern_engine.py -v -k "sequence or loop"`
Expected: All PASSED

- [ ] **Step 6: Commit**

```bash
git add portfolio_doctor/core/pattern_engine.py tests/portfolio_doctor/core/test_pattern_engine.py
git commit -m "feat(pattern-engine): sequence detection and behavioral loop counting"
```

---

## Task 3: Pattern Engine — Temporal Drift (Multi-Scale)

**Files:**
- Modify: `portfolio_doctor/core/pattern_engine.py`
- Modify: `tests/portfolio_doctor/core/test_pattern_engine.py`

Can run in parallel with Task 2 (both depend only on Task 1).

- [ ] **Step 1: Write tests for temporal drift**

Add to test file:
- `test_granular_windows` — 3+ year history produces 12-month sliding windows
- `test_phase_windows_split_at_drawdowns` — phases split at Nifty >10% drawdowns
- `test_halves_always_produced` — even short history gets first-half vs second-half
- `test_short_history_degraded_mode` — <18 months: only halves, granular/phase empty
- `test_trend_direction_worsening` — declining composite across windows
- `test_trend_direction_improving` — improving composite across windows
- `test_inflection_points` — detect direction change >0.2

Build synthetic trade histories spanning 4+ years with known behavioral shifts.
Need `nifty_data` with a major drawdown in the middle to test phase splitting.

- [ ] **Step 2: Implement `compute_temporal_drift()`**

Add to `pattern_engine.py`:
- Compute three scales:
  - `granular`: 12-month windows sliding by 6 months (min 18 months history)
  - `phase`: split timeline at Nifty drawdowns >10% from peak (min 3 years + 1 drawdown)
  - `halves`: first half vs second half of full history (min 2 years)
- Per window: filter trades, run 4 detectors (overtrading, panic_selling, fomo_buying, herd_behavior), compute simple average composite
- Compute `trend` from `granular_windows` if ≥3 exist, else from `halves`
- Helper: `_find_major_drawdowns(nifty_data, threshold=0.10) → list[dict]` for phase splitting

- [ ] **Step 3: Run tests — verify pass**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/core/test_pattern_engine.py -v -k drift`
Expected: All PASSED

- [ ] **Step 4: Commit**

```bash
git add portfolio_doctor/core/pattern_engine.py tests/portfolio_doctor/core/test_pattern_engine.py
git commit -m "feat(pattern-engine): multi-scale temporal drift analysis"
```

---

## Task 4: Pattern Engine — Calendar Patterns + Drawdown Responses

**Files:**
- Modify: `portfolio_doctor/core/pattern_engine.py`
- Modify: `tests/portfolio_doctor/core/test_pattern_engine.py`

Can run in parallel with Tasks 2 and 3 (depends only on Task 1 for drawdown responses).

- [ ] **Step 1: Write tests for calendar patterns**

Add to test file:
- `test_detects_expiry_clustering` — trades clustered on last Thursday of month
- `test_detects_monthly_clustering` — trades concentrated in specific months
- `test_uniform_distribution_no_pattern` — evenly spread trades return empty
- `test_too_few_trades_returns_empty` — <20 trades skips analysis
- `test_low_expected_frequency_skipped` — bins with expected <5 not tested

- [ ] **Step 2: Write tests for drawdown responses**

Add to test file:
- `test_client_sold_during_drawdown` — sell trades during Nifty drawdown → `"sold"`
- `test_client_bought_during_drawdown` — buy trades during drawdown → `"bought"`
- `test_client_held_during_drawdown` — no trades during drawdown → `"held"`
- `test_mixed_response` — both buys and sells → `"mixed"`
- `test_outcome_calculations` — verify 30d and 90d post-trough Nifty change
- `test_was_good_response` — bought/held + market recovered = True

- [ ] **Step 3: Implement `detect_calendar_patterns()`**

Add to `pattern_engine.py`:
- Group trades by: month-of-year, day-of-week, proximity to known events
- Known events: budget (Feb 1 ±5 days), expiry (last Thu ±2 days), quarter-end
- Chi-squared test against uniform distribution per grouping
- Filter: min 20 trades total, expected frequency ≥5 per bin
- Return patterns with p < 0.05

- [ ] **Step 4: Implement `build_drawdown_response_table()`**

Add to `pattern_engine.py`:
- Identify distinct Nifty drawdown episodes (>threshold from running peak)
- Episode starts when Nifty crosses below threshold, ends when within 2% of prior peak
- Min 10 trading days between episodes
- For each episode: classify client response, count trades, compute net action, 30d/90d outcomes

- [ ] **Step 5: Run tests — verify pass**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/core/test_pattern_engine.py -v -k "calendar or drawdown"`
Expected: All PASSED

- [ ] **Step 6: Commit**

```bash
git add portfolio_doctor/core/pattern_engine.py tests/portfolio_doctor/core/test_pattern_engine.py
git commit -m "feat(pattern-engine): calendar patterns and drawdown response table"
```

---

## Task 5: Pattern Engine — Enriched Summary + Orchestrator

**Files:**
- Modify: `portfolio_doctor/core/pattern_engine.py`
- Modify: `tests/portfolio_doctor/core/test_pattern_engine.py`

Depends on: Tasks 1-4 (assembles all outputs).

- [ ] **Step 1: Write tests for enriched trade summary**

Add to test file:
- `test_summary_format` — verify one-line-per-trade format with all fields
- `test_summary_includes_regime_context` — regime, nifty drawdown, VIX present
- `test_summary_not_truncated` — even 500+ trades produce full output

- [ ] **Step 2: Write tests for pattern summary orchestrator**

Add to test file:
- `test_build_pattern_summary_output_shape` — all required keys present
- `test_costliest_loop_extracted` — highest-cost loop bubbled to top
- `test_behavioral_evolution_from_drift` — maps drift trend to evolution label
- `test_empty_patterns_valid_structure` — few trades → valid structure with empty lists

- [ ] **Step 3: Implement `build_enriched_trade_summary()`**

Add to `pattern_engine.py`:
- Takes regime-tagged trades
- Produces one line per trade: `date | action | symbol | amount | qty @ price | regime | nifty_context | vix`
- Format amounts with INR comma style
- No truncation regardless of trade count

- [ ] **Step 4: Implement `build_pattern_summary()`**

Add to `pattern_engine.py`:
- Calls: `tag_trades_with_regime` → `detect_sequences` → `count_behavioral_loops` → `compute_temporal_drift` → `detect_calendar_patterns` → `build_drawdown_response_table` → `build_enriched_trade_summary`
- Assembles all results into the spec's output shape
- Extracts `costliest_loop` and `behavioral_evolution` summary fields

- [ ] **Step 5: Run full pattern engine test suite**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/core/test_pattern_engine.py -v`
Expected: All PASSED

- [ ] **Step 6: Commit**

```bash
git add portfolio_doctor/core/pattern_engine.py tests/portfolio_doctor/core/test_pattern_engine.py
git commit -m "feat(pattern-engine): enriched trade summary and pattern summary orchestrator"
```

---

## Task 6: Scenario Engine — Behavior-Corrected Replay

**Files:**
- Create: `portfolio_doctor/core/scenario_engine.py`
- Create: `tests/portfolio_doctor/core/test_scenario_engine.py`

Depends on: Task 5 (needs pattern_summary for instance data).

- [ ] **Step 1: Write tests for behavior-corrected replay**

Create `tests/portfolio_doctor/core/test_scenario_engine.py`:
- `test_remove_panic_sells_increases_value` — removing sell during crash → higher final value
- `test_remove_fomo_buys_reduces_invested` — removing FOMO buy → less capital deployed
- `test_fifo_lots_rebuilt_correctly` — after removing trades, FIFO ledger is consistent
- `test_xirr_recomputed_with_filtered_flows` — cash flows match filtered trades
- `test_no_instances_returns_unchanged` — empty instances list → same as actual
- `test_sell_then_rebuy_removal` — both sell and rebuy removed from sequence

Build synthetic trades with known panic sells and expected post-removal portfolio values.

- [ ] **Step 2: Implement `simulate_behavior_corrected()`**

Create `portfolio_doctor/core/scenario_engine.py`:
- 6-step replay pipeline from spec:
  1. Filter: copy trades, remove matching instances (match by date+symbol+action+amount)
  2. Rebuild ledger: `build_position_ledger(filtered_trades)`
  3. Value positions: quantity × current_prices
  4. Rebuild cash flows: `build_cash_flows(filtered_trades)`
  5. Compute XIRR: `compute_xirr(rebuilt_flows + terminal_value)`
  6. Compute totals: sum inflows
- Import `build_position_ledger`, `build_cash_flows` from `csv_parser`
- Import `compute_xirr` from `portfolio_engine`
- Build `vs_actual` comparison dict

- [ ] **Step 3: Run tests — verify pass**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/core/test_scenario_engine.py -v -k behavior_corrected`
Expected: All PASSED

- [ ] **Step 4: Commit**

```bash
git add portfolio_doctor/core/scenario_engine.py tests/portfolio_doctor/core/test_scenario_engine.py
git commit -m "feat(scenario-engine): behavior-corrected trade replay with FIFO rebuild"
```

---

## Task 7: Scenario Engine — Regime-Aware + Discipline + SIP-Through-Crash

**Files:**
- Modify: `portfolio_doctor/core/scenario_engine.py`
- Modify: `tests/portfolio_doctor/core/test_scenario_engine.py`

Can partially run in parallel with Task 6 (independent scenario functions).

- [ ] **Step 1: Write tests for regime-aware timing**

Add to test file:
- `test_buys_delayed_to_correction` — verify buy dates shift to correction regime
- `test_90_day_fallback` — if no correction within 90 days, invest anyway
- `test_all_flows_route_through_nifty_proxy` — even equity flows go to Nifty NAV

- [ ] **Step 2: Write tests for discipline-enforced**

Add to test file:
- `test_max_trades_per_month` — after limit, remaining trades skipped
- `test_only_below_200dma` — buys above 200 DMA skipped
- `test_min_holding_days` — sells before threshold skipped

- [ ] **Step 3: Write tests for SIP-through-crash**

Add to test file:
- `test_extends_sip_through_crash` — stopped SIP continues at same monthly amount
- `test_no_crash_sip_stop_unchanged` — SIP that didn't stop during crash → no change

- [ ] **Step 4: Implement `simulate_regime_aware_buying()`**

Add to `scenario_engine.py`:
- Walk cash flows chronologically
- For each buy: check regime at date; if not target_regime, scan forward up to 90 days
- If found, buy Nifty proxy at that date's NAV; if not found, buy at original date
- Compute XIRR of the regime-timed portfolio

- [ ] **Step 5: Implement `simulate_discipline_enforced()`**

Add to `scenario_engine.py`:
- Replay trades with rule filter
- Three rule types: `max_trades_per_month`, `only_below_200dma`, `min_holding_days`
- Each rule returns True/False for "should this trade be included?"
- After filtering, rebuild ledger + XIRR (same pipeline as behavior-corrected)

- [ ] **Step 6: Implement `simulate_sip_through_crash()`**

Add to `scenario_engine.py`:
- Identify SIPs that stopped during crash windows (from `sip_patterns` + `crash_dates`)
- Extend each stopped SIP at the same monthly amount through the crash period
- Use actual MF NAV for hypothetical purchases
- Compute additional units + final value

- [ ] **Step 7: Run tests — verify pass**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/core/test_scenario_engine.py -v`
Expected: All PASSED

- [ ] **Step 8: Commit**

```bash
git add portfolio_doctor/core/scenario_engine.py tests/portfolio_doctor/core/test_scenario_engine.py
git commit -m "feat(scenario-engine): regime-aware, discipline-enforced, and SIP-through-crash scenarios"
```

---

## Task 8: Scenario Engine — Dynamic Selector + Orchestrator

**Files:**
- Modify: `portfolio_doctor/core/scenario_engine.py`
- Modify: `tests/portfolio_doctor/core/test_scenario_engine.py`

Depends on: Tasks 6 + 7 (all scenario functions).

- [ ] **Step 1: Write tests for dynamic selector**

Add to test file:
- `test_priority_1_always_selected` — costliest pattern always picked
- `test_priority_2_regime_aware_on_panic` — panic score ≤ -0.3 triggers regime-aware
- `test_priority_3_picks_highest_cost` — among equal priority, pick by cost
- `test_no_patterns_returns_empty` — no scores ≤ -0.3 and no loops → 0 scenarios
- `test_max_3_scenarios` — never returns more than 3

- [ ] **Step 2: Write tests for orchestrator**

Add to test file:
- `test_run_dynamic_scenarios_calls_selected` — verify selected scenarios are executed
- `test_vs_actual_attached` — each result has `vs_actual` comparison
- `test_error_in_one_scenario_doesnt_break_others` — graceful per-scenario error handling

- [ ] **Step 3: Implement `select_dynamic_scenarios()`**

Add to `scenario_engine.py`:
- Check priority 1: costliest loop or detector → `behavior_corrected`
- Check priority 2: panic/FOMO score ≤ -0.3 → `regime_aware_timing`
- Check priority 3 (pick one): overtrading → `max_trades_per_month`; herd → `only_below_200dma`; SIP issues → `sip_through_crash`
- Return ordered list of up to 3 scenario specs

- [ ] **Step 4: Implement `run_dynamic_scenarios()`**

Add to `scenario_engine.py`:
- Call `select_dynamic_scenarios`
- Execute each selected scenario function with appropriate params
- Compute `vs_actual` for each
- Return `{"selected_scenarios": list, "results": list}`

- [ ] **Step 5: Run full scenario engine test suite**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/core/test_scenario_engine.py -v`
Expected: All PASSED

- [ ] **Step 6: Commit**

```bash
git add portfolio_doctor/core/scenario_engine.py tests/portfolio_doctor/core/test_scenario_engine.py
git commit -m "feat(scenario-engine): dynamic scenario selector and orchestrator"
```

---

## Task 9: MCP Tools — pattern_tools.py + Server Update

**Files:**
- Create: `portfolio_doctor/tools/pattern_tools.py`
- Modify: `portfolio_doctor/server/app.py`
- Create: `tests/portfolio_doctor/tools/test_pattern_tools.py`

Depends on: Tasks 5 + 8 (needs both engines complete).

- [ ] **Step 1: Implement `get_deep_analysis()`**

Create `portfolio_doctor/tools/pattern_tools.py`:
- Load trades, positions, sip_patterns, behavioral_audit from client dir
- Fetch Nifty data (daily close + VIX) via `shared/price_history.py`
- Fetch stock price data for all symbols in trades
- Call `build_pattern_summary()` from pattern engine
- Call `run_dynamic_scenarios()` from scenario engine
- Save `pattern_summary.json` and `dynamic_scenarios.json`
- Return combined output including `enriched_trade_summary` for Claude

Network boundary seams (mockable for tests):
- `_fetch_nifty_history(start, end)` — Nifty close series
- `_fetch_vix_history(start, end)` — VIX close series
- `_fetch_all_stock_prices(symbols, start, end)` — per-stock close series
- `_fetch_mf_navs(scheme_codes, start, end)` — MF NAV series

- [ ] **Step 2: Write tests**

Create `tests/portfolio_doctor/tools/test_pattern_tools.py`:
- `test_deep_analysis_returns_pattern_summary` — verify output contains all pattern fields
- `test_deep_analysis_returns_dynamic_scenarios` — verify scenario results present
- `test_deep_analysis_includes_enriched_summary` — verify text summary present
- `test_deep_analysis_saves_to_disk` — verify JSON files created
- `test_deep_analysis_handles_missing_client` — error handling
Mock all network calls.

- [ ] **Step 3: Update server/app.py**

Add `deep_analysis` tool registration:
```python
@mcp.tool()
def deep_analysis(client_name: str) -> dict:
    """
    Run AI-powered deep analysis — patterns, behavioral loops, personalized scenarios.
    ...
    """
    return get_deep_analysis(client_name)
```

Update system prompt with `deep_analysis` usage guidance from spec.

- [ ] **Step 4: Run tests — verify pass**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/tools/test_pattern_tools.py -v`
Expected: All PASSED

- [ ] **Step 5: Verify server starts**

Run: `.venv/bin/python -c "from portfolio_doctor.server.app import mcp; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add portfolio_doctor/tools/pattern_tools.py portfolio_doctor/server/app.py tests/portfolio_doctor/tools/test_pattern_tools.py
git commit -m "feat: add deep_analysis MCP tool — patterns + dynamic scenarios"
```

---

## Task 10: Report Updates — full_report_data + HTML Template

**Files:**
- Modify: `portfolio_doctor/tools/report_tools.py`
- Modify: `portfolio_doctor/report/template.html`

Depends on: Task 9 (needs pattern_summary and dynamic_scenarios data).

- [ ] **Step 1: Update `get_full_report_data()`**

In `report_tools.py`:
- Add optional loading of `pattern_summary.json` and `dynamic_scenarios.json`
- If they exist (from prior `deep_analysis` call), include in output:
  - New section G: `"pattern_insights"` — behavioral evolution, costliest loop, drawdown responses
  - New section H: `"dynamic_scenarios"` — personalized scenario results with reasons
- If they don't exist, sections G and H are omitted (backward compatible)

- [ ] **Step 2: Update HTML template**

In `template.html`:
- Add new section after constant scenarios: "Personalized — based on your trading patterns"
- Render dynamic scenario rows with `reason` displayed below each
- Add pattern insights section: behavioral evolution timeline, drawdown response summary
- Conditional rendering: sections only appear if data exists in `REPORT_DATA`

- [ ] **Step 3: Test with existing client data**

Verify that `generate_report` still works for clients without deep_analysis run.

- [ ] **Step 4: Commit**

```bash
git add portfolio_doctor/tools/report_tools.py portfolio_doctor/report/template.html
git commit -m "feat: include pattern insights and dynamic scenarios in full report"
```

---

## Task 11: Update .cursor/rules + Project Memory

**Files:**
- Modify: `.cursor/rules/project-architecture.mdc`
- Modify: `.cursor/rules/portfolio-doctor-patterns.mdc`
- Modify: `.cursor/rules/portfolio-doctor-progress.mdc`

- [ ] **Step 1: Update project-architecture.mdc**

Add Pattern Engine and Scenario Engine to the Portfolio Doctor component table.
Add `deep_analysis` to the MCP Server tool count.

- [ ] **Step 2: Update portfolio-doctor-patterns.mdc**

Add new cached files to Client Data Storage section:
- `pattern_summary.json`
- `dynamic_scenarios.json`

Add Pattern Engine function pattern (pure computation, regime tagging).
Add Scenario Engine pattern (replay pipeline, 6-step behavior-corrected).

- [ ] **Step 3: Update portfolio-doctor-progress.mdc**

Mark all Phase 2 tasks complete.

- [ ] **Step 4: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add .cursor/rules/
git commit -m "docs: update cursor rules with AI patterns architecture and progress"
```

---

## Summary

| Task | What it builds | Depends on |
|------|---------------|------------|
| 1 | Regime tagging (foundation) | — |
| 2 | Sequence detection + loop counting | 1 |
| 3 | Temporal drift (multi-scale) | 1 |
| 4 | Calendar patterns + drawdown responses | 1 |
| 5 | Enriched summary + orchestrator | 1, 2, 3, 4 |
| 6 | Behavior-corrected replay | 5 |
| 7 | Regime-aware + discipline + SIP-through-crash | 1 (partially 5) |
| 8 | Dynamic selector + orchestrator | 6, 7 |
| 9 | MCP tools + server update | 5, 8 |
| 10 | Report updates (full_report_data + HTML) | 9 |
| 11 | .cursor/rules updates | 10 |
| **Total** | | **11 tasks** |

### Dependency graph

```
Task 1 (regime tagging)
  ├→ Task 2 (sequences + loops)  ─┐
  ├→ Task 3 (temporal drift)     ─┤
  └→ Task 4 (calendar + drawdown)┘
                                  └→ Task 5 (enriched summary + orchestrator)
                                      ├→ Task 6 (behavior-corrected replay)  ─┐
                                      └→ Task 7 (other scenarios)            ─┤
                                                                              └→ Task 8 (selector + orchestrator)
                                                                                  └→ Task 9 (MCP tools)
                                                                                      └→ Task 10 (report updates)
                                                                                          └→ Task 11 (rules)
```

Tasks 2, 3, 4 can run in parallel after Task 1.
Tasks 6 and 7 can partially run in parallel after Task 5.
