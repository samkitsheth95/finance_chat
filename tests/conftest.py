import pytest
from datetime import date


@pytest.fixture
def sample_equity_trades():
    """Minimal equity trades for testing."""
    return [
        {"date": date(2020, 1, 15), "instrument_type": "EQUITY", "symbol": "RELIANCE",
         "action": "BUY", "quantity": 50, "price": 1500.0, "amount": 75000.0},
        {"date": date(2020, 6, 15), "instrument_type": "EQUITY", "symbol": "RELIANCE",
         "action": "SELL", "quantity": 20, "price": 1800.0, "amount": 36000.0},
        {"date": date(2020, 3, 20), "instrument_type": "EQUITY", "symbol": "HDFCBANK",
         "action": "BUY", "quantity": 30, "price": 850.0, "amount": 25500.0},
    ]


@pytest.fixture
def sample_mf_trades():
    """Minimal MF trades for testing."""
    return [
        {"date": date(2020, 1, 10), "instrument_type": "MF", "symbol": "119551",
         "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Growth",
         "action": "SIP", "quantity": 200.5, "price": 25.0, "amount": 5012.5},
        {"date": date(2020, 2, 10), "instrument_type": "MF", "symbol": "119551",
         "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Growth",
         "action": "SIP", "quantity": 195.3, "price": 25.6, "amount": 4999.68},
    ]


@pytest.fixture
def sample_csv_content():
    """Valid CSV string for parser testing."""
    return (
        "date,instrument_type,symbol,scheme_name,action,quantity,price,amount,brokerage,notes\n"
        "2020-01-15,EQUITY,RELIANCE,,BUY,50,1500.00,75000.00,20.00,\n"
        "2020-06-15,EQUITY,RELIANCE,,SELL,20,1800.00,36000.00,20.00,\n"
        "2020-01-10,MF,119551,Parag Parikh Flexi Cap Fund - Direct Growth,SIP,200.5,25.00,5012.50,0,Monthly SIP\n"
    )


@pytest.fixture
def tmp_csv(tmp_path, sample_csv_content):
    """Write sample CSV to a temp file, return path."""
    p = tmp_path / "test_trades.csv"
    p.write_text(sample_csv_content)
    return str(p)


@pytest.fixture
def tmp_portfolio_dir(tmp_path):
    """Temp directory simulating data/portfolios/{client}/."""
    d = tmp_path / "portfolios" / "test_client"
    d.mkdir(parents=True)
    return str(d)
