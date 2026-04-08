"""
Portfolio Doctor tools — portfolio ingestion and overview.

Orchestrates csv_parser and portfolio_engine. Manages file I/O to
data/portfolios/{client_name}/.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from portfolio_doctor.core.csv_parser import (
    parse_csv,
    validate_trades,
    validate_symbols,
    build_position_ledger,
    build_cash_flows,
    detect_sip_patterns,
)
from portfolio_doctor.core.portfolio_engine import (
    compute_returns,
    compute_sector_allocation,
    compute_turnover,
    compute_tax_drag,
)
from shared.nse_utils import nse_to_yf
from shared.yf_client import yf_latest, get_yf_session

PORTFOLIO_DIR = Path("data/portfolios")


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def _client_dir(client_name: str) -> Path:
    d = PORTFOLIO_DIR / client_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_json(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _load_json(path: Path) -> dict | list:
    with open(path) as f:
        return json.load(f)


def _load_trades(path: Path) -> list[dict]:
    """Load trades JSON and reconstruct date objects from ISO strings."""
    raw = _load_json(path)
    for t in raw:
        if isinstance(t.get("date"), str):
            y, m, d = t["date"].split("-")
            t["date"] = date(int(y), int(m), int(d))
    return raw


# ---------------------------------------------------------------------------
# ingest_client_trades
# ---------------------------------------------------------------------------

def ingest_client_trades(csv_path: str, client_name: str) -> dict:
    """
    Parse and validate a client's trading CSV, store processed data.

    Returns validation summary with trade count, date range, symbols, etc.
    """
    try:
        trades = parse_csv(csv_path)
        warnings = validate_trades(trades)
        symbol_warnings = validate_symbols(trades)
        warnings.extend(symbol_warnings)
        ledger = build_position_ledger(trades)
        cash_flows = build_cash_flows(trades)
        sip_patterns = detect_sip_patterns(trades)

        cdir = _client_dir(client_name)
        _save_json(cdir / "trades.json", trades)
        _save_json(cdir / "positions.json", ledger)
        _save_json(cdir / "cashflows.json", cash_flows)
        _save_json(cdir / "sip_patterns.json", sip_patterns)

        symbols = sorted(set(t["symbol"] for t in trades))
        equity_count = sum(
            1 for s, p in ledger.items()
            if p.get("instrument_type") == "EQUITY"
        )
        mf_count = sum(
            1 for s, p in ledger.items()
            if p.get("instrument_type") == "MF"
        )

        return {
            "client_name": client_name,
            "trade_count": len(trades),
            "date_range": {
                "first": str(trades[0]["date"]) if trades else None,
                "last": str(trades[-1]["date"]) if trades else None,
            },
            "symbols": symbols,
            "equity_positions": equity_count,
            "mf_positions": mf_count,
            "capital_deployed": sum(
                abs(cf["amount"]) for cf in cash_flows if cf["amount"] < 0
            ),
            "sip_patterns_detected": len(sip_patterns),
            "warnings": warnings,
            "status": "ingested",
        }
    except Exception as e:
        return {"error": str(e), "client_name": client_name}


# ---------------------------------------------------------------------------
# Price fetching (network boundary — mockable seam for tests)
# ---------------------------------------------------------------------------

def _fetch_current_prices(
    positions: dict,
) -> tuple[dict[str, float], dict[str, str], list[str]]:
    """Fetch current prices and sector map for all held positions.

    Returns:
        (current_prices, sector_map, errors) where:
        - current_prices: {symbol: price_or_nav}
        - sector_map: {symbol: sector_name} (equity only)
        - errors: list of error messages for failed fetches
    """
    import yfinance as yf
    from shared.mf_client import get_nav_series

    current_prices: dict[str, float] = {}
    sector_map: dict[str, str] = {}
    errors: list[str] = []

    for sym, pos in positions.items():
        if pos["instrument_type"] == "EQUITY":
            try:
                ticker_str = nse_to_yf(sym)
                data = yf_latest(ticker_str)
                if data.get("error"):
                    errors.append(f"{sym}: yf_latest failed — {data['error']}")
                elif data.get("price") is not None:
                    current_prices[sym] = data["price"]
                else:
                    errors.append(f"{sym}: yf_latest returned no price")

                session = get_yf_session()
                t = yf.Ticker(ticker_str, session=session) if session else yf.Ticker(ticker_str)
                info = t.info or {}
                sector_map[sym] = info.get("sector", "Unknown")
            except Exception as e:
                errors.append(f"{sym}: equity price fetch error — {e}")
                sector_map[sym] = "Unknown"

        elif pos["instrument_type"] == "MF":
            try:
                today = date.today()
                series = get_nav_series(
                    sym, today - timedelta(days=7), today,
                )
                if series:
                    latest_date = max(series.keys())
                    current_prices[sym] = series[latest_date]
                else:
                    errors.append(f"{sym}: get_nav_series returned empty")
            except Exception as e:
                errors.append(f"{sym}: MF NAV fetch error — {e}")

    return current_prices, sector_map, errors


# ---------------------------------------------------------------------------
# get_portfolio_overview
# ---------------------------------------------------------------------------

def get_portfolio_overview(client_name: str) -> dict:
    """
    Compute portfolio overview — holdings, returns, allocation, turnover.

    Requires ingest_client_trades to have been called first.
    Fetches current prices, computes returns and metrics.
    """
    cdir = PORTFOLIO_DIR / client_name
    if not cdir.exists():
        return {
            "error": f"No data for client '{client_name}'. "
                     "Run ingest_trades first.",
        }

    try:
        trades = _load_trades(cdir / "trades.json")
        positions = _load_json(cdir / "positions.json")
        as_of = date.today()

        current_prices, sector_map, price_errors = _fetch_current_prices(positions)

        returns = compute_returns(trades, current_prices, as_of)

        holdings_for_alloc: dict[str, dict] = {}
        for p in returns["positions"]:
            holdings_for_alloc[p["symbol"]] = {
                "value": p["current_value"],
                "instrument_type": p["instrument_type"],
            }
        allocation = compute_sector_allocation(holdings_for_alloc, sector_map)

        avg_value = (returns["total_invested"] + returns["current_value"]) / 2
        turnover = compute_turnover(trades, avg_value)

        tax_drag = compute_tax_drag(trades)

        result = {
            "client_name": client_name,
            "as_of": str(as_of),
            "holdings": returns["positions"],
            "portfolio_xirr": returns["portfolio_xirr"],
            "total_invested": returns["total_invested"],
            "current_value": returns["current_value"],
            "absolute_return": returns["absolute_return"],
            "return_pct": returns["return_pct"],
            "total_brokerage": returns["total_brokerage"],
            "sector_allocation": allocation["sectors"],
            "type_allocation": allocation["types"],
            "turnover_ratio": turnover,
            "tax_drag": tax_drag,
        }
        if price_errors:
            result["price_fetch_errors"] = price_errors

        _save_json(cdir / "overview.json", result)
        return result

    except Exception as e:
        return {"error": str(e), "client_name": client_name}
