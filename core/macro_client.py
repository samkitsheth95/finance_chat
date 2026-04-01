"""
Layer 4 — Global Macro
Raw data-fetch layer for yfinance (global markets and US Treasury yields).

Session management and caching now live in shared/yf_client.py.
This module re-exports what india-markets tools expect.
"""
from shared.yf_client import get_yf_session as _get_yf_session  # noqa: F401
from shared.yf_client import yf_latest  # noqa: F401
