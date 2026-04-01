"""
Batch historical OHLC fetcher via yfinance.

Used by portfolio-doctor to compute portfolio value series and alternative
scenario returns. Fetches daily close data for NSE stocks (.NS tickers).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import yfinance as yf

from shared.nse_utils import nse_to_yf
from shared.yf_client import get_yf_session


def fetch_price_history(
    symbol: str,
    start_date: date,
    end_date: Optional[date] = None,
) -> dict:
    """
    Fetch daily OHLC for an NSE stock from start_date to end_date.

    Args:
        symbol: NSE trading symbol (e.g. "RELIANCE") or yfinance ticker
        start_date: First date (inclusive)
        end_date: Last date (inclusive). Defaults to today.

    Returns:
        {
            "symbol": str,
            "ticker": str,
            "prices": [{"date": "YYYY-MM-DD", "open": float, "high": float,
                         "low": float, "close": float, "volume": int}, ...],
            "count": int
        }
        On error: {"symbol": str, "ticker": str, "error": str}
    """
    if end_date is None:
        end_date = date.today()

    if "." in symbol or symbol.startswith("^"):
        ticker = symbol
    else:
        ticker = nse_to_yf(symbol)

    try:
        session = get_yf_session()
        t = yf.Ticker(ticker, session=session) if session else yf.Ticker(ticker)
        hist = t.history(
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=True,
        )

        if hist.empty:
            return {"symbol": symbol, "ticker": ticker,
                    "error": f"No price data for {ticker} in range"}

        prices = []
        for dt, row in hist.iterrows():
            prices.append({
                "date": dt.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            })

        return {
            "symbol": symbol,
            "ticker": ticker,
            "prices": prices,
            "count": len(prices),
        }
    except Exception as e:
        return {"symbol": symbol, "ticker": ticker, "error": str(e)}


def get_close_series(symbol: str, start_date: date, end_date: Optional[date] = None) -> dict[str, float]:
    """
    Convenience: return {date_str: close_price} dict for quick lookups.
    Returns empty dict on error.
    """
    result = fetch_price_history(symbol, start_date, end_date)
    if "error" in result:
        return {}
    return {p["date"]: p["close"] for p in result["prices"]}
