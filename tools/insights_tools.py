"""
Track A, Step 5 — Daily Insights

Loads all stored daily snapshots, computes percentile rankings for today's
values, flags unusual divergences, and detects trend breaks. Designed to
run alongside market_brief() — adds "where are we relative to history?"
context to every broad market question.

IMPORTANT: Most snapshots are backfilled from Kite OHLC + yfinance and only
contain Nifty OHLC, VIX, macro, and technicals. FII/DII flows, option chain
data, composite scores, and regime labels only exist in live snapshots
(~60 since Dec 2025). Each metric therefore ranks against its own population.

No live API calls. Reads entirely from core.daily_store.
"""

from __future__ import annotations

from bisect import bisect_left
from datetime import datetime

from core.daily_store import load_recent


# ── Metrics to rank ────────────────────────────────────────────────────

# (snapshot_key, human_label, higher_is_bearish, data_source)
# data_source: "backfill" = available across full history (~1400 snapshots),
#              "live_only" = only in live daily snapshots (~60+)
_METRICS: list[tuple[str, str, bool, str]] = [
    ("vix_close",                 "VIX",                True,  "backfill"),
    ("nifty_rsi",                 "Nifty RSI",          False, "backfill"),
    ("nifty_bollinger_bandwidth", "Bollinger bandwidth", True,  "backfill"),
    ("nifty_day_range_pct",       "Nifty day range",    True,  "backfill"),
    ("nifty_vs_200dma_pct",       "Nifty vs 200 DMA",   False, "backfill"),
    ("nifty_change_pct",          "Nifty day change",    False, "backfill"),
    ("fii_net_cr",                "FII net (₹ Cr)",      False, "live_only"),
    ("composite_score",           "Composite score",     False, "live_only"),
]


# ── Helpers ────────────────────────────────────────────────────────────

def _percentile(sorted_values: list[float], value: float) -> float:
    """Percentile rank of value within a sorted list (0–100)."""
    n = len(sorted_values)
    if n == 0:
        return 50.0
    pos = bisect_left(sorted_values, value)
    return round(pos / n * 100, 1)


def _confidence_label(sample_size: int) -> str:
    if sample_size >= 200:
        return "high"
    if sample_size >= 90:
        return "moderate"
    if sample_size >= 30:
        return "low"
    return "very_low"


def _extremity_label(pctile: float, higher_is_bearish: bool) -> str | None:
    """Flag when a metric is at a historical extreme."""
    if pctile >= 95:
        return "unusually_high_bearish" if higher_is_bearish else "unusually_high_bullish"
    if pctile >= 90:
        return "elevated" if higher_is_bearish else "strong"
    if pctile <= 5:
        return "unusually_low_bullish" if higher_is_bearish else "unusually_low_bearish"
    if pctile <= 10:
        return "subdued" if higher_is_bearish else "weak"
    return None


def _detect_divergences(rankings: dict[str, dict]) -> list[dict]:
    """
    Flag when two metrics that normally move together are at opposite extremes.

    Only compares metrics that share comparable sample sizes — avoids misleading
    divergences between a metric ranked across 1400 days and one ranked across 60.
    """
    divergences: list[dict] = []

    def _check(
        key_a: str, key_b: str, desc: str,
        threshold: float = 40.0,
        min_samples: int = 20,
    ):
        a = rankings.get(key_a)
        b = rankings.get(key_b)
        if not a or not b:
            return
        if a["sample_size"] < min_samples or b["sample_size"] < min_samples:
            return
        pa, pb = a["percentile"], b["percentile"]
        gap = abs(pa - pb)
        if gap >= threshold:
            # Note if sample sizes differ dramatically
            size_ratio = max(a["sample_size"], b["sample_size"]) / min(a["sample_size"], b["sample_size"])
            entry: dict = {
                "type": desc,
                "metrics": {
                    key_a: {"percentile": pa, "value": a["value"], "sample_size": a["sample_size"]},
                    key_b: {"percentile": pb, "value": b["value"], "sample_size": b["sample_size"]},
                },
                "gap_pct": round(gap, 1),
            }
            if size_ratio > 5:
                entry["caveat"] = (
                    f"Different sample sizes ({a['sample_size']} vs {b['sample_size']}) — "
                    "percentiles are not directly comparable"
                )
            divergences.append(entry)

    # Same-population comparisons (both available in backfill)
    _check(
        "vix_close", "nifty_rsi",
        "VIX vs RSI divergence — fear gauge disagrees with momentum",
        threshold=50.0,
    )
    _check(
        "vix_close", "nifty_bollinger_bandwidth",
        "VIX vs Bollinger BW — implied vol diverges from realized vol",
        threshold=50.0,
    )
    _check(
        "nifty_vs_200dma_pct", "nifty_rsi",
        "DMA distance vs RSI — trend position disagrees with momentum",
        threshold=50.0,
    )

    # Cross-population comparisons (flagged with caveat if sizes differ)
    _check(
        "fii_net_cr", "composite_score",
        "FII flows vs composite — institutional action diverges from overall signal",
        threshold=50.0,
        min_samples=20,
    )
    _check(
        "nifty_change_pct", "fii_net_cr",
        "Nifty move vs FII flow — price action diverges from institutional flow",
        threshold=60.0,
        min_samples=20,
    )

    return divergences


def _detect_trend_breaks(snaps: list[dict], today: dict) -> list[str]:
    """
    Flag when today's value breaks a recent streak or crosses a threshold
    that hadn't been crossed in the lookback window.

    Only uses fields that exist in recent snapshots (which are live,
    not backfilled).
    """
    breaks: list[str] = []

    if len(snaps) < 6:
        return breaks

    recent_5 = snaps[-6:-1]

    # VIX regime change
    recent_regimes = [s.get("vix_regime") for s in recent_5 if s.get("vix_regime")]
    today_regime = today.get("vix_regime")
    if recent_regimes and today_regime and today_regime != recent_regimes[-1]:
        breaks.append(
            f"VIX regime shifted to '{today_regime}' from '{recent_regimes[-1]}'"
        )

    # Nifty crossed 200 DMA
    recent_dma = [s.get("nifty_vs_200dma_pct") for s in recent_5]
    today_dma = today.get("nifty_vs_200dma_pct")
    if today_dma is not None:
        last_valid = next((v for v in reversed(recent_dma) if v is not None), None)
        if last_valid is not None:
            if last_valid >= 0 and today_dma < 0:
                breaks.append("Nifty crossed below 200 DMA")
            elif last_valid < 0 and today_dma >= 0:
                breaks.append("Nifty crossed above 200 DMA")

    # FII flow direction reversal
    recent_fii = [s.get("fii_net_cr") for s in recent_5 if s.get("fii_net_cr") is not None]
    today_fii = today.get("fii_net_cr")
    if today_fii is not None and len(recent_fii) >= 3:
        if all(f < 0 for f in recent_fii) and today_fii > 0:
            breaks.append(
                f"FII turned net buyer (+₹{today_fii:.0f} Cr) after "
                f"{len(recent_fii)}-day selling streak"
            )
        elif all(f > 0 for f in recent_fii) and today_fii < 0:
            breaks.append(
                f"FII turned net seller (₹{today_fii:.0f} Cr) after "
                f"{len(recent_fii)}-day buying streak"
            )

    # Market regime change
    recent_market_regimes = [s.get("regime") for s in recent_5 if s.get("regime")]
    today_market_regime = today.get("regime")
    if recent_market_regimes and today_market_regime:
        if today_market_regime != recent_market_regimes[-1]:
            breaks.append(
                f"Market regime shifted to '{today_market_regime}' "
                f"from '{recent_market_regimes[-1]}'"
            )

    return breaks


# ── Main tool ──────────────────────────────────────────────────────────

def daily_insights() -> dict:
    """
    Percentile rankings, divergence detection, and trend-break flags
    for today's market values vs all stored history.

    Each metric is ranked against its own population — metrics available
    in backfilled data rank across ~1400 days, while live-only metrics
    (FII flows, composite score) rank across ~60+ live snapshots.
    Per-metric sample sizes and confidence labels are always included.
    """
    snaps = load_recent(9999)  # all available
    if not snaps:
        return {"error": "No daily snapshots available"}

    if len(snaps) < 5:
        return {"error": f"Only {len(snaps)} snapshots — need at least 5 for meaningful insights"}

    today = snaps[-1]
    total_snapshots = len(snaps)

    # Build sorted arrays per metric (only non-null values)
    metric_arrays: dict[str, list[float]] = {}
    for key, _, _, _ in _METRICS:
        values = sorted(v for s in snaps if (v := s.get(key)) is not None)
        if values:
            metric_arrays[key] = values

    # Compute percentile rankings with per-metric sample sizes
    rankings: dict[str, dict] = {}
    extremes: list[dict] = []

    for key, label, higher_is_bearish, data_source in _METRICS:
        today_val = today.get(key)
        sorted_vals = metric_arrays.get(key)

        if today_val is None or not sorted_vals:
            continue

        metric_n = len(sorted_vals)
        pctile = _percentile(sorted_vals, today_val)
        confidence = _confidence_label(metric_n)

        entry: dict = {
            "value": today_val,
            "percentile": pctile,
            "label": label,
            "sample_size": metric_n,
            "confidence": confidence,
            "data_source": data_source,
            "sample_min": sorted_vals[0],
            "sample_max": sorted_vals[-1],
            "sample_median": sorted_vals[len(sorted_vals) // 2],
        }

        extremity = _extremity_label(pctile, higher_is_bearish)
        if extremity:
            entry["flag"] = extremity
            extremes.append({
                "metric": label,
                "key": key,
                "value": today_val,
                "percentile": pctile,
                "flag": extremity,
                "sample_size": metric_n,
                "confidence": confidence,
            })

        rankings[key] = entry

    divergences = _detect_divergences(rankings)
    trend_breaks = _detect_trend_breaks(snaps, today)

    # Summarize data coverage for Claude
    backfill_n = len(metric_arrays.get("vix_close", []))
    live_n = len(metric_arrays.get("fii_net_cr", []))

    return {
        "date": today.get("date"),
        "total_snapshots": total_snapshots,
        "data_coverage": {
            "backfill_metrics": backfill_n,
            "live_only_metrics": live_n,
            "note": (
                f"Backfilled metrics (VIX, RSI, Bollinger, DMAs, day range, macro) "
                f"rank across {backfill_n} trading days. "
                f"Live-only metrics (FII flows, composite score) rank across "
                f"{live_n} days. Per-metric sample_size and confidence are always shown."
            ),
        },
        "rankings": rankings,
        "extreme_readings": extremes or None,
        "divergences": divergences or None,
        "trend_breaks": trend_breaks or None,
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
