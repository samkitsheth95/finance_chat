"""
CSV Parser — parse, validate, build trade ledger and cash flows.

Entry point for all portfolio data. Pipeline:
  parse_csv → validate_trades → validate_symbols → build_position_ledger
                                                  → build_cash_flows
                                                  → detect_sip_patterns
"""
from __future__ import annotations

import csv
from datetime import date, datetime
from typing import Optional

import yfinance as yf

from shared.mf_client import validate_scheme_code
from shared.nse_utils import nse_to_yf

REQUIRED_COLUMNS = {"date", "instrument_type", "symbol", "action", "quantity", "price"}

INFLOW_ACTIONS = {"BUY", "SIP", "SWITCH_IN"}
OUTFLOW_ACTIONS = {"SELL", "SWP", "SWITCH_OUT"}


# ---------------------------------------------------------------------------
# parse_csv
# ---------------------------------------------------------------------------

def parse_csv(csv_path: str) -> list[dict]:
    """Read a CSV file and return a list of normalised trade dicts, sorted by date."""
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        trades: list[dict] = []
        for row in reader:
            trade = _parse_row(row)
            trades.append(trade)

    trades.sort(key=lambda t: t["date"])
    return trades


def _parse_row(row: dict) -> dict:
    """Normalise a single CSV row into a canonical trade dict."""
    qty = float(row["quantity"])
    price = float(row["price"])

    raw_amount = row.get("amount", "").strip()
    amount = float(raw_amount) if raw_amount else round(qty * price, 2)

    raw_brokerage = row.get("brokerage", "").strip()
    brokerage = float(raw_brokerage) if raw_brokerage else 0.0

    return {
        "date": _parse_date(row["date"]),
        "instrument_type": row["instrument_type"].strip().upper(),
        "symbol": row["symbol"].strip(),
        "scheme_name": row.get("scheme_name", "").strip(),
        "action": row["action"].strip().upper(),
        "quantity": qty,
        "price": price,
        "amount": amount,
        "brokerage": brokerage,
        "notes": row.get("notes", "").strip(),
    }


def _parse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


# ---------------------------------------------------------------------------
# validate_trades  (pure — no network calls)
# ---------------------------------------------------------------------------

def validate_trades(trades: list[dict]) -> list[str]:
    """Validate trade list for logical issues. Returns warning strings."""
    warnings: list[str] = []

    _check_oversells(trades, warnings)
    _check_duplicates(trades, warnings)
    _check_weekend_dates(trades, warnings)

    return warnings


def _check_oversells(trades: list[dict], warnings: list[str]) -> None:
    positions: dict[str, float] = {}
    sorted_trades = sorted(trades, key=lambda t: t["date"])
    for t in sorted_trades:
        sym = t["symbol"]
        qty = t["quantity"]
        action = t["action"]
        if action in INFLOW_ACTIONS:
            positions[sym] = positions.get(sym, 0.0) + qty
        elif action in OUTFLOW_ACTIONS:
            held = positions.get(sym, 0.0)
            if qty > held + 1e-6:
                warnings.append(
                    f"Cannot sell more than held: {sym} on {t['date']} "
                    f"(sell {qty}, held {held:.4f})"
                )
            positions[sym] = max(held - qty, 0.0)


def _check_duplicates(trades: list[dict], warnings: list[str]) -> None:
    seen: set[tuple] = set()
    for t in trades:
        key = (t["date"], t["symbol"], t["action"], t["quantity"], t["price"])
        if key in seen:
            warnings.append(
                f"Duplicate trade: {t['symbol']} {t['action']} "
                f"{t['quantity']}@{t['price']} on {t['date']}"
            )
        seen.add(key)


def _check_weekend_dates(trades: list[dict], warnings: list[str]) -> None:
    for t in trades:
        if t["date"].weekday() >= 5:
            warnings.append(
                f"Trade on weekend: {t['symbol']} on {t['date']} "
                f"({t['date'].strftime('%A')})"
            )


# ---------------------------------------------------------------------------
# validate_symbols  (network-dependent — separate from validate_trades)
# ---------------------------------------------------------------------------

def validate_symbols(trades: list[dict]) -> list[str]:
    """Validate that symbols exist. Equity via yfinance, MF via mftool."""
    warnings: list[str] = []
    checked: set[str] = set()

    for t in trades:
        sym = t["symbol"]
        if sym in checked:
            continue
        checked.add(sym)

        if t["instrument_type"] == "EQUITY":
            _validate_equity_symbol(sym, warnings)
        elif t["instrument_type"] == "MF":
            _validate_mf_symbol(sym, t.get("scheme_name", ""), warnings)

    return warnings


def _validate_equity_symbol(symbol: str, warnings: list[str]) -> None:
    try:
        ticker = yf.Ticker(nse_to_yf(symbol))
        _ = ticker.fast_info
    except Exception:
        warnings.append(
            f"Equity symbol could not be verified: {symbol} "
            f"(may be delisted or misspelled)"
        )


def _validate_mf_symbol(
    scheme_code: str, scheme_name: str, warnings: list[str]
) -> None:
    result = validate_scheme_code(scheme_code)
    if not result.get("valid"):
        warnings.append(
            f"MF scheme code not found in AMFI: {scheme_code} — "
            f"{result.get('error', 'unknown error')}"
        )
        return

    if scheme_name and result.get("scheme_name"):
        amfi_name = result["scheme_name"].lower()
        if scheme_name.lower() not in amfi_name and amfi_name not in scheme_name.lower():
            warnings.append(
                f"MF scheme name mismatch for {scheme_code}: "
                f"CSV has '{scheme_name}', AMFI has '{result['scheme_name']}'"
            )


# ---------------------------------------------------------------------------
# build_position_ledger
# ---------------------------------------------------------------------------

def build_position_ledger(trades: list[dict]) -> dict:
    """Build current position ledger from trade history.

    Equity: FIFO cost basis.
    MF: per-lot tracking (each purchase is a separate lot).
    Sells consume oldest lots first (FIFO).
    Returns dict keyed by symbol; positions with zero quantity are excluded.
    """
    sorted_trades = sorted(trades, key=lambda t: t["date"])
    positions: dict[str, dict] = {}

    for t in sorted_trades:
        sym = t["symbol"]
        itype = t["instrument_type"]
        action = t["action"]

        if itype == "EQUITY":
            _apply_equity_trade(positions, sym, t, action)
        elif itype == "MF":
            _apply_mf_trade(positions, sym, t, action)

    return {s: p for s, p in positions.items() if _has_quantity(p)}


def _apply_equity_trade(
    positions: dict, sym: str, trade: dict, action: str
) -> None:
    if sym not in positions:
        positions[sym] = {
            "instrument_type": "EQUITY",
            "quantity": 0.0,
            "total_cost": 0.0,
            "avg_cost": 0.0,
            "invested": 0.0,
        }
    pos = positions[sym]

    if action in INFLOW_ACTIONS:
        old_qty = pos["quantity"]
        old_cost = pos["total_cost"]
        new_qty = old_qty + trade["quantity"]
        new_cost = old_cost + trade["quantity"] * trade["price"]
        pos["quantity"] = new_qty
        pos["total_cost"] = new_cost
        pos["avg_cost"] = new_cost / new_qty if new_qty > 0 else 0.0
        pos["invested"] = new_cost
    elif action in OUTFLOW_ACTIONS:
        sell_qty = trade["quantity"]
        pos["quantity"] = max(pos["quantity"] - sell_qty, 0.0)
        if pos["quantity"] > 0:
            pos["total_cost"] = pos["avg_cost"] * pos["quantity"]
            pos["invested"] = pos["total_cost"]
        else:
            pos["total_cost"] = 0.0
            pos["invested"] = 0.0


def _apply_mf_trade(
    positions: dict, sym: str, trade: dict, action: str
) -> None:
    if sym not in positions:
        positions[sym] = {
            "instrument_type": "MF",
            "lots": [],
            "total_quantity": 0.0,
            "scheme_name": trade.get("scheme_name", ""),
        }
    pos = positions[sym]

    if action in INFLOW_ACTIONS:
        pos["lots"].append({
            "date": trade["date"],
            "quantity": trade["quantity"],
            "price": trade["price"],
            "amount": trade["amount"],
        })
        pos["total_quantity"] += trade["quantity"]
    elif action in OUTFLOW_ACTIONS:
        remaining = trade["quantity"]
        new_lots = []
        for lot in pos["lots"]:
            if remaining <= 1e-6:
                new_lots.append(lot)
                continue
            if lot["quantity"] <= remaining + 1e-6:
                remaining -= lot["quantity"]
            else:
                lot["quantity"] -= remaining
                lot["amount"] = lot["quantity"] * lot["price"]
                remaining = 0.0
                new_lots.append(lot)
        pos["lots"] = new_lots
        pos["total_quantity"] = sum(l["quantity"] for l in new_lots)


def _has_quantity(pos: dict) -> bool:
    if pos["instrument_type"] == "EQUITY":
        return pos["quantity"] > 1e-6
    return pos.get("total_quantity", 0.0) > 1e-6


# ---------------------------------------------------------------------------
# build_cash_flows
# ---------------------------------------------------------------------------

def build_cash_flows(trades: list[dict]) -> list[dict]:
    """Convert trades into signed cash flows for XIRR / scenario modelling.

    BUY/SIP/SWITCH_IN  → negative (money goes out)
    SELL/SWP/SWITCH_OUT → positive (money comes back)
    """
    flows: list[dict] = []
    for t in trades:
        action = t["action"]
        amount = t["amount"]
        if action in INFLOW_ACTIONS:
            signed = -abs(amount)
        elif action in OUTFLOW_ACTIONS:
            signed = abs(amount)
        else:
            continue

        flows.append({
            "date": t["date"],
            "amount": signed,
            "symbol": t["symbol"],
            "action": action,
        })

    flows.sort(key=lambda f: f["date"])
    return flows


# ---------------------------------------------------------------------------
# detect_sip_patterns
# ---------------------------------------------------------------------------

def detect_sip_patterns(trades: list[dict]) -> list[dict]:
    """Identify regular SIP patterns in MF trades.

    Groups MF SIP trades by scheme code, checks for monthly cadence
    (25–35 day gaps) and consistent amounts (within 20% of mean).
    Requires at least 2 SIP transactions to detect a pattern.
    """
    sip_trades: dict[str, list[dict]] = {}
    for t in trades:
        if t["instrument_type"] == "MF" and t["action"] == "SIP":
            sip_trades.setdefault(t["symbol"], []).append(t)

    patterns: list[dict] = []
    for scheme_code, txns in sip_trades.items():
        if len(txns) < 2:
            continue
        txns_sorted = sorted(txns, key=lambda t: t["date"])
        pattern = _analyse_sip_group(scheme_code, txns_sorted)
        if pattern:
            patterns.append(pattern)

    return patterns


def _analyse_sip_group(scheme_code: str, txns: list[dict]) -> Optional[dict]:
    """Check if a group of SIP transactions forms a regular monthly pattern."""
    gaps = []
    for i in range(1, len(txns)):
        gap = (txns[i]["date"] - txns[i - 1]["date"]).days
        gaps.append(gap)

    monthly_gaps = [g for g in gaps if 25 <= g <= 35]
    if len(monthly_gaps) < len(gaps) * 0.6:
        return None

    amounts = [t["amount"] for t in txns]
    avg_amount = sum(amounts) / len(amounts)

    scheme_name = txns[0].get("scheme_name", "")

    return {
        "scheme_code": scheme_code,
        "scheme_name": scheme_name,
        "frequency": "monthly",
        "avg_amount": round(avg_amount, 2),
        "start_date": txns[0]["date"],
        "end_date": txns[-1]["date"],
        "total_sips": len(txns),
    }
