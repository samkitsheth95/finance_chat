"""
Alternatives Engine — 5 "what if" scenario comparisons.

Same cash flows, different vehicles. Each scenario function takes the client's
actual investment timeline and simulates what would have happened with a
passive/alternative strategy. Used by the tools layer to build Section D of
the canvas report.

Primary scenarios (5 rows in UI bar chart):
  1. nifty_50_sip    — UTI Nifty 50 Index Direct as TRI proxy
  2. popular_mf_sip  — best-performing of 4 popular MF schemes
  3. model_70_30     — 70% equity (Nifty proxy) / 30% debt (HDFC Liquid)
  4. buy_and_hold    — same stocks, same buy timing, never sell
  5. no_reentry      — for stocks with buy→sell→buy: hold from first buy only

Metadata rows (computed but not primary bars):
  - model_100_equity, model_50_50
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from portfolio_doctor.core.portfolio_engine import compute_xirr

POPULAR_MF_SCHEMES = ["120716", "122639", "118989", "119065"]
DEBT_SCHEME = "119062"

INFLOW_ACTIONS = {"BUY", "SIP", "SWITCH_IN"}
OUTFLOW_ACTIONS = {"SELL", "SWP", "SWITCH_OUT"}


def _nearest_nav(nav_dict: dict[str, float], target_date: date, window: int = 5) -> Optional[float]:
    """Find NAV on target_date or nearest available date within ±window days."""
    key = target_date.isoformat()
    if key in nav_dict:
        return nav_dict[key]

    for delta in range(1, window + 1):
        for direction in (timedelta(days=delta), timedelta(days=-delta)):
            candidate = (target_date + direction).isoformat()
            if candidate in nav_dict:
                return nav_dict[candidate]
    return None


def _latest_nav(nav_dict: dict[str, float], end_date: date) -> Optional[float]:
    """Get NAV at end_date, falling back to nearest prior date."""
    key = end_date.isoformat()
    if key in nav_dict:
        return nav_dict[key]

    for delta in range(1, 30):
        candidate = (end_date - timedelta(days=delta)).isoformat()
        if candidate in nav_dict:
            return nav_dict[candidate]
    return None


def _compute_return_pct(invested: float, final_value: float) -> float:
    if invested <= 0:
        return 0.0
    return round((final_value - invested) / invested * 100, 2)


def _compute_xirr_for_scenario(
    investments: list[tuple[date, float]],
    final_value: float,
    end_date: date,
) -> float:
    if not investments or final_value <= 0:
        return 0.0
    cf = [(d, amt) for d, amt in investments]
    cf.append((end_date, final_value))
    return compute_xirr(cf)


# ---------------------------------------------------------------------------
# simulate_nifty_sip
# ---------------------------------------------------------------------------

def simulate_nifty_sip(
    cash_flows: list[dict],
    nifty_nav: dict[str, float],
    end_date: date,
) -> dict:
    """Simulate investing the same cash flows into Nifty 50 TRI proxy.

    For each negative cash flow (investment), buy Nifty units at that date's NAV.
    Final value = total units × latest NAV.
    """
    total_invested = 0.0
    total_units = 0.0
    investments: list[tuple[date, float]] = []

    for cf in cash_flows:
        if cf["amount"] >= 0:
            continue
        invest_amount = abs(cf["amount"])
        nav = _nearest_nav(nifty_nav, cf["date"])
        if nav is None or nav <= 0:
            continue
        units = invest_amount / nav
        total_units += units
        total_invested += invest_amount
        investments.append((cf["date"], -invest_amount))

    end_nav = _latest_nav(nifty_nav, end_date)
    final_value = total_units * end_nav if end_nav else 0.0

    return {
        "scenario": "nifty_50_sip",
        "total_invested": round(total_invested, 2),
        "final_value": round(final_value, 2),
        "xirr": _compute_xirr_for_scenario(investments, final_value, end_date),
        "absolute_return_pct": _compute_return_pct(total_invested, final_value),
        "units_purchased": round(total_units, 4),
    }


# ---------------------------------------------------------------------------
# simulate_buy_and_hold
# ---------------------------------------------------------------------------

def simulate_buy_and_hold(
    trades: list[dict],
    current_prices: dict[str, float],
) -> dict:
    """Simulate holding all bought positions forever — ignore all sells.

    Total held = sum of all bought quantities per symbol.
    Final value = sum(quantity × current_price).
    """
    holdings: dict[str, float] = {}
    total_invested = 0.0

    for t in trades:
        if t.get("instrument_type") != "EQUITY":
            continue
        if t["action"] not in INFLOW_ACTIONS:
            continue
        sym = t["symbol"]
        holdings[sym] = holdings.get(sym, 0.0) + t["quantity"]
        total_invested += t["quantity"] * t["price"]

    final_value = 0.0
    for sym, qty in holdings.items():
        price = current_prices.get(sym, 0.0)
        final_value += qty * price

    investments = [
        (t["date"], -(t["quantity"] * t["price"]))
        for t in trades
        if t.get("instrument_type") == "EQUITY" and t["action"] in INFLOW_ACTIONS
    ]

    return {
        "scenario": "buy_and_hold",
        "total_invested": round(total_invested, 2),
        "final_value": round(final_value, 2),
        "xirr": _compute_xirr_for_scenario(
            investments, final_value,
            max((t["date"] for t in trades), default=date.today()),
        ),
        "absolute_return_pct": _compute_return_pct(total_invested, final_value),
        "holdings": {s: round(q, 4) for s, q in holdings.items()},
    }


# ---------------------------------------------------------------------------
# simulate_mf_sip
# ---------------------------------------------------------------------------

def simulate_mf_sip(
    cash_flows: list[dict],
    mf_nav: dict[str, float],
    scheme_code: str,
    end_date: date,
) -> dict:
    """Simulate investing the same cash flows into a specific MF scheme.

    Same logic as nifty_sip but uses mutual fund NAVs.
    """
    total_invested = 0.0
    total_units = 0.0
    investments: list[tuple[date, float]] = []

    for cf in cash_flows:
        if cf["amount"] >= 0:
            continue
        invest_amount = abs(cf["amount"])
        nav = _nearest_nav(mf_nav, cf["date"])
        if nav is None or nav <= 0:
            continue
        units = invest_amount / nav
        total_units += units
        total_invested += invest_amount
        investments.append((cf["date"], -invest_amount))

    end_nav = _latest_nav(mf_nav, end_date)
    final_value = total_units * end_nav if end_nav else 0.0

    return {
        "scenario": f"mf_sip_{scheme_code}",
        "total_invested": round(total_invested, 2),
        "final_value": round(final_value, 2),
        "xirr": _compute_xirr_for_scenario(investments, final_value, end_date),
        "absolute_return_pct": _compute_return_pct(total_invested, final_value),
        "scheme_code": scheme_code,
        "units_purchased": round(total_units, 4),
    }


# ---------------------------------------------------------------------------
# simulate_model_portfolio
# ---------------------------------------------------------------------------

def simulate_model_portfolio(
    cash_flows: list[dict],
    equity_nav: dict[str, float],
    debt_nav: dict[str, float],
    equity_pct: float,
    end_date: date,
) -> dict:
    """Simulate a model portfolio split between equity and debt.

    Each cash flow is split: equity_pct goes to equity NAV, rest to debt NAV.
    """
    debt_pct = 1.0 - equity_pct
    total_invested = 0.0
    equity_units = 0.0
    debt_units = 0.0
    investments: list[tuple[date, float]] = []

    for cf in cash_flows:
        if cf["amount"] >= 0:
            continue
        invest_amount = abs(cf["amount"])
        eq_amount = invest_amount * equity_pct
        dt_amount = invest_amount * debt_pct

        eq_nav = _nearest_nav(equity_nav, cf["date"])
        dt_nav = _nearest_nav(debt_nav, cf["date"])

        bought = False
        if eq_nav and eq_nav > 0 and eq_amount > 0:
            equity_units += eq_amount / eq_nav
            bought = True
        if dt_nav and dt_nav > 0 and dt_amount > 0:
            debt_units += dt_amount / dt_nav
            bought = True

        if bought:
            total_invested += invest_amount
            investments.append((cf["date"], -invest_amount))

    eq_end = _latest_nav(equity_nav, end_date) or 0.0
    dt_end = _latest_nav(debt_nav, end_date) or 0.0
    final_value = (equity_units * eq_end) + (debt_units * dt_end)

    pct_label = int(equity_pct * 100)
    if pct_label == 100:
        scenario_name = "model_100_equity"
    elif pct_label == 70:
        scenario_name = "model_70_30"
    elif pct_label == 50:
        scenario_name = "model_50_50"
    else:
        scenario_name = f"model_{pct_label}_{100 - pct_label}"

    return {
        "scenario": scenario_name,
        "total_invested": round(total_invested, 2),
        "final_value": round(final_value, 2),
        "xirr": _compute_xirr_for_scenario(investments, final_value, end_date),
        "absolute_return_pct": _compute_return_pct(total_invested, final_value),
        "equity_pct": equity_pct,
    }


# ---------------------------------------------------------------------------
# simulate_no_reentry
# ---------------------------------------------------------------------------

def simulate_no_reentry(
    trades: list[dict],
    current_prices: dict[str, float],
) -> dict:
    """Simulate holding from first buy, never re-entering after a sell.

    For stocks with buy→sell→buy patterns: keep the first buy quantity only.
    Stocks with no re-entry pattern are included at their original buy quantity.
    """
    sorted_trades = sorted(
        [t for t in trades if t.get("instrument_type") == "EQUITY"],
        key=lambda t: t["date"],
    )

    first_buy_qty: dict[str, float] = {}
    first_buy_cost: dict[str, float] = {}
    has_sold: dict[str, bool] = {}
    investments: list[tuple[date, float]] = []

    for t in sorted_trades:
        sym = t["symbol"]
        action = t["action"]

        if action in INFLOW_ACTIONS:
            if sym not in first_buy_qty:
                first_buy_qty[sym] = t["quantity"]
                first_buy_cost[sym] = t["quantity"] * t["price"]
                investments.append((t["date"], -(t["quantity"] * t["price"])))
            elif not has_sold.get(sym, False):
                first_buy_qty[sym] += t["quantity"]
                cost = t["quantity"] * t["price"]
                first_buy_cost[sym] = first_buy_cost.get(sym, 0.0) + cost
                investments.append((t["date"], -cost))
        elif action in OUTFLOW_ACTIONS:
            has_sold[sym] = True

    total_invested = sum(first_buy_cost.values())
    final_value = 0.0
    for sym, qty in first_buy_qty.items():
        price = current_prices.get(sym, 0.0)
        final_value += qty * price

    return {
        "scenario": "no_reentry",
        "total_invested": round(total_invested, 2),
        "final_value": round(final_value, 2),
        "xirr": _compute_xirr_for_scenario(
            investments, final_value,
            max((t["date"] for t in sorted_trades), default=date.today()),
        ),
        "absolute_return_pct": _compute_return_pct(total_invested, final_value),
        "holdings": {s: round(q, 4) for s, q in first_buy_qty.items()},
    }


# ---------------------------------------------------------------------------
# run_all_scenarios
# ---------------------------------------------------------------------------

def run_all_scenarios(
    cash_flows: list[dict],
    trades: list[dict],
    actual_return: dict,
    nifty_nav: dict[str, float],
    mf_navs: dict[str, dict[str, float]],
    current_prices: dict[str, float],
    end_date: date,
    debt_nav: Optional[dict[str, float]] = None,
) -> list[dict]:
    """Run all alternative scenarios and compare against actual portfolio.

    Args:
        cash_flows: Client's actual cash flow timeline [{date, amount}].
        trades: Client's full trade list.
        actual_return: {xirr, final_value, total_invested} of actual portfolio.
        nifty_nav: {date_str: nav} for Nifty 50 TRI proxy.
        mf_navs: {scheme_code: {date_str: nav}} for popular MF schemes.
        current_prices: {symbol: price} for equity holdings.
        end_date: Valuation date.
        debt_nav: {date_str: nav} for debt fund (HDFC Liquid). Optional.

    Returns:
        List of scenario result dicts, each with vs_actual comparison.
    """
    actual_value = actual_return.get("final_value", 0)
    actual_xirr = actual_return.get("xirr", 0)
    scenarios: list[dict] = []

    def _add(fn, *args, **kwargs):
        try:
            result = fn(*args, **kwargs)
            result["vs_actual"] = _build_vs_actual(result, actual_value, actual_xirr)
            scenarios.append(result)
        except Exception:
            pass

    _add(simulate_nifty_sip, cash_flows, nifty_nav, end_date)

    best_mf = None
    for scheme_code, nav_data in mf_navs.items():
        try:
            mf_result = simulate_mf_sip(cash_flows, nav_data, scheme_code, end_date)
            if best_mf is None or mf_result["final_value"] > best_mf["final_value"]:
                best_mf = mf_result
        except Exception:
            continue

    if best_mf is not None:
        best_mf["scenario"] = "popular_mf_sip"
        best_mf["vs_actual"] = _build_vs_actual(best_mf, actual_value, actual_xirr)
        scenarios.append(best_mf)

    if debt_nav or nifty_nav:
        _debt = debt_nav or {}
        _add(
            simulate_model_portfolio,
            cash_flows, nifty_nav, _debt, 0.70, end_date,
        )

    _add(simulate_buy_and_hold, trades, current_prices)
    _add(simulate_no_reentry, trades, current_prices)

    return scenarios


def _build_vs_actual(
    scenario: dict,
    actual_value: float,
    actual_xirr: float,
) -> dict:
    value_diff = scenario["final_value"] - actual_value
    xirr_diff = scenario.get("xirr", 0) - actual_xirr

    if value_diff > 0:
        interpretation = (
            f"This strategy would have earned ₹{abs(round(value_diff)):,} more"
        )
    elif value_diff < 0:
        interpretation = (
            f"Your actual portfolio earned ₹{abs(round(value_diff)):,} more than this"
        )
    else:
        interpretation = "Same result as your actual portfolio"

    return {
        "value_difference": round(value_diff, 2),
        "return_difference_pct": round(xirr_diff * 100, 2),
        "interpretation": interpretation,
    }
