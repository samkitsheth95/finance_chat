import pytest
from datetime import date
from portfolio_doctor.core.csv_parser import (
    parse_csv,
    validate_trades,
    validate_symbols,
    build_position_ledger,
    build_cash_flows,
    detect_sip_patterns,
)


class TestParseCsv:
    def test_parses_valid_csv(self, tmp_csv):
        trades = parse_csv(tmp_csv)
        assert len(trades) == 3
        assert trades[0]["symbol"] == "119551"
        assert trades[0]["date"] == date(2020, 1, 10)

    def test_parses_quantity_as_float(self, tmp_csv):
        trades = parse_csv(tmp_csv)
        mf_trade = [t for t in trades if t["instrument_type"] == "MF"][0]
        assert mf_trade["quantity"] == 200.5

    def test_sorted_by_date(self, tmp_csv):
        trades = parse_csv(tmp_csv)
        dates = [t["date"] for t in trades]
        assert dates == sorted(dates)

    def test_normalizes_instrument_type(self, tmp_path):
        p = tmp_path / "mixed.csv"
        p.write_text(
            "date,instrument_type,symbol,action,quantity,price\n"
            "2020-01-01,equity,RELIANCE,buy,10,1500\n"
        )
        trades = parse_csv(str(p))
        assert trades[0]["instrument_type"] == "EQUITY"
        assert trades[0]["action"] == "BUY"

    def test_rejects_missing_required_columns(self, tmp_path):
        p = tmp_path / "bad.csv"
        p.write_text("date,symbol\n2020-01-01,RELIANCE\n")
        with pytest.raises(ValueError, match="Missing required columns"):
            parse_csv(str(p))

    def test_computes_amount_if_missing(self, tmp_path):
        p = tmp_path / "no_amount.csv"
        p.write_text(
            "date,instrument_type,symbol,action,quantity,price\n"
            "2020-01-01,EQUITY,RELIANCE,BUY,10,1500\n"
        )
        trades = parse_csv(str(p))
        assert trades[0]["amount"] == pytest.approx(15000.0)


class TestValidateTrades:
    def test_warns_on_oversell(self, sample_equity_trades):
        oversell = sample_equity_trades + [
            {"date": date(2020, 7, 1), "instrument_type": "EQUITY",
             "symbol": "RELIANCE", "action": "SELL", "quantity": 100,
             "price": 1900.0, "amount": 190000.0},
        ]
        warnings = validate_trades(oversell)
        assert any("sell more" in w.lower() for w in warnings)

    def test_warns_on_duplicate(self, sample_equity_trades):
        duped = sample_equity_trades + [sample_equity_trades[0].copy()]
        warnings = validate_trades(duped)
        assert any("duplicate" in w.lower() for w in warnings)

    def test_no_warnings_for_clean_data(self, sample_equity_trades):
        warnings = validate_trades(sample_equity_trades)
        assert len(warnings) == 0

    def test_warns_on_weekend_trade(self):
        trades = [
            {"date": date(2020, 1, 11), "instrument_type": "EQUITY",
             "symbol": "RELIANCE", "action": "BUY", "quantity": 10,
             "price": 1500.0, "amount": 15000.0},
        ]
        warnings = validate_trades(trades)
        assert any("weekend" in w.lower() for w in warnings)


class TestValidateSymbols:
    def test_warns_on_invalid_equity(self, monkeypatch):
        monkeypatch.setattr(
            "portfolio_doctor.core.csv_parser.yf.Ticker",
            lambda sym: (_ for _ in ()).throw(Exception("not found")),
        )
        trades = [
            {"date": date(2020, 1, 1), "instrument_type": "EQUITY",
             "symbol": "FAKESYMBOL", "action": "BUY", "quantity": 10,
             "price": 100, "amount": 1000},
        ]
        warnings = validate_symbols(trades)
        assert any("FAKESYMBOL" in w for w in warnings)

    def test_warns_on_invalid_mf(self, monkeypatch):
        monkeypatch.setattr(
            "portfolio_doctor.core.csv_parser.validate_scheme_code",
            lambda code: {"valid": False, "scheme_code": "999999",
                          "error": "not found"},
        )
        trades = [
            {"date": date(2020, 1, 1), "instrument_type": "MF",
             "symbol": "999999", "action": "SIP", "quantity": 100,
             "price": 25, "amount": 2500},
        ]
        warnings = validate_symbols(trades)
        assert any("999999" in w for w in warnings)

    def test_valid_equity_no_warning(self, monkeypatch):
        class FakeTicker:
            fast_info = {"lastPrice": 1500}
        monkeypatch.setattr(
            "portfolio_doctor.core.csv_parser.yf.Ticker",
            lambda sym: FakeTicker(),
        )
        trades = [
            {"date": date(2020, 1, 1), "instrument_type": "EQUITY",
             "symbol": "RELIANCE", "action": "BUY", "quantity": 10,
             "price": 1500, "amount": 15000},
        ]
        warnings = validate_symbols(trades)
        assert len(warnings) == 0


class TestBuildPositionLedger:
    def test_fifo_equity(self, sample_equity_trades):
        ledger = build_position_ledger(sample_equity_trades)
        rel = ledger["RELIANCE"]
        assert rel["quantity"] == 30
        assert rel["instrument_type"] == "EQUITY"

    def test_fifo_avg_cost_after_partial_sell(self, sample_equity_trades):
        ledger = build_position_ledger(sample_equity_trades)
        rel = ledger["RELIANCE"]
        assert rel["avg_cost"] == pytest.approx(1500.0)

    def test_mf_per_lot_tracking(self, sample_mf_trades):
        ledger = build_position_ledger(sample_mf_trades)
        mf = ledger["119551"]
        assert len(mf["lots"]) == 2
        assert mf["total_quantity"] == pytest.approx(395.8)

    def test_full_sell_removes_position(self):
        trades = [
            {"date": date(2020, 1, 1), "instrument_type": "EQUITY",
             "symbol": "TCS", "action": "BUY", "quantity": 10,
             "price": 2000.0, "amount": 20000.0},
            {"date": date(2020, 6, 1), "instrument_type": "EQUITY",
             "symbol": "TCS", "action": "SELL", "quantity": 10,
             "price": 2200.0, "amount": 22000.0},
        ]
        ledger = build_position_ledger(trades)
        assert "TCS" not in ledger

    def test_mf_sell_consumes_oldest_lots_first(self):
        trades = [
            {"date": date(2020, 1, 1), "instrument_type": "MF",
             "symbol": "119551", "action": "SIP", "quantity": 100.0,
             "price": 25.0, "amount": 2500.0},
            {"date": date(2020, 2, 1), "instrument_type": "MF",
             "symbol": "119551", "action": "SIP", "quantity": 100.0,
             "price": 26.0, "amount": 2600.0},
            {"date": date(2020, 3, 1), "instrument_type": "MF",
             "symbol": "119551", "action": "SELL", "quantity": 120.0,
             "price": 28.0, "amount": 3360.0},
        ]
        ledger = build_position_ledger(trades)
        mf = ledger["119551"]
        assert len(mf["lots"]) == 1
        assert mf["lots"][0]["quantity"] == pytest.approx(80.0)
        assert mf["lots"][0]["price"] == pytest.approx(26.0)
        assert mf["total_quantity"] == pytest.approx(80.0)


class TestBuildCashFlows:
    def test_buy_is_negative_flow(self, sample_equity_trades):
        flows = build_cash_flows(sample_equity_trades)
        buys = [f for f in flows if f["amount"] < 0]
        assert len(buys) == 2

    def test_sell_is_positive_flow(self, sample_equity_trades):
        flows = build_cash_flows(sample_equity_trades)
        sells = [f for f in flows if f["amount"] > 0]
        assert len(sells) == 1

    def test_sorted_by_date(self, sample_equity_trades):
        flows = build_cash_flows(sample_equity_trades)
        dates = [f["date"] for f in flows]
        assert dates == sorted(dates)

    def test_sip_is_negative_flow(self, sample_mf_trades):
        flows = build_cash_flows(sample_mf_trades)
        assert all(f["amount"] < 0 for f in flows)


class TestDetectSipPatterns:
    def test_detects_monthly_sip(self, sample_mf_trades):
        patterns = detect_sip_patterns(sample_mf_trades)
        assert len(patterns) >= 1
        assert patterns[0]["scheme_code"] == "119551"
        assert patterns[0]["frequency"] == "monthly"

    def test_no_sip_for_equity(self, sample_equity_trades):
        patterns = detect_sip_patterns(sample_equity_trades)
        assert len(patterns) == 0

    def test_requires_minimum_transactions(self):
        trades = [
            {"date": date(2020, 1, 10), "instrument_type": "MF",
             "symbol": "119551", "action": "SIP", "quantity": 200,
             "price": 25.0, "amount": 5000.0},
        ]
        patterns = detect_sip_patterns(trades)
        assert len(patterns) == 0

    def test_detects_sip_with_many_months(self):
        trades = [
            {"date": date(2020, m, 10), "instrument_type": "MF",
             "symbol": "119551", "action": "SIP", "quantity": 200,
             "price": 25.0, "amount": 5000.0}
            for m in range(1, 7)
        ]
        patterns = detect_sip_patterns(trades)
        assert len(patterns) == 1
        assert patterns[0]["total_sips"] == 6
        assert patterns[0]["avg_amount"] == pytest.approx(5000.0)
