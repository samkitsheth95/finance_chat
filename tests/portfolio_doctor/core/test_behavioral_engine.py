import pytest
from datetime import date
from portfolio_doctor.core.behavioral_engine import (
    detect_panic_selling,
    detect_fomo_buying,
    detect_disposition_effect,
    detect_overtrading,
    detect_concentration_risk,
    detect_sip_discipline,
    detect_herd_behavior,
    detect_anchoring_bias,
    detect_regular_plan_waste,
    compute_behavioral_composite,
)


DETECTOR_KEYS = {"pattern", "score", "severity", "instances", "cost_estimate", "evidence_summary"}


def _assert_detector_shape(result: dict):
    """Every detector must return the standard result dict."""
    assert set(result.keys()) >= DETECTOR_KEYS
    assert -1.0 <= result["score"] <= 1.0
    assert result["severity"] in ("low", "medium", "high")
    assert isinstance(result["instances"], list)
    assert isinstance(result["cost_estimate"], (int, float))


# ── Panic Selling ─────────────────────────────────────────────────────────

class TestPanicSelling:
    def test_detects_sell_during_crash(self):
        trades = [
            {"date": date(2020, 1, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1500, "instrument_type": "EQUITY",
             "amount": 75000},
            {"date": date(2020, 3, 23), "symbol": "RELIANCE", "action": "SELL",
             "quantity": 50, "price": 900, "instrument_type": "EQUITY",
             "amount": 45000},
        ]
        nifty_data = {
            "2020-01-01": 12200, "2020-01-15": 12300, "2020-02-01": 12000,
            "2020-02-20": 12200, "2020-03-01": 11200, "2020-03-15": 9500,
            "2020-03-23": 7610,
        }
        result = detect_panic_selling(trades, nifty_data)
        _assert_detector_shape(result)
        assert result["pattern"] == "panic_selling"
        assert result["score"] < 0
        assert len(result["instances"]) >= 1

    def test_no_panic_in_normal_market(self):
        trades = [
            {"date": date(2020, 1, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1500, "instrument_type": "EQUITY",
             "amount": 75000},
            {"date": date(2020, 6, 1), "symbol": "RELIANCE", "action": "SELL",
             "quantity": 50, "price": 1600, "instrument_type": "EQUITY",
             "amount": 80000},
        ]
        nifty_data = {
            "2020-01-01": 12200, "2020-03-01": 12100,
            "2020-06-01": 12500,
        }
        result = detect_panic_selling(trades, nifty_data)
        _assert_detector_shape(result)
        assert len(result["instances"]) == 0
        assert result["score"] >= 0

    def test_ignores_buy_trades(self):
        trades = [
            {"date": date(2020, 3, 23), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 900, "instrument_type": "EQUITY",
             "amount": 45000},
        ]
        nifty_data = {"2020-01-01": 12200, "2020-03-23": 7610}
        result = detect_panic_selling(trades, nifty_data)
        assert len(result["instances"]) == 0


# ── FOMO Buying ───────────────────────────────────────────────────────────

class TestFomoBuying:
    def test_detects_buy_near_nifty_peak(self):
        trades = [
            {"date": date(2021, 10, 18), "symbol": "TCS", "action": "BUY",
             "quantity": 10, "price": 3800, "instrument_type": "EQUITY",
             "amount": 38000},
        ]
        nifty_data = {
            "2021-09-01": 17300, "2021-09-15": 17600,
            "2021-10-01": 17800, "2021-10-18": 18400,
        }
        result = detect_fomo_buying(trades, nifty_data)
        _assert_detector_shape(result)
        assert result["pattern"] == "fomo_buying"
        assert result["score"] <= 0
        assert len(result["instances"]) >= 1

    def test_no_fomo_in_down_market(self):
        trades = [
            {"date": date(2020, 4, 1), "symbol": "TCS", "action": "BUY",
             "quantity": 10, "price": 1800, "instrument_type": "EQUITY",
             "amount": 18000},
        ]
        nifty_data = {
            "2020-01-01": 12200, "2020-02-01": 12000,
            "2020-03-23": 7610, "2020-04-01": 8500,
        }
        result = detect_fomo_buying(trades, nifty_data)
        _assert_detector_shape(result)
        assert len(result["instances"]) == 0

    def test_ignores_sell_trades(self):
        trades = [
            {"date": date(2021, 10, 18), "symbol": "TCS", "action": "SELL",
             "quantity": 10, "price": 3800, "instrument_type": "EQUITY",
             "amount": 38000},
        ]
        nifty_data = {"2021-10-18": 18400}
        result = detect_fomo_buying(trades, nifty_data)
        assert len(result["instances"]) == 0


# ── Disposition Effect ────────────────────────────────────────────────────

class TestDispositionEffect:
    def test_detects_holding_losers_longer(self):
        trades = [
            {"date": date(2019, 1, 1), "symbol": "WINNER", "action": "BUY",
             "quantity": 10, "price": 100, "instrument_type": "EQUITY",
             "amount": 1000},
            {"date": date(2019, 3, 1), "symbol": "WINNER", "action": "SELL",
             "quantity": 10, "price": 130, "instrument_type": "EQUITY",
             "amount": 1300},
            {"date": date(2019, 1, 1), "symbol": "LOSER", "action": "BUY",
             "quantity": 10, "price": 100, "instrument_type": "EQUITY",
             "amount": 1000},
            {"date": date(2020, 6, 1), "symbol": "LOSER", "action": "SELL",
             "quantity": 10, "price": 80, "instrument_type": "EQUITY",
             "amount": 800},
        ]
        result = detect_disposition_effect(trades)
        _assert_detector_shape(result)
        assert result["pattern"] == "disposition_effect"
        assert result["score"] < 0

    def test_no_disposition_when_balanced(self):
        trades = [
            {"date": date(2019, 1, 1), "symbol": "A", "action": "BUY",
             "quantity": 10, "price": 100, "instrument_type": "EQUITY",
             "amount": 1000},
            {"date": date(2019, 7, 1), "symbol": "A", "action": "SELL",
             "quantity": 10, "price": 130, "instrument_type": "EQUITY",
             "amount": 1300},
            {"date": date(2019, 1, 1), "symbol": "B", "action": "BUY",
             "quantity": 10, "price": 100, "instrument_type": "EQUITY",
             "amount": 1000},
            {"date": date(2019, 6, 15), "symbol": "B", "action": "SELL",
             "quantity": 10, "price": 80, "instrument_type": "EQUITY",
             "amount": 800},
        ]
        result = detect_disposition_effect(trades)
        _assert_detector_shape(result)
        assert result["score"] >= -0.1

    def test_needs_both_winners_and_losers(self):
        trades = [
            {"date": date(2019, 1, 1), "symbol": "A", "action": "BUY",
             "quantity": 10, "price": 100, "instrument_type": "EQUITY",
             "amount": 1000},
            {"date": date(2019, 7, 1), "symbol": "A", "action": "SELL",
             "quantity": 10, "price": 130, "instrument_type": "EQUITY",
             "amount": 1300},
        ]
        result = detect_disposition_effect(trades)
        assert result["score"] == 0.0


# ── Overtrading ───────────────────────────────────────────────────────────

class TestOvertrading:
    def test_detects_frequent_round_trips(self):
        trades = []
        for i in range(6):
            d_buy = date(2020, 1, 1 + i * 5)
            d_sell = date(2020, 1, 3 + i * 5)
            trades.append({"date": d_buy, "symbol": "RELIANCE", "action": "BUY",
                           "quantity": 10, "price": 1500,
                           "instrument_type": "EQUITY", "amount": 15000})
            trades.append({"date": d_sell, "symbol": "RELIANCE", "action": "SELL",
                           "quantity": 10, "price": 1510,
                           "instrument_type": "EQUITY", "amount": 15100})
        result = detect_overtrading(trades, total_days=30)
        _assert_detector_shape(result)
        assert result["pattern"] == "overtrading"
        assert result["score"] < 0

    def test_no_overtrading_with_few_trades(self):
        trades = [
            {"date": date(2020, 1, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1500, "instrument_type": "EQUITY",
             "amount": 75000},
            {"date": date(2020, 12, 1), "symbol": "RELIANCE", "action": "SELL",
             "quantity": 50, "price": 1800, "instrument_type": "EQUITY",
             "amount": 90000},
        ]
        result = detect_overtrading(trades, total_days=365)
        _assert_detector_shape(result)
        assert result["score"] >= -0.1

    def test_counts_round_trips(self):
        trades = [
            {"date": date(2020, 1, 1), "symbol": "A", "action": "BUY",
             "quantity": 10, "price": 100, "instrument_type": "EQUITY",
             "amount": 1000},
            {"date": date(2020, 1, 10), "symbol": "A", "action": "SELL",
             "quantity": 10, "price": 105, "instrument_type": "EQUITY",
             "amount": 1050},
            {"date": date(2020, 1, 15), "symbol": "A", "action": "BUY",
             "quantity": 10, "price": 103, "instrument_type": "EQUITY",
             "amount": 1030},
            {"date": date(2020, 1, 25), "symbol": "A", "action": "SELL",
             "quantity": 10, "price": 108, "instrument_type": "EQUITY",
             "amount": 1080},
        ]
        result = detect_overtrading(trades, total_days=30)
        assert result["instances"]


# ── Concentration Risk ────────────────────────────────────────────────────

class TestConcentrationRisk:
    def test_detects_single_stock_overweight(self):
        holdings = {
            "RELIANCE": {"value": 800000},
            "TCS": {"value": 100000},
            "INFY": {"value": 100000},
        }
        result = detect_concentration_risk(holdings, total_value=1000000)
        _assert_detector_shape(result)
        assert result["pattern"] == "concentration_risk"
        assert result["score"] < 0
        assert result["severity"] in ("medium", "high")

    def test_well_diversified_is_neutral(self):
        holdings = {
            "RELIANCE": {"value": 200000},
            "TCS": {"value": 200000},
            "INFY": {"value": 200000},
            "HDFC": {"value": 200000},
            "ITC": {"value": 200000},
        }
        result = detect_concentration_risk(holdings, total_value=1000000)
        _assert_detector_shape(result)
        assert result["score"] >= -0.1

    def test_empty_holdings(self):
        result = detect_concentration_risk({}, total_value=0)
        _assert_detector_shape(result)
        assert result["score"] == 0.0


# ── Herd Behavior ─────────────────────────────────────────────────────────

class TestHerdBehavior:
    def test_detects_buying_after_rally(self):
        trades = [
            {"date": date(2020, 3, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 10, "price": 1800, "instrument_type": "EQUITY",
             "amount": 18000},
        ]
        stock_price_data = {
            "RELIANCE": {
                "2020-01-15": 1200, "2020-02-01": 1350,
                "2020-02-15": 1500, "2020-03-01": 1800,
            }
        }
        result = detect_herd_behavior(trades, stock_price_data)
        _assert_detector_shape(result)
        assert result["pattern"] == "herd_behavior"
        assert result["score"] <= 0
        assert len(result["instances"]) >= 1

    def test_no_herd_for_flat_stock(self):
        trades = [
            {"date": date(2020, 3, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 10, "price": 1200, "instrument_type": "EQUITY",
             "amount": 12000},
        ]
        stock_price_data = {
            "RELIANCE": {
                "2020-01-15": 1180, "2020-02-01": 1190,
                "2020-02-15": 1195, "2020-03-01": 1200,
            }
        }
        result = detect_herd_behavior(trades, stock_price_data)
        _assert_detector_shape(result)
        assert len(result["instances"]) == 0

    def test_ignores_sell_trades(self):
        trades = [
            {"date": date(2020, 3, 1), "symbol": "RELIANCE", "action": "SELL",
             "quantity": 10, "price": 1800, "instrument_type": "EQUITY",
             "amount": 18000},
        ]
        result = detect_herd_behavior(trades, {})
        assert len(result["instances"]) == 0


# ── Anchoring Bias ────────────────────────────────────────────────────────

class TestAnchoringBias:
    def test_detects_breakeven_sells(self):
        trades = [
            {"date": date(2020, 1, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1500, "instrument_type": "EQUITY",
             "amount": 75000},
            {"date": date(2020, 6, 1), "symbol": "RELIANCE", "action": "SELL",
             "quantity": 50, "price": 1510, "instrument_type": "EQUITY",
             "amount": 75500},
        ]
        result = detect_anchoring_bias(trades)
        _assert_detector_shape(result)
        assert result["pattern"] == "anchoring_bias"
        assert result["score"] <= 0
        assert len(result["instances"]) >= 1

    def test_no_anchoring_on_clear_profit(self):
        trades = [
            {"date": date(2020, 1, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1500, "instrument_type": "EQUITY",
             "amount": 75000},
            {"date": date(2020, 6, 1), "symbol": "RELIANCE", "action": "SELL",
             "quantity": 50, "price": 1800, "instrument_type": "EQUITY",
             "amount": 90000},
        ]
        result = detect_anchoring_bias(trades)
        _assert_detector_shape(result)
        assert len(result["instances"]) == 0

    def test_no_anchoring_without_sells(self):
        trades = [
            {"date": date(2020, 1, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1500, "instrument_type": "EQUITY",
             "amount": 75000},
        ]
        result = detect_anchoring_bias(trades)
        assert result["score"] == 0.0


# ── SIP Discipline ────────────────────────────────────────────────────────

class TestSipDiscipline:
    def test_maintained_through_crash_is_positive(self):
        sip_patterns = [
            {"scheme_code": "119551", "start_date": date(2019, 6, 1),
             "end_date": date(2020, 12, 1), "total_sips": 18,
             "scheme_name": "PPFAS Flexi Cap"},
        ]
        nifty_data = {
            "2019-06-01": 11900, "2019-09-01": 11000, "2019-12-01": 12000,
            "2020-01-01": 12200, "2020-03-01": 11000, "2020-03-23": 7610,
            "2020-06-01": 10000, "2020-09-01": 11500, "2020-12-01": 13500,
        }
        result = detect_sip_discipline(sip_patterns, nifty_data)
        _assert_detector_shape(result)
        assert result["pattern"] == "sip_discipline"
        assert result["score"] > 0

    def test_no_sips_is_neutral(self):
        result = detect_sip_discipline([], {})
        _assert_detector_shape(result)
        assert result["score"] == 0.0

    def test_short_sip_stopped_before_crash(self):
        sip_patterns = [
            {"scheme_code": "119551", "start_date": date(2019, 10, 1),
             "end_date": date(2020, 1, 1), "total_sips": 3,
             "scheme_name": "PPFAS Flexi Cap"},
        ]
        nifty_data = {
            "2019-10-01": 11600, "2020-01-01": 12200,
            "2020-03-23": 7610, "2020-06-01": 10000,
        }
        result = detect_sip_discipline(sip_patterns, nifty_data)
        assert result["score"] <= 0


# ── Regular Plan Waste ────────────────────────────────────────────────────

class TestRegularPlanWaste:
    def test_detects_regular_plan_indicator(self):
        trades = [
            {"date": date(2020, 1, 1), "instrument_type": "MF", "symbol": "100123",
             "scheme_name": "HDFC Large Cap Fund - Regular Growth",
             "action": "SIP", "quantity": 100, "price": 50, "amount": 5000},
        ]
        result = detect_regular_plan_waste(trades)
        _assert_detector_shape(result)
        assert result["pattern"] == "regular_plan_waste"
        assert result["score"] <= 0
        assert result["cost_estimate"] > 0

    def test_no_waste_for_direct_plan(self):
        trades = [
            {"date": date(2020, 1, 1), "instrument_type": "MF", "symbol": "119551",
             "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Growth",
             "action": "SIP", "quantity": 100, "price": 50, "amount": 5000},
        ]
        result = detect_regular_plan_waste(trades)
        _assert_detector_shape(result)
        assert len(result["instances"]) == 0

    def test_ignores_equity_trades(self):
        trades = [
            {"date": date(2020, 1, 1), "instrument_type": "EQUITY",
             "symbol": "RELIANCE", "action": "BUY", "quantity": 50,
             "price": 1500, "amount": 75000},
        ]
        result = detect_regular_plan_waste(trades)
        assert len(result["instances"]) == 0


# ── Behavioral Composite ─────────────────────────────────────────────────

class TestBehavioralComposite:
    def test_returns_weighted_score(self):
        detector_results = [
            {"pattern": "panic_selling", "score": -0.5, "severity": "medium",
             "instances": [], "cost_estimate": 10000, "evidence_summary": "sold in crash"},
            {"pattern": "fomo_buying", "score": 0.0, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
            {"pattern": "disposition_effect", "score": -0.3, "severity": "medium",
             "instances": [], "cost_estimate": 5000, "evidence_summary": ""},
            {"pattern": "overtrading", "score": -0.2, "severity": "low",
             "instances": [], "cost_estimate": 2000, "evidence_summary": ""},
            {"pattern": "concentration_risk", "score": 0.0, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
            {"pattern": "herd_behavior", "score": 0.0, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
            {"pattern": "anchoring_bias", "score": 0.0, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
            {"pattern": "sip_discipline", "score": 0.8, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
            {"pattern": "regular_plan_waste", "score": 0.0, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
        ]
        composite = compute_behavioral_composite(detector_results)
        assert -1.0 <= composite["composite_score"] <= 1.0
        assert "top_issues" in composite
        assert composite["top_issues"][0]["cost_estimate"] == 10000

    def test_composite_bounded(self):
        all_bad = [
            {"pattern": f"detector_{i}", "score": -1.0, "severity": "high",
             "instances": [], "cost_estimate": 50000, "evidence_summary": ""}
            for i in range(9)
        ]
        for i, name in enumerate([
            "panic_selling", "fomo_buying", "disposition_effect",
            "overtrading", "concentration_risk", "herd_behavior",
            "anchoring_bias", "sip_discipline", "regular_plan_waste",
        ]):
            all_bad[i]["pattern"] = name
        composite = compute_behavioral_composite(all_bad)
        assert composite["composite_score"] >= -1.0
        assert composite["composite_score"] <= 1.0

    def test_composite_severity_mapping(self):
        neutral = [
            {"pattern": name, "score": 0.0, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""}
            for name in [
                "panic_selling", "fomo_buying", "disposition_effect",
                "overtrading", "concentration_risk", "herd_behavior",
                "anchoring_bias", "sip_discipline", "regular_plan_waste",
            ]
        ]
        composite = compute_behavioral_composite(neutral)
        assert composite["severity"] == "low"

    def test_top_issues_sorted_by_cost(self):
        results = [
            {"pattern": "panic_selling", "score": -0.5, "severity": "medium",
             "instances": [], "cost_estimate": 5000, "evidence_summary": ""},
            {"pattern": "fomo_buying", "score": -0.3, "severity": "medium",
             "instances": [], "cost_estimate": 20000, "evidence_summary": ""},
            {"pattern": "disposition_effect", "score": -0.2, "severity": "low",
             "instances": [], "cost_estimate": 15000, "evidence_summary": ""},
            {"pattern": "overtrading", "score": 0.0, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
            {"pattern": "concentration_risk", "score": 0.0, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
            {"pattern": "herd_behavior", "score": 0.0, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
            {"pattern": "anchoring_bias", "score": 0.0, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
            {"pattern": "sip_discipline", "score": 0.0, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
            {"pattern": "regular_plan_waste", "score": 0.0, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
        ]
        composite = compute_behavioral_composite(results)
        costs = [i["cost_estimate"] for i in composite["top_issues"]]
        assert costs == sorted(costs, reverse=True)
