"""
Mutual Fund NAV history via mftool (AMFI public data).

Used by portfolio-doctor for:
  - MF position valuation (daily NAVs for per-lot tracking)
  - Alternative scenario modeling (index fund / popular MF SIPs)
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from mftool import Mftool as Mf

_mf = None


def _get_mf() -> Mf:
    global _mf
    if _mf is None:
        _mf = Mf()
    return _mf


def validate_scheme_code(scheme_code: str) -> dict:
    """
    Validate an AMFI scheme code exists and return scheme details.

    Returns:
        {"valid": True, "scheme_code": str, "scheme_name": str}
        or {"valid": False, "scheme_code": str, "error": str}
    """
    try:
        mf = _get_mf()
        details = mf.get_scheme_details(scheme_code)
        name = details.get("scheme_name", "")
        if not name:
            return {"valid": False, "scheme_code": scheme_code,
                    "error": "Scheme code not found in AMFI database"}
        return {"valid": True, "scheme_code": scheme_code, "scheme_name": name}
    except Exception as e:
        return {"valid": False, "scheme_code": scheme_code, "error": str(e)}


def fetch_nav_history(
    scheme_code: str,
    start_date: date,
    end_date: Optional[date] = None,
) -> dict:
    """
    Fetch daily NAV history for a mutual fund scheme.

    Args:
        scheme_code: AMFI scheme code (e.g. "119551")
        start_date: First date (inclusive)
        end_date: Last date (inclusive). Defaults to today.

    Returns:
        {
            "scheme_code": str,
            "navs": [{"date": "YYYY-MM-DD", "nav": float}, ...],
            "count": int,
        }
        On error: {"scheme_code": str, "error": str}
    """
    if end_date is None:
        end_date = date.today()

    try:
        mf = _get_mf()
        raw = mf.get_scheme_historical_nav(
            scheme_code,
            start_date.strftime("%d-%m-%Y"),
            end_date.strftime("%d-%m-%Y"),
        )

        data_list = raw.get("data", [])
        if not data_list:
            return {"scheme_code": scheme_code,
                    "error": f"No NAV data for scheme {scheme_code} in range"}

        navs = []
        for entry in data_list:
            try:
                d = entry["date"]
                parts = d.split("-")
                iso_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
                navs.append({
                    "date": iso_date,
                    "nav": round(float(entry["nav"]), 4),
                })
            except (KeyError, ValueError, IndexError):
                continue

        navs.sort(key=lambda x: x["date"])
        return {"scheme_code": scheme_code, "navs": navs, "count": len(navs)}
    except Exception as e:
        return {"scheme_code": scheme_code, "error": str(e)}


def get_nav_series(scheme_code: str, start_date: date, end_date: Optional[date] = None) -> dict[str, float]:
    """Convenience: return {date_str: nav} dict for quick lookups."""
    result = fetch_nav_history(scheme_code, start_date, end_date)
    if "error" in result:
        return {}
    return {n["date"]: n["nav"] for n in result["navs"]}
