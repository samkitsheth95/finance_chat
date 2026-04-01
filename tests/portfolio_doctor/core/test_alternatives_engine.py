import pytest
from datetime import date
from portfolio_doctor.core.alternatives_engine import (
    simulate_nifty_sip,
    simulate_buy_and_hold,
    simulate_mf_sip,
    simulate_model_portfolio,
    simulate_no_reentry,
    run_all_scenarios,
)


SCENARIO_KEYS = {"scenario", "total_invested", "final_value", "xirr", "absolute_return_pct"}


def _assert_scenario_shape(result: dict, expected_scenario: str):
    assert set(result.keys()) >= SCENARIO_KEYS
    assert result["scenario"] == expected_scenario
    assert isinstance(result["total_invested"], (int, float))
    assert isinstance(result["final_value"], (int, float))
    assert isinstance(result["xirr"], (int, float))


# ── Nifty 50 SIP ────────────────────────────────────────────────────────────


class TestNiftySip:
    def test_same_cash_flows_different_result(self):
        cash_flows = [
            {"date": date(2020, 1, 15), "amount": -75000},
            {"date": date(2020, 3, 20), "amount": -25500},
        ]
        nifty_nav = {
            "2020-01-15": 100.0, "2020-03-20": 80.0,
            "2026-03-31": 200.0,
        }
        result = simulate_nifty_sip(cash_flows, nifty_nav, end_date=date(2026, 3, 31))
        _assert_scenario_shape(result, "nifty_50_sip")
        assert result["total_invested"] == 100500
        assert result["final_value"] > 0

    def test_handles_missing_nav_dates(self):
        cash_flows = [{"date": date(2020, 1, 15), "amount": -50000}]
        nifty_nav = {"2020-01-16": 100.0, "2026-03-31": 200.0}
        result = simulate_nifty_sip(cash_flows, nifty_nav, end_date=date(2026, 3, 31))
        _assert_scenario_shape(result, "nifty_50_sip")
        assert result["final_value"] > 0

    def test_units_calculation(self):
        cash_flows = [
            {"date": date(2020, 1, 1), "amount": -10000},
        ]
        nifty_nav = {"2020-01-01": 100.0, "2026-03-31": 300.0}
        result = simulate_nifty_sip(cash_flows, nifty_nav, end_date=date(2026, 3, 31))
        assert result["total_invested"] == 10000
        assert abs(result["final_value"] - 30000) < 0.01

    def test_ignores_positive_cash_flows(self):
        cash_flows = [
            {"date": date(2020, 1, 1), "amount": -10000},
            {"date": date(2020, 6, 1), "amount": 5000},
        ]
        nifty_nav = {"2020-01-01": 100.0, "2026-03-31": 200.0}
        result = simulate_nifty_sip(cash_flows, nifty_nav, end_date=date(2026, 3, 31))
        assert result["total_invested"] == 10000


# ── Buy and Hold ─────────────────────────────────────────────────────────────


class TestBuyAndHold:
    def test_never_sells(self):
        trades = [
            {"date": date(2020, 1, 15), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1500, "instrument_type": "EQUITY"},
            {"date": date(2020, 6, 15), "symbol": "RELIANCE", "action": "SELL",
             "quantity": 50, "price": 1800, "instrument_type": "EQUITY"},
        ]
        current_prices = {"RELIANCE": 2500.0}
        result = simulate_buy_and_hold(trades, current_prices)
        _assert_scenario_shape(result, "buy_and_hold")
        assert result["final_value"] == 125000

    def test_multiple_buys_same_stock(self):
        trades = [
            {"date": date(2020, 1, 1), "symbol": "TCS", "action": "BUY",
             "quantity": 10, "price": 2000, "instrument_type": "EQUITY"},
            {"date": date(2020, 3, 1), "symbol": "TCS", "action": "BUY",
             "quantity": 20, "price": 1800, "instrument_type": "EQUITY"},
        ]
        current_prices = {"TCS": 3000.0}
        result = simulate_buy_and_hold(trades, current_prices)
        assert result["final_value"] == 30 * 3000

    def test_multiple_stocks(self):
        trades = [
            {"date": date(2020, 1, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 10, "price": 1500, "instrument_type": "EQUITY"},
            {"date": date(2020, 1, 1), "symbol": "TCS", "action": "BUY",
             "quantity": 5, "price": 2000, "instrument_type": "EQUITY"},
        ]
        current_prices = {"RELIANCE": 2000.0, "TCS": 3000.0}
        result = simulate_buy_and_hold(trades, current_prices)
        assert result["final_value"] == (10 * 2000) + (5 * 3000)

    def test_invested_is_sum_of_buys(self):
        trades = [
            {"date": date(2020, 1, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 10, "price": 1500, "instrument_type": "EQUITY"},
            {"date": date(2020, 6, 1), "symbol": "RELIANCE", "action": "SELL",
             "quantity": 10, "price": 1800, "instrument_type": "EQUITY"},
        ]
        current_prices = {"RELIANCE": 2000.0}
        result = simulate_buy_and_hold(trades, current_prices)
        assert result["total_invested"] == 15000


# ── MF SIP ───────────────────────────────────────────────────────────────────


class TestMfSip:
    def test_basic_mf_sip(self):
        cash_flows = [
            {"date": date(2020, 1, 10), "amount": -5000},
            {"date": date(2020, 2, 10), "amount": -5000},
        ]
        mf_nav = {"2020-01-10": 50.0, "2020-02-10": 48.0, "2026-03-31": 100.0}
        result = simulate_mf_sip(cash_flows, mf_nav, scheme_code="120716",
                                  end_date=date(2026, 3, 31))
        _assert_scenario_shape(result, "mf_sip_120716")
        assert result["total_invested"] == 10000
        assert result["final_value"] > 0

    def test_mf_sip_units_accumulate(self):
        cash_flows = [
            {"date": date(2020, 1, 1), "amount": -10000},
        ]
        mf_nav = {"2020-01-01": 25.0, "2026-03-31": 50.0}
        result = simulate_mf_sip(cash_flows, mf_nav, scheme_code="122639",
                                  end_date=date(2026, 3, 31))
        assert abs(result["final_value"] - 20000) < 0.01

    def test_mf_sip_nearest_nav(self):
        cash_flows = [{"date": date(2020, 1, 15), "amount": -5000}]
        mf_nav = {"2020-01-14": 50.0, "2020-01-16": 52.0, "2026-03-31": 100.0}
        result = simulate_mf_sip(cash_flows, mf_nav, scheme_code="118989",
                                  end_date=date(2026, 3, 31))
        assert result["final_value"] > 0


# ── Model Portfolio ──────────────────────────────────────────────────────────


class TestModelPortfolio:
    def test_70_30_split(self):
        cash_flows = [
            {"date": date(2020, 1, 1), "amount": -100000},
        ]
        equity_nav = {"2020-01-01": 100.0, "2026-03-31": 200.0}
        debt_nav = {"2020-01-01": 100.0, "2026-03-31": 120.0}
        result = simulate_model_portfolio(
            cash_flows, equity_nav, debt_nav,
            equity_pct=0.70, end_date=date(2026, 3, 31),
        )
        _assert_scenario_shape(result, "model_70_30")
        equity_value = (70000 / 100.0) * 200.0
        debt_value = (30000 / 100.0) * 120.0
        expected = equity_value + debt_value
        assert abs(result["final_value"] - expected) < 0.01

    def test_100_equity(self):
        cash_flows = [{"date": date(2020, 1, 1), "amount": -50000}]
        equity_nav = {"2020-01-01": 100.0, "2026-03-31": 250.0}
        debt_nav = {"2020-01-01": 100.0, "2026-03-31": 110.0}
        result = simulate_model_portfolio(
            cash_flows, equity_nav, debt_nav,
            equity_pct=1.0, end_date=date(2026, 3, 31),
        )
        assert abs(result["final_value"] - 125000) < 0.01

    def test_50_50_split(self):
        cash_flows = [{"date": date(2020, 1, 1), "amount": -100000}]
        equity_nav = {"2020-01-01": 100.0, "2026-03-31": 200.0}
        debt_nav = {"2020-01-01": 100.0, "2026-03-31": 120.0}
        result = simulate_model_portfolio(
            cash_flows, equity_nav, debt_nav,
            equity_pct=0.50, end_date=date(2026, 3, 31),
        )
        equity_value = (50000 / 100.0) * 200.0
        debt_value = (50000 / 100.0) * 120.0
        assert abs(result["final_value"] - (equity_value + debt_value)) < 0.01


# ── No Re-entry ──────────────────────────────────────────────────────────────


class TestNoReentry:
    def test_eliminates_reentry(self):
        trades = [
            {"date": date(2020, 1, 1), "symbol": "INFY", "action": "BUY",
             "quantity": 100, "price": 700, "instrument_type": "EQUITY"},
            {"date": date(2020, 4, 1), "symbol": "INFY", "action": "SELL",
             "quantity": 100, "price": 600, "instrument_type": "EQUITY"},
            {"date": date(2020, 7, 1), "symbol": "INFY", "action": "BUY",
             "quantity": 80, "price": 750, "instrument_type": "EQUITY"},
        ]
        current_prices = {"INFY": 1500.0}
        result = simulate_no_reentry(trades, current_prices)
        _assert_scenario_shape(result, "no_reentry")
        assert result["final_value"] == 100 * 1500

    def test_no_reentry_pattern_returns_empty(self):
        trades = [
            {"date": date(2020, 1, 1), "symbol": "TCS", "action": "BUY",
             "quantity": 10, "price": 2000, "instrument_type": "EQUITY"},
        ]
        current_prices = {"TCS": 3000.0}
        result = simulate_no_reentry(trades, current_prices)
        assert result["scenario"] == "no_reentry"

    def test_multiple_reentries(self):
        trades = [
            {"date": date(2019, 1, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1000, "instrument_type": "EQUITY"},
            {"date": date(2019, 6, 1), "symbol": "RELIANCE", "action": "SELL",
             "quantity": 50, "price": 1200, "instrument_type": "EQUITY"},
            {"date": date(2019, 9, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 30, "price": 1300, "instrument_type": "EQUITY"},
            {"date": date(2020, 1, 1), "symbol": "RELIANCE", "action": "SELL",
             "quantity": 30, "price": 1100, "instrument_type": "EQUITY"},
            {"date": date(2020, 4, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 40, "price": 1150, "instrument_type": "EQUITY"},
        ]
        current_prices = {"RELIANCE": 2500.0}
        result = simulate_no_reentry(trades, current_prices)
        assert result["final_value"] == 50 * 2500


# ── Run All Scenarios ────────────────────────────────────────────────────────


class TestRunAllScenarios:
    def test_returns_all_scenarios(self):
        cash_flows = [{"date": date(2020, 1, 15), "amount": -75000}]
        trades = [
            {"date": date(2020, 1, 15), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1500, "instrument_type": "EQUITY"},
        ]
        result = run_all_scenarios(
            cash_flows=cash_flows,
            trades=trades,
            actual_return={"xirr": 0.12, "final_value": 90000, "total_invested": 75000},
            nifty_nav={"2020-01-15": 100.0, "2026-03-31": 180.0},
            mf_navs={},
            current_prices={"RELIANCE": 1800.0},
            end_date=date(2026, 3, 31),
        )
        assert len(result) >= 2

    def test_each_scenario_has_vs_actual(self):
        cash_flows = [{"date": date(2020, 1, 15), "amount": -75000}]
        trades = [
            {"date": date(2020, 1, 15), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1500, "instrument_type": "EQUITY"},
        ]
        result = run_all_scenarios(
            cash_flows=cash_flows,
            trades=trades,
            actual_return={"xirr": 0.12, "final_value": 90000, "total_invested": 75000},
            nifty_nav={"2020-01-15": 100.0, "2026-03-31": 180.0},
            mf_navs={},
            current_prices={"RELIANCE": 1800.0},
            end_date=date(2026, 3, 31),
        )
        for scenario in result:
            assert "vs_actual" in scenario
            vs = scenario["vs_actual"]
            assert "value_difference" in vs
            assert "interpretation" in vs

    def test_catches_per_scenario_errors(self):
        cash_flows = [{"date": date(2020, 1, 15), "amount": -75000}]
        trades = [
            {"date": date(2020, 1, 15), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1500, "instrument_type": "EQUITY"},
        ]
        result = run_all_scenarios(
            cash_flows=cash_flows,
            trades=trades,
            actual_return={"xirr": 0.12, "final_value": 90000, "total_invested": 75000},
            nifty_nav={},
            mf_navs={},
            current_prices={"RELIANCE": 1800.0},
            end_date=date(2026, 3, 31),
        )
        assert isinstance(result, list)

    def test_with_mf_navs(self):
        cash_flows = [{"date": date(2020, 1, 15), "amount": -75000}]
        trades = [
            {"date": date(2020, 1, 15), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1500, "instrument_type": "EQUITY"},
        ]
        mf_navs = {
            "120716": {"2020-01-15": 100.0, "2026-03-31": 220.0},
            "122639": {"2020-01-15": 30.0, "2026-03-31": 75.0},
        }
        result = run_all_scenarios(
            cash_flows=cash_flows,
            trades=trades,
            actual_return={"xirr": 0.12, "final_value": 90000, "total_invested": 75000},
            nifty_nav={"2020-01-15": 100.0, "2026-03-31": 180.0},
            mf_navs=mf_navs,
            current_prices={"RELIANCE": 1800.0},
            end_date=date(2026, 3, 31),
        )
        scenario_names = [s["scenario"] for s in result]
        assert "nifty_50_sip" in scenario_names
