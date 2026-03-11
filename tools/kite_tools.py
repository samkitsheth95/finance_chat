from datetime import datetime, timedelta
from core.kite_client import get_kite, resolve_instrument_token

# Major Indian indices and their Kite instrument strings
INDICES = {
    "NIFTY 50":        "NSE:NIFTY 50",
    "NIFTY BANK":      "NSE:NIFTY BANK",
    "INDIA VIX":       "NSE:INDIA VIX",
    "NIFTY IT":        "NSE:NIFTY IT",
    "NIFTY NEXT 50":   "NSE:NIFTY NEXT 50",
    "NIFTY MIDCAP 100":"NSE:NIFTY MIDCAP 100",
    "NIFTY FMCG":      "NSE:NIFTY FMCG",
    "NIFTY PHARMA":    "NSE:NIFTY PHARMA",
    "NIFTY AUTO":      "NSE:NIFTY AUTO",
    "NIFTY METAL":     "NSE:NIFTY METAL",
    "SENSEX":          "BSE:SENSEX",
}

# Valid intervals for historical data and their max lookback in days
VALID_INTERVALS = {
    "minute":    60,
    "3minute":   100,
    "5minute":   100,
    "10minute":  100,
    "15minute":  100,
    "30minute":  100,
    "60minute":  400,
    "day":       2000,
    "week":      2000,
    "month":     2000,
}


def _parse_symbol(symbol: str) -> tuple[str, str]:
    """
    Parse 'NSE:RELIANCE' → ('NSE', 'RELIANCE')
    Parse 'RELIANCE'     → ('NSE', 'RELIANCE')  (defaults to NSE)
    """
    if ":" in symbol:
        exchange, sym = symbol.split(":", 1)
        return exchange.upper(), sym.upper()
    return "NSE", symbol.upper()


def _format_change(ltp: float, close: float) -> dict:
    change = round(ltp - close, 2)
    change_pct = round((change / close) * 100, 2) if close else 0.0
    return {"change": change, "change_pct": change_pct}


def get_quote(symbol: str) -> dict:
    """
    Get a live quote for any NSE/BSE listed stock, ETF, or index.

    Args:
        symbol: Trading symbol. Examples:
                'RELIANCE'        → NSE equity
                'NSE:INFY'        → explicit exchange prefix
                'BSE:500325'      → BSE by scrip code
                'NIFTY 50'        → index (use get_indices for bulk)

    Returns:
        Live price, OHLC, volume, net change, and 52-week range.
    """
    kite = get_kite()
    exchange, sym = _parse_symbol(symbol)
    instrument = f"{exchange}:{sym}"

    try:
        raw = kite.quote([instrument])
    except Exception as e:
        return {"error": str(e), "symbol": symbol}

    if instrument not in raw:
        return {"error": f"No data returned for {instrument}", "symbol": symbol}

    q = raw[instrument]
    ohlc = q.get("ohlc", {})
    depth = q.get("depth", {})

    result = {
        "symbol":      sym,
        "exchange":    exchange,
        "ltp":         q["last_price"],
        "open":        ohlc.get("open"),
        "high":        ohlc.get("high"),
        "low":         ohlc.get("low"),
        "prev_close":  ohlc.get("close"),
        "volume":      q.get("volume", 0),
        "avg_price":   q.get("average_price"),
        "52w_high":    q.get("upper_circuit_limit"),
        "52w_low":     q.get("lower_circuit_limit"),
        "oi":          q.get("oi", 0),
        "timestamp":   str(q.get("timestamp", "")),
    }

    result.update(_format_change(q["last_price"], ohlc.get("close", 0)))

    # Best bid/ask spread
    if depth:
        bids = depth.get("buy", [])
        asks = depth.get("sell", [])
        if bids:
            result["best_bid"] = bids[0].get("price")
        if asks:
            result["best_ask"] = asks[0].get("price")

    return result


def get_indices() -> dict:
    """
    Get live data for all major Indian indices in one call.

    Returns:
        Dictionary of index name → price, change, OHLC.
        Includes Nifty 50, BankNifty, Sensex, India VIX, and sector indices.
    """
    kite = get_kite()

    try:
        raw = kite.quote(list(INDICES.values()))
    except Exception as e:
        return {"error": str(e)}

    result = {}
    for name, instrument in INDICES.items():
        if instrument not in raw:
            continue

        q = raw[instrument]
        ohlc = q.get("ohlc", {})
        entry = {
            "ltp":        q["last_price"],
            "open":       ohlc.get("open"),
            "high":       ohlc.get("high"),
            "low":        ohlc.get("low"),
            "prev_close": ohlc.get("close"),
        }
        entry.update(_format_change(q["last_price"], ohlc.get("close", 0)))
        result[name] = entry

    result["as_of"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return result


def get_historical_ohlc(
    symbol: str,
    interval: str = "day",
    days: int = 30,
) -> dict:
    """
    Get historical OHLC candlestick data for a stock or index.

    Args:
        symbol:   Trading symbol e.g. 'RELIANCE', 'NSE:INFY', 'NIFTY 50'
        interval: Candle interval. One of:
                  'minute', '3minute', '5minute', '10minute', '15minute',
                  '30minute', '60minute', 'day', 'week', 'month'
        days:     Number of calendar days of history to fetch (max depends on interval).
                  minute → max 60 days | day → max 2000 days

    Returns:
        List of OHLCV candles with dates, plus basic stats (high, low, avg close).
    """
    if interval not in VALID_INTERVALS:
        return {
            "error": f"Invalid interval '{interval}'. "
                     f"Choose from: {', '.join(VALID_INTERVALS.keys())}"
        }

    max_days = VALID_INTERVALS[interval]
    if days > max_days:
        days = max_days

    kite = get_kite()
    exchange, sym = _parse_symbol(symbol)

    try:
        token = resolve_instrument_token(exchange, sym)
    except ValueError as e:
        return {"error": str(e)}

    to_date   = datetime.now()
    from_date = to_date - timedelta(days=days)

    try:
        records = kite.historical_data(token, from_date, to_date, interval)
    except Exception as e:
        return {"error": str(e)}

    if not records:
        return {"error": f"No historical data returned for {symbol}", "candles": []}

    candles = [
        {
            "date":   r["date"].isoformat() if hasattr(r["date"], "isoformat") else str(r["date"]),
            "open":   r["open"],
            "high":   r["high"],
            "low":    r["low"],
            "close":  r["close"],
            "volume": r.get("volume", 0),
        }
        for r in records
    ]

    closes = [c["close"] for c in candles]
    return {
        "symbol":     sym,
        "exchange":   exchange,
        "interval":   interval,
        "candles":    candles,
        "count":      len(candles),
        "period_high": max(c["high"] for c in candles),
        "period_low":  min(c["low"] for c in candles),
        "avg_close":   round(sum(closes) / len(closes), 2),
        "first_date":  candles[0]["date"],
        "last_date":   candles[-1]["date"],
    }
