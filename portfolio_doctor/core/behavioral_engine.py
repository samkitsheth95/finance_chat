"""
Behavioral Engine — 9 detectors + composite behavioral score.

Each detector returns the standard result dict:
    {"pattern", "score", "severity", "instances", "cost_estimate", "evidence_summary"}

Score convention: -1.0 (severe) to +1.0 (excellent).
Composite weights from spec §3:
  timing (panic + FOMO) 25%, disposition 20%, overtrading 20%,
  concentration 15%, herd + anchoring 10%, SIP discipline 10%.
"""
from __future__ import annotations

from datetime import date, timedelta

INFLOW_ACTIONS = {"BUY", "SIP", "SWITCH_IN"}
OUTFLOW_ACTIONS = {"SELL", "SWP", "SWITCH_OUT"}

COMPOSITE_WEIGHTS = {
    "panic_selling": 0.125,
    "fomo_buying": 0.125,
    "disposition_effect": 0.20,
    "overtrading": 0.20,
    "concentration_risk": 0.15,
    "herd_behavior": 0.05,
    "anchoring_bias": 0.05,
    "sip_discipline": 0.05,
    "regular_plan_waste": 0.05,
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _empty_result(pattern: str) -> dict:
    return {
        "pattern": pattern,
        "score": 0.0,
        "severity": "low",
        "instances": [],
        "cost_estimate": 0.0,
        "evidence_summary": "",
    }


def _score_to_severity(score: float) -> str:
    abs_s = abs(score)
    if abs_s >= 0.6:
        return "high"
    if abs_s >= 0.3:
        return "medium"
    return "low"


def _parse_date_str(s: str) -> date | None:
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _nearest_value(
    data: dict[str, float], target: date, max_days: int = 5,
) -> float | None:
    """Find the value in *data* closest to *target*, within *max_days*."""
    best_val = None
    best_delta = max_days + 1
    for date_str, val in data.items():
        d = _parse_date_str(date_str)
        if d is None:
            continue
        delta = abs((d - target).days)
        if delta < best_delta:
            best_delta = delta
            best_val = val
    return best_val


def _peak_in_window(
    data: dict[str, float], target: date, lookback_days: int = 365,
) -> float | None:
    """Max value in *data* within [target − lookback_days, target] inclusive."""
    peak = None
    for date_str, val in data.items():
        d = _parse_date_str(date_str)
        if d is None:
            continue
        days_before = (target - d).days
        if 0 <= days_before <= lookback_days:
            if peak is None or val > peak:
                peak = val
    return peak


def _peak_after(
    data: dict[str, float], target: date, forward_days: int = 180,
) -> float | None:
    """Max value in *data* within (target, target + forward_days]."""
    peak = None
    for date_str, val in data.items():
        d = _parse_date_str(date_str)
        if d is None:
            continue
        days_after = (d - target).days
        if 0 < days_after <= forward_days:
            if peak is None or val > peak:
                peak = val
    return peak


def _find_crash_dates(
    nifty_data: dict[str, float], threshold: float = 0.15,
) -> list[date]:
    """Return dates where Nifty drawdown from running peak exceeds *threshold*."""
    dated_values = []
    for ds, val in nifty_data.items():
        d = _parse_date_str(ds)
        if d is not None:
            dated_values.append((d, val))
    dated_values.sort(key=lambda x: x[0])

    crash_dates: list[date] = []
    running_peak = 0.0
    for d, v in dated_values:
        running_peak = max(running_peak, v)
        if running_peak > 0 and (running_peak - v) / running_peak > threshold:
            crash_dates.append(d)
    return crash_dates


# ---------------------------------------------------------------------------
# 1. Panic Selling
# ---------------------------------------------------------------------------

def detect_panic_selling(
    trades: list[dict],
    nifty_data: dict[str, float],
) -> dict:
    """Sells when Nifty >10 % below 52-week high → panic selling."""
    sells = [
        t for t in trades
        if t["action"] in OUTFLOW_ACTIONS and t["instrument_type"] == "EQUITY"
    ]
    if not sells or not nifty_data:
        return _empty_result("panic_selling")

    instances: list[dict] = []
    total_cost = 0.0

    for sell in sells:
        nifty_now = _nearest_value(nifty_data, sell["date"], max_days=7)
        nifty_peak = _peak_in_window(nifty_data, sell["date"], lookback_days=365)
        if nifty_now is None or nifty_peak is None or nifty_peak <= 0:
            continue

        drawdown_pct = (nifty_peak - nifty_now) / nifty_peak * 100
        if drawdown_pct <= 10:
            continue

        recovery_peak = _peak_after(nifty_data, sell["date"], forward_days=180)
        recovery_pct = 0.0
        if recovery_peak and nifty_now > 0:
            recovery_pct = (recovery_peak - nifty_now) / nifty_now * 100

        sell_amount = sell.get("amount", sell["quantity"] * sell["price"])
        cost = sell_amount * recovery_pct / 100 if recovery_pct > 0 else 0.0

        instances.append({
            "date": sell["date"].isoformat(),
            "symbol": sell["symbol"],
            "sell_price": sell["price"],
            "nifty_drawdown_pct": round(drawdown_pct, 1),
            "amount": sell_amount,
            "estimated_recovery_cost": round(cost, 2),
        })
        total_cost += cost

    if instances:
        max_dd = max(i["nifty_drawdown_pct"] for i in instances)
        score = max(-1.0, -0.3 * (max_dd / 20))
    else:
        score = 0.0

    return {
        "pattern": "panic_selling",
        "score": round(score, 4),
        "severity": _score_to_severity(score),
        "instances": instances,
        "cost_estimate": round(total_cost, 2),
        "evidence_summary": (
            f"{len(instances)} sell(s) during market drawdown >10%. "
            f"Estimated opportunity cost: ₹{round(total_cost):,}."
            if instances else ""
        ),
    }


# ---------------------------------------------------------------------------
# 2. FOMO Buying
# ---------------------------------------------------------------------------

def detect_fomo_buying(
    trades: list[dict],
    nifty_data: dict[str, float],
    stock_dma_data: dict[str, dict[str, float]] | None = None,
) -> dict:
    """Buys when Nifty near ATH (<2 % from peak) or stock >20 % above 200 DMA."""
    buys = [
        t for t in trades
        if t["action"] in INFLOW_ACTIONS and t["instrument_type"] == "EQUITY"
    ]
    if not buys or not nifty_data:
        return _empty_result("fomo_buying")

    instances: list[dict] = []
    total_cost = 0.0

    for buy in buys:
        nifty_now = _nearest_value(nifty_data, buy["date"], max_days=7)
        nifty_peak = _peak_in_window(nifty_data, buy["date"], lookback_days=365)
        if nifty_now is None or nifty_peak is None or nifty_peak <= 0:
            continue

        gap_from_peak = (nifty_peak - nifty_now) / nifty_peak * 100
        near_ath = gap_from_peak < 2.0

        above_dma = False
        if stock_dma_data and buy["symbol"] in stock_dma_data:
            dma200 = _nearest_value(stock_dma_data[buy["symbol"]], buy["date"])
            if dma200 and dma200 > 0 and buy["price"] > dma200 * 1.2:
                above_dma = True

        if not (near_ath or above_dma):
            continue

        amount = buy.get("amount", buy["quantity"] * buy["price"])
        instances.append({
            "date": buy["date"].isoformat(),
            "symbol": buy["symbol"],
            "buy_price": buy["price"],
            "near_ath": near_ath,
            "above_200dma": above_dma,
            "amount": amount,
        })
        total_cost += amount * 0.05  # conservative 5 % subsequent drawdown estimate

    if instances:
        fomo_ratio = len(instances) / max(len(buys), 1)
        score = max(-1.0, -0.3 * fomo_ratio)
    else:
        score = 0.0

    return {
        "pattern": "fomo_buying",
        "score": round(score, 4),
        "severity": _score_to_severity(score),
        "instances": instances,
        "cost_estimate": round(total_cost, 2),
        "evidence_summary": (
            f"{len(instances)} buy(s) near market highs."
            if instances else ""
        ),
    }


# ---------------------------------------------------------------------------
# 3. Disposition Effect
# ---------------------------------------------------------------------------

def detect_disposition_effect(trades: list[dict]) -> dict:
    """Selling winners early, holding losers long."""
    sorted_trades = sorted(
        [t for t in trades if t["instrument_type"] == "EQUITY"],
        key=lambda t: t["date"],
    )
    buy_lots: dict[str, list[dict]] = {}
    sell_results: list[dict] = []

    for t in sorted_trades:
        sym = t["symbol"]
        if t["action"] in INFLOW_ACTIONS:
            buy_lots.setdefault(sym, []).append({
                "date": t["date"], "price": t["price"], "quantity": t["quantity"],
            })
        elif t["action"] in OUTFLOW_ACTIONS:
            remaining = t["quantity"]
            for lot in buy_lots.get(sym, []):
                if remaining <= 1e-6 or lot["quantity"] <= 1e-6:
                    continue
                consumed = min(lot["quantity"], remaining)
                holding_days = (t["date"] - lot["date"]).days
                gain = (t["price"] - lot["price"]) * consumed
                sell_results.append({
                    "symbol": sym,
                    "buy_date": lot["date"],
                    "sell_date": t["date"],
                    "holding_days": holding_days,
                    "gain": gain,
                })
                lot["quantity"] -= consumed
                remaining -= consumed

    winners = [r for r in sell_results if r["gain"] > 0]
    losers = [r for r in sell_results if r["gain"] < 0]

    if not winners or not losers:
        return _empty_result("disposition_effect")

    avg_winner_days = sum(w["holding_days"] for w in winners) / len(winners)
    avg_loser_days = sum(l["holding_days"] for l in losers) / len(losers)

    if avg_winner_days <= 0:
        return _empty_result("disposition_effect")

    ratio = avg_loser_days / avg_winner_days
    if ratio > 1.0:
        score = max(-1.0, -(ratio - 1) * 0.3)
    else:
        score = 0.0

    total_loser_cost = sum(abs(l["gain"]) for l in losers)

    instances = [
        {
            "type": "winner_sold_early",
            "avg_holding_days": round(avg_winner_days, 1),
            "count": len(winners),
        },
        {
            "type": "loser_held_long",
            "avg_holding_days": round(avg_loser_days, 1),
            "count": len(losers),
        },
    ]

    return {
        "pattern": "disposition_effect",
        "score": round(score, 4),
        "severity": _score_to_severity(score),
        "instances": instances,
        "cost_estimate": round(total_loser_cost, 2),
        "evidence_summary": (
            f"Winners held avg {avg_winner_days:.0f} days vs "
            f"losers held avg {avg_loser_days:.0f} days "
            f"(ratio {ratio:.1f}x)."
        ),
    }


# ---------------------------------------------------------------------------
# 4. Overtrading
# ---------------------------------------------------------------------------

def detect_overtrading(trades: list[dict], total_days: int) -> dict:
    """Frequent round-trips (buy+sell same stock within 30 days)."""
    equity_trades = [t for t in trades if t["instrument_type"] == "EQUITY"]
    if not equity_trades or total_days <= 0:
        return _empty_result("overtrading")

    sorted_trades = sorted(equity_trades, key=lambda t: t["date"])

    buys_by_sym: dict[str, list[dict]] = {}
    sells_by_sym: dict[str, list[dict]] = {}
    for t in sorted_trades:
        sym = t["symbol"]
        if t["action"] in INFLOW_ACTIONS:
            buys_by_sym.setdefault(sym, []).append(t)
        elif t["action"] in OUTFLOW_ACTIONS:
            sells_by_sym.setdefault(sym, []).append(t)

    round_trips: list[dict] = []
    for sym, sym_sells in sells_by_sym.items():
        used_buy_idx: set[int] = set()
        sym_buys = buys_by_sym.get(sym, [])
        for sell in sym_sells:
            for i, buy in enumerate(sym_buys):
                if i in used_buy_idx:
                    continue
                gap = (sell["date"] - buy["date"]).days
                if 0 <= gap <= 30:
                    round_trips.append({
                        "symbol": sym,
                        "buy_date": buy["date"].isoformat(),
                        "sell_date": sell["date"].isoformat(),
                        "gap_days": gap,
                    })
                    used_buy_idx.add(i)
                    break

    total_sells = sum(
        1 for t in equity_trades if t["action"] in OUTFLOW_ACTIONS
    )
    if total_sells == 0:
        return _empty_result("overtrading")

    rt_ratio = len(round_trips) / total_sells
    score = max(-1.0, -0.2 * rt_ratio)

    trades_per_month = len(equity_trades) / max(total_days / 30, 1)
    if trades_per_month > 10:
        score = max(-1.0, score - 0.2)

    cost_estimate = sum(
        abs(t.get("amount", 0)) * 0.005
        for t in equity_trades
        if t["action"] in OUTFLOW_ACTIONS
    )

    return {
        "pattern": "overtrading",
        "score": round(score, 4),
        "severity": _score_to_severity(score),
        "instances": round_trips,
        "cost_estimate": round(cost_estimate, 2),
        "evidence_summary": (
            f"{len(round_trips)} round-trip(s) in {total_days} days. "
            f"Trades/month: {trades_per_month:.1f}."
        ),
    }


# ---------------------------------------------------------------------------
# 5. Concentration Risk
# ---------------------------------------------------------------------------

def detect_concentration_risk(
    holdings: dict[str, dict],
    total_value: float,
) -> dict:
    """Single-stock >20 % weight or top-5 >80 %."""
    if not holdings or total_value <= 0:
        return _empty_result("concentration_risk")

    weights = {
        sym: h["value"] / total_value * 100
        for sym, h in holdings.items()
    }
    max_weight = max(weights.values()) if weights else 0
    top5 = sorted(weights.values(), reverse=True)[:5]
    top5_sum = sum(top5)

    instances: list[dict] = []
    if max_weight > 20:
        top_sym = max(weights, key=weights.get)  # type: ignore[arg-type]
        instances.append({
            "type": "single_stock_concentration",
            "symbol": top_sym,
            "weight_pct": round(max_weight, 1),
        })
    if top5_sum > 80 and len(weights) > 5:
        instances.append({
            "type": "top5_concentration",
            "weight_pct": round(top5_sum, 1),
        })

    if max_weight > 40:
        score = -0.8
    elif max_weight > 30:
        score = -0.5
    elif max_weight > 20:
        score = -0.3
    else:
        score = 0.0

    return {
        "pattern": "concentration_risk",
        "score": round(score, 4),
        "severity": _score_to_severity(score),
        "instances": instances,
        "cost_estimate": 0.0,
        "evidence_summary": (
            f"Max single-stock weight: {max_weight:.1f}%. "
            f"Top-5 concentration: {top5_sum:.1f}%."
            if instances else ""
        ),
    }


# ---------------------------------------------------------------------------
# 6. Herd Behavior
# ---------------------------------------------------------------------------

def detect_herd_behavior(
    trades: list[dict],
    stock_price_data: dict[str, dict[str, float]],
) -> dict:
    """Buying stocks that rallied >30 % in the prior month."""
    buys = [
        t for t in trades
        if t["action"] in INFLOW_ACTIONS and t["instrument_type"] == "EQUITY"
    ]
    if not buys:
        return _empty_result("herd_behavior")

    instances: list[dict] = []
    total_cost = 0.0

    for buy in buys:
        sym_prices = stock_price_data.get(buy["symbol"], {})
        if not sym_prices:
            continue

        month_ago = buy["date"] - timedelta(days=30)
        price_then = _nearest_value(sym_prices, month_ago, max_days=15)
        if price_then is None or price_then <= 0:
            continue

        run_up_pct = (buy["price"] - price_then) / price_then * 100
        if run_up_pct <= 30:
            continue

        amount = buy.get("amount", buy["quantity"] * buy["price"])
        instances.append({
            "date": buy["date"].isoformat(),
            "symbol": buy["symbol"],
            "buy_price": buy["price"],
            "price_month_ago": price_then,
            "run_up_pct": round(run_up_pct, 1),
        })
        total_cost += amount * 0.1  # estimate 10 % mean reversion loss

    if instances:
        herd_ratio = len(instances) / max(len(buys), 1)
        score = max(-1.0, -0.4 * herd_ratio)
    else:
        score = 0.0

    return {
        "pattern": "herd_behavior",
        "score": round(score, 4),
        "severity": _score_to_severity(score),
        "instances": instances,
        "cost_estimate": round(total_cost, 2),
        "evidence_summary": (
            f"{len(instances)} buy(s) after >30% rally in prior month."
            if instances else ""
        ),
    }


# ---------------------------------------------------------------------------
# 7. Anchoring Bias
# ---------------------------------------------------------------------------

def detect_anchoring_bias(trades: list[dict]) -> dict:
    """Repeated sells at ±2 % of buy price (breakeven anchoring)."""
    equity_trades = sorted(
        [t for t in trades if t["instrument_type"] == "EQUITY"],
        key=lambda t: t["date"],
    )
    buy_lots: dict[str, list[dict]] = {}
    instances: list[dict] = []
    total_sells = 0

    for t in equity_trades:
        sym = t["symbol"]
        if t["action"] in INFLOW_ACTIONS:
            buy_lots.setdefault(sym, []).append({
                "price": t["price"], "quantity": t["quantity"],
            })
        elif t["action"] in OUTFLOW_ACTIONS:
            total_sells += 1
            sym_lots = buy_lots.get(sym, [])
            if not sym_lots:
                continue

            total_qty = sum(l["quantity"] for l in sym_lots if l["quantity"] > 1e-6)
            if total_qty <= 0:
                continue
            avg_buy = sum(
                l["price"] * l["quantity"]
                for l in sym_lots if l["quantity"] > 1e-6
            ) / total_qty

            pct_diff = abs(t["price"] - avg_buy) / avg_buy * 100 if avg_buy > 0 else 999
            if pct_diff <= 2.0:
                instances.append({
                    "date": t["date"].isoformat(),
                    "symbol": sym,
                    "buy_price": round(avg_buy, 2),
                    "sell_price": t["price"],
                    "pct_from_cost": round(pct_diff, 2),
                })

            remaining = t["quantity"]
            new_lots = []
            for lot in sym_lots:
                if remaining <= 1e-6:
                    new_lots.append(lot)
                    continue
                if lot["quantity"] <= remaining + 1e-6:
                    remaining -= lot["quantity"]
                else:
                    lot["quantity"] -= remaining
                    remaining = 0.0
                    new_lots.append(lot)
            buy_lots[sym] = new_lots

    if not instances:
        return _empty_result("anchoring_bias")

    frequency = len(instances) / max(total_sells, 1)
    score = max(-1.0, -0.5 * frequency)

    return {
        "pattern": "anchoring_bias",
        "score": round(score, 4),
        "severity": _score_to_severity(score),
        "instances": instances,
        "cost_estimate": 0.0,
        "evidence_summary": (
            f"{len(instances)} sell(s) within ±2% of buy price (breakeven anchoring)."
        ),
    }


# ---------------------------------------------------------------------------
# 8. SIP Discipline
# ---------------------------------------------------------------------------

def detect_sip_discipline(
    sip_patterns: list[dict],
    nifty_data: dict[str, float],
) -> dict:
    """SIPs maintained through market crashes → positive; stopped → negative."""
    if not sip_patterns:
        return _empty_result("sip_discipline")

    crash_dates = _find_crash_dates(nifty_data, threshold=0.15)

    if not crash_dates:
        mild_score = min(0.3, 0.1 * len(sip_patterns))
        return {
            "pattern": "sip_discipline",
            "score": round(mild_score, 4),
            "severity": "low",
            "instances": [],
            "cost_estimate": 0.0,
            "evidence_summary": "No major crashes during SIP period to measure discipline.",
        }

    maintained = 0
    stopped = 0
    instances: list[dict] = []

    for sip in sip_patterns:
        sip_start = sip["start_date"]
        sip_end = sip["end_date"]

        for crash_date in crash_dates:
            if sip_start <= crash_date <= sip_end:
                maintained += 1
                instances.append({
                    "scheme_code": sip["scheme_code"],
                    "maintained_through_crash": True,
                    "crash_date": crash_date.isoformat(),
                })
                break
            if sip_end < crash_date and (crash_date - sip_end).days < 90:
                stopped += 1
                instances.append({
                    "scheme_code": sip["scheme_code"],
                    "maintained_through_crash": False,
                    "sip_ended": sip_end.isoformat(),
                    "crash_date": crash_date.isoformat(),
                })
                break

    if maintained > 0 and stopped == 0:
        score = min(1.0, 0.5 + 0.2 * maintained)
    elif stopped > 0 and maintained == 0:
        score = max(-1.0, -0.3 * stopped)
    elif maintained > stopped:
        score = min(1.0, 0.3 * (maintained - stopped))
    else:
        score = max(-1.0, -0.2 * (stopped - maintained))

    return {
        "pattern": "sip_discipline",
        "score": round(score, 4),
        "severity": _score_to_severity(score),
        "instances": instances,
        "cost_estimate": 0.0,
        "evidence_summary": (
            f"{'Maintained' if maintained > 0 else 'Stopped'} SIPs "
            f"{'during' if maintained > 0 else 'before'} market crash. "
            f"Maintained: {maintained}, Stopped: {stopped}."
        ),
    }


# ---------------------------------------------------------------------------
# 9. Regular Plan Waste
# ---------------------------------------------------------------------------

def detect_regular_plan_waste(trades: list[dict]) -> dict:
    """Flag MF holdings in regular plans; estimate expense ratio drag."""
    mf_trades = [t for t in trades if t["instrument_type"] == "MF"]

    regular_schemes: dict[str, dict] = {}
    for t in mf_trades:
        scheme_name = t.get("scheme_name", "")
        if not scheme_name:
            continue
        name_lower = scheme_name.lower()
        if "regular" in name_lower and "direct" not in name_lower:
            sym = t["symbol"]
            if sym not in regular_schemes:
                regular_schemes[sym] = {"scheme_name": scheme_name, "total_amount": 0.0}
            regular_schemes[sym]["total_amount"] += t.get(
                "amount", t["quantity"] * t["price"]
            )

    if not regular_schemes:
        return _empty_result("regular_plan_waste")

    instances: list[dict] = []
    total_cost = 0.0
    for sym, info in regular_schemes.items():
        annual_drag = info["total_amount"] * 0.01
        instances.append({
            "scheme_code": sym,
            "scheme_name": info["scheme_name"],
            "amount_in_regular": info["total_amount"],
            "estimated_annual_drag": round(annual_drag, 2),
        })
        total_cost += annual_drag

    score = max(-1.0, -0.3 * len(regular_schemes))

    return {
        "pattern": "regular_plan_waste",
        "score": round(score, 4),
        "severity": _score_to_severity(score),
        "instances": instances,
        "cost_estimate": round(total_cost, 2),
        "evidence_summary": (
            f"{len(regular_schemes)} regular-plan scheme(s). "
            f"Switch to direct plans to save ~₹{round(total_cost):,}/year."
        ),
    }


# ---------------------------------------------------------------------------
# Composite Score
# ---------------------------------------------------------------------------

def compute_behavioral_composite(detector_results: list[dict]) -> dict:
    """Weighted composite of all detector scores.

    Returns:
        {
            "composite_score": float (-1.0 to +1.0),
            "severity": str,
            "top_issues": list[dict] (top 3 by cost_estimate, descending),
            "total_estimated_cost": float,
        }
    """
    weighted_sum = 0.0
    for result in detector_results:
        pattern = result["pattern"]
        weight = COMPOSITE_WEIGHTS.get(pattern, 0.0)
        weighted_sum += result["score"] * weight

    composite = max(-1.0, min(1.0, weighted_sum))

    sorted_by_cost = sorted(
        [r for r in detector_results if r["cost_estimate"] > 0],
        key=lambda r: r["cost_estimate"],
        reverse=True,
    )
    top_issues = sorted_by_cost[:3]
    total_cost = sum(r["cost_estimate"] for r in detector_results)

    return {
        "composite_score": round(composite, 4),
        "severity": _score_to_severity(composite),
        "top_issues": top_issues,
        "total_estimated_cost": round(total_cost, 2),
    }
