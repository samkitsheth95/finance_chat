"""
Layer 8 — Stock Fundamentals Client

yfinance-based fundamental data fetching with in-memory caching.
Maps NSE trading symbols to Yahoo Finance .NS tickers.

Caching:
  Results cached for _FUND_CACHE_TTL seconds. Fundamentals change quarterly,
  but the cache is short enough to pick up intraday price-dependent ratios
  (P/E, P/B) without hammering the API.
"""

from __future__ import annotations

import time
from typing import Optional

import yfinance as yf

from shared.yf_client import get_yf_session as _get_yf_session
from shared.yf_client import safe_float as _safe_float
from shared.nse_utils import nse_to_yf as _nse_to_yf


# ── Cache ─────────────────────────────────────────────────────────────

_FUND_CACHE_TTL = 300  # 5 minutes
_fund_cache: dict[str, tuple[dict, float]] = {}


# ── Public API ────────────────────────────────────────────────────────

def yf_fundamentals(symbol: str) -> dict:
    """
    Fetch fundamental data for an NSE-listed stock via yfinance.

    Returns dict with market_cap, valuation ratios, growth metrics,
    margins, leverage, dividend yield, 52-week range, and metadata.
    On error: {"symbol": ..., "error": str}
    """
    ticker = _nse_to_yf(symbol)
    now = time.monotonic()

    if ticker in _fund_cache:
        cached, ts = _fund_cache[ticker]
        if now - ts < _FUND_CACHE_TTL:
            return cached

    try:
        session = _get_yf_session()
        t = yf.Ticker(ticker, session=session) if session else yf.Ticker(ticker)
        info = t.info or {}

        if not info.get("marketCap") and not info.get("trailingPE"):
            data: dict = {
                "symbol": symbol,
                "yf_ticker": ticker,
                "error": "No fundamental data available — verify symbol is correct",
            }
            _fund_cache[ticker] = (data, now)
            return data

        data = {
            "symbol": symbol,
            "yf_ticker": ticker,
            "name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "market_cap_cr": (
                round(info["marketCap"] / 1e7, 0)
                if info.get("marketCap")
                else None
            ),
            "pe_trailing": _safe_float(info.get("trailingPE")),
            "pe_forward": _safe_float(info.get("forwardPE")),
            "pb": _safe_float(info.get("priceToBook")),
            "ev_ebitda": _safe_float(info.get("enterpriseToEbitda")),
            "peg_ratio": _safe_float(info.get("pegRatio")),
            "revenue_growth_pct": (
                round(info["revenueGrowth"] * 100, 2)
                if info.get("revenueGrowth") is not None
                else None
            ),
            "earnings_growth_pct": (
                round(info["earningsGrowth"] * 100, 2)
                if info.get("earningsGrowth") is not None
                else None
            ),
            "profit_margin_pct": (
                round(info["profitMargins"] * 100, 2)
                if info.get("profitMargins") is not None
                else None
            ),
            "operating_margin_pct": (
                round(info["operatingMargins"] * 100, 2)
                if info.get("operatingMargins") is not None
                else None
            ),
            "roe_pct": (
                round(info["returnOnEquity"] * 100, 2)
                if info.get("returnOnEquity") is not None
                else None
            ),
            "debt_equity": _safe_float(info.get("debtToEquity")),
            "current_ratio": _safe_float(info.get("currentRatio")),
            "dividend_yield_pct": (
                round(info["dividendYield"] * 100, 2)
                if info.get("dividendYield") is not None
                else None
            ),
            "book_value": _safe_float(info.get("bookValue")),
            "52w_high": _safe_float(info.get("fiftyTwoWeekHigh")),
            "52w_low": _safe_float(info.get("fiftyTwoWeekLow")),
            "beta": _safe_float(info.get("beta")),
            "avg_volume_10d": info.get("averageDailyVolume10Day"),
        }
    except Exception as e:
        data = {"symbol": symbol, "yf_ticker": ticker, "error": str(e)}

    _fund_cache[ticker] = (data, now)
    return data
