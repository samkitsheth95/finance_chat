"""
Layer 6 — Market Brief

Aggregates all data layers in parallel, normalizes every signal to -1.0 → +1.0,
detects market regime, flags conflicts, and returns a single structured brief.

The brief includes regime-aware default weights. Claude should adjust weighting
based on the user's specific question and time horizon.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from core.signal_scorer import (
    score_pcr,
    score_max_pain_distance,
    score_vix,
    score_oi_walls,
    score_fii_cash,
    score_dii_cash,
    score_fii_futures,
    score_signal_string,
    score_event_risk,
    detect_regime,
    get_default_weights,
    find_conflicts,
    compute_composite,
    magnitude_label,
    direction_label,
)
from core.daily_store import load_recent
from tools.kite_tools import get_indices
from tools.derivatives_tools import get_option_chain, get_vix
from tools.nse_tools import get_fii_dii_activity, get_participant_oi
from tools.macro_tools import get_macro_snapshot
from tools.news_tools import get_market_news
from tools.technicals_tools import technical_analysis as _run_technicals


# Key macro factors most relevant to India FII flow direction.
# (section_in_macro_snapshot, key, human_label)
_KEY_MACRO_FACTORS: list[tuple[str, str, str]] = [
    ("forex",          "dxy",       "DXY (USD strength → EM outflows)"),
    ("forex",          "usdinr",    "USD/INR (rupee weakness)"),
    ("commodities",    "wti_crude", "Crude oil (import bill pressure)"),
    ("global_indices", "sp500",     "S&P 500 (risk-on/off)"),
]


# ── Helpers ──────────────────────────────────────────────────────────

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


def _layer_avg(signals: dict) -> float | None:
    """Average score of scored sub-signals in a layer dict."""
    scores = [
        v["score"] for v in signals.values()
        if isinstance(v, dict) and "score" in v
    ]
    return round(sum(scores) / len(scores), 2) if scores else None


# ── Multi-day context (A3) ────────────────────────────────────────────

def _compute_multiday_context() -> dict:
    """
    Derive multi-day regime inputs from stored daily snapshots.

    Returns dict with optional keys: fii_5d_sum_cr, vix_3d_change_pct,
    drawdown_pct. Fast — reads only local JSON files.
    """
    snaps = load_recent(250)
    if not snaps:
        return {}

    ctx: dict = {}

    recent = snaps[-5:] if len(snaps) >= 5 else snaps
    fii_nets = [s.get("fii_net_cr") for s in recent if s.get("fii_net_cr") is not None]
    if fii_nets:
        ctx["fii_5d_sum_cr"] = round(sum(fii_nets), 2)

    vix_values = [s.get("vix_close") for s in snaps if s.get("vix_close") is not None]
    if len(vix_values) >= 4:
        vix_3d_ago = vix_values[-4]
        vix_now = vix_values[-1]
        if vix_3d_ago and vix_3d_ago > 0:
            ctx["vix_3d_change_pct"] = round((vix_now - vix_3d_ago) / vix_3d_ago * 100, 2)

    nifty_closes = [s.get("nifty_close") for s in snaps if s.get("nifty_close") is not None]
    if nifty_closes:
        peak = max(nifty_closes)
        current = nifty_closes[-1]
        if peak > 0:
            ctx["drawdown_pct"] = round((current - peak) / peak * 100, 2)

    return ctx


# ── Main tool ────────────────────────────────────────────────────────

def get_market_brief() -> dict:
    """
    One-call market brief: fetches all layers, scores signals, detects regime.

    Calls Layers 1–5 in parallel, normalizes every signal to -1.0 → +1.0,
    detects the current market regime, identifies inter-signal conflicts,
    and computes a regime-aware default composite score.

    Returns a structured brief designed for Claude to reason over.
    Claude should adjust the default weights based on the user's question
    type (options/flows/macro/general) and time horizon (intraday → yearly).
    """
    # ── 0. Multi-day context from daily snapshots (local reads) ──
    multiday = _compute_multiday_context()

    # ── 1. Parallel data fetch ────────────────────────────────────
    tasks = {
        "vix":        (get_vix,),
        "oc":         (get_option_chain, "NIFTY", "near"),
        "fii_dii":    (get_fii_dii_activity,),
        "oi":         (get_participant_oi, "latest"),
        "macro":      (get_macro_snapshot,),
        "news":       (get_market_news,),
        "indices":    (get_indices,),
        "technicals": (_run_technicals, "NIFTY 50", 200),
    }
    raw: dict = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {}
        for key, call in tasks.items():
            fn, *args = call
            futures[pool.submit(_safe, fn, *args)] = key
        for fut in as_completed(futures):
            raw[futures[fut]] = fut.result()

    # ── 2. Score derivatives ──────────────────────────────────────
    deriv: dict = {}
    oc = raw.get("oc", {})
    vix_data = raw.get("vix", {})

    if _ok(oc):
        pcr_val = oc.get("pcr", {}).get("value")
        if pcr_val is not None:
            deriv["pcr"] = score_pcr(pcr_val)

        spot = oc.get("spot")
        mp = oc.get("max_pain", {}).get("strike")
        if spot and mp:
            deriv["max_pain_distance"] = score_max_pain_distance(spot, mp)

        cw = (oc.get("call_oi_wall") or {}).get("strike")
        pw = (oc.get("put_oi_wall") or {}).get("strike")
        if spot and cw and pw:
            deriv["oi_walls"] = score_oi_walls(spot, cw, pw)

    if _ok(vix_data):
        vix_val = vix_data.get("vix")
        if vix_val is not None:
            deriv["vix"] = score_vix(vix_val)

    deriv["layer_score"] = _layer_avg(deriv)

    # ── 3. Score flows ────────────────────────────────────────────
    flows: dict = {}
    fii_dii = raw.get("fii_dii", {})
    oi_data = raw.get("oi", {})

    if _ok(fii_dii):
        fii_net = fii_dii.get("fii", {}).get("net_cr")
        if fii_net is not None:
            flows["fii_cash"] = score_fii_cash(fii_net)
        dii_net = fii_dii.get("dii", {}).get("net_cr")
        if dii_net is not None:
            flows["dii_cash"] = score_dii_cash(dii_net)

    if _ok(oi_data):
        fii_fut = oi_data.get("participants", {}).get("FII", {}).get("fut_index_net")
        if fii_fut is not None:
            flows["fii_futures_net"] = score_fii_futures(fii_fut)

    flows["layer_score"] = _layer_avg(flows)

    # ── 4. Score macro ────────────────────────────────────────────
    macro: dict = {}
    macro_data = raw.get("macro", {})

    if _ok(macro_data):
        # Composite signal
        comp_str = macro_data.get("india_macro_signal")
        if comp_str:
            macro["india_macro"] = score_signal_string(
                comp_str,
                "India macro composite: " + comp_str,
            )

        # Key individual factors
        for section, fkey, label in _KEY_MACRO_FACTORS:
            factor = macro_data.get(section, {}).get(fkey, {})
            sig = factor.get("india_signal")
            if sig:
                change_pct = factor.get("change_pct")
                suffix = f" ({change_pct:+.2f}%)" if change_pct is not None else ""
                macro[fkey] = score_signal_string(sig, label + suffix)

        # US 10Y yield — extracted separately because it lives in us_yields
        us10y = macro_data.get("us_yields", {}).get("us10y", {})
        sig_10y = us10y.get("india_signal")
        if sig_10y:
            level = us10y.get("yield_pct")
            suffix = f" (at {level:.2f}%)" if level is not None else ""
            macro["us10y"] = score_signal_string(
                sig_10y,
                f"US 10Y yield{suffix}",
            )

    macro_comp = macro.get("india_macro", {})
    macro["layer_score"] = macro_comp.get("score") if macro_comp else None

    # ── 5. Score news ─────────────────────────────────────────────
    news: dict = {}
    news_data = raw.get("news", {})

    if _ok(news_data):
        news["event_risk"] = score_event_risk(
            news_data.get("event_risk_count", 0),
            news_data.get("total_headlines", 0),
        )
        er_headlines = news_data.get("event_risk_headlines", [])
        if er_headlines:
            news["event_risk_headlines"] = er_headlines[:5]

    news["layer_score"] = (news.get("event_risk") or {}).get("score")

    # ── 6. Context extraction ─────────────────────────────────────
    # Nifty spot + day range for regime detection
    indices = raw.get("indices", {})
    nifty_spot = nifty_change_pct = nifty_range_pct = None
    if _ok(indices):
        n50 = indices.get("NIFTY 50", {})
        nifty_spot = n50.get("ltp")
        nifty_change_pct = n50.get("change_pct")
        high = n50.get("high")
        low = n50.get("low")
        if high and low and low > 0:
            nifty_range_pct = round((high - low) / low * 100, 2)

    days_to_expiry = oc.get("days_to_expiry") if _ok(oc) else None
    vix_val = vix_data.get("vix") if _ok(vix_data) else None
    pcr_val = (oc.get("pcr", {}).get("value")) if _ok(oc) else None
    fii_cash_net = fii_dii.get("fii", {}).get("net_cr") if _ok(fii_dii) else None

    # A3: extract 200 DMA distance from technicals
    nifty_vs_200dma_pct = None
    tech_data = raw.get("technicals", {})
    if _ok(tech_data):
        nifty_vs_200dma_pct = tech_data.get("dma", {}).get("distance_200dma_pct")

    # S2: single-day VIX rate of change
    vix_day_change_pct = None
    if _ok(vix_data):
        vix_day_change_pct = vix_data.get("change_pct")

    # ── 7. Regime detection (A3 + S2 enhanced) ────────────────────
    regime = detect_regime(
        vix=vix_val,
        pcr=pcr_val,
        fii_cash_net_cr=fii_cash_net,
        nifty_day_range_pct=nifty_range_pct,
        days_to_expiry=days_to_expiry,
        fii_5d_sum_cr=multiday.get("fii_5d_sum_cr"),
        vix_3d_change_pct=multiday.get("vix_3d_change_pct"),
        drawdown_pct=multiday.get("drawdown_pct"),
        nifty_vs_200dma_pct=nifty_vs_200dma_pct,
        vix_change_pct=vix_day_change_pct,
    )

    # ── 8. Composite score (S1: agreement multiplier) ────────────
    weights = get_default_weights(regime["key"])
    layer_scores = {
        "derivatives": deriv.get("layer_score"),
        "flows":       flows.get("layer_score"),
        "macro":       macro.get("layer_score"),
        "news":        news.get("layer_score"),
    }
    composite_result = compute_composite(layer_scores, weights)
    composite = composite_result["score"]

    # ── 9. Conflicts ──────────────────────────────────────────────
    conflicts = find_conflicts({
        "derivatives": deriv,
        "flows": flows,
        "macro": macro,
    })

    # ── 10. Data issues ───────────────────────────────────────────
    errors = [
        f"{k}: {v['_error']}" for k, v in raw.items()
        if isinstance(v, dict) and "_error" in v
    ]

    # ── 11. Assemble brief ────────────────────────────────────────
    composite_block: dict = {
        "score": composite,
        "magnitude": magnitude_label(composite),
        "direction": direction_label(composite),
        "weights_used": weights,
        "layer_scores": {k: v for k, v in layer_scores.items() if v is not None},
    }
    if composite_result.get("agreement_boost"):
        composite_block["agreement_boost"] = True
        composite_block["agreement_detail"] = (
            f"{composite_result['layers_bullish']}B/{composite_result['layers_bearish']}Be "
            f"of {composite_result['layers_available']} layers — 1.3× amplified"
        )

    multiday_block: dict = {}
    if multiday.get("fii_5d_sum_cr") is not None:
        multiday_block["fii_5d_sum_cr"] = multiday["fii_5d_sum_cr"]
    if multiday.get("vix_3d_change_pct") is not None:
        multiday_block["vix_3d_change_pct"] = multiday["vix_3d_change_pct"]
    if multiday.get("drawdown_pct") is not None:
        multiday_block["drawdown_pct"] = multiday["drawdown_pct"]
    if nifty_vs_200dma_pct is not None:
        multiday_block["nifty_vs_200dma_pct"] = nifty_vs_200dma_pct

    return {
        "nifty": {
            "spot": nifty_spot,
            "change_pct": nifty_change_pct,
            "days_to_expiry": days_to_expiry,
        },
        "regime": regime,
        "multiday_context": multiday_block or None,
        "signals": {
            "derivatives": deriv,
            "flows": flows,
            "macro": macro,
            "news": news,
        },
        "conflicts": conflicts,
        "composite": composite_block,
        "data_issues": errors or None,
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
