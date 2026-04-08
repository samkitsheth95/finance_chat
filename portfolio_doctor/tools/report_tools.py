"""
Portfolio Doctor tools — action plan and full report aggregation.

Builds Start/Stop/Keep recommendations from behavioral audit and alternative
scenario results. Aggregates all analysis into a single JSON blob matching the
canvas schema (spec §5 sections A–F) for rendering.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from portfolio_doctor.tools.portfolio_tools import (
    PORTFOLIO_DIR,
    _load_json,
    _load_trades,
    _save_json,
)


# ---------------------------------------------------------------------------
# Recommendation templates
# ---------------------------------------------------------------------------

_SCENARIO_ACTIONS: dict[str, str] = {
    "nifty_50_sip": "Start a Nifty 50 index SIP for systematic long-term growth",
    "buy_and_hold": "Adopt a buy-and-hold approach — avoid selling during drawdowns",
    "popular_mf_sip": "Consider a diversified equity mutual fund SIP",
    "model_portfolio_70_30": (
        "Allocate to a 70/30 equity-debt model portfolio for balance"
    ),
    "no_reentry": "Avoid trading around positions — hold from initial entry",
}

_STOP_ACTIONS: dict[str, str] = {
    "panic_selling": (
        "Stop selling during market crashes — use rules-based exit criteria"
    ),
    "fomo_buying": "Stop buying at market peaks — use SIP or staggered entry",
    "disposition_effect": (
        "Stop selling winners early while holding losers — review on fundamentals"
    ),
    "overtrading": "Reduce trading frequency — excessive churning erodes returns",
    "concentration_risk": (
        "Reduce single-stock concentration — cap at 15-20% per position"
    ),
    "herd_behavior": "Avoid chasing stocks that already rallied 30%+ in a month",
    "anchoring_bias": (
        "Stop anchoring to buy price — evaluate on current fundamentals"
    ),
    "regular_plan_waste": (
        "Switch from Regular to Direct mutual fund plans to save on commissions"
    ),
}

_KEEP_ACTIONS: dict[str, str] = {
    "sip_discipline": (
        "Keep maintaining SIP discipline — consistency compounds over time"
    ),
    "panic_selling": "Keep staying calm during market crashes",
    "fomo_buying": "Keep avoiding peak-buying — disciplined entry approach",
    "disposition_effect": "Keep balanced approach to winners and losers",
    "overtrading": "Keep trading frequency under control",
    "concentration_risk": "Keep portfolio well-diversified",
    "herd_behavior": "Keep making independent investment decisions",
    "anchoring_bias": (
        "Keep evaluating sell decisions on fundamentals, not purchase price"
    ),
    "regular_plan_waste": "Keep using Direct plans for mutual funds",
}

_RADAR_MAP: dict[str, str] = {
    "panic_selling": "timing_discipline",
    "fomo_buying": "timing_discipline",
    "disposition_effect": "holding_discipline",
    "concentration_risk": "diversification",
    "overtrading": "trading_discipline",
    "anchoring_bias": "trading_discipline",
    "herd_behavior": "crowd_independence",
    "sip_discipline": "sip_consistency",
    "regular_plan_waste": "sip_consistency",
}


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
# Score transform
# ---------------------------------------------------------------------------

def _score_to_0_10(score: float) -> float:
    """Transform -1.0..+1.0 internal score to 0-10 display scale."""
    return round((score + 1.0) * 5.0, 1)


# ---------------------------------------------------------------------------
# build_action_plan  (pure logic — no I/O)
# ---------------------------------------------------------------------------

def build_action_plan(
    behavioral_results: dict,
    alternative_results: list[dict],
) -> dict:
    """Build Start/Stop/Keep action plan.

    Args:
        behavioral_results: Dict with ``detectors`` list and ``composite_score``.
        alternative_results: List of scenario dicts, each with ``vs_actual``.

    Returns:
        ``{"start": [...], "stop": [...], "keep": [...]}``.
    """
    start: list[dict] = []
    stop: list[dict] = []
    keep: list[dict] = []

    for scenario in alternative_results:
        vs = scenario.get("vs_actual", {})
        diff = vs.get("value_difference", 0)
        if diff > 0:
            name = scenario.get("scenario", "")
            action = _SCENARIO_ACTIONS.get(name, f"Consider {name} strategy")
            start.append({
                "action": action,
                "benefit_inr": diff,
                "scenario": name,
            })

    for det in behavioral_results.get("detectors", []):
        pattern = det.get("pattern", "")
        score = det.get("score", 0.0)
        cost = det.get("cost_estimate", 0)

        if score < -0.2 and cost > 0:
            action = _STOP_ACTIONS.get(pattern, f"Address {pattern}")
            stop.append({
                "action": action,
                "cost_inr": cost,
                "pattern": pattern,
                "severity": det.get("severity", "low"),
            })
        elif score > 0.2:
            action = _KEEP_ACTIONS.get(pattern, f"Continue {pattern}")
            keep.append({
                "action": action,
                "note": det.get("evidence_summary", ""),
                "pattern": pattern,
            })

    stop.sort(key=lambda x: x.get("cost_inr", 0), reverse=True)

    return {"start": start, "stop": stop, "keep": keep}


# ---------------------------------------------------------------------------
# get_action_plan  (I/O wrapper)
# ---------------------------------------------------------------------------

def get_action_plan(client_name: str) -> dict:
    """Load behavioral + alternative data and build an action plan.

    Loads cached JSON where available; calls upstream tools otherwise.
    """
    cdir = PORTFOLIO_DIR / client_name
    if not cdir.exists():
        return {
            "error": f"No data for client '{client_name}'. "
                     "Run ingest_trades first.",
        }

    try:
        behavioral_path = cdir / "behavioral_audit.json"
        if behavioral_path.exists():
            behavioral = _load_json(behavioral_path)
        else:
            from portfolio_doctor.tools.behavioral_tools import (
                get_behavioral_audit,
            )
            behavioral = get_behavioral_audit(client_name)
            if "error" in behavioral:
                return behavioral

        alternatives_path = cdir / "alternatives.json"
        if alternatives_path.exists():
            alternatives = _load_json(alternatives_path)
        else:
            from portfolio_doctor.tools.alternative_tools import (
                get_alternative_scenarios,
            )
            alternatives = get_alternative_scenarios(client_name)
            if "error" in alternatives:
                return alternatives

        plan = build_action_plan(
            behavioral, alternatives.get("scenarios", []),
        )

        result = {"client_name": client_name, **plan}

        _save_json(cdir / "action_plan.json", result)
        return result

    except Exception as e:
        return {"error": str(e), "client_name": client_name}


# ---------------------------------------------------------------------------
# Equity-curve network boundary (mockable seam)
# ---------------------------------------------------------------------------

def _fetch_equity_curve_data(
    trades: list[dict],
    cashflows: list[dict],
    overview: dict,
    end_date: date,
) -> tuple[list[dict], list[dict]]:
    """Fetch historical prices and compute equity-curve series.

    Returns ``(actual_curve, nifty_curve)`` where each entry is
    ``{"date": str, "value": float}``.
    """
    from shared.price_history import get_close_series
    from shared.mf_client import get_nav_series
    from portfolio_doctor.core.portfolio_engine import (
        compute_portfolio_value_series,
    )

    if not trades:
        return [], []

    dates = [
        t["date"] if isinstance(t["date"], date) else date.fromisoformat(t["date"])
        for t in trades
    ]
    start_date = min(dates)

    price_data: dict[str, dict[str, float]] = {}
    equity_symbols = sorted(set(
        t["symbol"] for t in trades if t["instrument_type"] == "EQUITY"
    ))
    for sym in equity_symbols:
        series = get_close_series(sym, start_date, end_date)
        if series:
            price_data[sym] = series

    mf_symbols = sorted(set(
        t["symbol"] for t in trades if t["instrument_type"] == "MF"
    ))
    for sym in mf_symbols:
        series = get_nav_series(sym, start_date, end_date)
        if series:
            price_data[sym] = series

    actual_curve = compute_portfolio_value_series(
        trades, price_data, start_date, end_date,
    )

    nifty_nav = get_nav_series("120716", start_date, end_date)
    nifty_curve = _compute_nifty_comparison(cashflows, nifty_nav)

    return actual_curve, nifty_curve


def _compute_nifty_comparison(
    cashflows: list[dict],
    nifty_nav: dict[str, float],
) -> list[dict]:
    """Compute Nifty SIP value series from cash flows + Nifty NAV history.

    For each buy cash flow, purchases units at the nearest available NAV on
    or after the flow date. Returns daily ``{"date": str, "value": float}``
    entries.
    """
    if not nifty_nav or not cashflows:
        return []

    sorted_dates = sorted(nifty_nav.keys())
    buy_flows = sorted(
        [cf for cf in cashflows if cf.get("amount", 0) < 0],
        key=lambda cf: str(cf["date"]),
    )

    unit_events: list[tuple[str, float]] = []
    for cf in buy_flows:
        cf_date = str(cf["date"])
        amount = abs(cf["amount"])
        nav_date = next((d for d in sorted_dates if d >= cf_date), None)
        if nav_date is None:
            nav_date = sorted_dates[-1]
        nav = nifty_nav[nav_date]
        if nav > 0:
            unit_events.append((cf_date, amount / nav))

    units = 0.0
    event_idx = 0
    curve: list[dict] = []
    for date_str in sorted_dates:
        while event_idx < len(unit_events):
            ev_date, ev_units = unit_events[event_idx]
            if ev_date <= date_str:
                units += ev_units
                event_idx += 1
            else:
                break
        if units > 0:
            curve.append({
                "date": date_str,
                "value": round(units * nifty_nav[date_str], 2),
            })

    return curve


# ---------------------------------------------------------------------------
# Full-report helpers (pure transforms)
# ---------------------------------------------------------------------------

def _build_snapshot(
    trades: list[dict], overview: dict, behavioral: dict,
) -> dict:
    """Section A — client snapshot header."""
    dates = [
        t["date"] if isinstance(t["date"], date)
        else date.fromisoformat(t["date"])
        for t in trades
    ]
    first_date = min(dates)
    duration_years = (date.today() - first_date).days / 365.25

    equity_count = sum(
        1 for h in overview.get("holdings", [])
        if h.get("instrument_type") == "EQUITY"
    )
    mf_count = sum(
        1 for h in overview.get("holdings", [])
        if h.get("instrument_type") == "MF"
    )

    tax_drag = overview.get("tax_drag", {})
    tax_est = tax_drag.get("total_tax_drag", 0.0) if isinstance(tax_drag, dict) else 0.0

    return {
        "client_name": overview.get("client_name", ""),
        "trading_since": str(first_date),
        "duration_years": round(duration_years, 1),
        "total_invested": overview.get("total_invested", 0.0),
        "current_value": overview.get("current_value", 0.0),
        "xirr": overview.get("portfolio_xirr", 0.0),
        "instrument_count": {"equity": equity_count, "mf": mf_count},
        "behavioral_score_0_10": _score_to_0_10(
            behavioral.get("composite_score", 0.0),
        ),
        "turnover_ratio": overview.get("turnover_ratio", 0.0),
        "tax_drag_estimate": tax_est,
    }


def _build_behavioral_radar(behavioral: dict) -> dict:
    """Section C radar — average per-dimension score on 0-10 scale."""
    dimensions: dict[str, list[float]] = {
        "timing_discipline": [],
        "holding_discipline": [],
        "diversification": [],
        "trading_discipline": [],
        "crowd_independence": [],
        "sip_consistency": [],
    }

    for det in behavioral.get("detectors", []):
        dim = _RADAR_MAP.get(det.get("pattern", ""))
        if dim and dim in dimensions:
            dimensions[dim].append(det.get("score", 0.0))

    return {
        dim: _score_to_0_10(sum(scores) / len(scores) if scores else 0.0)
        for dim, scores in dimensions.items()
    }


def _extract_behavioral_markers(behavioral: dict) -> list[dict]:
    """Section B markers — panic sells, FOMO buys, and good decisions."""
    type_map = {
        "panic_selling": "panic_sell",
        "fomo_buying": "fomo_buy",
    }
    markers: list[dict] = []
    for det in behavioral.get("detectors", []):
        mtype = type_map.get(det.get("pattern", ""))
        if not mtype:
            continue
        for inst in det.get("instances", []):
            markers.append({
                "date": inst.get("date", ""),
                "type": mtype,
                "symbol": inst.get("symbol", ""),
                "detail": inst.get(
                    "detail", det.get("evidence_summary", ""),
                ),
            })
    return markers


def _transform_top_issues(behavioral: dict) -> list[dict]:
    """Section C detail cards — top issues with 0-10 scores."""
    detectors_by_pattern = {
        d["pattern"]: d for d in behavioral.get("detectors", [])
    }
    issues: list[dict] = []
    for issue in behavioral.get("top_issues", []):
        pattern = issue.get("pattern", "")
        det = detectors_by_pattern.get(pattern, issue)
        issues.append({
            "pattern": pattern,
            "score_0_10": _score_to_0_10(det.get("score", 0.0)),
            "severity": det.get("severity", "low"),
            "cost_estimate": det.get("cost_estimate", 0),
            "instances": det.get("instances", []),
            "evidence_summary": det.get("evidence_summary", ""),
        })
    return issues


def _transform_scenarios(alternatives: dict) -> list[dict]:
    """Section D — flatten scenario data for canvas display."""
    result: list[dict] = []
    for s in alternatives.get("scenarios", []):
        vs = s.get("vs_actual", {})
        result.append({
            "scenario": s.get("scenario", ""),
            "total_invested": s.get("total_invested", 0),
            "final_value": s.get("final_value", 0),
            "xirr": s.get("xirr", 0),
            "vs_actual_value_diff": vs.get("value_difference", 0),
        })
    return result


def _build_allocation(overview: dict) -> dict:
    """Section E — sector, type, and per-holding weights."""
    sectors = [
        {"name": name, "weight_pct": weight}
        for name, weight in overview.get("sector_allocation", {}).items()
    ]
    types = [
        {"name": name, "weight_pct": weight}
        for name, weight in overview.get("type_allocation", {}).items()
    ]

    total_value = overview.get("current_value", 0.0)
    holdings: list[dict] = []
    for h in overview.get("holdings", []):
        val = h.get("current_value", 0.0)
        weight = (val / total_value * 100) if total_value > 0 else 0.0
        display_name = h.get("scheme_name") or h.get("symbol", "")
        is_mf = h.get("instrument_type") == "MF"
        qty = h.get("total_quantity") if is_mf else h.get("quantity", 0)
        price = h.get("current_nav") if is_mf else h.get("current_price", 0)
        avg = h.get("avg_cost", 0) or 0
        holdings.append({
            "symbol": h.get("symbol", ""),
            "display_name": display_name,
            "instrument_type": h.get("instrument_type", "EQUITY"),
            "weight_pct": round(weight, 1),
            "return_pct": h.get("return_pct", 0.0),
            "current_value": round(val, 2),
            "invested": round(h.get("invested", 0.0), 2),
            "qty": qty or 0,
            "avg_cost": round(avg, 2),
            "current_price": round(price or 0, 2),
        })

    return {"sectors": sectors, "types": types, "holdings": holdings}


# ---------------------------------------------------------------------------
# get_full_report_data  (aggregation + I/O)
# ---------------------------------------------------------------------------

def get_full_report_data(client_name: str) -> dict:
    """Aggregate all analysis into a single JSON blob for canvas rendering.

    Loads cached data where available; calls upstream tools for any pieces
    not yet computed.  Pre-transforms scores to the 0-10 display scale.
    """
    cdir = PORTFOLIO_DIR / client_name
    if not cdir.exists():
        return {
            "error": f"No data for client '{client_name}'. "
                     "Run ingest_trades first.",
        }

    try:
        trades = _load_trades(cdir / "trades.json")
        if not trades:
            return {"error": "No trades found.", "client_name": client_name}

        overview = _load_or_compute(
            cdir, "overview.json",
            lambda: _call_overview(client_name),
        )
        if "error" in overview:
            return overview

        behavioral = _load_or_compute(
            cdir, "behavioral_audit.json",
            lambda: _call_behavioral(client_name),
        )
        if "error" in behavioral:
            return behavioral

        alternatives = _load_or_compute(
            cdir, "alternatives.json",
            lambda: _call_alternatives(client_name),
        )
        if "error" in alternatives:
            return alternatives

        plan = build_action_plan(
            behavioral, alternatives.get("scenarios", []),
        )

        cashflows = _load_cashflows(cdir / "cashflows.json")
        end_date = date.today()
        actual_curve, nifty_curve = _fetch_equity_curve_data(
            trades, cashflows, overview, end_date,
        )

        markers = _extract_behavioral_markers(behavioral)

        result = {
            "client_name": client_name,
            "snapshot": _build_snapshot(trades, overview, behavioral),
            "equity_curve": {
                "actual": actual_curve,
                "nifty_sip": nifty_curve,
                "markers": markers,
            },
            "behavioral": {
                "radar": _build_behavioral_radar(behavioral),
                "top_issues": _transform_top_issues(behavioral),
            },
            "alternatives": {
                "scenarios": _transform_scenarios(alternatives),
            },
            "allocation": _build_allocation(overview),
            "action_plan": plan,
        }

        _save_json(cdir / "full_report.json", result)
        return result

    except Exception as e:
        return {"error": str(e), "client_name": client_name}


# ---------------------------------------------------------------------------
# Lazy-load helpers  (avoid circular imports)
# ---------------------------------------------------------------------------

def _load_or_compute(cdir: Path, filename: str, compute_fn) -> dict:
    """Return cached JSON if present, otherwise call *compute_fn*."""
    path = cdir / filename
    if path.exists():
        return _load_json(path)
    return compute_fn()


def _call_overview(client_name: str) -> dict:
    from portfolio_doctor.tools.portfolio_tools import get_portfolio_overview
    return get_portfolio_overview(client_name)


def _call_behavioral(client_name: str) -> dict:
    from portfolio_doctor.tools.behavioral_tools import get_behavioral_audit
    return get_behavioral_audit(client_name)


def _call_alternatives(client_name: str) -> dict:
    from portfolio_doctor.tools.alternative_tools import get_alternative_scenarios
    return get_alternative_scenarios(client_name)


# ---------------------------------------------------------------------------
# HTML Report Generator
# ---------------------------------------------------------------------------

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "report" / "template.html"


def _sample_curve(points: list[dict], max_points: int = 200) -> list[dict]:
    """Downsample equity-curve points for embedding in HTML."""
    if len(points) <= max_points:
        return points
    step = len(points) // max_points
    sampled = [points[i] for i in range(0, len(points), step)]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled


def generate_report_html(client_name: str) -> dict:
    """Generate a standalone HTML report for a client.

    Calls full_report_data if not cached, embeds the JSON into the HTML
    template, and saves to data/portfolios/{client_name}/report.html.

    Returns {"client_name", "path", "status"} or {"error"}.
    """
    import json as _json

    cdir = PORTFOLIO_DIR / client_name
    report_path = cdir / "full_report.json"

    if report_path.exists():
        report_data = _load_json(report_path)
    else:
        report_data = get_full_report_data(client_name)

    if "error" in report_data:
        return report_data

    ec = report_data.get("equity_curve", {})
    report_data["equity_curve"] = {
        "actual": _sample_curve(ec.get("actual", [])),
        "nifty_sip": _sample_curve(ec.get("nifty_sip", [])),
        "markers": ec.get("markers", []),
    }

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    data_script = (
        "<script>\nwindow.REPORT_DATA = "
        + _json.dumps(report_data, default=str)
        + ";\n</script>"
    )
    html = template.replace("<!--REPORT_DATA_PLACEHOLDER-->", data_script)

    out_path = cdir / "report.html"
    out_path.write_text(html, encoding="utf-8")

    return {
        "client_name": client_name,
        "path": str(out_path.resolve()),
        "status": "generated",
    }
