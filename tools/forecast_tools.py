"""
Track A, Step 4 — Volatility Range Forecast

Synthesizes multiple range estimation methods into an honest, multi-lens
view of where the underlying might trade over a given horizon.

Three independent lenses, each with different validity windows:
  1. VIX-implied statistical range  — valid across regimes, forward-looking
  2. Bollinger Bands realized range  — backward-looking, shows recent behavior
  3. Historical range from snapshots — "what range did we actually see in similar periods?"

Plus an optional OI-derived containment zone (valid only for ~2 days around
the nearest expiry — clearly labelled as such).

No lens is "the answer." Claude synthesizes them for the user.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from core.daily_store import load_recent
from tools.derivatives_tools import get_option_chain, get_vix
from tools.technicals_tools import technical_analysis as _run_technicals


# ── Helpers ────────────────────────────────────────────────────────────

def _safe(fn, *args, **kwargs):
    """Call fn; normalise errors to {"_error": str}."""
    try:
        result = fn(*args, **kwargs)
        if isinstance(result, dict) and "error" in result:
            return {"_error": result["error"]}
        return result
    except Exception as e:
        return {"_error": f"{fn.__name__}: {e}"}


def _ok(data) -> bool:
    return isinstance(data, dict) and "_error" not in data


def _percentile(sorted_values: list[float], value: float) -> float:
    n = len(sorted_values)
    if n == 0:
        return 50.0
    pos = bisect_left(sorted_values, value)
    return round(pos / n * 100, 1)


# ── VIX-implied range ─────────────────────────────────────────────────

def _vix_implied_range(
    spot: float, vix: float, horizon_days: int
) -> dict:
    """
    VIX is annualized implied volatility. Scale to the horizon:
      σ_horizon = VIX / 100 × √(horizon_days / 365)

    Returns 1σ and 2σ bands. 1σ ≈ 68% containment, 2σ ≈ 95%.
    """
    sigma = (vix / 100) * math.sqrt(horizon_days / 365)
    move_1s = round(spot * sigma, 2)
    move_2s = round(spot * sigma * 2, 2)

    return {
        "method": "VIX-implied statistical range",
        "vix_used": vix,
        "horizon_days": horizon_days,
        "spot": spot,
        "range_1sigma": {
            "low": round(spot - move_1s, 2),
            "high": round(spot + move_1s, 2),
            "move_pct": round(sigma * 100, 2),
            "containment": "~68% probability (1 standard deviation)",
        },
        "range_2sigma": {
            "low": round(spot - move_2s, 2),
            "high": round(spot + move_2s, 2),
            "move_pct": round(sigma * 200, 2),
            "containment": "~95% probability (2 standard deviations)",
        },
        "note": (
            "VIX-derived range assumes log-normal returns. In trending or "
            "event-driven markets, actual moves can exceed 2σ. This is the "
            "market's own estimate of uncertainty, not a prediction."
        ),
    }


# ── Bollinger-based realized range ────────────────────────────────────

def _bollinger_range(tech_data: dict) -> dict | None:
    """Extract Bollinger band context from technicals output."""
    bb = tech_data.get("bollinger")
    if not bb:
        return None

    price = tech_data.get("current_price")
    upper = bb["upper"]
    lower = bb["lower"]
    bw = bb["bandwidth_pct"]
    pct_b = bb["percent_b"]

    # Position within the bands
    if pct_b > 0.8:
        position = "near upper band — momentum is strong but may be extended"
    elif pct_b < 0.2:
        position = "near lower band — oversold; mean reversion likely but not guaranteed"
    else:
        position = "mid-range within bands"

    # Bandwidth context
    if bw > 8:
        bw_note = "wide bands — high recent volatility, range may stay elevated"
    elif bw < 3:
        bw_note = "narrow bands — low recent volatility, breakout may be imminent"
    else:
        bw_note = "normal bandwidth — no unusual compression or expansion"

    return {
        "method": "Bollinger Bands (20-day, 2σ) — realized volatility",
        "upper_band": upper,
        "lower_band": lower,
        "current_price": price,
        "bandwidth_pct": bw,
        "percent_b": pct_b,
        "position": position,
        "bandwidth_note": bw_note,
        "note": (
            "Bollinger Bands reflect the PAST 20 days of realized volatility. "
            "Price often stays within bands in range-bound markets but breaks "
            "out during trending moves. Best used alongside VIX-implied range."
        ),
    }


# ── Historical range from snapshots ───────────────────────────────────

def _historical_range_stats(horizon_days: int) -> dict | None:
    """
    What N-day ranges have we actually seen in stored history?

    Computes rolling N-day Nifty ranges from snapshots and returns
    percentile context for the current range.
    """
    snaps = load_recent(9999)
    if not snaps or len(snaps) < horizon_days + 5:
        return None

    closes = [s["nifty_close"] for s in snaps if s.get("nifty_close") is not None]
    if len(closes) < horizon_days + 5:
        return None

    # Compute all rolling N-day ranges (high-low spread as % of start)
    rolling_ranges: list[float] = []
    rolling_returns: list[float] = []
    for i in range(horizon_days, len(closes)):
        window = closes[i - horizon_days : i + 1]
        high = max(window)
        low = min(window)
        start = window[0]
        end = window[-1]
        if start > 0:
            rolling_ranges.append(round((high - low) / start * 100, 2))
            rolling_returns.append(round((end - start) / start * 100, 2))

    if not rolling_ranges:
        return None

    sorted_ranges = sorted(rolling_ranges)
    sorted_returns = sorted(rolling_returns)

    # Current N-day range (most recent window)
    recent_window = closes[-horizon_days - 1 :]
    current_range = round((max(recent_window) - min(recent_window)) / recent_window[0] * 100, 2)
    current_return = round((recent_window[-1] - recent_window[0]) / recent_window[0] * 100, 2)

    positive_returns = sum(1 for r in rolling_returns if r > 0)

    return {
        "method": f"Historical {horizon_days}-day range from stored snapshots",
        "sample_windows": len(rolling_ranges),
        "range_stats": {
            "median_range_pct": sorted_ranges[len(sorted_ranges) // 2],
            "p25_range_pct": sorted_ranges[len(sorted_ranges) // 4],
            "p75_range_pct": sorted_ranges[3 * len(sorted_ranges) // 4],
            "p90_range_pct": sorted_ranges[int(len(sorted_ranges) * 0.9)],
            "max_range_pct": sorted_ranges[-1],
        },
        "return_stats": {
            "median_return_pct": sorted_returns[len(sorted_returns) // 2],
            "positive_pct": round(positive_returns / len(rolling_returns) * 100, 1),
            "p10_return_pct": sorted_returns[int(len(sorted_returns) * 0.1)],
            "p90_return_pct": sorted_returns[int(len(sorted_returns) * 0.9)],
        },
        "current_window": {
            "range_pct": current_range,
            "range_percentile": _percentile(sorted_ranges, current_range),
            "return_pct": current_return,
            "return_percentile": _percentile(sorted_returns, current_return),
        },
        "note": (
            f"Based on {len(rolling_ranges)} rolling {horizon_days}-day windows from "
            f"stored data. Shows what ranges actually occurred — not a forecast, "
            f"but context for how unusual the current window is."
        ),
    }


# ── OI-derived containment zone ───────────────────────────────────────

def _oi_containment(oc_data: dict) -> dict | None:
    """
    OI walls + max pain define a short-term containment zone.
    Only meaningful within ~2 days of expiry.
    """
    spot = oc_data.get("spot")
    dte = oc_data.get("days_to_expiry")
    cw = oc_data.get("call_oi_wall")
    pw = oc_data.get("put_oi_wall")
    mp = oc_data.get("max_pain", {}).get("strike")

    if not all([spot, cw, pw, mp]):
        return None

    call_wall = cw["strike"]
    put_wall = pw["strike"]

    # Relevance degrades with time to expiry
    if dte is not None and dte > 5:
        validity = "low — expiry is far away; OI distribution will shift significantly"
    elif dte is not None and dte > 2:
        validity = "moderate — OI positions are semi-sticky but can shift"
    else:
        validity = "high — near expiry, max pain gravity is strongest"

    return {
        "method": "OI-derived containment zone (options market positioning)",
        "call_oi_wall": call_wall,
        "put_oi_wall": put_wall,
        "max_pain": mp,
        "spot": spot,
        "days_to_expiry": dte,
        "implied_range": {
            "support": put_wall,
            "resistance": call_wall,
            "width_pct": round((call_wall - put_wall) / spot * 100, 2) if spot else None,
        },
        "max_pain_distance_pct": round((mp - spot) / spot * 100, 2) if spot else None,
        "validity": validity,
        "note": (
            "OI walls show where the largest option positions sit — these act as "
            "magnets/barriers near expiry. Max pain is where writers profit most. "
            "This zone is ONLY valid for the current expiry cycle and becomes "
            "unreliable beyond ~2 trading days as positions roll or unwind."
        ),
    }


# ── Main tool ──────────────────────────────────────────────────────────

def forecast_range(
    underlying: str = "NIFTY",
    horizon_days: int = 5,
) -> dict:
    """
    Multi-lens range estimation for an index.

    Synthesizes VIX-implied bands, Bollinger context, historical range stats,
    and OI containment into an honest, multi-perspective view.

    Args:
        underlying: "NIFTY" (default) or "BANKNIFTY"
        horizon_days: Forecast horizon in trading days (default 5 = 1 week)

    Returns a dict with independent range estimates from each lens,
    clearly labelled with validity and limitations.
    """
    underlying = underlying.upper()

    # Map underlying to technicals symbol
    tech_symbol_map = {
        "NIFTY": "NIFTY 50",
        "BANKNIFTY": "NIFTY BANK",
        "FINNIFTY": "NIFTY FIN SERVICE",
    }
    tech_symbol = tech_symbol_map.get(underlying, underlying)

    # Parallel fetch: VIX, option chain, technicals
    tasks = {
        "vix": (get_vix,),
        "oc": (get_option_chain, underlying, "near"),
        "technicals": (_run_technicals, tech_symbol, 200),
    }
    raw: dict = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {}
        for key, call in tasks.items():
            fn, *args = call
            futures[pool.submit(_safe, fn, *args)] = key
        for fut in as_completed(futures):
            raw[futures[fut]] = fut.result()

    vix_data = raw.get("vix", {})
    oc_data = raw.get("oc", {})
    tech_data = raw.get("technicals", {})

    # Determine spot price (prefer option chain spot, fallback to technicals)
    spot = None
    if _ok(oc_data):
        spot = oc_data.get("spot")
    if not spot and _ok(tech_data):
        spot = tech_data.get("current_price")

    if not spot:
        return {"error": "Could not determine spot price for range estimation"}

    lenses: list[dict] = []
    errors: list[str] = []

    # Lens 1: VIX-implied range
    if _ok(vix_data) and vix_data.get("vix"):
        lenses.append(_vix_implied_range(spot, vix_data["vix"], horizon_days))
    else:
        errors.append("VIX unavailable — cannot compute implied range")

    # Lens 2: Bollinger realized range
    if _ok(tech_data):
        bb = _bollinger_range(tech_data)
        if bb:
            lenses.append(bb)
    else:
        errors.append("Technicals unavailable — cannot compute Bollinger range")

    # Lens 3: Historical range from snapshots
    hist = _historical_range_stats(horizon_days)
    if hist:
        lenses.append(hist)

    # Lens 4: OI containment (optional, short-term only)
    oi_zone = None
    if _ok(oc_data):
        oi_zone = _oi_containment(oc_data)

    # Synthesis: extract key levels for quick reference
    key_levels: dict = {"spot": spot}
    for lens in lenses:
        if lens.get("method", "").startswith("VIX"):
            key_levels["vix_1sigma_low"] = lens["range_1sigma"]["low"]
            key_levels["vix_1sigma_high"] = lens["range_1sigma"]["high"]
        elif lens.get("method", "").startswith("Bollinger"):
            key_levels["bollinger_lower"] = lens["lower_band"]
            key_levels["bollinger_upper"] = lens["upper_band"]
    if oi_zone:
        key_levels["oi_support"] = oi_zone["put_oi_wall"]
        key_levels["oi_resistance"] = oi_zone["call_oi_wall"]
        key_levels["max_pain"] = oi_zone["max_pain"]

    return {
        "underlying": underlying,
        "spot": spot,
        "horizon_days": horizon_days,
        "lenses": lenses,
        "oi_containment": oi_zone,
        "key_levels": key_levels,
        "interpretation_guide": (
            "Each lens uses a different method with different validity. "
            "VIX-implied range is the market's own forward estimate of uncertainty. "
            "Bollinger bands reflect recent realized volatility (backward-looking). "
            "Historical range shows what actually happened in similar windows. "
            "OI containment is only valid near the current expiry. "
            "Convergence across lenses increases confidence; divergence means uncertainty."
        ),
        "data_issues": errors or None,
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
