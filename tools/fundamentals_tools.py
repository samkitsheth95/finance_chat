"""
Layer 8 — Stock Fundamentals

Fetches and structures fundamental data for NSE-listed stocks:
valuation ratios, growth metrics, profitability, financial health, and more.

Source: yfinance (.NS tickers) — no additional API keys required.
"""

from __future__ import annotations

from datetime import datetime

from core.fundamentals_client import yf_fundamentals


def _assess_valuation(data: dict) -> dict:
    """
    Multi-factor valuation assessment.

    Uses PEG ratio (growth-adjusted P/E) as primary signal,
    falls back to absolute P/E, and cross-checks with P/B.
    """
    pe = data.get("pe_trailing")
    pe_fwd = data.get("pe_forward")
    peg = data.get("peg_ratio")
    pb = data.get("pb")

    signals: list[str] = []

    if pe is not None and pe < 0:
        return {"signal": "loss_making", "details": signals}

    if peg is not None and peg > 0:
        if peg < 0.5:
            signals.append(f"PEG {peg:.2f} — low vs growth")
        elif peg < 1.0:
            signals.append(f"PEG {peg:.2f} — reasonable for growth")
        elif peg < 2.0:
            signals.append(f"PEG {peg:.2f} — fully priced")
        else:
            signals.append(f"PEG {peg:.2f} — expensive vs growth")

    if pe is not None and pe > 0:
        if pe < 15:
            signals.append(f"Trailing P/E {pe:.1f} — low")
        elif pe < 25:
            signals.append(f"Trailing P/E {pe:.1f} — moderate")
        elif pe < 40:
            signals.append(f"Trailing P/E {pe:.1f} — high")
        else:
            signals.append(f"Trailing P/E {pe:.1f} — very high")

    if pe_fwd is not None and pe is not None and pe_fwd > 0 and pe > 0:
        if pe_fwd < pe * 0.85:
            signals.append("Forward P/E significantly lower — earnings growth expected")
        elif pe_fwd > pe * 1.15:
            signals.append("Forward P/E higher — earnings compression expected")

    if pb is not None:
        if pb < 1.0:
            signals.append(f"P/B {pb:.2f} — below book value")
        elif pb > 8.0:
            signals.append(f"P/B {pb:.2f} — steep premium to book")

    # Composite signal from PEG (primary) or P/E (fallback)
    if peg is not None and peg > 0:
        if peg < 0.75:
            composite = "potentially_undervalued"
        elif peg < 1.2:
            composite = "fairly_valued"
        elif peg < 2.0:
            composite = "fully_valued"
        else:
            composite = "potentially_overvalued"
    elif pe is not None and pe > 0:
        if pe < 12:
            composite = "low_valuation"
        elif pe < 22:
            composite = "moderate_valuation"
        elif pe < 35:
            composite = "high_valuation"
        else:
            composite = "very_high_valuation"
    else:
        composite = "insufficient_data"

    return {"signal": composite, "details": signals}


def _assess_financial_health(data: dict) -> str:
    """Simple financial health check from debt/equity and current ratio."""
    de = data.get("debt_equity")
    cr = data.get("current_ratio")

    if de is not None and de > 200:
        return "highly_leveraged"
    if de is not None and de > 100:
        return "moderate_leverage"
    if cr is not None and cr < 0.8:
        return "low_liquidity"
    if de is not None and de < 30 and cr is not None and cr > 1.5:
        return "strong"
    if de is not None and de < 50:
        return "healthy"
    return "adequate"


def stock_fundamentals(symbol: str) -> dict:
    """
    Get fundamental analysis for an NSE-listed stock.

    Args:
        symbol: NSE trading symbol e.g. 'RELIANCE', 'INFY', 'HDFCBANK'

    Returns:
        Dict with valuation (P/E, P/B, EV/EBITDA, PEG + assessment),
        growth (revenue, earnings), profitability (margins, ROE),
        financial health (debt/equity, current ratio + assessment),
        and market data (52w range, beta, volume, dividend yield).
    """
    raw = yf_fundamentals(symbol)

    if "error" in raw:
        return raw

    valuation = _assess_valuation(raw)
    health = _assess_financial_health(raw)

    fifty_two_week = {}
    if raw.get("52w_high") and raw.get("52w_low"):
        h, l = raw["52w_high"], raw["52w_low"]
        fifty_two_week = {
            "52w_high": h,
            "52w_low": l,
            "52w_range_pct": round((h / l - 1) * 100, 1) if l > 0 else None,
        }

    return {
        "symbol": raw["symbol"],
        "name": raw.get("name"),
        "sector": raw.get("sector"),
        "industry": raw.get("industry"),
        "market_cap_cr": raw.get("market_cap_cr"),
        "valuation": {
            "pe_trailing": raw.get("pe_trailing"),
            "pe_forward": raw.get("pe_forward"),
            "pb": raw.get("pb"),
            "ev_ebitda": raw.get("ev_ebitda"),
            "peg_ratio": raw.get("peg_ratio"),
            **valuation,
        },
        "growth": {
            "revenue_growth_pct": raw.get("revenue_growth_pct"),
            "earnings_growth_pct": raw.get("earnings_growth_pct"),
        },
        "profitability": {
            "profit_margin_pct": raw.get("profit_margin_pct"),
            "operating_margin_pct": raw.get("operating_margin_pct"),
            "roe_pct": raw.get("roe_pct"),
        },
        "financial_health": {
            "debt_equity": raw.get("debt_equity"),
            "current_ratio": raw.get("current_ratio"),
            "assessment": health,
        },
        "market_data": {
            "beta": raw.get("beta"),
            "dividend_yield_pct": raw.get("dividend_yield_pct"),
            "book_value": raw.get("book_value"),
            "avg_volume_10d": raw.get("avg_volume_10d"),
            **fifty_two_week,
        },
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
