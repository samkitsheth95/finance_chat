#!/usr/bin/env python3
"""
Backfill Historical Snapshots

One-time script to populate data/daily/ with partial snapshots using
Kite OHLC (2000 days) + yfinance macro history. Existing full snapshots
are never overwritten.

What's populated:
  - Nifty 50 OHLC (close, open, high, low, change, day range)
  - BankNifty close + change
  - India VIX close + change
  - Full Nifty technicals (RSI, 20/50/200 DMA, Bollinger, MACD, stance)
  - Macro data (S&P 500, DXY, USD/INR, crude, gold, US 10Y/5Y yields)

What's NOT available historically (left as None):
  - FII/DII cash flows, option chain, participant OI, news

Usage:
    python -m scripts.backfill_history              # all ~2000 days
    python -m scripts.backfill_history --days 500   # last 500 days only

Requires a valid KITE_ACCESS_TOKEN in .env.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from core.daily_store import save, load

# Technicals computation (import private helpers from technicals_tools)
from tools.technicals_tools import _sma, _rsi, _bollinger, _macd


# ── Kite OHLC fetch ──────────────────────────────────────────────────

def _fetch_kite_ohlc(days: int) -> tuple[list[dict], list[dict], list[dict]]:
    """Fetch daily candles for Nifty, BankNifty, India VIX from Kite."""
    from tools.kite_tools import get_historical_ohlc

    print("[backfill] Fetching Kite OHLC...")
    nifty = get_historical_ohlc("NIFTY 50", "day", days)
    if "error" in nifty:
        print(f"  FATAL: Nifty fetch failed: {nifty['error']}")
        sys.exit(1)
    print(f"  Nifty 50:   {nifty['count']} candles ({nifty['first_date'][:10]} → {nifty['last_date'][:10]})")

    banknifty = get_historical_ohlc("NIFTY BANK", "day", days)
    if "error" in banknifty:
        print(f"  WARN: BankNifty fetch failed: {banknifty['error']}")
        banknifty = {"candles": []}
    else:
        print(f"  BankNifty:  {banknifty['count']} candles")

    vix = get_historical_ohlc("INDIA VIX", "day", days)
    if "error" in vix:
        print(f"  WARN: VIX fetch failed: {vix['error']}")
        vix = {"candles": []}
    else:
        print(f"  India VIX:  {vix['count']} candles")

    return nifty["candles"], banknifty.get("candles", []), vix.get("candles", [])


# ── yfinance macro fetch ─────────────────────────────────────────────

_MACRO_TICKERS = {
    "^GSPC":     "sp500",
    "DX-Y.NYB":  "dxy",
    "CL=F":      "crude",
    "GC=F":      "gold",
    "^TNX":      "us10y",
    "^FVX":      "us5y",
    "USDINR=X":  "usdinr",
}


def _fetch_macro_history(start_date: str, end_date: str) -> dict[str, dict[str, dict]]:
    """
    Fetch historical macro data from yfinance.

    Returns {ticker_key: {date_str: {price, change_pct}}} for each macro ticker.
    """
    import yfinance as yf
    import pandas as pd
    from core.macro_client import _get_yf_session

    print("[backfill] Fetching yfinance macro history...")
    session = _get_yf_session()

    result: dict[str, dict[str, dict]] = {}

    for ticker, key in _MACRO_TICKERS.items():
        try:
            t = yf.Ticker(ticker, session=session) if session else yf.Ticker(ticker)
            hist = t.history(start=start_date, end=end_date, interval="1d", auto_adjust=True)
            if hist.empty:
                print(f"  WARN: No data for {ticker} ({key})")
                result[key] = {}
                continue

            series: dict[str, dict] = {}
            closes = hist["Close"]
            prev_close = None
            for dt, close_val in closes.items():
                close = round(float(close_val), 4)
                if pd.isna(close):
                    continue
                d = dt.strftime("%Y-%m-%d")
                change_pct = None
                if prev_close and prev_close != 0:
                    change_pct = round((close - prev_close) / prev_close * 100, 2)
                series[d] = {"price": close, "prev_close": prev_close, "change_pct": change_pct}
                prev_close = close

            result[key] = series
            print(f"  {key:10s}: {len(series)} days")
        except Exception as e:
            print(f"  WARN: {ticker} ({key}) failed: {e}")
            result[key] = {}

    return result


# ── Technicals computation ───────────────────────────────────────────

def _compute_technicals_at(
    all_closes: list[float],
    i: int,
    sma_20_all: list[float | None],
    sma_50_all: list[float | None],
    sma_200_all: list[float | None],
) -> dict:
    """Compute technical indicators for candle at index i using history up to i."""
    current = all_closes[i]
    sma_20 = sma_20_all[i]
    sma_50 = sma_50_all[i]
    sma_200 = sma_200_all[i]

    # DMA fields
    dma: dict = {}
    dma["dma_20"] = sma_20
    dma["dma_50"] = sma_50
    dma["dma_200"] = sma_200

    if sma_20:
        dma["distance_20dma_pct"] = round((current / sma_20 - 1) * 100, 2)
    if sma_50:
        dma["distance_50dma_pct"] = round((current / sma_50 - 1) * 100, 2)
    if sma_200:
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

    # RSI, Bollinger, MACD — computed from slice up to this date
    closes_slice = all_closes[: i + 1]

    rsi_val = _rsi(closes_slice)
    rsi_signal = None
    if rsi_val is not None:
        rsi_signal = "overbought" if rsi_val > 70 else "oversold" if rsi_val < 30 else "neutral"

    boll = _bollinger(closes_slice)
    macd = _macd(closes_slice)

    # Technical stance (same logic as technical_analysis())
    bullish = bearish = total = 0

    if rsi_val is not None:
        total += 1
        if rsi_signal == "overbought":
            bearish += 1
        elif rsi_signal == "oversold":
            bullish += 1

    if boll:
        total += 1
        if boll["signal"] == "overbought":
            bearish += 1
        elif boll["signal"] == "oversold":
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

    return {
        "rsi_val": rsi_val,
        "rsi_signal": rsi_signal,
        "dma": dma,
        "bollinger": boll,
        "macd": macd,
        "stance": stance,
    }


# ── Macro signal derivation (reuse logic from macro_tools) ──────────

def _sp500_signal(change_pct: float | None) -> str | None:
    if change_pct is None:
        return None
    if change_pct >= 1.5:
        return "bullish"
    if change_pct >= 0.4:
        return "mildly_bullish"
    if change_pct > -0.4:
        return "neutral"
    if change_pct > -1.5:
        return "mildly_bearish"
    return "bearish"


def _dxy_signal(change_pct: float | None) -> str | None:
    if change_pct is None:
        return None
    if change_pct >= 0.5:
        return "bearish"
    if change_pct >= 0.15:
        return "mildly_bearish"
    if change_pct > -0.15:
        return "neutral"
    if change_pct > -0.5:
        return "mildly_bullish"
    return "bullish"


def _usdinr_signal(change_pct: float | None) -> str | None:
    if change_pct is None:
        return None
    if change_pct >= 0.3:
        return "bearish"
    if change_pct >= 0.1:
        return "mildly_bearish"
    if change_pct > -0.1:
        return "neutral"
    if change_pct > -0.3:
        return "mildly_bullish"
    return "bullish"


def _crude_signal(change_pct: float | None) -> str | None:
    if change_pct is None:
        return None
    if change_pct >= 2.5:
        return "bearish"
    if change_pct >= 0.7:
        return "mildly_bearish"
    if change_pct > -0.7:
        return "neutral"
    if change_pct > -2.5:
        return "mildly_bullish"
    return "bullish"


def _us10y_signal(change: float | None, level: float | None) -> str | None:
    if change is None or level is None:
        return None
    if level >= 4.5 and change >= 0.05:
        return "bearish"
    if change >= 0.05:
        return "mildly_bearish"
    if change > -0.05:
        return "neutral"
    if change > -0.1:
        return "mildly_bullish"
    return "bullish"


def _composite_macro_signal(signals: list[str | None]) -> str | None:
    _scores = {
        "bullish": 2, "mildly_bullish": 1, "neutral": 0,
        "mildly_bearish": -1, "bearish": -2,
    }
    valid = [s for s in signals if s is not None and s in _scores]
    if not valid:
        return None
    avg = sum(_scores[s] for s in valid) / len(valid)
    if avg >= 1.0:
        return "bullish"
    if avg >= 0.3:
        return "mildly_bullish"
    if avg > -0.3:
        return "neutral"
    if avg > -1.0:
        return "mildly_bearish"
    return "bearish"


# ── Snapshot builder ─────────────────────────────────────────────────

def _build_snapshot(
    nifty_candle: dict,
    prev_nifty_close: float | None,
    technicals: dict,
    bnf_data: dict | None,
    vix_data: dict | None,
    prev_vix_close: float | None,
    macro: dict[str, dict[str, dict]],
    date_str: str,
) -> dict:
    """Assemble a partial snapshot from available historical data."""
    snap: dict = {}
    close = nifty_candle["close"]

    # Nifty OHLC
    snap["nifty_close"] = close
    snap["nifty_open"] = nifty_candle["open"]
    snap["nifty_high"] = nifty_candle["high"]
    snap["nifty_low"] = nifty_candle["low"]
    snap["nifty_prev_close"] = prev_nifty_close
    if prev_nifty_close and prev_nifty_close > 0:
        snap["nifty_change_pct"] = round((close - prev_nifty_close) / prev_nifty_close * 100, 2)
    else:
        snap["nifty_change_pct"] = None

    low = nifty_candle["low"]
    if nifty_candle["high"] and low and low > 0:
        snap["nifty_day_range_pct"] = round(
            (nifty_candle["high"] - low) / low * 100, 2
        )
    else:
        snap["nifty_day_range_pct"] = None

    # BankNifty
    if bnf_data:
        snap["banknifty_close"] = bnf_data["close"]
        snap["banknifty_change_pct"] = bnf_data.get("change_pct")
    else:
        snap["banknifty_close"] = None
        snap["banknifty_change_pct"] = None

    # VIX
    if vix_data:
        vix_close = vix_data["close"]
        snap["vix_close"] = vix_close
        snap["vix_prev_close"] = prev_vix_close
        if prev_vix_close and prev_vix_close > 0:
            snap["vix_change_pct"] = round(
                (vix_close - prev_vix_close) / prev_vix_close * 100, 2
            )
        else:
            snap["vix_change_pct"] = None
    else:
        snap["vix_close"] = None
        snap["vix_prev_close"] = None
        snap["vix_change_pct"] = None
    snap["vix_regime"] = None

    # Derivatives — not available historically
    for field in [
        "nifty_spot", "nifty_pcr", "nifty_total_call_oi", "nifty_total_put_oi",
        "nifty_max_pain", "nifty_call_wall", "nifty_call_wall_oi",
        "nifty_put_wall", "nifty_put_wall_oi", "nifty_atm_strike", "days_to_expiry",
    ]:
        snap[field] = None

    # FII/DII — not available historically
    for field in [
        "fii_buy_cr", "fii_sell_cr", "fii_net_cr",
        "dii_buy_cr", "dii_sell_cr", "dii_net_cr",
        "fii_dii_combined_net_cr", "fii_dii_signal",
    ]:
        snap[field] = None

    # Participant OI — not available historically
    for field in [
        "fii_fut_index_long", "fii_fut_index_short", "fii_fut_index_net",
        "fii_total_long", "fii_total_short", "fii_total_net", "fii_futures_signal",
        "client_fut_index_net", "client_total_net",
    ]:
        snap[field] = None

    # Macro
    _apply_macro(snap, macro, date_str)

    # News — not available historically
    snap["event_risk_count"] = None
    snap["total_headlines"] = None
    snap["event_risk_headlines"] = None

    # Technicals
    dma = technicals["dma"]
    snap["nifty_rsi"] = technicals["rsi_val"]
    snap["nifty_rsi_signal"] = technicals["rsi_signal"]
    snap["nifty_dma_20"] = dma.get("dma_20")
    snap["nifty_dma_50"] = dma.get("dma_50")
    snap["nifty_dma_200"] = dma.get("dma_200")
    snap["nifty_vs_200dma_pct"] = dma.get("distance_200dma_pct")
    snap["nifty_vs_50dma_pct"] = dma.get("distance_50dma_pct")
    snap["nifty_dma_trend"] = dma.get("trend")
    snap["nifty_dma_cross"] = dma.get("cross")
    boll = technicals["bollinger"] or {}
    snap["nifty_bollinger_bandwidth"] = boll.get("bandwidth_pct")
    snap["nifty_bollinger_pct_b"] = boll.get("percent_b")
    snap["nifty_bollinger_signal"] = boll.get("signal")
    macd = technicals["macd"] or {}
    snap["nifty_macd_histogram"] = macd.get("histogram")
    snap["nifty_macd_crossover"] = macd.get("crossover")
    snap["nifty_macd_trend"] = macd.get("trend")
    snap["nifty_technical_stance"] = technicals["stance"]

    snap["_backfilled"] = True

    return snap


def _apply_macro(
    snap: dict,
    macro: dict[str, dict[str, dict]],
    date_str: str,
) -> None:
    """Fill macro fields from yfinance historical data, with signal derivation."""

    def _get(key: str) -> dict | None:
        series = macro.get(key, {})
        if date_str in series:
            return series[date_str]
        # US market might be closed on an India trading day — try previous 3 days
        from datetime import timedelta, date as date_cls
        dt = date_cls.fromisoformat(date_str)
        for offset in range(1, 4):
            prev = (dt - timedelta(days=offset)).isoformat()
            if prev in series:
                return {**series[prev], "change_pct": None}
        return None

    sp = _get("sp500")
    snap["sp500_change_pct"] = sp["change_pct"] if sp else None
    snap["sp500_signal"] = _sp500_signal(sp["change_pct"] if sp else None)

    dxy = _get("dxy")
    snap["dxy_price"] = dxy["price"] if dxy else None
    snap["dxy_change_pct"] = dxy["change_pct"] if dxy else None
    snap["dxy_signal"] = _dxy_signal(dxy["change_pct"] if dxy else None)

    usdinr = _get("usdinr")
    snap["usdinr_price"] = usdinr["price"] if usdinr else None
    snap["usdinr_change_pct"] = usdinr["change_pct"] if usdinr else None
    snap["usdinr_signal"] = _usdinr_signal(usdinr["change_pct"] if usdinr else None)

    crude = _get("crude")
    snap["crude_price"] = crude["price"] if crude else None
    snap["crude_change_pct"] = crude["change_pct"] if crude else None
    snap["crude_signal"] = _crude_signal(crude["change_pct"] if crude else None)

    gold = _get("gold")
    snap["gold_price"] = gold["price"] if gold else None
    snap["gold_change_pct"] = gold["change_pct"] if gold else None

    us10y = _get("us10y")
    us5y = _get("us5y")
    us10y_yield = us10y["price"] if us10y else None
    us5y_yield = us5y["price"] if us5y else None
    snap["us10y_yield"] = us10y_yield
    snap["us5y_yield"] = us5y_yield

    us10y_change = None
    if us10y and us10y.get("prev_close") and us10y["price"]:
        us10y_change = round(us10y["price"] - us10y["prev_close"], 4)
    snap["us10y_signal"] = _us10y_signal(us10y_change, us10y_yield)

    if us10y_yield is not None and us5y_yield is not None:
        snap["yield_curve_spread"] = round(us10y_yield - us5y_yield, 3)
    else:
        snap["yield_curve_spread"] = None

    # Composite macro signal
    signals = [
        snap.get("sp500_signal"),
        snap.get("dxy_signal"),
        snap.get("usdinr_signal"),
        snap.get("crude_signal"),
        snap.get("us10y_signal"),
    ]
    snap["india_macro_signal"] = _composite_macro_signal(signals)


# ── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill historical snapshots")
    parser.add_argument("--days", type=int, default=2000, help="Days of OHLC to fetch (max 2000)")
    parser.add_argument(
        "--reprocess", action="store_true",
        help="Re-process existing backfilled snapshots (e.g. to add macro data). "
             "Full daily snapshots are never overwritten.",
    )
    args = parser.parse_args()

    days = min(args.days, 2000)

    # 1. Fetch Kite OHLC
    nifty_candles, bnf_candles, vix_candles = _fetch_kite_ohlc(days)

    if not nifty_candles:
        print("[backfill] No Nifty candles. Aborting.")
        sys.exit(1)

    # Build date-indexed lookups for BankNifty and VIX
    bnf_by_date: dict[str, dict] = {}
    prev_bnf_close: float | None = None
    for c in bnf_candles:
        d = c["date"][:10]
        change_pct = None
        if prev_bnf_close and prev_bnf_close > 0:
            change_pct = round((c["close"] - prev_bnf_close) / prev_bnf_close * 100, 2)
        bnf_by_date[d] = {"close": c["close"], "change_pct": change_pct}
        prev_bnf_close = c["close"]

    vix_by_date: dict[str, dict] = {}
    for c in vix_candles:
        vix_by_date[c["date"][:10]] = c

    # 2. Fetch yfinance macro history
    first_date = nifty_candles[0]["date"][:10]
    last_date = nifty_candles[-1]["date"][:10]
    macro = _fetch_macro_history(first_date, last_date)

    # 3. Pre-compute Nifty SMA arrays
    all_closes = [c["close"] for c in nifty_candles]
    print("[backfill] Pre-computing SMAs...")
    sma_20_all = _sma(all_closes, 20)
    sma_50_all = _sma(all_closes, 50)
    sma_200_all = _sma(all_closes, 200)

    # 4. Determine which dates to skip
    from core.daily_store import available_dates
    existing = set(available_dates())

    # With --reprocess, overwrite backfilled snapshots but never full ones
    reprocessable: set[str] = set()
    if args.reprocess:
        for d_str in existing:
            snap = load(date.fromisoformat(d_str))
            if snap and snap.get("_backfilled"):
                reprocessable.add(d_str)
        print(f"[backfill] --reprocess: {len(reprocessable)} backfilled snapshots will be re-generated")

    saved = 0
    skipped = 0
    prev_nifty_close: float | None = None
    prev_vix_close: float | None = None

    total = len(nifty_candles)
    print(f"[backfill] Processing {total} trading days...")

    for i, candle in enumerate(nifty_candles):
        date_str = candle["date"][:10]

        if date_str in existing and date_str not in reprocessable:
            prev_nifty_close = candle["close"]
            vix_c = vix_by_date.get(date_str)
            if vix_c:
                prev_vix_close = vix_c["close"]
            skipped += 1
            continue

        tech = _compute_technicals_at(all_closes, i, sma_20_all, sma_50_all, sma_200_all)

        vix_data = vix_by_date.get(date_str)

        snap = _build_snapshot(
            nifty_candle=candle,
            prev_nifty_close=prev_nifty_close,
            technicals=tech,
            bnf_data=bnf_by_date.get(date_str),
            vix_data=vix_data,
            prev_vix_close=prev_vix_close,
            macro=macro,
            date_str=date_str,
        )

        dt = date.fromisoformat(date_str)
        save(snap, dt)
        saved += 1

        prev_nifty_close = candle["close"]
        if vix_data:
            prev_vix_close = vix_data["close"]

        if saved % 100 == 0 or saved == 1:
            print(f"  saved {saved} ... ({date_str})")

    print(f"\n[backfill] Done. {saved} new snapshots, {skipped} existing skipped.")
    print(f"[backfill] Total snapshots now: {saved + skipped + len(existing) - skipped}")


if __name__ == "__main__":
    main()
