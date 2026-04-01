"""
Portfolio Doctor tools — behavioral audit.

Orchestrates behavioral_engine detectors. Fetches Nifty and stock price data
needed by detectors, saves results to data/portfolios/{client_name}/.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from portfolio_doctor.core.behavioral_engine import (
    detect_panic_selling,
    detect_fomo_buying,
    detect_disposition_effect,
    detect_overtrading,
    detect_concentration_risk,
    detect_herd_behavior,
    detect_anchoring_bias,
    detect_sip_discipline,
    detect_regular_plan_waste,
    compute_behavioral_composite,
)
from portfolio_doctor.tools.portfolio_tools import (
    PORTFOLIO_DIR,
    _load_json,
    _load_trades,
    _save_json,
    _fetch_current_prices,
)


# ---------------------------------------------------------------------------
# Network boundary — mockable seams
# ---------------------------------------------------------------------------

def _fetch_nifty_data(start_date: date, end_date: date) -> dict[str, float]:
    """Fetch Nifty 50 close series for behavioral detectors."""
    from shared.price_history import get_close_series
    return get_close_series("^NSEI", start_date, end_date)


def _fetch_stock_data(
    symbols: list[str], start_date: date, end_date: date,
) -> dict[str, dict[str, float]]:
    """Fetch per-stock close series for herd/DMA detection."""
    from shared.price_history import get_close_series
    result: dict[str, dict[str, float]] = {}
    for sym in symbols:
        series = get_close_series(sym, start_date, end_date)
        if series:
            result[sym] = series
    return result


# ---------------------------------------------------------------------------
# Date reconstruction helpers
# ---------------------------------------------------------------------------

def _load_sip_patterns(path: Path) -> list[dict]:
    """Load SIP patterns JSON and reconstruct date objects."""
    raw = _load_json(path)
    for sp in raw:
        for key in ("start_date", "end_date"):
            if isinstance(sp.get(key), str):
                y, m, d = sp[key].split("-")
                sp[key] = date(int(y), int(m), int(d))
    return raw


def _load_cashflows(path: Path) -> list[dict]:
    """Load cashflows JSON and reconstruct date objects."""
    raw = _load_json(path)
    for cf in raw:
        if isinstance(cf.get("date"), str):
            y, m, d = cf["date"].split("-")
            cf["date"] = date(int(y), int(m), int(d))
    return raw


# ---------------------------------------------------------------------------
# get_behavioral_audit
# ---------------------------------------------------------------------------

def get_behavioral_audit(client_name: str) -> dict:
    """
    Run all 9 behavioral detectors on a client's trading history.

    Requires ingest_client_trades to have been called first.
    Fetches Nifty and stock price data for context-dependent detectors.

    Returns all 9 detector results, composite score, and top 3 costliest
    behaviors with evidence.
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
        sip_patterns = _load_sip_patterns(cdir / "sip_patterns.json")

        if not trades:
            return {"error": "No trades found.", "client_name": client_name}

        dates = [t["date"] for t in trades]
        earliest = min(dates)
        latest = max(dates)
        total_days = (latest - earliest).days

        lookback_start = earliest - timedelta(days=365)
        end_date = date.today()

        nifty_data = _fetch_nifty_data(lookback_start, end_date)

        equity_symbols = sorted(set(
            t["symbol"] for t in trades if t["instrument_type"] == "EQUITY"
        ))
        stock_data = _fetch_stock_data(equity_symbols, lookback_start, end_date)

        current_prices, _ = _fetch_current_prices(positions)
        holdings_for_concentration: dict[str, dict] = {}
        total_value = 0.0
        for sym, pos in positions.items():
            if pos["instrument_type"] == "EQUITY":
                price = current_prices.get(sym, 0.0)
                value = pos["quantity"] * price
            elif pos["instrument_type"] == "MF":
                price = current_prices.get(sym, 0.0)
                qty = pos.get("total_quantity", 0.0)
                value = qty * price
            else:
                value = 0.0
            holdings_for_concentration[sym] = {"value": value}
            total_value += value

        detector_results = [
            detect_panic_selling(trades, nifty_data),
            detect_fomo_buying(trades, nifty_data, stock_dma_data=stock_data),
            detect_disposition_effect(trades),
            detect_overtrading(trades, total_days),
            detect_concentration_risk(holdings_for_concentration, total_value),
            detect_herd_behavior(trades, stock_data),
            detect_anchoring_bias(trades),
            detect_sip_discipline(sip_patterns, nifty_data),
            detect_regular_plan_waste(trades),
        ]

        composite = compute_behavioral_composite(detector_results)

        result = {
            "client_name": client_name,
            "detectors": detector_results,
            "composite_score": composite["composite_score"],
            "severity": composite["severity"],
            "top_issues": composite["top_issues"],
            "total_estimated_cost": composite["total_estimated_cost"],
        }

        _save_json(cdir / "behavioral_audit.json", result)
        return result

    except Exception as e:
        return {"error": str(e), "client_name": client_name}
