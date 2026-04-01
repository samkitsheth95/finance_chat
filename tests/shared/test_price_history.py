from unittest.mock import patch, MagicMock
import pandas as pd
from datetime import date
from shared.price_history import fetch_price_history


def _mock_history_df():
    """Build a small OHLC dataframe for mocking."""
    idx = pd.to_datetime(["2020-01-15", "2020-01-16", "2020-01-17"])
    return pd.DataFrame({
        "Open": [100.0, 101.0, 102.0],
        "High": [105.0, 106.0, 107.0],
        "Low": [99.0, 100.0, 101.0],
        "Close": [103.0, 104.0, 105.0],
        "Volume": [1000, 1100, 1200],
    }, index=idx)


@patch("shared.price_history.yf.Ticker")
def test_returns_close_series(mock_ticker_cls):
    mock_t = MagicMock()
    mock_t.history.return_value = _mock_history_df()
    mock_ticker_cls.return_value = mock_t

    result = fetch_price_history("RELIANCE", date(2020, 1, 14), date(2020, 1, 18))
    assert "error" not in result
    assert len(result["prices"]) == 3
    assert result["prices"][0]["close"] == 103.0


@patch("shared.price_history.yf.Ticker")
def test_empty_history_returns_error(mock_ticker_cls):
    mock_t = MagicMock()
    mock_t.history.return_value = pd.DataFrame()
    mock_ticker_cls.return_value = mock_t

    result = fetch_price_history("FAKESYM", date(2020, 1, 1), date(2020, 1, 31))
    assert "error" in result


@patch("shared.price_history.yf.Ticker")
def test_index_ticker_passthrough(mock_ticker_cls):
    """^NSEI should NOT go through nse_to_yf mapping."""
    mock_t = MagicMock()
    mock_t.history.return_value = _mock_history_df()
    mock_ticker_cls.return_value = mock_t

    result = fetch_price_history("^NSEI", date(2020, 1, 14), date(2020, 1, 18))
    mock_ticker_cls.assert_called_once()
    call_args = mock_ticker_cls.call_args
    assert call_args[0][0] == "^NSEI"
