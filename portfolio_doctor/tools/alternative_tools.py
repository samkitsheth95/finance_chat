"""
Portfolio Doctor tools — alternative scenario comparisons.

Orchestrates alternatives_engine. Fetches MF NAV histories for Nifty proxy,
popular MF schemes, and debt fund. Saves results to
data/portfolios/{client_name}/.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from portfolio_doctor.core.alternatives_engine import (
    POPULAR_MF_SCHEMES,
    DEBT_SCHEME,
    run_all_scenarios,
)
from portfolio_doctor.tools.portfolio_tools import (
    PORTFOLIO_DIR,
    _load_json,
    _load_trades,
    _save_json,
    _fetch_current_prices,
    get_portfolio_overview,
)

NIFTY_SCHEME = "120716"


# ---------------------------------------------------------------------------
# Network boundary — mockable seams
# ---------------------------------------------------------------------------

def _fetch_scheme_navs(
    scheme_codes: list[str], start_date: date, end_date: date,
) -> dict[str, dict[str, float]]:
    """Fetch NAV history for multiple MF schemes.

    Returns {scheme_code: {date_str: nav}}.
    """
    from shared.mf_client import get_nav_series
    result: dict[str, dict[str, float]] = {}
    for code in scheme_codes:
        series = get_nav_series(code, start_date, end_date)
        if series:
            result[code] = series
    return result


# ---------------------------------------------------------------------------
# Date reconstruction helper
# ---------------------------------------------------------------------------

def _load_cashflows(path: Path) -> list[dict]:
    """Load cashflows JSON and reconstruct date objects."""
    raw = _load_json(path)
    for cf in raw:
        if isinstance(cf.get("date"), str):
            y, m, d = cf["date"].split("-")
            cf["date"] = date(int(y), int(m), int(d))
    return raw


# ---------------------------------------------------------------------------
# get_alternative_scenarios
# ---------------------------------------------------------------------------

def get_alternative_scenarios(client_name: str) -> dict:
    """
    Compare client's actual returns against 5 alternative strategies.

    Requires ingest_client_trades to have been called first.
    Loads or computes portfolio_overview for actual return data.
    Fetches MF NAV histories for Nifty proxy, popular schemes, and debt fund.

    Returns all scenario comparisons with vs_actual analysis.
    """
    cdir = PORTFOLIO_DIR / client_name
    if not cdir.exists():
        return {
            "error": f"No data for client '{client_name}'. "
                     "Run ingest_trades first.",
        }

    try:
        trades = _load_trades(cdir / "trades.json")
        cash_flows = _load_cashflows(cdir / "cashflows.json")

        if not trades:
            return {"error": "No trades found.", "client_name": client_name}

        overview_path = cdir / "overview.json"
        if overview_path.exists():
            overview = _load_json(overview_path)
        else:
            overview = get_portfolio_overview(client_name)
            if "error" in overview:
                return overview

        actual_return = {
            "xirr": overview.get("portfolio_xirr", 0),
            "final_value": overview.get("current_value", 0),
            "total_invested": overview.get("total_invested", 0),
        }

        current_prices: dict[str, float] = {}
        for h in overview.get("holdings", []):
            sym = h["symbol"]
            if h.get("instrument_type") == "EQUITY":
                current_prices[sym] = h.get("current_price", 0.0)
            elif h.get("instrument_type") == "MF":
                current_prices[sym] = h.get("current_nav", 0.0)

        dates = [t["date"] for t in trades]
        earliest = min(dates)
        end_date = date.today()
        start_date = earliest - timedelta(days=30)

        all_schemes = [NIFTY_SCHEME] + POPULAR_MF_SCHEMES + [DEBT_SCHEME]
        unique_schemes = sorted(set(all_schemes))
        nav_data = _fetch_scheme_navs(unique_schemes, start_date, end_date)

        nifty_nav = nav_data.get(NIFTY_SCHEME, {})
        mf_navs = {
            code: nav_data[code]
            for code in POPULAR_MF_SCHEMES
            if code in nav_data
        }
        debt_nav = nav_data.get(DEBT_SCHEME)

        scenarios = run_all_scenarios(
            cash_flows=cash_flows,
            trades=trades,
            actual_return=actual_return,
            nifty_nav=nifty_nav,
            mf_navs=mf_navs,
            current_prices=current_prices,
            end_date=end_date,
            debt_nav=debt_nav,
        )

        result = {
            "client_name": client_name,
            "actual": actual_return,
            "scenarios": scenarios,
            "scenario_count": len(scenarios),
        }

        _save_json(cdir / "alternatives.json", result)
        return result

    except Exception as e:
        return {"error": str(e), "client_name": client_name}
