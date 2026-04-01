import pytest
from datetime import date
from portfolio_doctor.core.portfolio_engine import (
    compute_holdings,
    compute_xirr,
    compute_returns,
    compute_portfolio_value_series,
    compute_sector_allocation,
    compute_turnover,
    compute_tax_drag,
    compute_cash_flows,
)


class TestComputeHoldings:
    def test_tracks_equity_positions(self, sample_equity_trades):
        holdings = compute_holdings(sample_equity_trades, as_of=date(2020, 12, 31))
        assert "RELIANCE" in holdings
        assert holdings["RELIANCE"]["quantity"] == 30

    def test_handles_full_sell(self, sample_equity_trades):
        trades = sample_equity_trades + [
            {"date": date(2020, 8, 1), "instrument_type": "EQUITY",
             "symbol": "RELIANCE", "action": "SELL", "quantity": 30,
             "price": 2000.0, "amount": 60000.0}
        ]
        holdings = compute_holdings(trades, as_of=date(2020, 12, 31))
        assert "RELIANCE" not in holdings

    def test_as_of_filters_future_trades(self, sample_equity_trades):
        holdings = compute_holdings(sample_equity_trades, as_of=date(2020, 2, 1))
        assert "RELIANCE" in holdings
        assert holdings["RELIANCE"]["quantity"] == 50
        assert "HDFCBANK" not in holdings

    def test_mf_per_lot_tracking(self, sample_mf_trades):
        holdings = compute_holdings(sample_mf_trades, as_of=date(2020, 12, 31))
        mf = holdings["119551"]
        assert len(mf["lots"]) == 2
        assert mf["total_quantity"] == pytest.approx(395.8)

    def test_equity_avg_cost(self, sample_equity_trades):
        holdings = compute_holdings(sample_equity_trades, as_of=date(2020, 12, 31))
        assert holdings["RELIANCE"]["avg_cost"] == pytest.approx(1500.0)
        assert holdings["HDFCBANK"]["avg_cost"] == pytest.approx(850.0)


class TestComputeXirr:
    def test_positive_return(self):
        cash_flows = [
            (date(2020, 1, 1), -100000),
            (date(2021, 1, 1), 115000),
        ]
        xirr = compute_xirr(cash_flows)
        assert xirr == pytest.approx(0.15, abs=0.01)

    def test_zero_return(self):
        cash_flows = [
            (date(2020, 1, 1), -100000),
            (date(2021, 1, 1), 100000),
        ]
        xirr = compute_xirr(cash_flows)
        assert xirr == pytest.approx(0.0, abs=0.01)

    def test_negative_return(self):
        cash_flows = [
            (date(2020, 1, 1), -100000),
            (date(2021, 1, 1), 85000),
        ]
        xirr = compute_xirr(cash_flows)
        assert xirr == pytest.approx(-0.15, abs=0.01)

    def test_multiple_cash_flows(self):
        cash_flows = [
            (date(2020, 1, 1), -50000),
            (date(2020, 7, 1), -50000),
            (date(2021, 1, 1), 110000),
        ]
        xirr = compute_xirr(cash_flows)
        assert -0.5 < xirr < 0.5

    def test_single_cash_flow_returns_zero(self):
        cash_flows = [(date(2020, 1, 1), -100000)]
        xirr = compute_xirr(cash_flows)
        assert xirr == 0.0


class TestComputeReturns:
    def test_per_position_returns(self, sample_equity_trades):
        current_prices = {"RELIANCE": 2000.0, "HDFCBANK": 1200.0}
        result = compute_returns(sample_equity_trades, current_prices,
                                 as_of=date(2020, 12, 31))
        assert "positions" in result
        rel = next(p for p in result["positions"] if p["symbol"] == "RELIANCE")
        assert rel["current_value"] == pytest.approx(60000.0)
        assert rel["return_pct"] > 0

    def test_portfolio_level_metrics(self, sample_equity_trades):
        current_prices = {"RELIANCE": 2000.0, "HDFCBANK": 1200.0}
        result = compute_returns(sample_equity_trades, current_prices,
                                 as_of=date(2020, 12, 31))
        assert "total_invested" in result
        assert "current_value" in result
        assert "absolute_return" in result
        assert "return_pct" in result
        assert result["current_value"] == pytest.approx(96000.0)

    def test_includes_xirr(self, sample_equity_trades):
        current_prices = {"RELIANCE": 2000.0, "HDFCBANK": 1200.0}
        result = compute_returns(sample_equity_trades, current_prices,
                                 as_of=date(2020, 12, 31))
        assert "portfolio_xirr" in result


class TestComputePortfolioValueSeries:
    def test_returns_daily_values(self):
        trades = [
            {"date": date(2020, 1, 15), "instrument_type": "EQUITY",
             "symbol": "RELIANCE", "action": "BUY", "quantity": 50,
             "price": 1500.0, "amount": 75000.0},
        ]
        price_data = {
            "RELIANCE": {
                "2020-01-15": 1500, "2020-01-16": 1510, "2020-01-17": 1520,
            },
        }
        series = compute_portfolio_value_series(
            trades, price_data,
            start_date=date(2020, 1, 15), end_date=date(2020, 1, 17)
        )
        assert len(series) == 3
        assert series[0]["value"] == pytest.approx(75000.0)
        assert series[2]["value"] == pytest.approx(76000.0)

    def test_reflects_sells(self):
        trades = [
            {"date": date(2020, 1, 15), "instrument_type": "EQUITY",
             "symbol": "RELIANCE", "action": "BUY", "quantity": 50,
             "price": 1500.0, "amount": 75000.0},
            {"date": date(2020, 1, 16), "instrument_type": "EQUITY",
             "symbol": "RELIANCE", "action": "SELL", "quantity": 20,
             "price": 1510.0, "amount": 30200.0},
        ]
        price_data = {
            "RELIANCE": {
                "2020-01-15": 1500, "2020-01-16": 1510, "2020-01-17": 1520,
            },
        }
        series = compute_portfolio_value_series(
            trades, price_data,
            start_date=date(2020, 1, 15), end_date=date(2020, 1, 17)
        )
        assert series[2]["value"] == pytest.approx(30 * 1520)

    def test_skips_dates_without_prices(self):
        trades = [
            {"date": date(2020, 1, 15), "instrument_type": "EQUITY",
             "symbol": "RELIANCE", "action": "BUY", "quantity": 50,
             "price": 1500.0, "amount": 75000.0},
        ]
        price_data = {
            "RELIANCE": {"2020-01-15": 1500, "2020-01-17": 1520},
        }
        series = compute_portfolio_value_series(
            trades, price_data,
            start_date=date(2020, 1, 15), end_date=date(2020, 1, 17)
        )
        dates_in_series = {s["date"] for s in series}
        assert "2020-01-16" not in dates_in_series


class TestComputeSectorAllocation:
    def test_returns_sector_weights(self):
        holdings = {
            "RELIANCE": {"value": 600000, "instrument_type": "EQUITY"},
            "HDFCBANK": {"value": 400000, "instrument_type": "EQUITY"},
        }
        sector_map = {"RELIANCE": "Energy", "HDFCBANK": "Financials"}
        result = compute_sector_allocation(holdings, sector_map)
        assert result["sectors"]["Energy"] == pytest.approx(60.0)
        assert result["sectors"]["Financials"] == pytest.approx(40.0)

    def test_handles_mf_types(self):
        holdings = {
            "RELIANCE": {"value": 500000, "instrument_type": "EQUITY"},
            "119551": {"value": 500000, "instrument_type": "MF"},
        }
        result = compute_sector_allocation(holdings, {})
        assert "types" in result
        assert result["types"]["EQUITY"] == pytest.approx(50.0)
        assert result["types"]["MF"] == pytest.approx(50.0)

    def test_unknown_sector_grouped(self):
        holdings = {
            "RELIANCE": {"value": 600000, "instrument_type": "EQUITY"},
            "XYZ": {"value": 400000, "instrument_type": "EQUITY"},
        }
        sector_map = {"RELIANCE": "Energy"}
        result = compute_sector_allocation(holdings, sector_map)
        assert "Unknown" in result["sectors"]


class TestComputeTurnover:
    def test_calculates_ratio(self):
        trades = [
            {"date": date(2020, 1, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1500, "instrument_type": "EQUITY",
             "amount": 75000},
            {"date": date(2020, 6, 1), "symbol": "RELIANCE", "action": "SELL",
             "quantity": 50, "price": 1800, "instrument_type": "EQUITY",
             "amount": 90000},
        ]
        ratio = compute_turnover(trades, avg_portfolio_value=100000)
        assert ratio == pytest.approx(0.9)

    def test_no_sells_zero_turnover(self):
        trades = [
            {"date": date(2020, 1, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1500, "instrument_type": "EQUITY",
             "amount": 75000},
        ]
        ratio = compute_turnover(trades, avg_portfolio_value=100000)
        assert ratio == pytest.approx(0.0)

    def test_zero_avg_value_returns_zero(self):
        trades = [
            {"date": date(2020, 6, 1), "symbol": "RELIANCE", "action": "SELL",
             "quantity": 50, "price": 1800, "instrument_type": "EQUITY",
             "amount": 90000},
        ]
        ratio = compute_turnover(trades, avg_portfolio_value=0)
        assert ratio == 0.0


class TestComputeTaxDrag:
    def test_stcg_on_short_hold(self):
        trades = [
            {"date": date(2020, 1, 1), "instrument_type": "EQUITY",
             "symbol": "RELIANCE", "action": "BUY", "quantity": 50,
             "price": 1500.0, "amount": 75000.0, "brokerage": 20.0},
            {"date": date(2020, 6, 1), "instrument_type": "EQUITY",
             "symbol": "RELIANCE", "action": "SELL", "quantity": 50,
             "price": 1800.0, "amount": 90000.0, "brokerage": 20.0},
        ]
        result = compute_tax_drag(trades)
        assert result["stcg_estimated"] > 0
        assert result["ltcg_estimated"] == 0

    def test_ltcg_on_long_hold(self):
        trades = [
            {"date": date(2019, 1, 1), "instrument_type": "EQUITY",
             "symbol": "RELIANCE", "action": "BUY", "quantity": 500,
             "price": 1500.0, "amount": 750000.0, "brokerage": 20.0},
            {"date": date(2020, 6, 1), "instrument_type": "EQUITY",
             "symbol": "RELIANCE", "action": "SELL", "quantity": 500,
             "price": 1800.0, "amount": 900000.0, "brokerage": 20.0},
        ]
        result = compute_tax_drag(trades)
        # gain = 500 * 300 = 150000, taxable = 150000 - 100000 = 50000, tax = 5000
        assert result["ltcg_estimated"] == pytest.approx(5000.0)
        assert result["stcg_estimated"] == 0

    def test_tracks_total_brokerage(self):
        trades = [
            {"date": date(2020, 1, 1), "instrument_type": "EQUITY",
             "symbol": "RELIANCE", "action": "BUY", "quantity": 50,
             "price": 1500.0, "amount": 75000.0, "brokerage": 20.0},
            {"date": date(2020, 6, 1), "instrument_type": "EQUITY",
             "symbol": "RELIANCE", "action": "SELL", "quantity": 50,
             "price": 1800.0, "amount": 90000.0, "brokerage": 20.0},
        ]
        result = compute_tax_drag(trades)
        assert result["total_brokerage"] == pytest.approx(40.0)

    def test_no_tax_on_loss(self):
        trades = [
            {"date": date(2020, 1, 1), "instrument_type": "EQUITY",
             "symbol": "RELIANCE", "action": "BUY", "quantity": 50,
             "price": 1800.0, "amount": 90000.0, "brokerage": 0},
            {"date": date(2020, 6, 1), "instrument_type": "EQUITY",
             "symbol": "RELIANCE", "action": "SELL", "quantity": 50,
             "price": 1500.0, "amount": 75000.0, "brokerage": 0},
        ]
        result = compute_tax_drag(trades)
        assert result["stcg_estimated"] == 0
        assert result["ltcg_estimated"] == 0
        assert result["total_tax_drag"] == 0


class TestComputeCashFlows:
    def test_reexport_from_csv_parser(self):
        """compute_cash_flows is a re-export of csv_parser.build_cash_flows."""
        from portfolio_doctor.core.csv_parser import build_cash_flows
        assert compute_cash_flows is build_cash_flows
