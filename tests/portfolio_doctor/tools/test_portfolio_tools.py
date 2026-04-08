"""Tests for portfolio_doctor/tools/portfolio_tools.py — ingest + overview."""
import json
from datetime import date
from pathlib import Path

import pytest

from portfolio_doctor.tools.portfolio_tools import (
    ingest_client_trades,
    get_portfolio_overview,
    PORTFOLIO_DIR,
    _load_json,
    _load_trades,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, default=str)


def _setup_equity_client(portfolio_dir, client_name="test_client"):
    """Pre-populate a client directory with one equity buy."""
    cdir = portfolio_dir / client_name
    cdir.mkdir(parents=True, exist_ok=True)

    trades = [
        {"date": "2020-01-15", "instrument_type": "EQUITY", "symbol": "RELIANCE",
         "scheme_name": "", "action": "BUY", "quantity": 50, "price": 1500.0,
         "amount": 75000.0, "brokerage": 20.0, "notes": ""},
    ]
    positions = {
        "RELIANCE": {
            "instrument_type": "EQUITY",
            "quantity": 50,
            "total_cost": 75000.0,
            "avg_cost": 1500.0,
            "invested": 75000.0,
        },
    }
    cashflows = [
        {"date": "2020-01-15", "amount": -75000.0,
         "symbol": "RELIANCE", "action": "BUY"},
    ]

    for name, data in [
        ("trades.json", trades),
        ("positions.json", positions),
        ("cashflows.json", cashflows),
        ("sip_patterns.json", []),
    ]:
        _write_json(cdir / name, data)

    return cdir


# ---------------------------------------------------------------------------
# ingest_client_trades
# ---------------------------------------------------------------------------

class TestIngestClientTrades:

    def test_stores_json_files(self, tmp_path, sample_csv_content, monkeypatch):
        csv_path = tmp_path / "trades.csv"
        csv_path.write_text(sample_csv_content)

        portfolio_dir = tmp_path / "portfolios"
        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools.PORTFOLIO_DIR", portfolio_dir,
        )
        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools.validate_symbols",
            lambda trades: [],
        )

        ingest_client_trades(str(csv_path), "alice")

        cdir = portfolio_dir / "alice"
        assert (cdir / "trades.json").exists()
        assert (cdir / "positions.json").exists()
        assert (cdir / "cashflows.json").exists()
        assert (cdir / "sip_patterns.json").exists()

    def test_returns_correct_summary(self, tmp_path, sample_csv_content, monkeypatch):
        csv_path = tmp_path / "trades.csv"
        csv_path.write_text(sample_csv_content)

        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools.PORTFOLIO_DIR",
            tmp_path / "portfolios",
        )
        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools.validate_symbols",
            lambda trades: [],
        )

        result = ingest_client_trades(str(csv_path), "alice")

        assert result["status"] == "ingested"
        assert result["trade_count"] == 3
        assert result["client_name"] == "alice"
        assert result["symbols"] == ["119551", "RELIANCE"]
        assert result["equity_positions"] == 1
        assert result["mf_positions"] == 1
        assert result["capital_deployed"] == pytest.approx(80012.50)
        assert result["date_range"]["first"] == "2020-01-10"
        assert result["date_range"]["last"] == "2020-06-15"

    def test_error_on_bad_csv_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools.PORTFOLIO_DIR",
            tmp_path / "portfolios",
        )
        result = ingest_client_trades("/nonexistent/path.csv", "alice")
        assert "error" in result
        assert result["client_name"] == "alice"

    def test_includes_validation_warnings(self, tmp_path, monkeypatch):
        csv_content = (
            "date,instrument_type,symbol,scheme_name,action,quantity,price,amount\n"
            "2020-01-18,EQUITY,RELIANCE,,BUY,50,1500.00,75000.00\n"
        )
        csv_path = tmp_path / "trades.csv"
        csv_path.write_text(csv_content)

        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools.PORTFOLIO_DIR",
            tmp_path / "portfolios",
        )
        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools.validate_symbols",
            lambda trades: [],
        )

        result = ingest_client_trades(str(csv_path), "alice")
        assert any("weekend" in w.lower() for w in result["warnings"])

    def test_stored_trades_are_valid_json(self, tmp_path, sample_csv_content, monkeypatch):
        csv_path = tmp_path / "trades.csv"
        csv_path.write_text(sample_csv_content)

        portfolio_dir = tmp_path / "portfolios"
        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools.PORTFOLIO_DIR", portfolio_dir,
        )
        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools.validate_symbols",
            lambda trades: [],
        )

        ingest_client_trades(str(csv_path), "alice")

        trades = _load_json(portfolio_dir / "alice" / "trades.json")
        assert len(trades) == 3
        assert all("date" in t for t in trades)


# ---------------------------------------------------------------------------
# get_portfolio_overview
# ---------------------------------------------------------------------------

class TestGetPortfolioOverview:

    def test_error_if_no_client_data(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools.PORTFOLIO_DIR",
            tmp_path / "portfolios",
        )
        result = get_portfolio_overview("nonexistent")
        assert "error" in result

    def test_returns_all_expected_keys(self, tmp_path, monkeypatch):
        portfolio_dir = tmp_path / "portfolios"
        _setup_equity_client(portfolio_dir)

        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools.PORTFOLIO_DIR", portfolio_dir,
        )
        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools._fetch_current_prices",
            lambda positions: ({"RELIANCE": 2000.0}, {"RELIANCE": "Technology"}, []),
        )

        result = get_portfolio_overview("test_client")

        expected_keys = [
            "client_name", "as_of", "holdings", "portfolio_xirr",
            "total_invested", "current_value", "absolute_return",
            "return_pct", "total_brokerage", "sector_allocation",
            "type_allocation", "turnover_ratio", "tax_drag",
        ]
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_computes_correct_equity_returns(self, tmp_path, monkeypatch):
        portfolio_dir = tmp_path / "portfolios"
        _setup_equity_client(portfolio_dir)

        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools.PORTFOLIO_DIR", portfolio_dir,
        )
        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools._fetch_current_prices",
            lambda positions: ({"RELIANCE": 2000.0}, {"RELIANCE": "Technology"}, []),
        )

        result = get_portfolio_overview("test_client")

        assert result["total_invested"] == pytest.approx(75000.0)
        assert result["current_value"] == pytest.approx(100000.0)
        assert result["absolute_return"] == pytest.approx(25000.0)
        assert result["return_pct"] == pytest.approx(33.33, abs=0.01)

    def test_includes_sector_allocation(self, tmp_path, monkeypatch):
        portfolio_dir = tmp_path / "portfolios"
        _setup_equity_client(portfolio_dir)

        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools.PORTFOLIO_DIR", portfolio_dir,
        )
        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools._fetch_current_prices",
            lambda positions: ({"RELIANCE": 2000.0}, {"RELIANCE": "Energy"}, []),
        )

        result = get_portfolio_overview("test_client")

        assert "Energy" in result["sector_allocation"]
        assert result["sector_allocation"]["Energy"] == pytest.approx(100.0)
        assert "EQUITY" in result["type_allocation"]

    def test_caches_overview_to_json(self, tmp_path, monkeypatch):
        portfolio_dir = tmp_path / "portfolios"
        _setup_equity_client(portfolio_dir)

        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools.PORTFOLIO_DIR", portfolio_dir,
        )
        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools._fetch_current_prices",
            lambda positions: ({"RELIANCE": 2000.0}, {"RELIANCE": "Technology"}, []),
        )

        get_portfolio_overview("test_client")

        assert (portfolio_dir / "test_client" / "overview.json").exists()

    def test_handles_mf_positions(self, tmp_path, monkeypatch):
        portfolio_dir = tmp_path / "portfolios"
        cdir = portfolio_dir / "test_mf"
        cdir.mkdir(parents=True)

        trades = [
            {"date": "2020-01-10", "instrument_type": "MF", "symbol": "119551",
             "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Growth",
             "action": "SIP", "quantity": 200.5, "price": 25.0,
             "amount": 5012.5, "brokerage": 0, "notes": ""},
        ]
        positions = {
            "119551": {
                "instrument_type": "MF",
                "lots": [{"date": "2020-01-10", "quantity": 200.5,
                          "price": 25.0, "amount": 5012.5}],
                "total_quantity": 200.5,
                "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Growth",
            },
        }

        for name, data in [
            ("trades.json", trades),
            ("positions.json", positions),
            ("cashflows.json", [{"date": "2020-01-10", "amount": -5012.5,
                                 "symbol": "119551", "action": "SIP"}]),
            ("sip_patterns.json", []),
        ]:
            _write_json(cdir / name, data)

        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools.PORTFOLIO_DIR", portfolio_dir,
        )
        monkeypatch.setattr(
            "portfolio_doctor.tools.portfolio_tools._fetch_current_prices",
            lambda positions: ({"119551": 40.0}, {}, []),
        )

        result = get_portfolio_overview("test_mf")

        assert result["total_invested"] == pytest.approx(5012.5)
        assert result["current_value"] == pytest.approx(8020.0)


# ---------------------------------------------------------------------------
# _load_trades
# ---------------------------------------------------------------------------

class TestLoadTrades:

    def test_reconstructs_date_objects(self, tmp_path):
        trades = [
            {"date": "2020-01-15", "symbol": "RELIANCE", "action": "BUY"},
        ]
        path = tmp_path / "trades.json"
        _write_json(path, trades)

        loaded = _load_trades(path)
        assert loaded[0]["date"] == date(2020, 1, 15)
        assert isinstance(loaded[0]["date"], date)
