"""
Stock-Level Signal Scoring

Pure functions that normalize per-stock signals to a common -1.0 → +1.0 scale,
detect a stock stance (the per-stock equivalent of market regime), and compute
a weighted composite.

Score convention (same as signal_scorer.py):
  +1.0 = extremely bullish
   0.0 = neutral
  -1.0 = extremely bearish

No side effects; no imports from tools/ or core/ — just math and logic.
"""

from __future__ import annotations

from core.signal_scorer import _clamp, _make, _lerp, magnitude_label, direction_label


# ── Technical signals ────────────────────────────────────────────────

def score_technicals(tech_data: dict) -> dict:
    """Score from technical_analysis() result using the composite stance."""
    stance = tech_data.get("technical_stance", {})
    bullish = stance.get("bullish_count", 0)
    bearish = stance.get("bearish_count", 0)
    total = stance.get("total_signals", 0)

    if total == 0:
        return _make(0, stance.get("signal", "neutral"), "No technical signals")

    net = (bullish - bearish) / total

    dma_trend = tech_data.get("dma", {}).get("trend", "")
    if dma_trend == "strong_uptrend":
        net = min(net + 0.15, 1.0)
    elif dma_trend == "strong_downtrend":
        net = max(net - 0.15, -1.0)

    signal = stance.get("signal", "neutral")
    return _make(net, signal, f"{signal} ({bullish}B/{bearish}Be of {total})")


def score_relative_strength(rs_data: dict | None) -> dict:
    """Score relative strength vs Nifty across timeframes.

    Weights: 1w × 1.0, 1m × 1.5, 3m × 2.0 (longer term matters more).
    Maps ±5% weighted-avg outperformance → ±1.0.
    """
    if not rs_data:
        return _make(0, None, "Relative strength unavailable")

    weights = {"1_week": 1.0, "1_month": 1.5, "3_month": 2.0}
    total = w_sum = 0.0
    for period, w in weights.items():
        if period in rs_data:
            op = rs_data[period].get("outperformance_pct", 0)
            total += op * w
            w_sum += w

    if w_sum == 0:
        return _make(0, None, "No relative strength data")

    avg = total / w_sum
    score = avg / 5.0

    parts = [
        f"{k}: {v.get('outperformance_pct', 0):+.1f}%"
        for k, v in rs_data.items()
    ]
    return _make(score, rs_data, f"vs Nifty: {', '.join(parts)}")


# ── Fundamental signals ──────────────────────────────────────────────

_VALUATION_SCORES: dict[str, float] = {
    "potentially_undervalued": +0.7,
    "low_valuation": +0.6,
    "fairly_valued": +0.2,
    "moderate_valuation": 0.0,
    "fully_valued": -0.2,
    "high_valuation": -0.4,
    "potentially_overvalued": -0.7,
    "very_high_valuation": -0.8,
    "loss_making": -0.5,
    "insufficient_data": 0.0,
}


def score_valuation(val_data: dict) -> dict:
    """Score from fundamentals valuation assessment."""
    signal = val_data.get("signal", "insufficient_data")
    score = _VALUATION_SCORES.get(signal, 0.0)

    details = val_data.get("details", [])
    note = f"Valuation: {signal}"
    if details:
        note += f" — {details[0]}"
    return _make(score, signal, note)


def score_growth(growth_data: dict) -> dict:
    """Score revenue + earnings growth. Earnings weighted 60/40."""
    rev_g = growth_data.get("revenue_growth_pct")
    earn_g = growth_data.get("earnings_growth_pct")

    if rev_g is None and earn_g is None:
        return _make(0, None, "Growth data unavailable")

    scores = []
    parts = []
    if earn_g is not None:
        scores.append((earn_g / 30.0, 0.6))
        parts.append(f"Earn {earn_g:+.1f}%")
    if rev_g is not None:
        scores.append((rev_g / 30.0, 0.4))
        parts.append(f"Rev {rev_g:+.1f}%")

    w_sum = sum(w for _, w in scores)
    avg = sum(s * w for s, w in scores) / w_sum if w_sum else 0

    return _make(avg, growth_data, f"Growth: {', '.join(parts)}")


_HEALTH_SCORES: dict[str, float] = {
    "strong": +0.5,
    "healthy": +0.3,
    "adequate": 0.0,
    "low_liquidity": -0.3,
    "moderate_leverage": -0.4,
    "highly_leveraged": -0.7,
}


def score_financial_health(health_data: dict) -> dict:
    """Score financial health from debt/equity + current ratio assessment."""
    assessment = health_data.get("assessment", "adequate")
    score = _HEALTH_SCORES.get(assessment, 0.0)

    parts = [assessment]
    de = health_data.get("debt_equity")
    cr = health_data.get("current_ratio")
    if de is not None:
        parts.append(f"D/E {de:.1f}")
    if cr is not None:
        parts.append(f"CR {cr:.2f}")

    return _make(score, assessment, f"Health: {', '.join(parts)}")


# ── Session momentum ─────────────────────────────────────────────────

def score_momentum(change_pct: float | None) -> dict:
    """Score today's session change. ±3% → ±1.0."""
    if change_pct is None:
        return _make(0, None, "No session data")

    score = change_pct / 3.0
    return _make(score, round(change_pct, 2), f"Session: {change_pct:+.2f}%")


# ── News ─────────────────────────────────────────────────────────────

def score_stock_news(news_data: dict) -> dict:
    """Light scoring from news_search results — mainly event-risk density.

    Claude does the real sentiment interpretation from headline text.
    This just flags whether there's notable event-risk noise.
    """
    if not news_data or "_error" in news_data or "error" in news_data:
        return _make(0, None, "News unavailable")

    total = news_data.get("total_results", 0)
    if total == 0:
        return _make(0, 0, "No recent news")

    headlines = news_data.get("headlines", [])
    er_count = sum(1 for h in headlines if h.get("event_risk"))

    score = _lerp(float(er_count), [
        (0, 0.0), (1, -0.15), (3, -0.35), (5, -0.6),
    ])
    return _make(score, er_count, f"{total} headlines, {er_count} event-risk")


# ── Stock stance (per-stock equivalent of market regime) ─────────────

_STOCK_STANCES: dict[str, dict] = {
    "technically_strong": {
        "label": "TECHNICALLY STRONG",
        "note": "Strong price action and relative strength — trend is the primary signal",
    },
    "fundamentally_strong": {
        "label": "FUNDAMENTALLY STRONG",
        "note": "Good valuation + growth — suited for medium-to-long-term positioning",
    },
    "momentum_expensive": {
        "label": "MOMENTUM (EXPENSIVE)",
        "note": "Strong technicals but stretched valuation — ride the trend with a tight stop",
    },
    "value_with_weak_momentum": {
        "label": "VALUE OPPORTUNITY",
        "note": "Attractive fundamentals but weak price action — may need a catalyst to re-rate",
    },
    "technically_weak": {
        "label": "TECHNICALLY WEAK",
        "note": "Poor price action — wait for trend reversal before entry",
    },
    "overvalued": {
        "label": "OVERVALUED",
        "note": "Stretched valuation without supporting growth — risk of de-rating",
    },
    "deteriorating": {
        "label": "DETERIORATING",
        "note": "Weak technicals + poor fundamentals — avoid or consider exit",
    },
    "neutral": {
        "label": "NEUTRAL",
        "note": "Mixed signals across dimensions — no strong directional conviction",
    },
}


def detect_stock_stance(signals: dict) -> dict:
    """Determine the stock's overall stance from scored signals."""
    def _score(key: str) -> float:
        return signals.get(key, {}).get("score", 0)

    tech = _score("technicals")
    rs = _score("relative_strength")
    val = _score("valuation")
    growth = _score("growth")
    health = _score("financial_health")

    if tech < -0.3 and (val < -0.2 or health < -0.2):
        key = "deteriorating"
    elif tech > 0.3 and rs > 0.15:
        key = "momentum_expensive" if val < -0.3 else "technically_strong"
    elif val > 0.3 and growth > 0.15:
        key = "value_with_weak_momentum" if tech < -0.2 else "fundamentally_strong"
    elif tech < -0.3:
        key = "technically_weak"
    elif val < -0.3:
        key = "overvalued"
    else:
        key = "neutral"

    info = _STOCK_STANCES[key].copy()
    info["key"] = key
    return info


# ── Stance-based weight profiles ──────────────────────────────────────
#
# Each stance shifts which signal dimensions matter most:
#
#   neutral               — Mixed signals. Balanced weights.
#   technically_strong    — Strong price action + RS. Technicals and momentum lead.
#   fundamentally_strong  — Good valuation + growth. Fundamentals dominate.
#   momentum_expensive    — Riding a trend on stretched valuation. Both technicals
#                           and valuation need high weight to surface the tension.
#   value_with_weak_momentum — Attractive fundamentals, weak price. Fundamentals
#                           dominate; technicals help time entry.
#   technically_weak      — Poor price action. Technicals + momentum to spot reversal.
#   overvalued            — Stretched valuation. Valuation + growth are key.
#   deteriorating         — Weak everything. Financial health matters more (survival risk).
#
# Rows sum to 1.0.

_STANCE_WEIGHTS: dict[str, dict[str, float]] = {
    #                           tech    rs      val     growth  health  mom     news
    "neutral":                 {"technicals": 0.25, "relative_strength": 0.10, "valuation": 0.20, "growth": 0.15, "financial_health": 0.10, "momentum": 0.10, "news": 0.10},
    "technically_strong":      {"technicals": 0.30, "relative_strength": 0.15, "valuation": 0.10, "growth": 0.10, "financial_health": 0.05, "momentum": 0.20, "news": 0.10},
    "fundamentally_strong":    {"technicals": 0.15, "relative_strength": 0.05, "valuation": 0.25, "growth": 0.25, "financial_health": 0.15, "momentum": 0.05, "news": 0.10},
    "momentum_expensive":      {"technicals": 0.25, "relative_strength": 0.15, "valuation": 0.25, "growth": 0.10, "financial_health": 0.05, "momentum": 0.15, "news": 0.05},
    "value_with_weak_momentum": {"technicals": 0.15, "relative_strength": 0.05, "valuation": 0.25, "growth": 0.25, "financial_health": 0.15, "momentum": 0.05, "news": 0.10},
    "technically_weak":        {"technicals": 0.30, "relative_strength": 0.10, "valuation": 0.15, "growth": 0.10, "financial_health": 0.10, "momentum": 0.15, "news": 0.10},
    "overvalued":              {"technicals": 0.15, "relative_strength": 0.10, "valuation": 0.30, "growth": 0.20, "financial_health": 0.10, "momentum": 0.05, "news": 0.10},
    "deteriorating":           {"technicals": 0.20, "relative_strength": 0.10, "valuation": 0.20, "growth": 0.15, "financial_health": 0.20, "momentum": 0.05, "news": 0.10},
}


def get_stock_weights(stance_key: str = "neutral") -> dict[str, float]:
    return _STANCE_WEIGHTS.get(stance_key, _STANCE_WEIGHTS["neutral"]).copy()


_AGREEMENT_MULTIPLIER = 1.3
_AGREEMENT_MIN_LAYERS = 3
_AGREEMENT_THRESHOLD = 0.15


def compute_stock_composite(
    layer_scores: dict[str, float | None],
    weights: dict[str, float],
) -> dict:
    """
    Weighted average of available stock signal scores.

    When ≥3 dimensions agree on direction, amplify composite by 1.3×
    (capped at ±1.0). Mirrors market-level agreement logic.
    """
    total = w_sum = 0.0
    for layer, score in layer_scores.items():
        if score is not None and layer in weights:
            w = weights[layer]
            total += score * w
            w_sum += w
    composite = total / w_sum if w_sum else 0.0

    available = {k: v for k, v in layer_scores.items() if v is not None}
    bullish_count = sum(1 for v in available.values() if v > _AGREEMENT_THRESHOLD)
    bearish_count = sum(1 for v in available.values() if v < -_AGREEMENT_THRESHOLD)

    agreement_boost = False
    if len(available) >= _AGREEMENT_MIN_LAYERS:
        if bullish_count >= _AGREEMENT_MIN_LAYERS or bearish_count >= _AGREEMENT_MIN_LAYERS:
            composite *= _AGREEMENT_MULTIPLIER
            agreement_boost = True

    return {
        "score": _clamp(composite),
        "magnitude": magnitude_label(_clamp(composite)),
        "direction": direction_label(_clamp(composite)),
        "agreement_boost": agreement_boost,
        "layers_bullish": bullish_count,
        "layers_bearish": bearish_count,
        "layers_available": len(available),
    }
