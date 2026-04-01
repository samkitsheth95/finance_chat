"""
Portfolio Engine — holdings, returns, XIRR, value series, allocation, tax drag.

The math layer. Computes returns, portfolio value series, allocation, turnover,
and tax drag. No opinions — pure computation from trade data and price inputs.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from scipy.optimize import brentq

from portfolio_doctor.core.csv_parser import build_cash_flows as compute_cash_flows  # noqa: F401

INFLOW_ACTIONS = {"BUY", "SIP", "SWITCH_IN"}
OUTFLOW_ACTIONS = {"SELL", "SWP", "SWITCH_OUT"}

STCG_RATE = 0.15
LTCG_RATE = 0.10
LTCG_EXEMPT = 100000


# ---------------------------------------------------------------------------
# compute_holdings
# ---------------------------------------------------------------------------

def compute_holdings(trades: list[dict], as_of: date) -> dict:
    """Compute held positions as of a given date.

    Equity: FIFO cost basis with avg_cost tracking.
    MF: per-lot tracking (each purchase is a separate lot, FIFO sell).
    Positions with zero quantity are excluded.
    """
    filtered = sorted(
        [t for t in trades if t["date"] <= as_of],
        key=lambda t: t["date"],
    )
    positions: dict[str, dict] = {}

    for t in filtered:
        sym = t["symbol"]
        itype = t["instrument_type"]
        action = t["action"]

        if itype == "EQUITY":
            _apply_equity(positions, sym, t, action)
        elif itype == "MF":
            _apply_mf(positions, sym, t, action)

    return {s: p for s, p in positions.items() if _has_quantity(p)}


def _apply_equity(positions: dict, sym: str, trade: dict, action: str) -> None:
    if sym not in positions:
        positions[sym] = {
            "instrument_type": "EQUITY",
            "quantity": 0.0,
            "total_cost": 0.0,
            "avg_cost": 0.0,
            "invested": 0.0,
        }
    pos = positions[sym]

    if action in INFLOW_ACTIONS:
        old_qty = pos["quantity"]
        new_qty = old_qty + trade["quantity"]
        new_cost = pos["total_cost"] + trade["quantity"] * trade["price"]
        pos["quantity"] = new_qty
        pos["total_cost"] = new_cost
        pos["avg_cost"] = new_cost / new_qty if new_qty > 0 else 0.0
        pos["invested"] = new_cost
    elif action in OUTFLOW_ACTIONS:
        sell_qty = trade["quantity"]
        pos["quantity"] = max(pos["quantity"] - sell_qty, 0.0)
        if pos["quantity"] > 0:
            pos["total_cost"] = pos["avg_cost"] * pos["quantity"]
            pos["invested"] = pos["total_cost"]
        else:
            pos["total_cost"] = 0.0
            pos["invested"] = 0.0


def _apply_mf(positions: dict, sym: str, trade: dict, action: str) -> None:
    if sym not in positions:
        positions[sym] = {
            "instrument_type": "MF",
            "lots": [],
            "total_quantity": 0.0,
            "scheme_name": trade.get("scheme_name", ""),
        }
    pos = positions[sym]

    if action in INFLOW_ACTIONS:
        pos["lots"].append({
            "date": trade["date"],
            "quantity": trade["quantity"],
            "price": trade["price"],
            "amount": trade["amount"],
        })
        pos["total_quantity"] += trade["quantity"]
    elif action in OUTFLOW_ACTIONS:
        remaining = trade["quantity"]
        new_lots = []
        for lot in pos["lots"]:
            if remaining <= 1e-6:
                new_lots.append(lot)
                continue
            if lot["quantity"] <= remaining + 1e-6:
                remaining -= lot["quantity"]
            else:
                lot["quantity"] -= remaining
                lot["amount"] = lot["quantity"] * lot["price"]
                remaining = 0.0
                new_lots.append(lot)
        pos["lots"] = new_lots
        pos["total_quantity"] = sum(lt["quantity"] for lt in new_lots)


def _has_quantity(pos: dict) -> bool:
    if pos["instrument_type"] == "EQUITY":
        return pos["quantity"] > 1e-6
    return pos.get("total_quantity", 0.0) > 1e-6


# ---------------------------------------------------------------------------
# compute_xirr
# ---------------------------------------------------------------------------

def compute_xirr(cash_flows: list[tuple[date, float]]) -> float:
    """Compute XIRR (annualized internal rate of return) for a series of cash flows.

    Args:
        cash_flows: List of (date, amount) tuples. Negative = money out,
                    positive = money in. The last entry should typically be the
                    current portfolio value as a positive inflow.

    Returns:
        Annualized rate as a decimal (0.15 = 15%). Returns 0.0 if cannot solve.
    """
    if len(cash_flows) < 2:
        return 0.0

    sorted_cf = sorted(cash_flows, key=lambda x: x[0])
    d0 = sorted_cf[0][0]

    def _xnpv(rate: float) -> float:
        return sum(
            amount / (1 + rate) ** ((dt - d0).days / 365.0)
            for dt, amount in sorted_cf
        )

    try:
        return round(brentq(_xnpv, -0.99, 10.0, xtol=1e-6, maxiter=200), 6)
    except (ValueError, RuntimeError):
        return 0.0


# ---------------------------------------------------------------------------
# compute_returns
# ---------------------------------------------------------------------------

def compute_returns(
    trades: list[dict],
    current_prices: dict[str, float],
    as_of: date,
) -> dict:
    """Compute per-position and portfolio-level returns.

    Args:
        trades: Full trade list.
        current_prices: {symbol: current_price} for equity or {scheme_code: current_nav} for MF.
        as_of: Valuation date.

    Returns:
        Dict with positions, portfolio_xirr, total_invested, current_value,
        absolute_return, return_pct, total_brokerage.
    """
    holdings = compute_holdings(trades, as_of=as_of)

    positions = []
    total_invested = 0.0
    current_value = 0.0
    total_brokerage = sum(t.get("brokerage", 0.0) for t in trades if t["date"] <= as_of)

    for sym, pos in holdings.items():
        price = current_prices.get(sym)
        if price is None:
            continue

        if pos["instrument_type"] == "EQUITY":
            qty = pos["quantity"]
            invested = pos["invested"]
            val = qty * price
            ret_pct = ((val - invested) / invested * 100) if invested > 0 else 0.0

            positions.append({
                "symbol": sym,
                "instrument_type": "EQUITY",
                "quantity": qty,
                "avg_cost": pos["avg_cost"],
                "current_price": price,
                "invested": round(invested, 2),
                "current_value": round(val, 2),
                "absolute_return": round(val - invested, 2),
                "return_pct": round(ret_pct, 2),
            })
            total_invested += invested
            current_value += val

        elif pos["instrument_type"] == "MF":
            qty = pos["total_quantity"]
            invested = sum(lt["amount"] for lt in pos["lots"])
            val = qty * price
            ret_pct = ((val - invested) / invested * 100) if invested > 0 else 0.0

            positions.append({
                "symbol": sym,
                "instrument_type": "MF",
                "scheme_name": pos.get("scheme_name", ""),
                "total_quantity": qty,
                "current_nav": price,
                "invested": round(invested, 2),
                "current_value": round(val, 2),
                "absolute_return": round(val - invested, 2),
                "return_pct": round(ret_pct, 2),
            })
            total_invested += invested
            current_value += val

    cash_flows_raw = compute_cash_flows(
        [t for t in trades if t["date"] <= as_of]
    )
    cf_tuples = [(cf["date"], cf["amount"]) for cf in cash_flows_raw]
    if current_value > 0:
        cf_tuples.append((as_of, current_value))
    portfolio_xirr = compute_xirr(cf_tuples)

    absolute_return = current_value - total_invested
    return_pct = (absolute_return / total_invested * 100) if total_invested > 0 else 0.0

    return {
        "positions": positions,
        "portfolio_xirr": portfolio_xirr,
        "total_invested": round(total_invested, 2),
        "current_value": round(current_value, 2),
        "absolute_return": round(absolute_return, 2),
        "return_pct": round(return_pct, 2),
        "total_brokerage": round(total_brokerage, 2),
    }


# ---------------------------------------------------------------------------
# compute_portfolio_value_series
# ---------------------------------------------------------------------------

def compute_portfolio_value_series(
    trades: list[dict],
    price_data: dict[str, dict[str, float]],
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Compute daily portfolio value from trade history and price data.

    Args:
        trades: Full trade list.
        price_data: {symbol: {date_str: close_price}}.
        start_date: First date (inclusive).
        end_date: Last date (inclusive).

    Returns:
        List of {"date": str, "value": float} entries.
        Dates with no price data for any held position are skipped.
    """
    sorted_trades = sorted(trades, key=lambda t: t["date"])
    series: list[dict] = []
    current_day = start_date

    while current_day <= end_date:
        day_str = current_day.isoformat()
        holdings = compute_holdings(sorted_trades, as_of=current_day)

        has_prices = False
        day_value = 0.0
        for sym, pos in holdings.items():
            sym_prices = price_data.get(sym, {})
            price = sym_prices.get(day_str)
            if price is None:
                continue
            has_prices = True

            if pos["instrument_type"] == "EQUITY":
                day_value += pos["quantity"] * price
            elif pos["instrument_type"] == "MF":
                day_value += pos["total_quantity"] * price

        if has_prices:
            series.append({"date": day_str, "value": round(day_value, 2)})

        current_day += timedelta(days=1)

    return series


# ---------------------------------------------------------------------------
# compute_sector_allocation
# ---------------------------------------------------------------------------

def compute_sector_allocation(
    holdings: dict,
    sector_map: Optional[dict[str, str]] = None,
) -> dict:
    """Map holdings to sectors and instrument types.

    Args:
        holdings: {symbol: {value: float, instrument_type: str, ...}}.
        sector_map: {symbol: sector_name} for equity symbols.

    Returns:
        {"sectors": {sector: weight_pct}, "types": {type: weight_pct}}
    """
    if sector_map is None:
        sector_map = {}

    total_value = sum(h["value"] for h in holdings.values())
    if total_value <= 0:
        return {"sectors": {}, "types": {}}

    sectors: dict[str, float] = {}
    types: dict[str, float] = {}

    for sym, h in holdings.items():
        val = h["value"]
        itype = h.get("instrument_type", "EQUITY")
        weight = val / total_value * 100

        types[itype] = types.get(itype, 0.0) + weight

        if itype == "EQUITY":
            sector = sector_map.get(sym, "Unknown")
            sectors[sector] = sectors.get(sector, 0.0) + weight
        else:
            sectors[itype] = sectors.get(itype, 0.0) + weight

    sectors = {k: round(v, 2) for k, v in sectors.items()}
    types = {k: round(v, 2) for k, v in types.items()}

    return {"sectors": sectors, "types": types}


# ---------------------------------------------------------------------------
# compute_turnover
# ---------------------------------------------------------------------------

def compute_turnover(trades: list[dict], avg_portfolio_value: float) -> float:
    """Compute portfolio turnover ratio.

    turnover = total sell amounts / avg_portfolio_value.
    """
    if avg_portfolio_value <= 0:
        return 0.0

    total_sells = sum(
        t["amount"]
        for t in trades
        if t["action"] in OUTFLOW_ACTIONS
    )
    return round(total_sells / avg_portfolio_value, 4)


# ---------------------------------------------------------------------------
# compute_tax_drag
# ---------------------------------------------------------------------------

def compute_tax_drag(trades: list[dict]) -> dict:
    """Estimate STCG and LTCG tax on realized equity gains.

    Equity-oriented:
      - Held < 1 year → STCG at 15%
      - Held >= 1 year → LTCG at 10% above ₹1L exemption

    Returns:
        {"stcg_estimated", "ltcg_estimated", "total_tax_drag", "total_brokerage"}
    """
    sorted_trades = sorted(trades, key=lambda t: t["date"])
    lots: dict[str, list[dict]] = {}
    stcg_gains = 0.0
    ltcg_gains = 0.0
    total_brokerage = 0.0

    for t in sorted_trades:
        total_brokerage += t.get("brokerage", 0.0)
        sym = t["symbol"]
        action = t["action"]

        if action in INFLOW_ACTIONS:
            lots.setdefault(sym, []).append({
                "date": t["date"],
                "quantity": t["quantity"],
                "price": t["price"],
            })
        elif action in OUTFLOW_ACTIONS:
            remaining = t["quantity"]
            sell_price = t["price"]
            sell_date = t["date"]
            sym_lots = lots.get(sym, [])

            i = 0
            while remaining > 1e-6 and i < len(sym_lots):
                lot = sym_lots[i]
                if lot["quantity"] <= 1e-6:
                    i += 1
                    continue

                consumed = min(lot["quantity"], remaining)
                gain = (sell_price - lot["price"]) * consumed
                holding_days = (sell_date - lot["date"]).days

                if gain > 0:
                    if holding_days < 365:
                        stcg_gains += gain
                    else:
                        ltcg_gains += gain

                lot["quantity"] -= consumed
                remaining -= consumed
                if lot["quantity"] <= 1e-6:
                    i += 1

            lots[sym] = [lt for lt in sym_lots if lt["quantity"] > 1e-6]

    stcg_tax = round(stcg_gains * STCG_RATE, 2)
    ltcg_taxable = max(ltcg_gains - LTCG_EXEMPT, 0.0)
    ltcg_tax = round(ltcg_taxable * LTCG_RATE, 2)

    return {
        "stcg_estimated": stcg_tax,
        "ltcg_estimated": ltcg_tax,
        "total_tax_drag": round(stcg_tax + ltcg_tax, 2),
        "total_brokerage": round(total_brokerage, 2),
    }
