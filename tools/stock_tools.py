"""
Stock Brief — Per-Stock Signal Scoring & Synthesis (B3)

The stock-level equivalent of market_brief(). Fetches technicals, fundamentals,
quote, and news in parallel, scores each dimension to -1.0 → +1.0, detects
stock stance, and returns a single structured brief for Claude to reason over.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from core.stock_scorer import (
    score_technicals,
    score_relative_strength,
    score_valuation,
    score_growth,
    score_financial_health,
    score_momentum,
    score_stock_news,
    detect_stock_stance,
    get_stock_weights,
    compute_stock_composite,
)
from tools.kite_tools import get_quote
from tools.technicals_tools import technical_analysis
from tools.fundamentals_tools import stock_fundamentals
from tools.news_tools import get_news_search


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


# ── Main tool ────────────────────────────────────────────────────────

def get_stock_brief(symbol: str) -> dict:
    """
    One-call stock brief: fetches all dimensions, scores signals, detects stance.

    Calls quote + technicals + fundamentals + news_search in parallel,
    normalizes every signal to -1.0 → +1.0, detects the stock's overall
    stance, and computes a weighted composite score.

    Returns a structured brief designed for Claude to reason over.
    """
    sym = symbol.upper().replace("NSE:", "").replace("BSE:", "")

    # ── 1. Parallel data fetch ────────────────────────────────────
    tasks = {
        "quote":        (get_quote, sym),
        "technicals":   (technical_analysis, sym, 200),
        "fundamentals": (stock_fundamentals, sym),
        "news":         (get_news_search, sym, "7d"),
    }
    raw: dict = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {}
        for key, call in tasks.items():
            fn, *args = call
            futures[pool.submit(_safe, fn, *args)] = key
        for fut in as_completed(futures):
            raw[futures[fut]] = fut.result()

    # ── 2. Score technicals ───────────────────────────────────────
    signals: dict = {}
    tech = raw.get("technicals", {})
    if _ok(tech):
        signals["technicals"] = score_technicals(tech)
        signals["relative_strength"] = score_relative_strength(
            tech.get("relative_strength_vs_nifty")
        )
    else:
        signals["technicals"] = {"score": None, "note": "Technicals unavailable"}
        signals["relative_strength"] = {"score": None, "note": "Relative strength unavailable"}

    # ── 3. Score fundamentals ─────────────────────────────────────
    fund = raw.get("fundamentals", {})
    if _ok(fund):
        signals["valuation"] = score_valuation(fund.get("valuation", {}))
        signals["growth"] = score_growth(fund.get("growth", {}))
        signals["financial_health"] = score_financial_health(
            fund.get("financial_health", {})
        )
    else:
        signals["valuation"] = {"score": None, "note": "Valuation unavailable"}
        signals["growth"] = {"score": None, "note": "Growth data unavailable"}
        signals["financial_health"] = {"score": None, "note": "Health data unavailable"}

    # ── 4. Score momentum (from quote) ────────────────────────────
    quote_data = raw.get("quote", {})
    if _ok(quote_data):
        signals["momentum"] = score_momentum(quote_data.get("change_pct"))
    else:
        signals["momentum"] = {"score": None, "note": "Quote unavailable"}

    # ── 5. Score news ─────────────────────────────────────────────
    news = raw.get("news", {})
    signals["news"] = score_stock_news(news) if _ok(news) else {
        "score": None, "note": "News unavailable",
    }

    # ── 6. Stock stance ───────────────────────────────────────────
    stance = detect_stock_stance(signals)

    # ── 7. Composite score (stance-aware weights) ────────────────
    weights = get_stock_weights(stance["key"])
    layer_scores = {k: v.get("score") for k, v in signals.items()}
    composite = compute_stock_composite(layer_scores, weights)
    composite["weights_used"] = weights
    composite["layer_scores"] = {
        k: v for k, v in layer_scores.items() if v is not None
    }

    # ── 8. Price context ──────────────────────────────────────────
    price_block: dict = {}
    if _ok(quote_data):
        price_block = {
            "ltp": quote_data.get("ltp"),
            "change": quote_data.get("change"),
            "change_pct": quote_data.get("change_pct"),
            "volume": quote_data.get("volume"),
        }

    # ── 9. Key levels from technicals ─────────────────────────────
    key_levels: dict | None = None
    if _ok(tech):
        dma = tech.get("dma", {})
        sr = tech.get("support_resistance", {})
        key_levels = {
            "dma_20": dma.get("dma_20"),
            "dma_50": dma.get("dma_50"),
            "dma_200": dma.get("dma_200"),
            "support": sr.get("support", []),
            "resistance": sr.get("resistance", []),
        }

    # ── 10. Fundamental snapshot ──────────────────────────────────
    fund_snapshot: dict | None = None
    if _ok(fund):
        fund_snapshot = {
            "sector": fund.get("sector"),
            "industry": fund.get("industry"),
            "market_cap_cr": fund.get("market_cap_cr"),
            "pe_trailing": fund.get("valuation", {}).get("pe_trailing"),
            "pe_forward": fund.get("valuation", {}).get("pe_forward"),
            "roe_pct": fund.get("profitability", {}).get("roe_pct"),
        }

    # ── 11. Recent news headlines (for Claude to interpret) ───────
    news_headlines: list | None = None
    if _ok(news):
        headlines = news.get("headlines", [])
        news_headlines = [
            {"title": h.get("title"), "source": h.get("source"),
             "event_risk": h.get("event_risk", False)}
            for h in headlines[:8]
        ]

    # ── 12. Data issues ───────────────────────────────────────────
    errors = [
        f"{k}: {v['_error']}" for k, v in raw.items()
        if isinstance(v, dict) and "_error" in v
    ]

    # ── 13. Assemble brief ────────────────────────────────────────
    result: dict = {
        "symbol": sym,
    }

    if _ok(fund):
        result["name"] = fund.get("name")

    result.update({
        "price": price_block or None,
        "stance": stance,
        "signals": signals,
        "composite": composite,
        "key_levels": key_levels,
        "fundamental_snapshot": fund_snapshot,
        "recent_news": news_headlines,
        "data_issues": errors or None,
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    return result
