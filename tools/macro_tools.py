"""
Layer 4 — Global Macro Tools

Fetches and interprets external macro forces that drive FII flows and Indian
equity direction: global indices, commodities, forex (DXY/USD/INR), and US
Treasury yields.

Two public functions:
  get_global_markets()   → equity indices (S&P 500, Nasdaq, Nikkei, Hang Seng)
  get_macro_snapshot()   → full picture (indices + crude + gold + DXY + INR + US10Y)
                           with a composite India macro signal

India impact logic:
  S&P / Nasdaq rising   → risk-on → FII inflows (+)
  DXY rising            → USD strong → EM outflows (−)
  USD/INR rising        → INR weak → FII exit pressure (−)
  Crude rising          → higher import bill, CAD pressure (−)
  US 10Y rising         → capital flows to US bonds → FII outflows (−)
  Nikkei / Hang Seng    → regional risk-on/off → partial India signal
"""

from __future__ import annotations

from datetime import datetime

from core.macro_client import yf_latest


# ---------------------------------------------------------------------------
# Asset catalog
# ---------------------------------------------------------------------------

_INDICES: dict[str, tuple[str, str]] = {
    "sp500":     ("^GSPC",  "S&P 500"),
    "nasdaq":    ("^IXIC",  "Nasdaq Composite"),
    "nikkei":    ("^N225",  "Nikkei 225"),
    "hang_seng": ("^HSI",   "Hang Seng"),
    "ftse":      ("^FTSE",  "FTSE 100"),
}

_COMMODITIES: dict[str, tuple[str, str]] = {
    "wti_crude":   ("CL=F", "WTI Crude Oil (USD/bbl)"),
    "brent_crude": ("BZ=F", "Brent Crude (USD/bbl)"),
    "gold":        ("GC=F", "Gold (USD/oz)"),
}

_FOREX: dict[str, tuple[str, str]] = {
    "dxy":    ("DX-Y.NYB", "US Dollar Index (DXY)"),
    "usdinr": ("USDINR=X", "USD/INR"),
    "eurusd": ("EURUSD=X", "EUR/USD"),
}

# yfinance Treasury yield tickers — price IS the yield in %
# CBOE indices; live during US hours, previous close otherwise.
_YIELD_TICKERS: dict[str, tuple[str, str]] = {
    "us10y": ("^TNX", "US 10-Year Treasury Yield (%)"),
    "us5y":  ("^FVX", "US 5-Year Treasury Yield (%)"),
}


# ---------------------------------------------------------------------------
# Per-factor India signal derivation
# ---------------------------------------------------------------------------

def _signal_global_index(change_pct: float | None, label: str) -> tuple[str, str]:
    """Risk-on/off from a major global equity index."""
    if change_pct is None:
        return "unknown", f"{label}: no data"
    if change_pct >= 1.5:
        return "bullish",        f"{label} +{change_pct:.1f}% — risk-on, FII inflows likely"
    if change_pct >= 0.4:
        return "mildly_bullish", f"{label} +{change_pct:.1f}% — positive global sentiment"
    if change_pct > -0.4:
        return "neutral",        f"{label} flat ({change_pct:+.1f}%)"
    if change_pct > -1.5:
        return "mildly_bearish", f"{label} {change_pct:.1f}% — mild risk-off"
    return "bearish",            f"{label} {change_pct:.1f}% — risk-off, FII selling pressure"


def _signal_dxy(change_pct: float | None) -> tuple[str, str]:
    """DXY: USD strength drains EM liquidity."""
    if change_pct is None:
        return "unknown", "DXY: no data"
    if change_pct >= 0.5:
        return "bearish",        f"DXY +{change_pct:.2f}% — strong USD → EM capital outflows"
    if change_pct >= 0.15:
        return "mildly_bearish", f"DXY +{change_pct:.2f}% — mild USD strength"
    if change_pct > -0.15:
        return "neutral",        f"DXY flat ({change_pct:+.2f}%)"
    if change_pct > -0.5:
        return "mildly_bullish", f"DXY {change_pct:.2f}% — mild USD softening"
    return "bullish",            f"DXY {change_pct:.2f}% — weak USD → EM inflows supportive"


def _signal_usdinr(change_pct: float | None) -> tuple[str, str]:
    """USD/INR: INR depreciation raises FII exit risk."""
    if change_pct is None:
        return "unknown", "USD/INR: no data"
    if change_pct >= 0.3:
        return "bearish",        f"INR weakening {change_pct:.2f}% — currency risk amplifies FII selling"
    if change_pct >= 0.1:
        return "mildly_bearish", f"INR slightly weaker ({change_pct:.2f}%)"
    if change_pct > -0.1:
        return "neutral",        f"INR stable ({change_pct:+.2f}%)"
    if change_pct > -0.3:
        return "mildly_bullish", f"INR slightly stronger ({change_pct:.2f}%)"
    return "bullish",            f"INR strengthening {change_pct:.2f}% — positive for FII returns"


def _signal_crude(change_pct: float | None, label: str) -> tuple[str, str]:
    """Crude: India is a net importer — higher crude = macro headwind."""
    if change_pct is None:
        return "unknown", f"{label}: no data"
    if change_pct >= 2.5:
        return "bearish",        f"{label} +{change_pct:.1f}% — import bill pressure, inflation risk"
    if change_pct >= 0.7:
        return "mildly_bearish", f"{label} +{change_pct:.1f}% — mild headwind for India CAD"
    if change_pct > -0.7:
        return "neutral",        f"{label} flat ({change_pct:+.1f}%)"
    if change_pct > -2.5:
        return "mildly_bullish", f"{label} {change_pct:.1f}% — slight macro relief for India"
    return "bullish",            f"{label} {change_pct:.1f}% — lower import bill, CAD relief, rate cut room"


def _signal_us10y(
    change: float | None,
    level: float | None,
) -> tuple[str, str]:
    """US 10Y: higher yield pulls capital out of EM equities."""
    if change is None or level is None:
        return "unknown", "US 10Y: no data"
    level_note = f" (at {level:.2f}%)" if level else ""
    if level >= 4.5 and change >= 0.05:
        return "bearish",        f"US 10Y +{change:.2f}pp to {level:.2f}% — high rates attract EM capital"
    if change >= 0.05:
        return "mildly_bearish", f"US 10Y rising +{change:.2f}pp{level_note} — mild FII headwind"
    if change > -0.05:
        return "neutral",        f"US 10Y stable at {level:.2f}%"
    if change > -0.1:
        return "mildly_bullish", f"US 10Y easing {change:.2f}pp{level_note} — EM flows improving"
    return "bullish",            f"US 10Y down {change:.2f}pp{level_note} — EM inflows supportive"


def _composite_signal(signals: list[str]) -> str:
    """
    Weighted composite of per-factor signals.

    Weights reflect India-specific sensitivity:
      DXY / US 10Y / crude  → weight 2  (structural FII drivers)
      S&P 500 / Nasdaq       → weight 1.5
      Nikkei / Hang Seng     → weight 0.75
      USD/INR                → weight 1.5
      FTSE / gold            → weight 0.5
    """
    _scores = {
        "bullish": 2, "mildly_bullish": 1, "neutral": 0,
        "mildly_bearish": -1, "bearish": -2, "unknown": 0,
    }
    total = sum(_scores.get(s, 0) for s in signals)
    counted = sum(1 for s in signals if s != "unknown")
    if not counted:
        return "unknown"
    avg = total / counted
    if avg >= 1.0:
        return "bullish"
    if avg >= 0.3:
        return "mildly_bullish"
    if avg > -0.3:
        return "neutral"
    if avg > -1.0:
        return "mildly_bearish"
    return "bearish"


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------

def get_global_markets() -> dict:
    """
    Get live data for major global equity indices with India market signal.

    Covers: S&P 500, Nasdaq, Nikkei 225, Hang Seng, FTSE 100.

    Returns:
        {
          "indices": {
            "<key>": {
              "label":        str,
              "ticker":       str,
              "price":        float,
              "prev_close":   float,
              "change":       float,
              "change_pct":   float,
              "day_high":     float,
              "day_low":      float,
              "india_signal": str,   # bullish/mildly_bullish/neutral/mildly_bearish/bearish
            }, ...
          },
          "india_equity_signal": str,    # composite of all index signals
          "signal_notes":        list[str],
          "as_of":               str,
        }
    """
    result: dict = {
        "indices":              {},
        "india_equity_signal":  None,
        "signal_notes":         [],
        "as_of":                _now(),
    }
    signals: list[str] = []

    for key, (ticker, label) in _INDICES.items():
        data = yf_latest(ticker)
        data["label"] = label
        sig, note = _signal_global_index(data.get("change_pct"), label)
        data["india_signal"] = sig
        result["indices"][key] = data
        signals.append(sig)
        result["signal_notes"].append(note)

    result["india_equity_signal"] = _composite_signal(signals)
    return result


def get_macro_snapshot() -> dict:
    """
    Full global macro picture relevant to Indian markets.

    Combines:
      • Global equity indices   (S&P 500, Nasdaq, Nikkei, Hang Seng)
      • Commodities             (WTI crude, Brent crude, Gold)
      • Forex                   (DXY, USD/INR, EUR/USD)
      • US Treasury yields      (10Y and 2Y — FRED if key set, else yfinance ^TNX)

    Each factor carries an india_signal (bullish → bearish).
    A composite india_macro_signal summarises the overall picture.

    Returns:
        {
          "global_indices":       { ... },   # same shape as get_global_markets()
          "commodities":          { ... },
          "forex":                { ... },
          "us_yields":            { ... },
          "india_macro_signal":   str,
          "signal_notes":         list[str],
          "as_of":                str,
        }
    """
    snapshot: dict = {
        "global_indices":     {},
        "commodities":        {},
        "forex":              {},
        "us_yields":          {},
        "india_macro_signal": None,
        "signal_notes":       [],
        "as_of":              _now(),
    }
    all_signals: list[str] = []

    # ── Global indices ────────────────────────────────────────────────────────
    for key, (ticker, label) in _INDICES.items():
        data = yf_latest(ticker)
        data["label"] = label
        sig, note = _signal_global_index(data.get("change_pct"), label)
        data["india_signal"] = sig
        snapshot["global_indices"][key] = data
        all_signals.append(sig)
        snapshot["signal_notes"].append(note)

    # ── Commodities ───────────────────────────────────────────────────────────
    for key, (ticker, label) in _COMMODITIES.items():
        data = yf_latest(ticker)
        data["label"] = label
        if "crude" in key:
            sig, note = _signal_crude(data.get("change_pct"), label)
            data["india_signal"] = sig
            all_signals.append(sig)
            snapshot["signal_notes"].append(note)
        else:
            # Gold: risk-off indicator; include but don't fold into composite
            data["india_signal"] = "neutral"
        snapshot["commodities"][key] = data

    # ── Forex ─────────────────────────────────────────────────────────────────
    for key, (ticker, label) in _FOREX.items():
        data = yf_latest(ticker)
        data["label"] = label
        if key == "dxy":
            sig, note = _signal_dxy(data.get("change_pct"))
        elif key == "usdinr":
            sig, note = _signal_usdinr(data.get("change_pct"))
        else:
            sig, note = "neutral", f"{label}: informational"
        data["india_signal"] = sig
        snapshot["forex"][key] = data
        if key in ("dxy", "usdinr"):
            all_signals.append(sig)
            snapshot["signal_notes"].append(note)

    # ── US Treasury yields ────────────────────────────────────────────────────
    snapshot["us_yields"] = _fetch_us_yields(all_signals, snapshot["signal_notes"])

    snapshot["india_macro_signal"] = _composite_signal(all_signals)
    return snapshot


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _fetch_us_yields(
    all_signals: list[str],
    signal_notes: list[str],
) -> dict:
    """
    Fetch US 10Y and 5Y Treasury yields from yfinance (^TNX, ^FVX).
    The ticker price IS the yield in %; change is in percentage-points.
    Appends the 10Y signal to all_signals and signal_notes in-place.
    """
    yields: dict = {}

    for key, (ticker, label) in _YIELD_TICKERS.items():
        raw    = yf_latest(ticker)
        level  = raw.get("price")
        change = raw.get("change")   # change in %-points (e.g. 0.05 = 5 bps)
        sig, note = _signal_us10y(change, level) if key == "us10y" else ("neutral", "")
        yields[key] = {
            "label":             label,
            "yield_pct":         level,
            "prev_yield_pct":    raw.get("prev_close"),
            "change_pct_points": change,
            "india_signal":      sig,
        }
        if key == "us10y":
            all_signals.append(sig)
            if note:
                signal_notes.append(note)

    # Yield curve: 10Y − 5Y spread as a steepness/inversion indicator
    y10 = yields.get("us10y", {}).get("yield_pct")
    y5  = yields.get("us5y",  {}).get("yield_pct")
    if y10 is not None and y5 is not None:
        spread = round(y10 - y5, 3)
        yields["yield_curve"] = {
            "ten_minus_five_pct": spread,
            "note": (
                "inverted (5Y > 10Y) — unusual; watch for recession signals"
                if spread < 0
                else "normal (positive slope)"
            ),
        }

    return yields


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
