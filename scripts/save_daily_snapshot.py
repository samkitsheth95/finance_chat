#!/usr/bin/env python3
"""
Daily Snapshot Saver

Run at ~9:30 PM IST each trading day (after NSE publishes FII/DII at 8:30–9:30 PM).
Fetches all layers in parallel, extracts key scalar metrics, and writes a flat
JSON snapshot to data/daily/YYYY-MM-DD.json.

Usage:
    python -m scripts.save_daily_snapshot           # today
    python -m scripts.save_daily_snapshot 2026-03-11 # specific date (warns about stale data)

Cron example (9:30 PM IST = 4:00 PM UTC, Mon–Fri):
    0 16 * * 1-5 cd /path/to/finance_chat && .venv/bin/python -m scripts.save_daily_snapshot
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime

from core.daily_store import save


# ── Data fetchers ─────────────────────────────────────────────────────

def _safe(fn, *args, **kwargs) -> dict | None:
    """Call fn, return result or None on error."""
    try:
        result = fn(*args, **kwargs)
        if isinstance(result, dict) and "error" in result:
            print(f"  WARN  {fn.__name__}: {result['error']}")
            return None
        return result
    except Exception as e:
        print(f"  ERROR {fn.__name__}: {e}")
        return None


def _fetch_all() -> dict:
    """Fetch all layers in parallel and return raw results keyed by layer name."""
    from tools.kite_tools import get_indices, get_historical_ohlc
    from tools.derivatives_tools import get_option_chain, get_vix
    from tools.nse_tools import get_fii_dii_activity, get_participant_oi
    from tools.macro_tools import get_macro_snapshot
    from tools.news_tools import get_market_news
    from tools.technicals_tools import technical_analysis

    tasks = {
        "indices":   (get_indices,),
        "nifty_ohlc": (get_historical_ohlc, "NIFTY 50", "day", 1),
        "vix":       (get_vix,),
        "oc":        (get_option_chain, "NIFTY", "near"),
        "fii_dii":   (get_fii_dii_activity,),
        "oi":        (get_participant_oi, "latest"),
        "macro":     (get_macro_snapshot,),
        "news":      (get_market_news,),
        "technicals": (technical_analysis, "NIFTY 50", 200),
    }

    raw: dict = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {}
        for key, call in tasks.items():
            fn, *args = call
            futures[pool.submit(_safe, fn, *args)] = key
        for fut in as_completed(futures):
            raw[futures[fut]] = fut.result()

    return raw


# ── Snapshot extraction ───────────────────────────────────────────────

def _extract_snapshot(raw: dict) -> dict:
    """Flatten parallel-fetched raw data into a compact snapshot dict."""
    snap: dict = {}

    # --- Nifty 50 ---
    indices = raw.get("indices") or {}
    n50 = indices.get("NIFTY 50", {})
    snap["nifty_close"] = n50.get("ltp")
    snap["nifty_open"] = n50.get("open")
    snap["nifty_high"] = n50.get("high")
    snap["nifty_low"] = n50.get("low")
    snap["nifty_prev_close"] = n50.get("prev_close")
    snap["nifty_change_pct"] = n50.get("change_pct")

    # BankNifty
    bnf = indices.get("NIFTY BANK", {})
    snap["banknifty_close"] = bnf.get("ltp")
    snap["banknifty_change_pct"] = bnf.get("change_pct")

    # Nifty day range %
    if n50.get("high") and n50.get("low") and n50["low"] > 0:
        snap["nifty_day_range_pct"] = round(
            (n50["high"] - n50["low"]) / n50["low"] * 100, 2
        )
    else:
        snap["nifty_day_range_pct"] = None

    # --- VIX ---
    vix = raw.get("vix") or {}
    snap["vix_close"] = vix.get("vix")
    snap["vix_prev_close"] = vix.get("prev_close")
    snap["vix_change_pct"] = vix.get("change_pct")
    snap["vix_regime"] = vix.get("regime")

    # --- Derivatives (Nifty option chain) ---
    oc = raw.get("oc") or {}
    snap["nifty_spot"] = oc.get("spot")
    snap["nifty_pcr"] = (oc.get("pcr") or {}).get("value")
    snap["nifty_total_call_oi"] = (oc.get("pcr") or {}).get("total_call_oi")
    snap["nifty_total_put_oi"] = (oc.get("pcr") or {}).get("total_put_oi")
    snap["nifty_max_pain"] = (oc.get("max_pain") or {}).get("strike")
    snap["nifty_call_wall"] = (oc.get("call_oi_wall") or {}).get("strike")
    snap["nifty_call_wall_oi"] = (oc.get("call_oi_wall") or {}).get("oi")
    snap["nifty_put_wall"] = (oc.get("put_oi_wall") or {}).get("strike")
    snap["nifty_put_wall_oi"] = (oc.get("put_oi_wall") or {}).get("oi")
    snap["nifty_atm_strike"] = oc.get("atm_strike")
    snap["days_to_expiry"] = oc.get("days_to_expiry")

    # --- FII / DII cash flows ---
    fd = raw.get("fii_dii") or {}
    fii = fd.get("fii", {})
    dii = fd.get("dii", {})
    snap["fii_dii_data_date"] = fd.get("date")
    snap["fii_buy_cr"] = fii.get("buy_cr")
    snap["fii_sell_cr"] = fii.get("sell_cr")
    snap["fii_net_cr"] = fii.get("net_cr")
    snap["dii_buy_cr"] = dii.get("buy_cr")
    snap["dii_sell_cr"] = dii.get("sell_cr")
    snap["dii_net_cr"] = dii.get("net_cr")
    snap["fii_dii_combined_net_cr"] = fd.get("combined_net")
    snap["fii_dii_signal"] = fd.get("signal")

    # --- Participant OI (F&O) ---
    oi = raw.get("oi") or {}
    participants = oi.get("participants", {})
    fii_oi = participants.get("FII", {})
    snap["fii_fut_index_long"] = fii_oi.get("fut_index_long")
    snap["fii_fut_index_short"] = fii_oi.get("fut_index_short")
    snap["fii_fut_index_net"] = fii_oi.get("fut_index_net")
    snap["fii_total_long"] = fii_oi.get("total_long")
    snap["fii_total_short"] = fii_oi.get("total_short")
    snap["fii_total_net"] = fii_oi.get("total_net")
    snap["fii_futures_signal"] = oi.get("fii_index_futures_signal")

    # Client (retail) OI for FII-vs-retail divergence
    client_oi = participants.get("Client", {})
    snap["client_fut_index_net"] = client_oi.get("fut_index_net")
    snap["client_total_net"] = client_oi.get("total_net")

    # --- Macro ---
    macro = raw.get("macro") or {}
    snap["india_macro_signal"] = macro.get("india_macro_signal")

    # Key individual factors
    gi = macro.get("global_indices", {})
    sp = gi.get("sp500", {})
    snap["sp500_change_pct"] = sp.get("change_pct")
    snap["sp500_signal"] = sp.get("india_signal")

    fx = macro.get("forex", {})
    dxy = fx.get("dxy", {})
    snap["dxy_price"] = dxy.get("price")
    snap["dxy_change_pct"] = dxy.get("change_pct")
    snap["dxy_signal"] = dxy.get("india_signal")

    usdinr = fx.get("usdinr", {})
    snap["usdinr_price"] = usdinr.get("price")
    snap["usdinr_change_pct"] = usdinr.get("change_pct")
    snap["usdinr_signal"] = usdinr.get("india_signal")

    comm = macro.get("commodities", {})
    crude = comm.get("wti_crude", {})
    snap["crude_price"] = crude.get("price")
    snap["crude_change_pct"] = crude.get("change_pct")
    snap["crude_signal"] = crude.get("india_signal")

    gold = comm.get("gold", {})
    snap["gold_price"] = gold.get("price")
    snap["gold_change_pct"] = gold.get("change_pct")

    ust = macro.get("us_yields", {})
    us10y = ust.get("us10y", {})
    snap["us10y_yield"] = us10y.get("yield_pct")
    snap["us10y_signal"] = us10y.get("india_signal")
    us5y = ust.get("us5y", {})
    snap["us5y_yield"] = us5y.get("yield_pct")
    curve = ust.get("yield_curve", {})
    snap["yield_curve_spread"] = curve.get("ten_minus_five_pct")

    # --- News ---
    news = raw.get("news") or {}
    snap["event_risk_count"] = news.get("event_risk_count", 0)
    snap["total_headlines"] = news.get("total_headlines", 0)
    er = news.get("event_risk_headlines", [])
    snap["event_risk_headlines"] = [
        h.get("title", h) if isinstance(h, dict) else str(h)
        for h in er[:5]
    ]

    # --- Nifty Technicals ---
    tech = raw.get("technicals") or {}
    dma = tech.get("dma", {})
    snap["nifty_rsi"] = (tech.get("rsi") or {}).get("value")
    snap["nifty_rsi_signal"] = (tech.get("rsi") or {}).get("signal")
    snap["nifty_dma_20"] = dma.get("dma_20")
    snap["nifty_dma_50"] = dma.get("dma_50")
    snap["nifty_dma_200"] = dma.get("dma_200")
    snap["nifty_vs_200dma_pct"] = dma.get("distance_200dma_pct")
    snap["nifty_vs_50dma_pct"] = dma.get("distance_50dma_pct")
    snap["nifty_dma_trend"] = dma.get("trend")
    snap["nifty_dma_cross"] = dma.get("cross")
    boll = tech.get("bollinger") or {}
    snap["nifty_bollinger_bandwidth"] = boll.get("bandwidth_pct")
    snap["nifty_bollinger_pct_b"] = boll.get("percent_b")
    snap["nifty_bollinger_signal"] = boll.get("signal")
    macd = tech.get("macd") or {}
    snap["nifty_macd_histogram"] = macd.get("histogram")
    snap["nifty_macd_crossover"] = macd.get("crossover")
    snap["nifty_macd_trend"] = macd.get("trend")
    snap["nifty_technical_stance"] = (tech.get("technical_stance") or {}).get("signal")

    # --- Computed scores (run signal scorer on extracted values) ---
    snap.update(_compute_scores(snap))

    return snap


def _compute_scores(snap: dict) -> dict:
    """Run the signal scorer on extracted snapshot values."""
    from core.signal_scorer import (
        score_pcr, score_max_pain_distance, score_vix, score_oi_walls,
        score_fii_cash, score_dii_cash, score_fii_futures,
        score_signal_string, score_event_risk,
        detect_regime, get_default_weights, compute_composite,
        find_conflicts, magnitude_label, direction_label,
    )

    scores: dict = {}

    # Derivatives
    deriv_scores = []
    if snap.get("nifty_pcr") is not None:
        s = score_pcr(snap["nifty_pcr"])
        scores["score_pcr"] = s["score"]
        deriv_scores.append(s["score"])
    if snap.get("nifty_spot") and snap.get("nifty_max_pain"):
        s = score_max_pain_distance(snap["nifty_spot"], snap["nifty_max_pain"])
        scores["score_max_pain"] = s["score"]
        deriv_scores.append(s["score"])
    if snap.get("vix_close") is not None:
        s = score_vix(snap["vix_close"])
        scores["score_vix"] = s["score"]
        deriv_scores.append(s["score"])
    if snap.get("nifty_spot") and snap.get("nifty_call_wall") and snap.get("nifty_put_wall"):
        s = score_oi_walls(snap["nifty_spot"], snap["nifty_call_wall"], snap["nifty_put_wall"])
        scores["score_oi_walls"] = s["score"]
        deriv_scores.append(s["score"])
    scores["layer_derivatives"] = (
        round(sum(deriv_scores) / len(deriv_scores), 2) if deriv_scores else None
    )

    # Flows
    flow_scores = []
    if snap.get("fii_net_cr") is not None:
        s = score_fii_cash(snap["fii_net_cr"])
        scores["score_fii_cash"] = s["score"]
        flow_scores.append(s["score"])
    if snap.get("dii_net_cr") is not None:
        s = score_dii_cash(snap["dii_net_cr"])
        scores["score_dii_cash"] = s["score"]
        flow_scores.append(s["score"])
    if snap.get("fii_fut_index_net") is not None:
        s = score_fii_futures(snap["fii_fut_index_net"])
        scores["score_fii_futures"] = s["score"]
        flow_scores.append(s["score"])
    scores["layer_flows"] = (
        round(sum(flow_scores) / len(flow_scores), 2) if flow_scores else None
    )

    # Macro
    if snap.get("india_macro_signal"):
        s = score_signal_string(snap["india_macro_signal"], "macro composite")
        scores["score_macro"] = s["score"]
        scores["layer_macro"] = s["score"]
    else:
        scores["layer_macro"] = None

    # News
    if snap.get("total_headlines"):
        s = score_event_risk(snap.get("event_risk_count", 0), snap["total_headlines"])
        scores["score_event_risk"] = s["score"]
        scores["layer_news"] = s["score"]
    else:
        scores["layer_news"] = None

    # Multi-day context from stored snapshots (A3)
    from core.daily_store import load_recent as _load_recent
    prior_snaps = _load_recent(10)
    fii_5d_sum_cr = None
    vix_3d_change_pct = None
    drawdown_pct = None

    if prior_snaps:
        recent_5 = prior_snaps[-5:] if len(prior_snaps) >= 5 else prior_snaps
        fii_nets_hist = [s.get("fii_net_cr") for s in recent_5 if s.get("fii_net_cr") is not None]
        if fii_nets_hist:
            fii_5d_sum_cr = round(sum(fii_nets_hist), 2)

        vix_hist = [s.get("vix_close") for s in prior_snaps if s.get("vix_close") is not None]
        if len(vix_hist) >= 4 and snap.get("vix_close"):
            vix_3d_ago = vix_hist[-3]
            if vix_3d_ago and vix_3d_ago > 0:
                vix_3d_change_pct = round(
                    (snap["vix_close"] - vix_3d_ago) / vix_3d_ago * 100, 2
                )

        nifty_hist = [s.get("nifty_close") for s in prior_snaps if s.get("nifty_close") is not None]
        if nifty_hist and snap.get("nifty_close"):
            peak = max(nifty_hist)
            if peak > 0:
                drawdown_pct = round((snap["nifty_close"] - peak) / peak * 100, 2)

    # Regime (A3 + S2 enhanced)
    regime = detect_regime(
        vix=snap.get("vix_close"),
        pcr=snap.get("nifty_pcr"),
        fii_cash_net_cr=snap.get("fii_net_cr"),
        nifty_day_range_pct=snap.get("nifty_day_range_pct"),
        days_to_expiry=snap.get("days_to_expiry"),
        fii_5d_sum_cr=fii_5d_sum_cr,
        vix_3d_change_pct=vix_3d_change_pct,
        drawdown_pct=drawdown_pct,
        nifty_vs_200dma_pct=snap.get("nifty_vs_200dma_pct"),
        vix_change_pct=snap.get("vix_change_pct"),
    )
    scores["regime"] = regime["key"]
    scores["regime_label"] = regime["label"]
    scores["regime_triggers"] = regime["triggers"]

    # Composite (S1: agreement multiplier)
    weights = get_default_weights(regime["key"])
    layer_scores = {
        "derivatives": scores.get("layer_derivatives"),
        "flows": scores.get("layer_flows"),
        "macro": scores.get("layer_macro"),
        "news": scores.get("layer_news"),
    }
    composite_result = compute_composite(layer_scores, weights)
    scores["composite_score"] = composite_result["score"]
    scores["composite_magnitude"] = magnitude_label(composite_result["score"])
    scores["composite_direction"] = direction_label(composite_result["score"])
    scores["composite_agreement_boost"] = composite_result.get("agreement_boost", False)
    scores["weights_used"] = weights

    # Conflicts
    signals_for_conflict = {
        "derivatives": {},
        "flows": {},
        "macro": {},
    }
    if snap.get("fii_net_cr") is not None:
        signals_for_conflict["flows"]["fii_cash"] = score_fii_cash(snap["fii_net_cr"])
    if snap.get("dii_net_cr") is not None:
        signals_for_conflict["flows"]["dii_cash"] = score_dii_cash(snap["dii_net_cr"])
    if snap.get("fii_fut_index_net") is not None:
        signals_for_conflict["flows"]["fii_futures_net"] = score_fii_futures(snap["fii_fut_index_net"])
    if snap.get("nifty_pcr") is not None:
        signals_for_conflict["derivatives"]["pcr"] = score_pcr(snap["nifty_pcr"])
    if snap.get("vix_close") is not None:
        signals_for_conflict["derivatives"]["vix"] = score_vix(snap["vix_close"])
    if snap.get("india_macro_signal"):
        signals_for_conflict["macro"]["india_macro"] = score_signal_string(
            snap["india_macro_signal"], "macro"
        )
    scores["conflicts"] = find_conflicts(signals_for_conflict)

    return scores


# ── Entry point ───────────────────────────────────────────────────────

def main() -> None:
    target_date = date.today()
    if len(sys.argv) > 1:
        try:
            target_date = date.fromisoformat(sys.argv[1])
        except ValueError:
            print(f"Invalid date: {sys.argv[1]}. Use YYYY-MM-DD format.")
            sys.exit(1)

    if target_date != date.today():
        print(
            f"WARNING: Fetching LIVE data but saving as {target_date.isoformat()}.\n"
            f"  FII/DII, macro, news, and option chain are always today's data.\n"
            f"  Only Kite OHLC reflects the actual date. For historical backfill,\n"
            f"  use: python -m scripts.backfill_history\n"
        )
        answer = input("  Continue anyway? [y/N] ").strip().lower()
        if answer != "y":
            print("[snapshot] Aborted.")
            sys.exit(0)

    print(f"[snapshot] Fetching all layers for {target_date.isoformat()}...")
    raw = _fetch_all()

    available = sum(1 for v in raw.values() if v is not None)
    print(f"[snapshot] {available}/{len(raw)} layers fetched successfully")

    if available == 0:
        print("[snapshot] No data available — skipping save")
        sys.exit(1)

    snapshot = _extract_snapshot(raw)

    # Warn if NSE FII/DII date doesn't match the snapshot date
    fii_data_date = snapshot.get("fii_dii_data_date")
    if fii_data_date:
        try:
            from datetime import datetime as _dt
            parsed = _dt.strptime(fii_data_date, "%d-%b-%Y").date()
            if parsed != target_date:
                print(
                    f"  WARN  FII/DII data is for {fii_data_date}, not {target_date.isoformat()}.\n"
                    f"         NSE hasn't published today's numbers yet.\n"
                    f"         FII/DII fields will be STALE. Re-run after ~7 PM IST."
                )
                snapshot["_fii_dii_stale"] = True
        except ValueError:
            pass

    path = save(snapshot, target_date)
    print(f"[snapshot] Saved → {path}")

    # Summary
    nifty = snapshot.get("nifty_close")
    chg = snapshot.get("nifty_change_pct")
    vix = snapshot.get("vix_close")
    fii = snapshot.get("fii_net_cr")
    comp = snapshot.get("composite_score")
    regime = snapshot.get("regime_label")

    print(f"\n  Nifty: {nifty}  ({chg:+.2f}%)" if nifty and chg else "")
    print(f"  VIX:   {vix}" if vix else "")
    print(f"  FII:   ₹{fii:+,.0f} Cr" if fii else "")
    print(f"  Score: {comp}  |  Regime: {regime}" if comp is not None else "")
    tech_stance = snapshot.get("nifty_technical_stance")
    rsi = snapshot.get("nifty_rsi")
    dma200 = snapshot.get("nifty_vs_200dma_pct")
    if tech_stance:
        parts = [f"Technicals: {tech_stance}"]
        if rsi is not None:
            parts.append(f"RSI {rsi}")
        if dma200 is not None:
            parts.append(f"200DMA {dma200:+.1f}%")
        print(f"  {' | '.join(parts)}")

    conflicts = snapshot.get("conflicts", [])
    if conflicts:
        print(f"  Conflicts: {len(conflicts)}")
        for c in conflicts:
            print(f"    • {c}")

    print()


if __name__ == "__main__":
    main()
