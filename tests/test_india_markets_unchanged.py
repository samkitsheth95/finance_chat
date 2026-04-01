"""Regression tests: existing india-markets imports must still resolve after extractions."""


def test_macro_client_imports():
    from core.macro_client import yf_latest
    assert callable(yf_latest)


def test_fundamentals_client_imports():
    from core.fundamentals_client import yf_fundamentals
    assert callable(yf_fundamentals)


def test_macro_client_has_session_helper():
    """macro_client must still expose _get_yf_session (fundamentals_client imports it)."""
    from core.macro_client import _get_yf_session
    assert callable(_get_yf_session)
