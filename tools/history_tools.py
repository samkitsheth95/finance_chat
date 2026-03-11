"""
Historical Query Tools — Track A, Step 1

Exposes accumulated daily snapshots (data/daily/*.json) to Claude for
multi-day trend analysis, FII flow persistence, similar historical setups,
and drawdown tracking.

No new data sources — reads entirely from core.daily_store.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime

from core.daily_store import load_recent, available_dates, load


# ── Helpers ────────────────────────────────────────────────────────────

def _pct_change(old: float, new: float) -> float | None:
    if old and old != 0:
        return round((new - old) / abs(old) * 100, 2)
    return None


def _safe_avg(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return round(sum(clean) / len(clean), 2) if clean else None


def _safe_sum(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return round(sum(clean), 2) if clean else None


def _safe_min(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return min(clean) if clean else None


def _safe_max(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return max(clean) if clean else None


def _streak(values: list[float | None], negative: bool = True) -> int:
    """Count consecutive streak from the end of the list."""
    count = 0
    for v in reversed(values):
        if v is None:
            break
        if (negative and v < 0) or (not negative and v > 0):
            count += 1
        else:
            break
    return count


# ── history_summary ────────────────────────────────────────────────────

def history_summary(days: int = 30) -> dict:
    """
    Summarize market conditions over the most recent N trading days.

    Returns Nifty performance, VIX statistics, FII/DII cumulative flows,
    regime distribution, and composite score trend.
    """
    snaps = load_recent(days)
    if not snaps:
        return {"error": "No daily snapshots available"}

    dates = [s.get("date", "?") for s in snaps]
    nifty_closes = [s.get("nifty_close") for s in snaps]
    vix_values = [s.get("vix_close") for s in snaps]
    fii_nets = [s.get("fii_net_cr") for s in snaps]
    dii_nets = [s.get("dii_net_cr") for s in snaps]
    composites = [s.get("composite_score") for s in snaps]
    regimes = [s.get("regime") for s in snaps if s.get("regime")]
    day_ranges = [s.get("nifty_day_range_pct") for s in snaps]

    first_close = next((c for c in nifty_closes if c is not None), None)
    last_close = next((c for c in reversed(nifty_closes) if c is not None), None)

    regime_counts = dict(Counter(regimes))

    fii_positive = sum(1 for f in fii_nets if f is not None and f > 0)
    fii_negative = sum(1 for f in fii_nets if f is not None and f < 0)
    fii_total = len([f for f in fii_nets if f is not None])

    return {
        "period": {
            "trading_days": len(snaps),
            "start_date": dates[0] if dates else None,
            "end_date": dates[-1] if dates else None,
            "snapshots_available": len(available_dates()),
        },
        "nifty": {
            "start_close": first_close,
            "end_close": last_close,
            "period_return_pct": _pct_change(first_close, last_close) if first_close and last_close else None,
            "period_high": _safe_max(nifty_closes),
            "period_low": _safe_min(nifty_closes),
            "avg_day_range_pct": _safe_avg(day_ranges),
        },
        "vix": {
            "current": vix_values[-1] if vix_values else None,
            "avg": _safe_avg(vix_values),
            "min": _safe_min(vix_values),
            "max": _safe_max(vix_values),
        },
        "fii_flows": {
            "cumulative_net_cr": _safe_sum(fii_nets),
            "avg_daily_net_cr": _safe_avg(fii_nets),
            "positive_days": fii_positive,
            "negative_days": fii_negative,
            "total_days_with_data": fii_total,
            "current_selling_streak": _streak(fii_nets, negative=True),
            "current_buying_streak": _streak(fii_nets, negative=False),
        },
        "dii_flows": {
            "cumulative_net_cr": _safe_sum(dii_nets),
            "avg_daily_net_cr": _safe_avg(dii_nets),
        },
        "composite": {
            "current": composites[-1] if composites else None,
            "avg": _safe_avg(composites),
            "min": _safe_min(composites),
            "max": _safe_max(composites),
        },
        "regimes": regime_counts,
    }


# ── fii_trend ──────────────────────────────────────────────────────────

def fii_trend(days: int = 5) -> dict:
    """
    FII flow trend over the most recent N trading days.

    Returns daily breakdown, running cumulative, streak, direction assessment,
    and whether DII is offsetting FII activity.
    """
    snaps = load_recent(days)
    if not snaps:
        return {"error": "No daily snapshots available"}

    daily: list[dict] = []
    cumulative = 0.0
    fii_cum_futures = 0

    for s in snaps:
        fii_cash = s.get("fii_net_cr")
        dii_cash = s.get("dii_net_cr")
        fii_fut_net = s.get("fii_fut_index_net")
        nifty_chg = s.get("nifty_change_pct")

        if fii_cash is not None:
            cumulative += fii_cash

        day_entry: dict = {
            "date": s.get("date"),
            "fii_cash_net_cr": fii_cash,
            "dii_cash_net_cr": dii_cash,
            "fii_fut_index_net": fii_fut_net,
            "nifty_change_pct": nifty_chg,
            "cumulative_fii_cr": round(cumulative, 2),
        }
        daily.append(day_entry)

        if fii_fut_net is not None:
            fii_cum_futures += fii_fut_net

    fii_nets = [s.get("fii_net_cr") for s in snaps]
    dii_nets = [s.get("dii_net_cr") for s in snaps]
    selling_streak = _streak(fii_nets, negative=True)
    buying_streak = _streak(fii_nets, negative=False)

    recent_fii = [f for f in fii_nets if f is not None]
    if len(recent_fii) >= 3:
        first_half = _safe_avg(recent_fii[:len(recent_fii)//2])
        second_half = _safe_avg(recent_fii[len(recent_fii)//2:])
        if first_half is not None and second_half is not None:
            if second_half < first_half - 200:
                trend_direction = "accelerating_selling"
            elif second_half > first_half + 200:
                trend_direction = "decelerating_selling" if second_half < 0 else "accelerating_buying"
            else:
                trend_direction = "steady"
        else:
            trend_direction = "insufficient_data"
    else:
        trend_direction = "insufficient_data"

    dii_offset = _safe_sum(dii_nets)
    fii_total = _safe_sum(fii_nets)
    dii_absorbing = (
        dii_offset is not None and fii_total is not None
        and fii_total < -500 and dii_offset > abs(fii_total) * 0.5
    )

    return {
        "trading_days": len(snaps),
        "daily": daily,
        "summary": {
            "cumulative_fii_cash_cr": round(cumulative, 2),
            "avg_daily_fii_cr": _safe_avg(fii_nets),
            "selling_streak_days": selling_streak,
            "buying_streak_days": buying_streak,
            "trend_direction": trend_direction,
        },
        "dii_offset": {
            "cumulative_dii_cash_cr": dii_offset,
            "dii_absorbing_fii_selling": dii_absorbing,
        },
        "fii_futures": {
            "latest_net": snaps[-1].get("fii_fut_index_net") if snaps else None,
            "latest_signal": snaps[-1].get("fii_futures_signal") if snaps else None,
        },
    }


# ── similar_setups ─────────────────────────────────────────────────────

def similar_setups(
    vix_above: float | None = None,
    vix_below: float | None = None,
    fii_net_below: float | None = None,
    fii_net_above: float | None = None,
    regime: str | None = None,
    composite_below: float | None = None,
    composite_above: float | None = None,
) -> dict:
    """
    Find past trading days where conditions matched the given filters.

    Returns matching days with their full snapshot summary, plus a
    next-day outcome analysis (what Nifty did the following trading day).
    """
    all_dates = available_dates()
    if not all_dates:
        return {"error": "No daily snapshots available"}

    date_to_snap: dict[str, dict] = {}
    for d_str in all_dates:
        snap = load(date.fromisoformat(d_str))
        if snap:
            date_to_snap[d_str] = snap

    sorted_dates = sorted(date_to_snap.keys())
    matches: list[dict] = []

    for d_str in sorted_dates:
        snap = date_to_snap[d_str]
        vix_val = snap.get("vix_close")
        fii_val = snap.get("fii_net_cr")
        reg_val = snap.get("regime")
        comp_val = snap.get("composite_score")

        if vix_above is not None and (vix_val is None or vix_val <= vix_above):
            continue
        if vix_below is not None and (vix_val is None or vix_val >= vix_below):
            continue
        if fii_net_below is not None and (fii_val is None or fii_val >= fii_net_below):
            continue
        if fii_net_above is not None and (fii_val is None or fii_val <= fii_net_above):
            continue
        if regime is not None and reg_val != regime:
            continue
        if composite_below is not None and (comp_val is None or comp_val >= composite_below):
            continue
        if composite_above is not None and (comp_val is None or comp_val <= composite_above):
            continue

        idx = sorted_dates.index(d_str)
        next_day = None
        if idx + 1 < len(sorted_dates):
            next_snap = date_to_snap.get(sorted_dates[idx + 1])
            if next_snap:
                next_day = {
                    "date": sorted_dates[idx + 1],
                    "nifty_change_pct": next_snap.get("nifty_change_pct"),
                    "nifty_close": next_snap.get("nifty_close"),
                }

        matches.append({
            "date": d_str,
            "nifty_close": snap.get("nifty_close"),
            "nifty_change_pct": snap.get("nifty_change_pct"),
            "vix_close": vix_val,
            "fii_net_cr": fii_val,
            "regime": reg_val,
            "composite_score": comp_val,
            "composite_direction": snap.get("composite_direction"),
            "next_day": next_day,
        })

    next_day_changes = [
        m["next_day"]["nifty_change_pct"]
        for m in matches
        if m.get("next_day") and m["next_day"].get("nifty_change_pct") is not None
    ]

    outcome = {}
    if next_day_changes:
        positive = sum(1 for c in next_day_changes if c > 0)
        negative = sum(1 for c in next_day_changes if c < 0)
        outcome = {
            "total_matches": len(next_day_changes),
            "next_day_avg_change_pct": _safe_avg(next_day_changes),
            "next_day_positive": positive,
            "next_day_negative": negative,
            "next_day_win_rate_pct": round(positive / len(next_day_changes) * 100, 1),
            "next_day_max_gain_pct": max(next_day_changes),
            "next_day_max_loss_pct": min(next_day_changes),
        }

    filters_used = {}
    if vix_above is not None:
        filters_used["vix_above"] = vix_above
    if vix_below is not None:
        filters_used["vix_below"] = vix_below
    if fii_net_below is not None:
        filters_used["fii_net_below"] = fii_net_below
    if fii_net_above is not None:
        filters_used["fii_net_above"] = fii_net_above
    if regime is not None:
        filters_used["regime"] = regime
    if composite_below is not None:
        filters_used["composite_below"] = composite_below
    if composite_above is not None:
        filters_used["composite_above"] = composite_above

    return {
        "filters": filters_used,
        "total_snapshots_searched": len(sorted_dates),
        "matches_found": len(matches),
        "matches": matches[-20:],
        "next_day_outcomes": outcome,
        "note": f"Showing last {min(20, len(matches))} of {len(matches)} matches" if len(matches) > 20 else None,
    }


# ── drawdown_status ────────────────────────────────────────────────────

def drawdown_status() -> dict:
    """
    Current drawdown analysis from recent Nifty highs.

    Looks back over all available snapshots to find the peak, calculates
    drawdown depth, duration, and contextual data (VIX, FII flows) during
    the drawdown period.
    """
    all_dates = available_dates()
    if not all_dates:
        return {"error": "No daily snapshots available"}

    snaps: list[dict] = []
    for d_str in all_dates:
        snap = load(date.fromisoformat(d_str))
        if snap and snap.get("nifty_close") is not None:
            snaps.append(snap)

    if not snaps:
        return {"error": "No snapshots with Nifty data"}

    peak_val = -1.0
    peak_date = None
    peak_idx = 0
    for i, s in enumerate(snaps):
        nifty = s["nifty_close"]
        if nifty > peak_val:
            peak_val = nifty
            peak_date = s.get("date")
            peak_idx = i

    current = snaps[-1]
    current_close = current["nifty_close"]
    drawdown_pct = round((current_close - peak_val) / peak_val * 100, 2)

    drawdown_snaps = snaps[peak_idx:]
    dd_fii_nets = [s.get("fii_net_cr") for s in drawdown_snaps]
    dd_dii_nets = [s.get("dii_net_cr") for s in drawdown_snaps]
    dd_vix_values = [s.get("vix_close") for s in drawdown_snaps]

    trough_val = min(s["nifty_close"] for s in drawdown_snaps)
    trough_snap = next(s for s in drawdown_snaps if s["nifty_close"] == trough_val)

    if drawdown_pct > -1.0:
        status = "near_highs"
    elif drawdown_pct > -3.0:
        status = "mild_pullback"
    elif drawdown_pct > -5.0:
        status = "moderate_correction"
    elif drawdown_pct > -10.0:
        status = "correction"
    elif drawdown_pct > -20.0:
        status = "deep_correction"
    else:
        status = "bear_market"

    recovery_pct = None
    if trough_val < peak_val and current_close > trough_val:
        recovery_pct = round(
            (current_close - trough_val) / (peak_val - trough_val) * 100, 1
        )

    return {
        "status": status,
        "peak": {
            "nifty_close": peak_val,
            "date": peak_date,
        },
        "trough": {
            "nifty_close": trough_val,
            "date": trough_snap.get("date"),
            "max_drawdown_pct": round((trough_val - peak_val) / peak_val * 100, 2),
        },
        "current": {
            "nifty_close": current_close,
            "date": current.get("date"),
            "drawdown_from_peak_pct": drawdown_pct,
            "recovery_from_trough_pct": recovery_pct,
        },
        "duration": {
            "days_since_peak": len(drawdown_snaps) - 1,
            "trading_days_in_drawdown": len(drawdown_snaps),
        },
        "during_drawdown": {
            "fii_cumulative_cr": _safe_sum(dd_fii_nets),
            "dii_cumulative_cr": _safe_sum(dd_dii_nets),
            "vix_at_peak": dd_vix_values[0] if dd_vix_values else None,
            "vix_current": dd_vix_values[-1] if dd_vix_values else None,
            "vix_max": _safe_max(dd_vix_values),
        },
    }
