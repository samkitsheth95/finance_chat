"""
Layer 6 — Signal Scoring Engine

Pure functions that normalize raw market signals to a common -1.0 → +1.0 scale,
detect market regimes, flag inter-signal conflicts, and compute weighted composites.

Score convention:
  +1.0 = extremely bullish for Indian equities
   0.0 = neutral
  -1.0 = extremely bearish for Indian equities

No side effects; no imports from tools/ or core/ — just math and logic.
"""

from __future__ import annotations


# ── Utilities ────────────────────────────────────────────────────────

def magnitude_label(score: float) -> str:
    a = abs(score)
    if a >= 0.75:
        return "extreme"
    if a >= 0.5:
        return "strong"
    if a >= 0.25:
        return "moderate"
    if a > 0.05:
        return "mild"
    return "neutral"


def direction_label(score: float) -> str:
    if score > 0.05:
        return "bullish"
    if score < -0.05:
        return "bearish"
    return "neutral"


def _clamp(val: float) -> float:
    return max(-1.0, min(1.0, round(val, 2)))


def _make(score: float, raw, note: str = "") -> dict:
    """Build a standardised scored-signal dict."""
    s = _clamp(score)
    return {
        "score": s,
        "magnitude": magnitude_label(s),
        "direction": direction_label(s),
        "raw": raw,
        "note": note,
    }


def _lerp(value: float, bp: list[tuple[float, float]]) -> float:
    """Piecewise-linear interpolation over sorted (input, output) breakpoints."""
    if value <= bp[0][0]:
        return bp[0][1]
    if value >= bp[-1][0]:
        return bp[-1][1]
    for i in range(len(bp) - 1):
        x0, y0 = bp[i]
        x1, y1 = bp[i + 1]
        if x0 <= value <= x1:
            t = (value - x0) / (x1 - x0) if x1 != x0 else 0
            return y0 + t * (y1 - y0)
    return 0.0


# ── Derivatives signals ──────────────────────────────────────────────

def score_pcr(pcr: float) -> dict:
    """Contrarian PCR: high = put writers defending = bullish."""
    s = _lerp(pcr, [
        (0.40, -1.0), (0.50, -0.75), (0.70, -0.25), (0.85, 0.0),
        (1.00, +0.25), (1.30, +0.75), (1.50, +1.0),
    ])
    return _make(s, round(pcr, 3), f"PCR {pcr:.2f}")


def score_max_pain_distance(spot: float, max_pain: float) -> dict:
    """Spot vs max pain: above = bearish gravity, below = bullish. ±2% → ±1.0."""
    if spot <= 0 or max_pain <= 0:
        return _make(0, None, "max pain unavailable")
    pct = (spot - max_pain) / max_pain * 100
    return _make(
        -pct / 2.0,
        {"spot": spot, "max_pain": int(max_pain), "distance_pct": round(pct, 2)},
        f"Spot {pct:+.1f}% from max pain {int(max_pain)}",
    )


def score_vix(vix: float) -> dict:
    """India VIX as fear gauge: high = bearish for directional longs."""
    s = _lerp(vix, [
        (10, +0.5), (13, +0.25), (16, 0.0),
        (20, -0.25), (25, -0.75), (30, -1.0),
    ])
    return _make(s, round(vix, 1), f"VIX {vix:.1f}")


def score_oi_walls(spot: float, call_wall: float, put_wall: float) -> dict:
    """Spot between put wall (support) and call wall (resistance)."""
    if not (spot and call_wall and put_wall and call_wall > put_wall):
        return _make(0, None, "OI wall data unavailable")
    pos = (spot - put_wall) / (call_wall - put_wall)  # 0→put wall, 1→call wall
    return _make(
        (0.5 - pos),
        {"spot": spot, "call_wall": int(call_wall), "put_wall": int(put_wall)},
        f"Spot between {int(put_wall)} support and {int(call_wall)} resistance",
    )


# ── Flow signals ─────────────────────────────────────────────────────

def score_fii_cash(net_cr: float) -> dict:
    """FII cash market net (₹ crores) — graduated intensity."""
    s = _lerp(net_cr, [
        (-5000, -1.0), (-2000, -0.75), (-1000, -0.5), (-500, -0.25),
        (0, 0.0),
        (500, +0.25), (1000, +0.5), (2000, +0.75), (5000, +1.0),
    ])
    return _make(s, f"{net_cr:+,.0f} Cr", f"FII cash ₹{net_cr:+,.0f} Cr")


def score_dii_cash(net_cr: float) -> dict:
    """DII cash market net (₹ crores)."""
    s = _lerp(net_cr, [
        (-3000, -0.75), (-1000, -0.5), (-500, -0.25),
        (0, 0.0),
        (500, +0.25), (1000, +0.5), (3000, +0.75),
    ])
    return _make(s, f"{net_cr:+,.0f} Cr", f"DII cash ₹{net_cr:+,.0f} Cr")


def score_fii_futures(net_contracts: int) -> dict:
    """FII index futures net — graduated (fixes binary ±50k threshold problem)."""
    s = _lerp(float(net_contracts), [
        (-200_000, -1.0), (-150_000, -0.85), (-100_000, -0.7), (-50_000, -0.5),
        (0, 0.0),
        (50_000, +0.5), (100_000, +0.7), (150_000, +0.85), (200_000, +1.0),
    ])
    return _make(s, net_contracts, f"FII fut net {net_contracts:+,} contracts")


# ── Macro signals ────────────────────────────────────────────────────

_SIG_STR_SCORES: dict[str, float] = {
    "strongly_bullish": +1.0, "bullish": +0.8, "mildly_bullish": +0.4,
    "neutral": 0.0,
    "mildly_bearish": -0.4, "bearish": -0.8, "strongly_bearish": -1.0,
    "unknown": 0.0,
}


def score_signal_string(signal_str: str, label: str) -> dict:
    """Convert an existing text signal (e.g. 'mildly_bearish') to a scored signal."""
    s = _SIG_STR_SCORES.get(signal_str, 0.0)
    return _make(s, signal_str, label)


# ── News signals ─────────────────────────────────────────────────────

def score_event_risk(count: int, total: int) -> dict:
    """Event-risk headline density as a fear signal."""
    if total == 0:
        return _make(0, 0, "no news data")
    s = _lerp(float(count), [
        (0, 0.0), (1, -0.1), (3, -0.35), (5, -0.6), (8, -0.8),
    ])
    return _make(s, count, f"{count} event-risk headlines / {total}")


# ── Regime detection ─────────────────────────────────────────────────

_REGIMES: dict[str, dict] = {
    "extreme_fear": {
        "label": "EXTREME FEAR",
        "focus": "flows",
        "note": "Extreme volatility — FII flows dominate; technicals unreliable",
    },
    "fear": {
        "label": "FEAR",
        "focus": "flows",
        "note": "Elevated fear — institutional flow direction is the primary signal",
    },
    "exodus": {
        "label": "FII EXODUS",
        "focus": "macro",
        "note": "Heavy FII selling driven by macro; focus on DXY, crude, US yields",
    },
    "greed": {
        "label": "GREED",
        "focus": "derivatives",
        "note": "Low fear + call-heavy positioning — option writers control reversal",
    },
    "sideways": {
        "label": "SIDEWAYS",
        "focus": "derivatives",
        "note": "Range-bound — max pain and OI walls dominate; Greeks-driven",
    },
    "expiry": {
        "label": "EXPIRY",
        "focus": "derivatives",
        "note": "Expiry day/week — theta decay at max; max pain gravity strongest",
    },
    "normal": {
        "label": "NORMAL",
        "focus": "balanced",
        "note": "No extreme regime — all layers carry default weight",
    },
}


def detect_regime(
    *,
    vix: float | None = None,
    pcr: float | None = None,
    fii_cash_net_cr: float | None = None,
    nifty_day_range_pct: float | None = None,
    days_to_expiry: int | None = None,
) -> dict:
    """
    Priority: extreme_fear > exodus > fear > expiry > greed > sideways > normal.
    """
    triggers: list[str] = []
    key = "normal"

    if vix is not None and vix > 30:
        key = "extreme_fear"
        triggers.append(f"VIX {vix:.1f} > 30")
    elif fii_cash_net_cr is not None and fii_cash_net_cr < -5000:
        key = "exodus"
        triggers.append(f"FII cash ₹{fii_cash_net_cr:,.0f} Cr (extreme single-day selling)")
    elif vix is not None and vix > 22:
        key = "fear"
        triggers.append(f"VIX {vix:.1f} > 22")
    elif days_to_expiry is not None and days_to_expiry <= 1:
        key = "expiry"
        triggers.append(f"{days_to_expiry}d to expiry — theta decay at maximum")
    elif vix is not None and vix < 13 and pcr is not None and pcr < 0.6:
        key = "greed"
        triggers.append(f"VIX {vix:.1f} < 13, PCR {pcr:.2f} < 0.6")
    elif (vix is not None and 14 <= vix <= 20
          and nifty_day_range_pct is not None and nifty_day_range_pct < 0.8):
        key = "sideways"
        triggers.append(f"VIX {vix:.1f} in normal range, day range {nifty_day_range_pct:.1f}%")

    if days_to_expiry is not None and days_to_expiry <= 3 and key != "expiry":
        triggers.append(f"{days_to_expiry}d to expiry — derivatives carry extra weight")

    info = _REGIMES[key].copy()
    info["key"] = key
    info["triggers"] = triggers
    return info


# ── Default weight profiles ──────────────────────────────────────────

_DEFAULT_WEIGHTS: dict[str, dict[str, float]] = {
    "normal":       {"derivatives": 0.30, "flows": 0.30, "macro": 0.25, "news": 0.15},
    "fear":         {"derivatives": 0.15, "flows": 0.50, "macro": 0.25, "news": 0.10},
    "extreme_fear": {"derivatives": 0.10, "flows": 0.55, "macro": 0.20, "news": 0.15},
    "exodus":       {"derivatives": 0.10, "flows": 0.25, "macro": 0.55, "news": 0.10},
    "greed":        {"derivatives": 0.55, "flows": 0.20, "macro": 0.15, "news": 0.10},
    "sideways":     {"derivatives": 0.55, "flows": 0.20, "macro": 0.15, "news": 0.10},
    "expiry":       {"derivatives": 0.60, "flows": 0.15, "macro": 0.15, "news": 0.10},
}


def get_default_weights(regime_key: str) -> dict[str, float]:
    return _DEFAULT_WEIGHTS.get(regime_key, _DEFAULT_WEIGHTS["normal"]).copy()


# ── Conflict detection ───────────────────────────────────────────────

def find_conflicts(signals: dict) -> list[str]:
    """Identify notable divergences between signal groups."""
    conflicts: list[str] = []
    flows = signals.get("flows", {})
    deriv = signals.get("derivatives", {})
    macro = signals.get("macro", {})

    fc = flows.get("fii_cash", {})
    ff = flows.get("fii_futures_net", {})
    dc = flows.get("dii_cash", {})

    if fc and ff:
        cd, fd = fc.get("direction"), ff.get("direction")
        if cd == "bullish" and fd == "bearish":
            conflicts.append(
                f"FII buying cash ({fc['raw']}) but short futures "
                f"({ff['raw']} contracts) — hedged/cautious"
            )
        elif cd == "bearish" and fd == "bullish":
            conflicts.append(
                f"FII selling cash ({fc['raw']}) but long futures "
                f"({ff['raw']} contracts) — possible rotation"
            )

    if fc and dc:
        if fc.get("direction") == "bearish" and dc.get("direction") == "bullish":
            conflicts.append(
                f"FII selling ({fc['raw']}) but DII absorbing ({dc['raw']})"
            )
        elif fc.get("direction") == "bullish" and dc.get("direction") == "bearish":
            conflicts.append(
                f"FII buying ({fc['raw']}) but DII booking profits ({dc['raw']})"
            )

    mc = macro.get("india_macro", {})
    if mc and fc:
        if mc.get("direction") == "bearish" and fc.get("direction") == "bullish":
            conflicts.append("Macro bearish but FII still buying — India-specific strength")
        elif mc.get("direction") == "bullish" and fc.get("direction") == "bearish":
            conflicts.append("Macro supportive but FII selling — India-specific concern")

    pcr_s = deriv.get("pcr", {})
    vix_s = deriv.get("vix", {})
    if pcr_s and vix_s:
        if pcr_s.get("direction") == "bullish" and vix_s.get("direction") == "bearish":
            conflicts.append(
                f"PCR bullish ({pcr_s['raw']}) but VIX elevated ({vix_s['raw']})"
            )

    return conflicts


# ── Composite ────────────────────────────────────────────────────────

def compute_composite(
    layer_scores: dict[str, float | None],
    weights: dict[str, float],
) -> float:
    """Weighted average of available layer scores."""
    total = w_sum = 0.0
    for layer, score in layer_scores.items():
        if score is not None and layer in weights:
            w = weights[layer]
            total += score * w
            w_sum += w
    return round(total / w_sum, 2) if w_sum else 0.0
