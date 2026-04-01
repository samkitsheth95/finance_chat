"""Tests for portfolio_doctor/tools/report_tools.py — action plan + full report."""
import json
from datetime import date
from pathlib import Path

import pytest

from portfolio_doctor.tools.report_tools import (
    build_action_plan,
    get_action_plan,
    get_full_report_data,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, default=str)


def _make_behavioral_audit():
    """Sample behavioral audit result with mix of negative and positive detectors."""
    return {
        "client_name": "test_client",
        "composite_score": -0.4,
        "severity": "medium",
        "total_estimated_cost": 55000,
        "detectors": [
            {"pattern": "panic_selling", "score": -0.7, "severity": "high",
             "cost_estimate": 45000, "instances": [
                 {"date": "2020-03-23", "symbol": "HDFCBANK", "action": "SELL",
                  "detail": "Sold during market crash"},
             ], "evidence_summary": "Sold during March 2020 crash"},
            {"pattern": "fomo_buying", "score": -0.5, "severity": "medium",
             "cost_estimate": 10000, "instances": [
                 {"date": "2021-10-15", "symbol": "RELIANCE", "action": "BUY",
                  "detail": "Bought near ATH"},
             ], "evidence_summary": "Bought near all-time high"},
            {"pattern": "sip_discipline", "score": 0.8, "severity": "low",
             "cost_estimate": 0, "instances": [],
             "evidence_summary": "SIPs maintained through crash"},
            {"pattern": "overtrading", "score": 0.3, "severity": "low",
             "cost_estimate": 0, "instances": [],
             "evidence_summary": "Trading frequency within normal range"},
            {"pattern": "disposition_effect", "score": -0.1, "severity": "low",
             "cost_estimate": 2000, "instances": [],
             "evidence_summary": "Minor tendency to sell winners early"},
            {"pattern": "concentration_risk", "score": 0.1, "severity": "low",
             "cost_estimate": 0, "instances": [],
             "evidence_summary": "Portfolio reasonably diversified"},
            {"pattern": "herd_behavior", "score": 0.0, "severity": "low",
             "cost_estimate": 0, "instances": [],
             "evidence_summary": "No significant herd behavior detected"},
            {"pattern": "anchoring_bias", "score": 0.0, "severity": "low",
             "cost_estimate": 0, "instances": [],
             "evidence_summary": "No significant anchoring detected"},
            {"pattern": "regular_plan_waste", "score": 0.0, "severity": "low",
             "cost_estimate": 0, "instances": [],
             "evidence_summary": "No regular plan holdings"},
        ],
        "top_issues": [
            {"pattern": "panic_selling", "cost_estimate": 45000},
            {"pattern": "fomo_buying", "cost_estimate": 10000},
            {"pattern": "disposition_effect", "cost_estimate": 2000},
        ],
    }


def _make_alternatives():
    """Sample alternatives result."""
    return {
        "client_name": "test_client",
        "actual": {"xirr": 0.12, "final_value": 200000, "total_invested": 150000},
        "scenarios": [
            {"scenario": "nifty_50_sip", "total_invested": 150000,
             "final_value": 248000, "xirr": 0.148,
             "vs_actual": {"value_difference": 48000, "return_difference_pct": 2.8,
                           "interpretation": "Nifty SIP would have earned more"}},
            {"scenario": "buy_and_hold", "total_invested": 150000,
             "final_value": 230000, "xirr": 0.138,
             "vs_actual": {"value_difference": 30000, "return_difference_pct": 1.8,
                           "interpretation": "Buy-and-hold would have earned more"}},
            {"scenario": "popular_mf_sip", "total_invested": 150000,
             "final_value": 190000, "xirr": 0.10,
             "vs_actual": {"value_difference": -10000, "return_difference_pct": -2.0,
                           "interpretation": "Actual portfolio outperformed"}},
        ],
        "scenario_count": 3,
    }


def _make_overview():
    """Sample portfolio overview result."""
    return {
        "client_name": "test_client",
        "as_of": "2024-01-15",
        "holdings": [
            {"symbol": "RELIANCE", "instrument_type": "EQUITY",
             "quantity": 50, "avg_cost": 1500.0, "current_price": 2500.0,
             "invested": 75000.0, "current_value": 125000.0,
             "return_pct": 66.67, "holding_days": 1461},
            {"symbol": "119551", "instrument_type": "MF",
             "quantity": 200.5, "avg_cost": 25.0, "current_nav": 37.5,
             "invested": 5012.5, "current_value": 7518.75,
             "return_pct": 50.0, "holding_days": 1466,
             "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Growth"},
        ],
        "portfolio_xirr": 0.12,
        "total_invested": 80012.5,
        "current_value": 132518.75,
        "absolute_return": 52506.25,
        "return_pct": 65.62,
        "total_brokerage": 40.0,
        "sector_allocation": {"Technology": 50.0, "Energy": 50.0},
        "type_allocation": {"EQUITY": 94.3, "MF": 5.7},
        "turnover_ratio": 0.15,
        "tax_drag": {"stcg_tax": 2000.0, "ltcg_tax": 1000.0, "total_tax_drag": 3000.0},
    }


def _setup_full_client(portfolio_dir, client_name="test_client"):
    """Pre-populate a client directory with all cached data files."""
    cdir = portfolio_dir / client_name
    cdir.mkdir(parents=True, exist_ok=True)

    trades = [
        {"date": "2020-01-15", "instrument_type": "EQUITY", "symbol": "RELIANCE",
         "scheme_name": "", "action": "BUY", "quantity": 50, "price": 1500.0,
         "amount": 75000.0, "brokerage": 20.0, "notes": ""},
        {"date": "2020-01-10", "instrument_type": "MF", "symbol": "119551",
         "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Growth",
         "action": "SIP", "quantity": 200.5, "price": 25.0,
         "amount": 5012.5, "brokerage": 0, "notes": ""},
    ]
    cashflows = [
        {"date": "2020-01-10", "amount": -5012.5, "symbol": "119551", "action": "SIP"},
        {"date": "2020-01-15", "amount": -75000.0, "symbol": "RELIANCE", "action": "BUY"},
    ]

    for name, data in [
        ("trades.json", trades),
        ("positions.json", {}),
        ("cashflows.json", cashflows),
        ("sip_patterns.json", []),
        ("overview.json", _make_overview()),
        ("behavioral_audit.json", _make_behavioral_audit()),
        ("alternatives.json", _make_alternatives()),
    ]:
        _write_json(cdir / name, data)

    return cdir


# ---------------------------------------------------------------------------
# build_action_plan
# ---------------------------------------------------------------------------

class TestBuildActionPlan:

    def test_generates_start_stop_keep(self):
        behavioral = {
            "composite_score": -0.4,
            "detectors": [
                {"pattern": "panic_selling", "score": -0.7, "severity": "high",
                 "cost_estimate": 45000,
                 "evidence_summary": "Sold during March 2020 crash"},
                {"pattern": "sip_discipline", "score": 0.8, "severity": "low",
                 "cost_estimate": 0,
                 "evidence_summary": "SIPs maintained through crash"},
            ],
        }
        alternatives = [
            {"scenario": "nifty_50_sip",
             "vs_actual": {"value_difference": 48000}},
        ]
        plan = build_action_plan(behavioral, alternatives)
        assert "start" in plan
        assert "stop" in plan
        assert "keep" in plan

    def test_start_from_outperforming_alternatives(self):
        behavioral = {"composite_score": 0.0, "detectors": []}
        alternatives = [
            {"scenario": "nifty_50_sip",
             "vs_actual": {"value_difference": 48000}},
            {"scenario": "buy_and_hold",
             "vs_actual": {"value_difference": 30000}},
            {"scenario": "popular_mf_sip",
             "vs_actual": {"value_difference": -5000}},
        ]
        plan = build_action_plan(behavioral, alternatives)
        start_scenarios = [s.get("scenario") for s in plan["start"] if "scenario" in s]
        assert "nifty_50_sip" in start_scenarios
        assert "buy_and_hold" in start_scenarios
        assert "popular_mf_sip" not in start_scenarios

    def test_stop_from_costly_behaviors(self):
        behavioral = {
            "composite_score": -0.5,
            "detectors": [
                {"pattern": "panic_selling", "score": -0.7, "severity": "high",
                 "cost_estimate": 45000, "evidence_summary": "Sold during crash"},
                {"pattern": "fomo_buying", "score": -0.3, "severity": "medium",
                 "cost_estimate": 10000, "evidence_summary": "Bought at peaks"},
            ],
        }
        plan = build_action_plan(behavioral, [])
        assert len(plan["stop"]) == 2
        assert plan["stop"][0]["cost_inr"] >= plan["stop"][1]["cost_inr"]

    def test_keep_positive_behaviors(self):
        behavioral = {
            "composite_score": 0.3,
            "detectors": [
                {"pattern": "sip_discipline", "score": 0.8, "severity": "low",
                 "cost_estimate": 0, "evidence_summary": "SIPs maintained"},
                {"pattern": "overtrading", "score": 0.5, "severity": "low",
                 "cost_estimate": 0, "evidence_summary": "Normal frequency"},
            ],
        }
        plan = build_action_plan(behavioral, [])
        assert len(plan["keep"]) == 2
        patterns = [k.get("pattern") for k in plan["keep"]]
        assert "sip_discipline" in patterns

    def test_empty_inputs_returns_empty_structure(self):
        plan = build_action_plan({"composite_score": 0.0, "detectors": []}, [])
        assert plan["start"] == []
        assert plan["stop"] == []
        assert plan["keep"] == []

    def test_stop_sorted_by_cost_descending(self):
        behavioral = {
            "composite_score": -0.5,
            "detectors": [
                {"pattern": "fomo_buying", "score": -0.4, "severity": "medium",
                 "cost_estimate": 5000, "evidence_summary": ""},
                {"pattern": "panic_selling", "score": -0.7, "severity": "high",
                 "cost_estimate": 45000, "evidence_summary": ""},
                {"pattern": "overtrading", "score": -0.3, "severity": "medium",
                 "cost_estimate": 15000, "evidence_summary": ""},
            ],
        }
        plan = build_action_plan(behavioral, [])
        costs = [item["cost_inr"] for item in plan["stop"]]
        assert costs == sorted(costs, reverse=True)


# ---------------------------------------------------------------------------
# get_action_plan
# ---------------------------------------------------------------------------

class TestGetActionPlan:

    def test_error_if_no_client_data(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "portfolio_doctor.tools.report_tools.PORTFOLIO_DIR",
            tmp_path / "portfolios",
        )
        result = get_action_plan("nonexistent")
        assert "error" in result

    def test_returns_start_stop_keep(self, tmp_path, monkeypatch):
        portfolio_dir = tmp_path / "portfolios"
        _setup_full_client(portfolio_dir)

        monkeypatch.setattr(
            "portfolio_doctor.tools.report_tools.PORTFOLIO_DIR", portfolio_dir,
        )

        result = get_action_plan("test_client")

        assert "start" in result
        assert "stop" in result
        assert "keep" in result
        assert result["client_name"] == "test_client"

    def test_saves_action_plan_json(self, tmp_path, monkeypatch):
        portfolio_dir = tmp_path / "portfolios"
        _setup_full_client(portfolio_dir)

        monkeypatch.setattr(
            "portfolio_doctor.tools.report_tools.PORTFOLIO_DIR", portfolio_dir,
        )

        get_action_plan("test_client")
        assert (portfolio_dir / "test_client" / "action_plan.json").exists()

    def test_stop_items_have_cost(self, tmp_path, monkeypatch):
        portfolio_dir = tmp_path / "portfolios"
        _setup_full_client(portfolio_dir)

        monkeypatch.setattr(
            "portfolio_doctor.tools.report_tools.PORTFOLIO_DIR", portfolio_dir,
        )

        result = get_action_plan("test_client")
        for item in result["stop"]:
            assert "cost_inr" in item
            assert item["cost_inr"] > 0


# ---------------------------------------------------------------------------
# get_full_report_data
# ---------------------------------------------------------------------------

class TestGetFullReportData:

    def test_error_if_no_client_data(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "portfolio_doctor.tools.report_tools.PORTFOLIO_DIR",
            tmp_path / "portfolios",
        )
        result = get_full_report_data("nonexistent")
        assert "error" in result

    def test_returns_all_sections(self, tmp_path, monkeypatch):
        portfolio_dir = tmp_path / "portfolios"
        _setup_full_client(portfolio_dir)

        monkeypatch.setattr(
            "portfolio_doctor.tools.report_tools.PORTFOLIO_DIR", portfolio_dir,
        )
        monkeypatch.setattr(
            "portfolio_doctor.tools.report_tools._fetch_equity_curve_data",
            lambda trades, cashflows, overview, end_date: (
                [{"date": "2020-01-15", "value": 75000.0}],
                [{"date": "2020-01-15", "value": 75000.0}],
            ),
        )

        result = get_full_report_data("test_client")

        for section in [
            "snapshot", "equity_curve", "behavioral",
            "alternatives", "allocation", "action_plan",
        ]:
            assert section in result, f"Missing section: {section}"

    def test_snapshot_fields(self, tmp_path, monkeypatch):
        portfolio_dir = tmp_path / "portfolios"
        _setup_full_client(portfolio_dir)

        monkeypatch.setattr(
            "portfolio_doctor.tools.report_tools.PORTFOLIO_DIR", portfolio_dir,
        )
        monkeypatch.setattr(
            "portfolio_doctor.tools.report_tools._fetch_equity_curve_data",
            lambda trades, cashflows, overview, end_date: ([], []),
        )

        result = get_full_report_data("test_client")
        snap = result["snapshot"]

        for key in [
            "client_name", "trading_since", "duration_years",
            "total_invested", "current_value", "xirr",
            "instrument_count", "behavioral_score_0_10",
            "turnover_ratio", "tax_drag_estimate",
        ]:
            assert key in snap, f"Missing snapshot key: {key}"

        assert snap["client_name"] == "test_client"
        assert snap["instrument_count"]["equity"] == 1
        assert snap["instrument_count"]["mf"] == 1

    def test_behavioral_scores_0_to_10(self, tmp_path, monkeypatch):
        portfolio_dir = tmp_path / "portfolios"
        _setup_full_client(portfolio_dir)

        monkeypatch.setattr(
            "portfolio_doctor.tools.report_tools.PORTFOLIO_DIR", portfolio_dir,
        )
        monkeypatch.setattr(
            "portfolio_doctor.tools.report_tools._fetch_equity_curve_data",
            lambda trades, cashflows, overview, end_date: ([], []),
        )

        result = get_full_report_data("test_client")
        radar = result["behavioral"]["radar"]

        for dim in [
            "timing_discipline", "holding_discipline", "diversification",
            "trading_discipline", "crowd_independence", "sip_consistency",
        ]:
            assert dim in radar, f"Missing radar dimension: {dim}"
            assert 0.0 <= radar[dim] <= 10.0, (
                f"Radar {dim}={radar[dim]} out of 0-10 range"
            )

        assert 0.0 <= result["snapshot"]["behavioral_score_0_10"] <= 10.0

    def test_alternatives_section_structure(self, tmp_path, monkeypatch):
        portfolio_dir = tmp_path / "portfolios"
        _setup_full_client(portfolio_dir)

        monkeypatch.setattr(
            "portfolio_doctor.tools.report_tools.PORTFOLIO_DIR", portfolio_dir,
        )
        monkeypatch.setattr(
            "portfolio_doctor.tools.report_tools._fetch_equity_curve_data",
            lambda trades, cashflows, overview, end_date: ([], []),
        )

        result = get_full_report_data("test_client")
        scenarios = result["alternatives"]["scenarios"]

        assert len(scenarios) == 3
        for s in scenarios:
            assert "scenario" in s
            assert "total_invested" in s
            assert "final_value" in s
            assert "xirr" in s
            assert "vs_actual_value_diff" in s

    def test_allocation_section_structure(self, tmp_path, monkeypatch):
        portfolio_dir = tmp_path / "portfolios"
        _setup_full_client(portfolio_dir)

        monkeypatch.setattr(
            "portfolio_doctor.tools.report_tools.PORTFOLIO_DIR", portfolio_dir,
        )
        monkeypatch.setattr(
            "portfolio_doctor.tools.report_tools._fetch_equity_curve_data",
            lambda trades, cashflows, overview, end_date: ([], []),
        )

        result = get_full_report_data("test_client")
        alloc = result["allocation"]

        assert "sectors" in alloc
        assert "types" in alloc
        assert "holdings" in alloc
        assert len(alloc["holdings"]) == 2

        for h in alloc["holdings"]:
            assert "symbol" in h
            assert "weight_pct" in h
            assert "return_pct" in h
            assert "holding_days" in h

    def test_saves_full_report_json(self, tmp_path, monkeypatch):
        portfolio_dir = tmp_path / "portfolios"
        _setup_full_client(portfolio_dir)

        monkeypatch.setattr(
            "portfolio_doctor.tools.report_tools.PORTFOLIO_DIR", portfolio_dir,
        )
        monkeypatch.setattr(
            "portfolio_doctor.tools.report_tools._fetch_equity_curve_data",
            lambda trades, cashflows, overview, end_date: ([], []),
        )

        get_full_report_data("test_client")
        assert (portfolio_dir / "test_client" / "full_report.json").exists()
