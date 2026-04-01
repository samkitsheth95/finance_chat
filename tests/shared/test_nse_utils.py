from shared.nse_utils import nse_to_yf


def test_plain_symbol():
    assert nse_to_yf("RELIANCE") == "RELIANCE.NS"


def test_with_nse_prefix():
    assert nse_to_yf("NSE:INFY") == "INFY.NS"


def test_with_bse_prefix():
    assert nse_to_yf("BSE:500325") == "500325.BO"


def test_already_has_ns_suffix():
    assert nse_to_yf("RELIANCE.NS") == "RELIANCE.NS"


def test_lowercase_normalized():
    assert nse_to_yf("reliance") == "RELIANCE.NS"
