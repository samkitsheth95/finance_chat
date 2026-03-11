"""
Layer 7 — Technical Analysis

Computes standard technical indicators for any NSE/BSE stock or index:
20/50/200 DMA, RSI-14, Bollinger Bands, MACD, support/resistance levels,
and relative strength vs Nifty (for stocks only).

Shared by Track A (index technicals) and Track B (stock technicals).
"""

from __future__ import annotations

from datetime import datetime

from tools.kite_tools import get_historical_ohlc, INDICES


# ── Indicator calculations ────────────────────────────────────────────

def _sma(values: list[float], period: int) -> list[float | None]:
    """Simple moving average. None where insufficient data."""
    result: list[float | None] = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(None)
        else:
            window = values[i - period + 1 : i + 1]
            result.append(round(sum(window) / period, 2))
    return result


def _ema(values: list[float], period: int) -> list[float]:
    """Exponential moving average (seed with SMA of first `period` values)."""
    if len(values) < period:
        return []
    seed = sum(values[:period]) / period
    k = 2 / (period + 1)
    result = [round(seed, 4)]
    for v in values[period:]:
        result.append(round(v * k + result[-1] * (1 - k), 4))
    return result


def _rsi(closes: list[float], period: int = 14) -> float | None:
    """RSI using Wilder's smoothing."""
    if len(closes) < period + 1:
        return None

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def _bollinger(
    closes: list[float], period: int = 20, std_mult: float = 2.0
) -> dict | None:
    """Bollinger Bands: middle (SMA), upper, lower, bandwidth, %B."""
    if len(closes) < period:
        return None

    window = closes[-period:]
    middle = sum(window) / period
    variance = sum((x - middle) ** 2 for x in window) / period
    std = variance**0.5
    upper = middle + std_mult * std
    lower = middle - std_mult * std

    current = closes[-1]
    bandwidth = round((upper - lower) / middle * 100, 2) if middle else 0
    pct_b = round((current - lower) / (upper - lower), 3) if upper != lower else 0.5

    if pct_b > 1.0:
        signal = "overbought"
    elif pct_b < 0.0:
        signal = "oversold"
    else:
        signal = "within_bands"

    return {
        "upper": round(upper, 2),
        "middle": round(middle, 2),
        "lower": round(lower, 2),
        "bandwidth_pct": bandwidth,
        "percent_b": pct_b,
        "signal": signal,
    }


def _macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> dict | None:
    """MACD line, signal line, histogram, crossover detection."""
    if len(closes) < slow + signal_period:
        return None

    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)

    # Align: ema_fast starts at index `fast`, ema_slow at index `slow`.
    # Trim ema_fast to start where ema_slow starts.
    offset = slow - fast
    macd_line = [
        round(f - s, 4)
        for f, s in zip(ema_fast[offset:], ema_slow)
    ]

    if len(macd_line) < signal_period:
        return None

    signal_line = _ema(macd_line, signal_period)
    # signal_line starts at index signal_period within macd_line
    # Align current values
    macd_current = macd_line[-1]
    signal_current = signal_line[-1] if signal_line else 0
    histogram = round(macd_current - signal_current, 4)

    crossover = "none"
    if len(macd_line) >= signal_period + 1 and len(signal_line) >= 2:
        prev_macd = macd_line[-2 - (len(macd_line) - signal_period - len(signal_line))] if len(signal_line) < len(macd_line) - signal_period + 1 else macd_line[-(len(signal_line))]
        # Simpler: compare last two aligned values
        prev_hist = round(macd_line[-(len(signal_line))] - signal_line[-2], 4) if len(signal_line) >= 2 else 0
        if prev_hist <= 0 and histogram > 0:
            crossover = "bullish_crossover"
        elif prev_hist >= 0 and histogram < 0:
            crossover = "bearish_crossover"

    return {
        "macd": round(macd_current, 2),
        "signal": round(signal_current, 2),
        "histogram": round(histogram, 2),
        "crossover": crossover,
        "trend": "bullish" if histogram > 0 else "bearish",
    }


def _support_resistance(candles: list[dict], lookback: int = 30) -> dict:
    """Support/resistance from swing highs/lows over the lookback period."""
    if len(candles) < 5:
        return {"resistance": [], "support": []}

    recent = candles[-min(lookback, len(candles)) :]
    highs = [c["high"] for c in recent]
    lows = [c["low"] for c in recent]

    swing_highs: list[float] = []
    swing_lows: list[float] = []

    for i in range(2, len(recent) - 2):
        if highs[i] >= highs[i - 1] and highs[i] >= highs[i + 1] and highs[i] >= highs[i - 2] and highs[i] >= highs[i + 2]:
            swing_highs.append(highs[i])
        if lows[i] <= lows[i - 1] and lows[i] <= lows[i + 1] and lows[i] <= lows[i - 2] and lows[i] <= lows[i + 2]:
            swing_lows.append(lows[i])

    resistance = sorted(set(swing_highs), reverse=True)[:3] if swing_highs else [max(highs)]
    support = sorted(set(swing_lows))[:3] if swing_lows else [min(lows)]

    return {
        "resistance": [round(r, 2) for r in resistance],
        "support": [round(s, 2) for s in support],
        "period_high": round(max(highs), 2),
        "period_low": round(min(lows), 2),
    }


def _relative_strength(
    stock_closes: list[float],
    nifty_closes: list[float],
    periods: dict[str, int],
) -> dict:
    """Relative performance of stock vs Nifty over multiple time horizons."""
    result = {}
    for label, days in periods.items():
        if len(stock_closes) > days and len(nifty_closes) > days:
            stock_ret = (stock_closes[-1] / stock_closes[-days - 1] - 1) * 100
            nifty_ret = (nifty_closes[-1] / nifty_closes[-days - 1] - 1) * 100
            outperf = round(stock_ret - nifty_ret, 2)
            if outperf > 2:
                sig = "outperforming"
            elif outperf < -2:
                sig = "underperforming"
            else:
                sig = "in_line"
            result[label] = {
                "stock_return_pct": round(stock_ret, 2),
                "nifty_return_pct": round(nifty_ret, 2),
                "outperformance_pct": outperf,
                "signal": sig,
            }
    return result


# Indices skip relative-strength calculation
_INDEX_SYMBOLS = set(INDICES.keys())


# ── Main tool ─────────────────────────────────────────────────────────

def technical_analysis(symbol: str, period: int = 200) -> dict:
    """
    Full technical analysis for any stock or index.

    Computes 20/50/200 DMA, RSI-14, Bollinger Bands (20,2), MACD (12,26,9),
    support/resistance, and relative strength vs Nifty (for stocks).

    Args:
        symbol: Trading symbol e.g. 'RELIANCE', 'NIFTY 50', 'NSE:INFY'
        period: Days of history for calculations (default 200, max 2000)

    Returns:
        Dict with current price, DMAs with trend, RSI, Bollinger, MACD,
        support/resistance, relative strength (stocks only), and overall stance.
    """
    fetch_days = min(int(period * 1.5) + 30, 2000)
    ohlc = get_historical_ohlc(symbol, "day", fetch_days)

    if "error" in ohlc:
        return {"error": ohlc["error"], "symbol": symbol}

    candles = ohlc.get("candles", [])
    if len(candles) < 20:
        return {
            "error": f"Insufficient data: {len(candles)} candles (need ≥20)",
            "symbol": symbol,
        }

    closes = [c["close"] for c in candles]
    current = closes[-1]

    # ── Moving averages ───────────────────────────────────────────
    sma_20_all = _sma(closes, 20)
    sma_50_all = _sma(closes, 50)
    sma_200_all = _sma(closes, 200)

    sma_20 = sma_20_all[-1]
    sma_50 = sma_50_all[-1] if len(closes) >= 50 else None
    sma_200 = sma_200_all[-1] if len(closes) >= 200 else None

    dma: dict = {
        "dma_20": sma_20,
        "dma_50": sma_50,
        "dma_200": sma_200,
    }

    if sma_20:
        dma["above_20dma"] = current > sma_20
        dma["distance_20dma_pct"] = round((current / sma_20 - 1) * 100, 2)
    if sma_50:
        dma["above_50dma"] = current > sma_50
        dma["distance_50dma_pct"] = round((current / sma_50 - 1) * 100, 2)
    if sma_200:
        dma["above_200dma"] = current > sma_200
        dma["distance_200dma_pct"] = round((current / sma_200 - 1) * 100, 2)

    if sma_50 and sma_200:
        dma["cross"] = "golden_cross" if sma_50 > sma_200 else "death_cross"

    if sma_20 and sma_50 and sma_200:
        if current > sma_20 > sma_50 > sma_200:
            dma["trend"] = "strong_uptrend"
        elif current > sma_20 and current > sma_50:
            dma["trend"] = "uptrend"
        elif current < sma_20 < sma_50 < sma_200:
            dma["trend"] = "strong_downtrend"
        elif current < sma_20 and current < sma_50:
            dma["trend"] = "downtrend"
        else:
            dma["trend"] = "mixed"

    # ── RSI ────────────────────────────────────────────────────────
    rsi_val = _rsi(closes)
    rsi_info = None
    if rsi_val is not None:
        if rsi_val > 70:
            rsi_sig = "overbought"
        elif rsi_val < 30:
            rsi_sig = "oversold"
        else:
            rsi_sig = "neutral"
        rsi_info = {"value": rsi_val, "signal": rsi_sig}

    # ── Bollinger Bands ────────────────────────────────────────────
    bollinger = _bollinger(closes)

    # ── MACD ───────────────────────────────────────────────────────
    macd = _macd(closes)

    # ── Support / Resistance ───────────────────────────────────────
    sr = _support_resistance(candles)

    # ── Relative strength vs Nifty (stocks only) ──────────────────
    parsed_sym = symbol.upper()
    is_index = (
        parsed_sym in _INDEX_SYMBOLS
        or "NIFTY" in parsed_sym
        or parsed_sym == "SENSEX"
    )

    rel_strength = None
    if not is_index:
        nifty_ohlc = get_historical_ohlc("NIFTY 50", "day", fetch_days)
        if "error" not in nifty_ohlc:
            nifty_closes = [c["close"] for c in nifty_ohlc.get("candles", [])]
            if len(nifty_closes) > 5:
                rel_strength = _relative_strength(
                    closes,
                    nifty_closes,
                    {"1_week": 5, "1_month": 22, "3_month": 66},
                )

    # ── Overall technical stance ───────────────────────────────────
    bullish = bearish = total = 0

    if rsi_info:
        total += 1
        if rsi_info["signal"] == "overbought":
            bearish += 1
        elif rsi_info["signal"] == "oversold":
            bullish += 1

    if bollinger:
        total += 1
        if bollinger["signal"] == "overbought":
            bearish += 1
        elif bollinger["signal"] == "oversold":
            bullish += 1

    if macd:
        total += 1
        if macd["trend"] == "bullish":
            bullish += 1
        else:
            bearish += 1
        if macd["crossover"] in ("bullish_crossover", "bearish_crossover"):
            total += 1
            if macd["crossover"] == "bullish_crossover":
                bullish += 1
            else:
                bearish += 1

    if dma.get("trend"):
        total += 1
        if "uptrend" in dma["trend"]:
            bullish += 1
        elif "downtrend" in dma["trend"]:
            bearish += 1

    if total > 0:
        net = (bullish - bearish) / total
        stance = "bullish" if net > 0.3 else "bearish" if net < -0.3 else "neutral"
    else:
        stance = "neutral"

    result: dict = {
        "symbol": ohlc["symbol"],
        "exchange": ohlc["exchange"],
        "current_price": current,
        "data_points": len(candles),
        "dma": dma,
        "rsi": rsi_info,
        "bollinger": bollinger,
        "macd": macd,
        "support_resistance": sr,
        "technical_stance": {
            "signal": stance,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "total_signals": total,
        },
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    if rel_strength:
        result["relative_strength_vs_nifty"] = rel_strength

    return result
