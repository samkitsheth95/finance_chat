from unittest.mock import patch, MagicMock
from datetime import date
import pytest

import shared.mf_client
from shared.mf_client import fetch_nav_history, validate_scheme_code


@pytest.fixture(autouse=True)
def _reset_mf_singleton():
    """Reset the module-level Mf singleton so each test gets a fresh mock."""
    shared.mf_client._mf = None
    yield
    shared.mf_client._mf = None


@patch("shared.mf_client.Mf")
def test_fetch_nav_history(mock_mf_cls):
    mock_mf = MagicMock()
    mock_mf.get_scheme_historical_nav.return_value = {
        "data": [
            {"date": "15-01-2020", "nav": "25.1234"},
            {"date": "16-01-2020", "nav": "25.5678"},
        ]
    }
    mock_mf_cls.return_value = mock_mf

    result = fetch_nav_history("119551", date(2020, 1, 14), date(2020, 1, 17))
    assert "error" not in result
    assert len(result["navs"]) == 2
    assert result["navs"][0]["nav"] == 25.1234


@patch("shared.mf_client.Mf")
def test_validate_scheme_code_valid(mock_mf_cls):
    mock_mf = MagicMock()
    mock_mf.get_scheme_details.return_value = {
        "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Growth"
    }
    mock_mf_cls.return_value = mock_mf

    result = validate_scheme_code("119551")
    assert result["valid"] is True
    assert "Parag Parikh" in result["scheme_name"]


@patch("shared.mf_client.Mf")
def test_validate_scheme_code_invalid(mock_mf_cls):
    mock_mf = MagicMock()
    mock_mf.get_scheme_details.return_value = {}
    mock_mf_cls.return_value = mock_mf

    result = validate_scheme_code("999999")
    assert result["valid"] is False
