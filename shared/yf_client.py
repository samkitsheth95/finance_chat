"""
Shared yfinance session management and price fetching.

Used by:
  - core/macro_client.py (india-markets Layer 4)
  - core/fundamentals_client.py (india-markets Layer 8)
  - shared/price_history.py (portfolio-doctor)
"""
from __future__ import annotations

import os
import time
from typing import Optional

import requests
import yfinance as yf

# ---------------------------------------------------------------------------
# SSL-safe yfinance session
# ---------------------------------------------------------------------------

_YF_SESSION: Optional[object] = None


def get_yf_session() -> Optional[object]:
    """
    Return a pre-configured yfinance session that disables SSL verification
    when KITE_SSL_VERIFY=false (corporate proxy with self-signed cert).
    Returns None when no override is needed.
    """
    global _YF_SESSION
    if _YF_SESSION is not None:
        return _YF_SESSION

    if os.getenv("KITE_SSL_VERIFY", "true").lower() != "false":
        return None

    try:
        from curl_cffi import requests as curl_requests  # type: ignore[import]
        _YF_SESSION = curl_requests.Session(verify=False, impersonate="chrome110")
        return _YF_SESSION
    except Exception:
        pass

    s = requests.Session()
    s.verify = False
    _YF_SESSION = s
    return _YF_SESSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def safe_float(val) -> Optional[float]:
    """Convert to float safely, returning None for NaN or non-numeric values."""
    try:
        f = float(val)
        return round(f, 4) if f == f else None  # NaN check
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Price cache
# ---------------------------------------------------------------------------

_YF_CACHE_TTL = 60  # seconds
_yf_cache: dict[str, tuple[dict, float]] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def yf_latest(ticker: str) -> dict:
    """
    Fetch the latest price and day-change for a yfinance ticker.

    Uses fast_info for minimal latency; falls back to 5-day history if
    fast_info returns null values (common outside US market hours).

    Returns:
        {
          "ticker":      str,
          "price":       float | None,
          "prev_close":  float | None,
          "change":      float | None,
          "change_pct":  float | None,
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
        session = get_yf_session()
        t = yf.Ticker(ticker, session=session) if session is not None else yf.Ticker(ticker)
        fi = t.fast_info

        price      = safe_float(fi.last_price)
        prev_close = safe_float(fi.previous_close)
        day_high   = safe_float(fi.day_high)
        day_low    = safe_float(fi.day_low)

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
