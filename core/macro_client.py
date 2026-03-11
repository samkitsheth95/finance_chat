"""
Layer 4 — Global Macro
Raw data-fetch layer for yfinance (global markets and US Treasury yields).

All data comes from yfinance — no additional API keys required.

Design:
  - yf_latest() → current price + day-change for any yfinance ticker

Caching:
  Results are cached in-process for _YF_CACHE_TTL seconds to avoid hammering
  the API on repeated Claude tool calls within the same session.

US Treasury yields via yfinance index tickers (CBOE; live during US hours):
  ^TNX → 10-Year yield    ^FVX → 5-Year yield    ^TYX → 30-Year yield
"""

from __future__ import annotations

import os
import time
from typing import Optional

import requests
import yfinance as yf

# ---------------------------------------------------------------------------
# SSL bypass for corporate proxies (same flag used by kite_client)
# ---------------------------------------------------------------------------
# yfinance >= 0.2.x prefers curl_cffi for HTTP, which runs its own C-level SSL
# stack and is unaffected by Python's ssl._create_default_https_context patch.
# Build a session with verify=False so it can be passed to every Ticker() call.

_YF_SESSION: Optional[object] = None


def _get_yf_session() -> Optional[object]:
    """
    Return a pre-configured yfinance session that disables SSL verification
    when KITE_SSL_VERIFY=false (corporate proxy with self-signed cert).
    Returns None when no override is needed (default path).
    """
    global _YF_SESSION
    if _YF_SESSION is not None:
        return _YF_SESSION

    if os.getenv("KITE_SSL_VERIFY", "true").lower() != "false":
        return None

    # Prefer curl_cffi.Session so yfinance doesn't fall back to requests
    try:
        from curl_cffi import requests as curl_requests  # type: ignore[import]
        _YF_SESSION = curl_requests.Session(verify=False, impersonate="chrome110")
        return _YF_SESSION
    except Exception:
        pass

    # Fallback: plain requests.Session with verify=False
    s = requests.Session()
    s.verify = False
    _YF_SESSION = s
    return _YF_SESSION


# ---------------------------------------------------------------------------
# Cache state
# ---------------------------------------------------------------------------

_YF_CACHE_TTL = 60  # seconds — prices change frequently intraday

_yf_cache: dict[str, tuple[dict, float]] = {}


# ---------------------------------------------------------------------------
# yfinance
# ---------------------------------------------------------------------------

def yf_latest(ticker: str) -> dict:
    """
    Fetch the latest price and day-change for a yfinance ticker.

    Uses fast_info for minimal latency; falls back to 5-day history if
    fast_info returns null values (common outside US market hours).

    Returns:
        {
          "ticker":      str,
          "price":       float | None,   # last traded price
          "prev_close":  float | None,   # previous session close
          "change":      float | None,   # price − prev_close
          "change_pct":  float | None,   # % change (2 dp)
          "day_high":    float | None,
          "day_low":     float | None,
        }
    On error: {"ticker": ticker, "error": str}
    """
    now = time.monotonic()
    if ticker in _yf_cache:
        cached, ts = _yf_cache[ticker]
        if now - ts < _YF_CACHE_TTL:
            return cached

    try:
        session = _get_yf_session()
        t = yf.Ticker(ticker, session=session) if session is not None else yf.Ticker(ticker)
        fi = t.fast_info

        price      = _safe_float(fi.last_price)
        prev_close = _safe_float(fi.previous_close)
        day_high   = _safe_float(fi.day_high)
        day_low    = _safe_float(fi.day_low)

        # fast_info can return None outside trading hours for some tickers —
        # fall back to the most recent close from history
        if price is None or prev_close is None:
            hist = t.history(period="5d", interval="1d", auto_adjust=True)
            if not hist.empty:
                price      = price or round(float(hist["Close"].iloc[-1]), 4)
                prev_close = prev_close or (
                    round(float(hist["Close"].iloc[-2]), 4) if len(hist) >= 2 else None
                )

        change     = round(price - prev_close, 4) if price and prev_close else None
        change_pct = round(change / prev_close * 100, 2) if change and prev_close else None

        data: dict = {
            "ticker":     ticker,
            "price":      price,
            "prev_close": prev_close,
            "change":     change,
            "change_pct": change_pct,
            "day_high":   day_high,
            "day_low":    day_low,
        }
    except Exception as e:
        data = {"ticker": ticker, "error": str(e)}

    _yf_cache[ticker] = (data, now)
    return data


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _safe_float(val) -> Optional[float]:
    try:
        f = float(val)
        return round(f, 4) if f == f else None  # NaN check
    except (TypeError, ValueError):
        return None
