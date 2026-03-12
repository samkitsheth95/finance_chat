"""
Layer 2 — Institutional Flows
Fetches FII/DII cash market activity and F&O participant-wise OI from NSE public data.
No auth required. HTTP session management lives in core/nse_client.py.

Data availability:
  - FII/DII cash flows  → live intraday via NSE API (same-day)
  - Participant OI      → NSE archives CSV, published after market close (~6 PM IST)
"""

from datetime import datetime, timedelta

import pandas as pd

from core.nse_client import nse_fetch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_float(val) -> float:
    """Coerce a string like '12,345.67' or '-6267.31' to float safely."""
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _prev_trading_day(days_back: int = 1) -> str:
    """Return date string DDMMYYYY for N trading-days back (skips weekends)."""
    dt = datetime.now()
    skipped = 0
    while skipped < days_back:
        dt -= timedelta(days=1)
        if dt.weekday() < 5:  # Monday–Friday
            skipped += 1
    return dt.strftime("%d%m%Y")


# ---------------------------------------------------------------------------
# FII / DII cash market activity
# ---------------------------------------------------------------------------

def get_fii_dii_activity() -> dict:
    """
    Get the latest available FII and DII cash market buy/sell/net activity from NSE.

    Returns buy value, sell value, and net for both FII/FPI and DII.
    Values are in ₹ crores.

    IMPORTANT — Data freshness:
      NSE publishes final FII/DII numbers between 8:30–9:30 PM IST.
      Before that, this endpoint returns the PREVIOUS trading day's data.
      The response includes a 'data_date' field showing which day the
      numbers actually belong to, and 'is_stale' if it's not today.

    Interpretation guide:
      FII net > 0  → foreign institutions net buyers (bullish signal)
      FII net < 0  → foreign institutions net sellers (bearish signal)
      DII net > 0  → domestic institutions absorbing FII selling (support)
      DII net < 0  → both selling together (strong bearish pressure)
    """
    try:
        raw = nse_fetch("https://www.nseindia.com/api/fiidiiTradeReact")
    except Exception as e:
        return {"error": f"Failed to fetch FII/DII data from NSE: {e}"}

    if not raw:
        return {"error": "NSE returned empty FII/DII data"}

    # raw is a list of {category, date, buyValue, sellValue, netValue}
    try:
        df = pd.DataFrame(raw)
    except Exception as e:
        return {"error": f"Could not parse FII/DII response: {e}", "raw": raw}

    if df.empty:
        return {"error": "NSE returned empty FII/DII data"}

    result: dict = {
        "date": None,
        "fii": {},
        "dii": {},
        "combined_net": None,
        "signal": None,
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    for _, row in df.iterrows():
        category = str(row.get("category", "")).upper()
        date_val = str(row.get("date", ""))
        buy  = _to_float(row.get("buyValue",  0))
        sell = _to_float(row.get("sellValue", 0))
        net  = _to_float(row.get("netValue",  0))

        entry = {"buy_cr": buy, "sell_cr": sell, "net_cr": net}

        if "FII" in category or "FPI" in category:
            result["fii"]  = entry
            result["date"] = date_val
        elif "DII" in category:
            result["dii"]  = entry
            result["date"] = result["date"] or date_val

    # Staleness detection: NSE publishes at 8:30–9:30 PM IST.
    # Before that, the API returns the previous day's data.
    nse_date_str = result.get("date")
    if nse_date_str:
        try:
            nse_date = datetime.strptime(nse_date_str, "%d-%b-%Y").date()
            today = datetime.now().date()
            if nse_date < today:
                result["is_stale"] = True
                result["stale_note"] = (
                    f"Data is for {nse_date_str}, not today. "
                    f"NSE publishes today's numbers after 8:30 PM IST."
                )
        except ValueError:
            pass

    # Derived combined net and directional signal
    fii_net = result["fii"].get("net_cr", 0.0)
    dii_net = result["dii"].get("net_cr", 0.0)
    combined = round(fii_net + dii_net, 2)
    result["combined_net"] = combined

    if fii_net > 500:
        signal = "bullish"
    elif fii_net < -500:
        signal = "bearish"
    else:
        signal = "neutral"

    if fii_net < -500 and dii_net < 0:
        signal = "strongly_bearish"
    elif fii_net > 500 and dii_net > 0:
        signal = "strongly_bullish"

    result["signal"] = signal
    return result


# ---------------------------------------------------------------------------
# F&O participant-wise open interest
# ---------------------------------------------------------------------------

# Maps CSV column names to short keys used in the returned dict.
# NSE CSV: first row is a title; actual headers are in the second row (skiprows=1).
# Column order from NSE archives: Client Type, Future Index Long, Future Index Short,
# Future Stock Long, Future Stock Short, Option Index Call Long, Option Index Put Long,
# Option Index Call Short, Option Index Put Short, Option Stock Call Long, Option Stock
# Put Long, Option Stock Call Short, Option Stock Put Short, Total Long Contracts,
# Total Short Contracts
_OI_COL_MAP = {
    "Future Index Long":        "fut_index_long",
    "Future Index Short":       "fut_index_short",
    "Future Stock Long":        "fut_stock_long",
    "Future Stock Short":       "fut_stock_short",
    "Option Index Call Long":   "opt_idx_call_long",
    "Option Index Call Short":  "opt_idx_call_short",
    "Option Index Put Long":    "opt_idx_put_long",
    "Option Index Put Short":   "opt_idx_put_short",
    "Option Stock Call Long":   "opt_stk_call_long",
    "Option Stock Call Short":  "opt_stk_call_short",
    "Option Stock Put Long":    "opt_stk_put_long",
    "Option Stock Put Short":   "opt_stk_put_short",
    "Total Long Contracts":     "total_long",
    "Total Short Contracts":    "total_short",
}

_PARTICIPANT_NAMES = {"CLIENT": "Client", "DII": "DII", "FII": "FII", "PRO": "Pro"}


def get_participant_oi(date: str = "latest") -> dict:
    """
    Get F&O participant-wise open interest breakdown from NSE archives.

    Participants: FII, DII, Client (retail), Pro (proprietary)
    Instruments:  Index futures, stock futures, index options (calls/puts),
                  stock options (calls/puts)

    Args:
        date: Trading date in DD-MM-YYYY format, e.g. "10-03-2026".
              Use "latest" to auto-detect the most recent available day.
              NSE publishes this data after market close (~6 PM IST).

    Returns:
        Participant-wise long/short OI for each instrument type, plus
        net index futures position per participant (key trading signal).

    Key signals:
      FII fut_index_net > 0  → FII long on index futures (bullish)
      FII fut_index_net < 0  → FII short on index futures (bearish hedge)
      Client OI diverging from FII → retail vs institutional positioning
    """
    date_str = _resolve_oi_date(date)
    url = f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{date_str}.csv"

    # NSE CSV has a title line on row 0; actual column headers are on row 1.
    def _read_oi_csv(u: str) -> pd.DataFrame:
        return pd.read_csv(u, skiprows=1)

    try:
        df = _read_oi_csv(url)
    except Exception as e:
        # Try previous trading day on failure (data published after close)
        if date == "latest":
            prev = _prev_trading_day(2)
            url2 = f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{prev}.csv"
            try:
                df = _read_oi_csv(url2)
                date_str = prev
            except Exception:
                return {"error": f"Could not fetch participant OI for {date_str} or {prev}: {e}"}
        else:
            return {"error": f"Could not fetch participant OI for {date_str}: {e}"}

    if df is None or df.empty:
        return {"error": f"Empty participant OI data for {date_str}"}

    # Normalize column names (strip whitespace)
    df.columns = [c.strip() for c in df.columns]

    # First column is "Client Type"
    client_col = df.columns[0]

    participants = {}
    for _, row in df.iterrows():
        ptype = str(row.get(client_col, "")).strip().upper()
        if ptype not in _PARTICIPANT_NAMES:
            continue  # skip "Total" row and empty rows

        label = _PARTICIPANT_NAMES[ptype]
        entry: dict = {}
        for csv_col, key in _OI_COL_MAP.items():
            if csv_col in df.columns:
                entry[key] = int(_to_float(row.get(csv_col, 0)))

        # Derived nets
        if "fut_index_long" in entry and "fut_index_short" in entry:
            entry["fut_index_net"] = entry["fut_index_long"] - entry["fut_index_short"]
        if "total_long" in entry and "total_short" in entry:
            entry["total_net"] = entry["total_long"] - entry["total_short"]

        participants[label] = entry

    # Top-level FII index futures signal
    fii_idx_net = participants.get("FII", {}).get("fut_index_net", 0)
    if fii_idx_net > 50000:
        signal = "bullish"
    elif fii_idx_net < -50000:
        signal = "bearish"
    else:
        signal = "neutral"

    # Convert DDMMYYYY → readable DD-MM-YYYY
    display_date = f"{date_str[:2]}-{date_str[2:4]}-{date_str[4:]}"

    return {
        "date": display_date,
        "participants": participants,
        "fii_index_futures_signal": signal,
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _resolve_oi_date(date: str) -> str:
    """
    Convert user-supplied date to DDMMYYYY archive filename format.
    'latest' → yesterday (or Friday if today is Monday/Tuesday).
    'DD-MM-YYYY' → 'DDMMYYYY'
    """
    if date == "latest":
        return _prev_trading_day(1)
    # Accept DD-MM-YYYY or YYYY-MM-DD
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date, fmt).strftime("%d%m%Y")
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date format: {date!r}. Use DD-MM-YYYY.")
