# Portfolio Doctor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new MCP server that analyzes client trading history (equities + mutual funds) to identify behavioral patterns, quantify mistake costs, compare against passive alternatives, and generate recommendations.

**Architecture:** Two-MCP repo sharing code via a new `shared/` package. Portfolio Doctor engines (portfolio, behavioral, alternatives) live in `portfolio_doctor/core/`, wrapped by `portfolio_doctor/tools/` and registered in `portfolio_doctor/server/app.py`. Data flows: CSV → csv_parser → engines → tools → MCP.

**Tech Stack:** Python, FastMCP, yfinance, mftool, scipy (XIRR), pandas

**Spec:** `docs/superpowers/specs/2026-04-01-portfolio-doctor-design.md`

---

## File Structure

### New files

```
shared/
├── __init__.py                          ← Package marker
├── yf_client.py                         ← Extracted from core/macro_client.py
├── nse_utils.py                         ← Extracted from core/fundamentals_client.py
├── price_history.py                     ← Batch historical OHLC via yfinance
└── mf_client.py                         ← MF NAV history via mftool

portfolio_doctor/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── csv_parser.py                    ← Parse, validate, build trade ledger
│   ├── portfolio_engine.py              ← Holdings, returns, XIRR, allocation
│   ├── behavioral_engine.py             ← 9 behavioral detectors + composite
│   └── alternatives_engine.py           ← 5 "what if" scenarios
├── tools/
│   ├── __init__.py
│   ├── portfolio_tools.py               ← ingest_trades, portfolio_overview
│   ├── behavioral_tools.py              ← behavioral_audit
│   ├── alternative_tools.py             ← compare_alternatives
│   └── report_tools.py                  ← action_plan, full_report_data
└── server/
    ├── __init__.py
    └── app.py                           ← Portfolio Doctor MCP server

tests/
├── conftest.py                          ← Shared fixtures (sample trades, etc.)
├── shared/
│   ├── test_yf_client.py
│   ├── test_nse_utils.py
│   ├── test_price_history.py
│   └── test_mf_client.py
├── portfolio_doctor/
│   ├── core/
│   │   ├── test_csv_parser.py
│   │   ├── test_portfolio_engine.py
│   │   ├── test_behavioral_engine.py
│   │   └── test_alternatives_engine.py
│   └── tools/
│       └── test_report_tools.py
└── test_india_markets_unchanged.py      ← Regression: existing imports still work

data/portfolios/                         ← NEW (gitignored)
```

### Modified files

| File | Change |
|------|--------|
| `core/macro_client.py` | Remove `_get_yf_session`, `_safe_float`, `_YF_SESSION`, `_YF_CACHE_TTL`, `_yf_cache`. Import from `shared.yf_client` |
| `core/fundamentals_client.py` | Remove `_nse_to_yf`, `_safe_float`. Import from `shared.nse_utils` and `shared.yf_client` |
| `.mcp.json` | Add `portfolio-doctor` server entry |
| `requirements.txt` | Add `mftool`, `scipy`, `pytest` |
| `.gitignore` | Add `data/portfolios/` |
| `.cursor/rules/project-architecture.mdc` | Add Portfolio Doctor section |

---

## Task 1: Test Infrastructure + Dependencies

**Files:**
- Create: `tests/conftest.py`
- Create: `pytest.ini`
- Modify: `requirements.txt`
- Modify: `.gitignore`

- [ ] **Step 1: Add test dependencies to requirements.txt**

Append to `requirements.txt`:
```
mftool>=3.2
scipy>=1.10.0
pytest>=7.0.0
```

- [ ] **Step 2: Install new dependencies**

Run: `cd /Users/samkit.sheth/Documents/github/finance_chat && .venv/bin/pip install mftool scipy pytest`
Expected: Successfully installed

- [ ] **Step 3: Create pytest.ini**

Create `pytest.ini`:
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

- [ ] **Step 4: Create tests/conftest.py with shared fixtures**

Create `tests/conftest.py` with sample trade data fixtures used across all test files:

```python
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
```

- [ ] **Step 5: Update .gitignore for portfolio data**

Append to `.gitignore`:
```
# Client portfolio data (contains trading history)
data/portfolios/
```

- [ ] **Step 6: Create data/portfolios/.gitkeep**

Run: `mkdir -p data/portfolios && touch data/portfolios/.gitkeep`

- [ ] **Step 7: Run pytest to verify infrastructure**

Run: `cd /Users/samkit.sheth/Documents/github/finance_chat && .venv/bin/python -m pytest --co -q`
Expected: `no tests ran` (collection works, no tests yet)

- [ ] **Step 8: Commit**

```bash
git add pytest.ini tests/conftest.py requirements.txt .gitignore data/portfolios/.gitkeep
git commit -m "chore: add test infrastructure and new dependencies for portfolio-doctor"
```

---

## Task 2: Extract shared/yf_client.py from core/macro_client.py

**Files:**
- Create: `shared/__init__.py`
- Create: `shared/yf_client.py`
- Modify: `core/macro_client.py`
- Modify: `core/fundamentals_client.py`
- Create: `tests/test_india_markets_unchanged.py`

The yfinance session management, caching, and `yf_latest()` currently live in
`core/macro_client.py`. Both `macro_client.py` and `fundamentals_client.py`
use `_get_yf_session()`. Extract to `shared/yf_client.py` so portfolio-doctor
can reuse without depending on india-markets internals.

- [ ] **Step 1: Write the regression test**

Create `tests/test_india_markets_unchanged.py` — verifies existing imports still resolve:

```python
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
```

- [ ] **Step 2: Run regression test — verify it passes before extraction**

Run: `.venv/bin/python -m pytest tests/test_india_markets_unchanged.py -v`
Expected: 3 PASSED

- [ ] **Step 3: Create shared/__init__.py**

```python
"""Shared utilities used by both india-markets and portfolio-doctor MCPs."""
```

- [ ] **Step 4: Create shared/yf_client.py**

Move `_get_yf_session`, `_safe_float`, `yf_latest`, and cache state from
`core/macro_client.py` into this file. The public API is:

```python
"""
Shared yfinance session management and price fetching.

Used by:
  - core/macro_client.py (india-markets Layer 4)
  - core/fundamentals_client.py (india-markets Layer 8)
  - shared/price_history.py (portfolio-doctor)
"""
from __future__ import annotations

import os
import time
from typing import Optional

import requests
import yfinance as yf

_YF_SESSION: Optional[object] = None


def get_yf_session() -> Optional[object]:
    """
    Return a pre-configured yfinance session that disables SSL verification
    when KITE_SSL_VERIFY=false (corporate proxy with self-signed cert).
    Returns None when no override is needed.
    """
    global _YF_SESSION
    if _YF_SESSION is not None:
        return _YF_SESSION

    if os.getenv("KITE_SSL_VERIFY", "true").lower() != "false":
        return None

    try:
        from curl_cffi import requests as curl_requests
        _YF_SESSION = curl_requests.Session(verify=False, impersonate="chrome110")
        return _YF_SESSION
    except Exception:
        pass

    s = requests.Session()
    s.verify = False
    _YF_SESSION = s
    return _YF_SESSION


def safe_float(val) -> Optional[float]:
    """Convert to float safely, returning None for NaN or non-numeric values."""
    try:
        f = float(val)
        return round(f, 4) if f == f else None
    except (TypeError, ValueError):
        return None


_YF_CACHE_TTL = 60
_yf_cache: dict[str, tuple[dict, float]] = {}


def yf_latest(ticker: str) -> dict:
    """
    Fetch the latest price and day-change for a yfinance ticker.
    Uses fast_info for minimal latency; falls back to 5-day history.
    """
    now = time.monotonic()
    if ticker in _yf_cache:
        cached, ts = _yf_cache[ticker]
        if now - ts < _YF_CACHE_TTL:
            return cached

    try:
        session = get_yf_session()
        t = yf.Ticker(ticker, session=session) if session is not None else yf.Ticker(ticker)
        fi = t.fast_info

        price      = safe_float(fi.last_price)
        prev_close = safe_float(fi.previous_close)
        day_high   = safe_float(fi.day_high)
        day_low    = safe_float(fi.day_low)

        if price is None or prev_close is None:
            hist = t.history(period="5d", interval="1d", auto_adjust=True)
            if not hist.empty:
                price      = price or round(float(hist["Close"].iloc[-1]), 4)
                prev_close = prev_close or (
                    round(float(hist["Close"].iloc[-2]), 4) if len(hist) >= 2 else None
                )

        change     = round(price - prev_close, 4) if price and prev_close else None
        change_pct = round(change / prev_close * 100, 2) if change and prev_close else None

        data: dict = {
            "ticker": ticker, "price": price, "prev_close": prev_close,
            "change": change, "change_pct": change_pct,
            "day_high": day_high, "day_low": day_low,
        }
    except Exception as e:
        data = {"ticker": ticker, "error": str(e)}

    _yf_cache[ticker] = (data, now)
    return data
```

- [ ] **Step 5: Slim down core/macro_client.py**

Replace `core/macro_client.py` with thin imports from shared. The entire file becomes:

```python
"""
Layer 4 — Global Macro
Raw data-fetch layer for yfinance (global markets and US Treasury yields).

Session management and caching now live in shared/yf_client.py.
This module re-exports what india-markets tools expect.
"""
from shared.yf_client import get_yf_session as _get_yf_session  # noqa: F401
from shared.yf_client import yf_latest  # noqa: F401
```

This preserves `from core.macro_client import _get_yf_session` for `fundamentals_client.py` and
`from core.macro_client import yf_latest` for `tools/macro_tools.py`.

- [ ] **Step 6: Update core/fundamentals_client.py imports**

Replace:
```python
from core.macro_client import _get_yf_session
```
With:
```python
from shared.yf_client import get_yf_session as _get_yf_session
```

Also replace the local `_safe_float` with:
```python
from shared.yf_client import safe_float as _safe_float
```

And replace the local `_nse_to_yf` definition — keep it for now (extracted in Task 3).

- [ ] **Step 7: Run regression test**

Run: `.venv/bin/python -m pytest tests/test_india_markets_unchanged.py -v`
Expected: 3 PASSED

- [ ] **Step 8: Commit**

```bash
git add shared/ core/macro_client.py core/fundamentals_client.py tests/test_india_markets_unchanged.py
git commit -m "refactor: extract shared/yf_client.py from core/macro_client.py"
```

---

## Task 3: Extract shared/nse_utils.py from core/fundamentals_client.py

**Files:**
- Create: `shared/nse_utils.py`
- Modify: `core/fundamentals_client.py`

- [ ] **Step 1: Write test for nse_to_yf**

Create `tests/shared/test_nse_utils.py`:
```python
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
```

- [ ] **Step 2: Run test — verify it fails**

Run: `.venv/bin/python -m pytest tests/shared/test_nse_utils.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Create shared/nse_utils.py**

```python
"""
NSE symbol utilities shared across MCPs.

Maps NSE trading symbols to Yahoo Finance tickers.
"""


def nse_to_yf(symbol: str) -> str:
    """Map NSE trading symbol to Yahoo Finance ticker."""
    sym = symbol.upper().strip()
    if sym.startswith("BSE:"):
        sym = sym[4:]
        if not sym.endswith(".BO"):
            sym = f"{sym}.BO"
        return sym
    for prefix in ("NSE:",):
        if sym.startswith(prefix):
            sym = sym[len(prefix):]
    if not sym.endswith(".NS") and not sym.endswith(".BO"):
        sym = f"{sym}.NS"
    return sym
```

Note: the current `_nse_to_yf` in `fundamentals_client.py` strips both `NSE:` and `BSE:` then
defaults to `.NS`. This loses the `.BO` suffix for BSE symbols. The improved version above
handles BSE correctly by appending `.BO`.

- [ ] **Step 4: Run test — verify it passes**

Run: `.venv/bin/python -m pytest tests/shared/test_nse_utils.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Update core/fundamentals_client.py**

Replace the local `_nse_to_yf` function with:
```python
from shared.nse_utils import nse_to_yf as _nse_to_yf
```

Remove the old `_nse_to_yf` function body.

- [ ] **Step 6: Run regression test**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All PASSED

- [ ] **Step 7: Commit**

```bash
git add shared/nse_utils.py core/fundamentals_client.py tests/shared/
git commit -m "refactor: extract shared/nse_utils.py from core/fundamentals_client.py"
```

---

## Task 4: Create shared/price_history.py

**Files:**
- Create: `shared/price_history.py`
- Create: `tests/shared/test_price_history.py`

Fetches daily OHLC for any NSE stock or index via yfinance. Used by portfolio-doctor to
compute historical portfolio values, alternative scenarios, and Nifty data for behavioral detectors.

Index ticker mapping: `fetch_price_history` should accept raw yfinance tickers (like `^NSEI` for Nifty)
when the symbol contains special characters. The `nse_to_yf` mapping is only applied when the symbol
looks like a plain NSE symbol (no `.` or `^` prefix). This lets callers pass `"^NSEI"` directly
for Nifty history or `"RELIANCE"` for equity.

- [ ] **Step 1: Write test**

Create `tests/shared/test_price_history.py`:
```python
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
    # Verify the ticker used was ^NSEI, not ^NSEI.NS
    call_args = mock_ticker_cls.call_args
    assert call_args[0][0] == "^NSEI"
```

- [ ] **Step 2: Run test — verify fail**

Run: `.venv/bin/python -m pytest tests/shared/test_price_history.py -v`
Expected: FAIL

- [ ] **Step 3: Implement shared/price_history.py**

```python
"""
Batch historical OHLC fetcher via yfinance.

Used by portfolio-doctor to compute portfolio value series and alternative
scenario returns. Fetches daily close data for NSE stocks (.NS tickers).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import yfinance as yf

from shared.nse_utils import nse_to_yf
from shared.yf_client import get_yf_session


def fetch_price_history(
    symbol: str,
    start_date: date,
    end_date: Optional[date] = None,
) -> dict:
    """
    Fetch daily OHLC for an NSE stock from start_date to end_date.

    Args:
        symbol: NSE trading symbol (e.g. "RELIANCE") or yfinance ticker
        start_date: First date (inclusive)
        end_date: Last date (inclusive). Defaults to today.

    Returns:
        {
            "symbol": str,
            "ticker": str,
            "prices": [{"date": "YYYY-MM-DD", "open": float, "high": float,
                         "low": float, "close": float, "volume": int}, ...],
            "count": int
        }
        On error: {"symbol": str, "error": str}
    """
    if end_date is None:
        end_date = date.today()

    # Pass through raw yfinance tickers (^NSEI, RELIANCE.NS, etc.)
    # Only apply nse_to_yf mapping for plain NSE symbols (no special chars)
    if "." in symbol or symbol.startswith("^"):
        ticker = symbol
    else:
        ticker = nse_to_yf(symbol)

    try:
        session = get_yf_session()
        t = yf.Ticker(ticker, session=session) if session else yf.Ticker(ticker)
        # yfinance end is exclusive, add 1 day
        hist = t.history(
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=True,
        )

        if hist.empty:
            return {"symbol": symbol, "ticker": ticker,
                    "error": f"No price data for {ticker} in range"}

        prices = []
        for dt, row in hist.iterrows():
            prices.append({
                "date": dt.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            })

        return {
            "symbol": symbol,
            "ticker": ticker,
            "prices": prices,
            "count": len(prices),
        }
    except Exception as e:
        return {"symbol": symbol, "ticker": ticker, "error": str(e)}


def get_close_series(symbol: str, start_date: date, end_date: Optional[date] = None) -> dict[str, float]:
    """
    Convenience: return {date_str: close_price} dict for quick lookups.
    Returns empty dict on error.
    """
    result = fetch_price_history(symbol, start_date, end_date)
    if "error" in result:
        return {}
    return {p["date"]: p["close"] for p in result["prices"]}
```

- [ ] **Step 4: Run test — verify pass**

Run: `.venv/bin/python -m pytest tests/shared/test_price_history.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add shared/price_history.py tests/shared/test_price_history.py
git commit -m "feat: add shared/price_history.py — batch OHLC fetcher via yfinance"
```

---

## Task 5: Create shared/mf_client.py

**Files:**
- Create: `shared/mf_client.py`
- Create: `tests/shared/test_mf_client.py`

Wraps `mftool` for mutual fund NAV history. AMFI scheme codes are the canonical identifier.

- [ ] **Step 1: Write test**

Create `tests/shared/test_mf_client.py`:
```python
from unittest.mock import patch, MagicMock
from datetime import date
from shared.mf_client import fetch_nav_history, validate_scheme_code


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
```

- [ ] **Step 2: Run test — verify fail**

Run: `.venv/bin/python -m pytest tests/shared/test_mf_client.py -v`
Expected: FAIL

- [ ] **Step 3: Implement shared/mf_client.py**

```python
"""
Mutual Fund NAV history via mftool (AMFI public data).

Used by portfolio-doctor for:
  - MF position valuation (daily NAVs for per-lot tracking)
  - Alternative scenario modeling (index fund / popular MF SIPs)
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from mftool import Mf

_mf = None


def _get_mf() -> Mf:
    global _mf
    if _mf is None:
        _mf = Mf()
    return _mf


def validate_scheme_code(scheme_code: str) -> dict:
    """
    Validate an AMFI scheme code exists and return scheme details.

    Returns:
        {"valid": True, "scheme_code": str, "scheme_name": str}
        or {"valid": False, "scheme_code": str, "error": str}
    """
    try:
        mf = _get_mf()
        details = mf.get_scheme_details(scheme_code)
        name = details.get("scheme_name", "")
        if not name:
            return {"valid": False, "scheme_code": scheme_code,
                    "error": "Scheme code not found in AMFI database"}
        return {"valid": True, "scheme_code": scheme_code, "scheme_name": name}
    except Exception as e:
        return {"valid": False, "scheme_code": scheme_code, "error": str(e)}


def fetch_nav_history(
    scheme_code: str,
    start_date: date,
    end_date: Optional[date] = None,
) -> dict:
    """
    Fetch daily NAV history for a mutual fund scheme.

    Args:
        scheme_code: AMFI scheme code (e.g. "119551")
        start_date: First date (inclusive)
        end_date: Last date (inclusive). Defaults to today.

    Returns:
        {
            "scheme_code": str,
            "navs": [{"date": "YYYY-MM-DD", "nav": float}, ...],
            "count": int,
        }
        On error: {"scheme_code": str, "error": str}
    """
    if end_date is None:
        end_date = date.today()

    try:
        mf = _get_mf()
        raw = mf.get_scheme_historical_nav(
            scheme_code,
            start_date.strftime("%d-%m-%Y"),
            end_date.strftime("%d-%m-%Y"),
        )

        data_list = raw.get("data", [])
        if not data_list:
            return {"scheme_code": scheme_code,
                    "error": f"No NAV data for scheme {scheme_code} in range"}

        navs = []
        for entry in data_list:
            try:
                d = entry["date"]
                parts = d.split("-")
                iso_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
                navs.append({
                    "date": iso_date,
                    "nav": round(float(entry["nav"]), 4),
                })
            except (KeyError, ValueError, IndexError):
                continue

        navs.sort(key=lambda x: x["date"])
        return {"scheme_code": scheme_code, "navs": navs, "count": len(navs)}
    except Exception as e:
        return {"scheme_code": scheme_code, "error": str(e)}


def get_nav_series(scheme_code: str, start_date: date, end_date: Optional[date] = None) -> dict[str, float]:
    """Convenience: return {date_str: nav} dict for quick lookups."""
    result = fetch_nav_history(scheme_code, start_date, end_date)
    if "error" in result:
        return {}
    return {n["date"]: n["nav"] for n in result["navs"]}
```

- [ ] **Step 4: Run test — verify pass**

Run: `.venv/bin/python -m pytest tests/shared/test_mf_client.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add shared/mf_client.py tests/shared/test_mf_client.py
git commit -m "feat: add shared/mf_client.py — MF NAV history via mftool"
```

---

## Task 6: Portfolio Doctor Directory Scaffolding

**Files:**
- Create: `portfolio_doctor/__init__.py`
- Create: `portfolio_doctor/core/__init__.py`
- Create: `portfolio_doctor/tools/__init__.py`
- Create: `portfolio_doctor/server/__init__.py`

- [x] **Step 1: Create all package markers**

```bash
mkdir -p portfolio_doctor/core portfolio_doctor/tools portfolio_doctor/server
touch portfolio_doctor/__init__.py portfolio_doctor/core/__init__.py \
      portfolio_doctor/tools/__init__.py portfolio_doctor/server/__init__.py
```

- [x] **Step 2: Commit**

```bash
git add portfolio_doctor/
git commit -m "chore: scaffold portfolio_doctor package directories"
```

---

## Task 7: CSV Parser — Parse, Validate, Build Trade Ledger

**Files:**
- Create: `portfolio_doctor/core/csv_parser.py`
- Create: `tests/portfolio_doctor/core/test_csv_parser.py`

This is the most important module — it's the entry point for all data.
Split into phases: parse → validate → build positions → build cash flows → detect SIPs.

- [x] **Step 1: Write parser tests**

Create `tests/portfolio_doctor/core/test_csv_parser.py`:

```python
import pytest
from datetime import date
from portfolio_doctor.core.csv_parser import (
    parse_csv,
    validate_trades,
    build_position_ledger,
    build_cash_flows,
    detect_sip_patterns,
)


class TestParseCsv:
    def test_parses_valid_csv(self, tmp_csv):
        trades = parse_csv(tmp_csv)
        assert len(trades) == 3
        assert trades[0]["symbol"] == "RELIANCE"
        assert trades[0]["date"] == date(2020, 1, 15)

    def test_parses_quantity_as_float(self, tmp_csv):
        trades = parse_csv(tmp_csv)
        mf_trade = [t for t in trades if t["instrument_type"] == "MF"][0]
        assert mf_trade["quantity"] == 200.5

    def test_rejects_missing_required_columns(self, tmp_path):
        p = tmp_path / "bad.csv"
        p.write_text("date,symbol\n2020-01-01,RELIANCE\n")
        with pytest.raises(ValueError, match="Missing required columns"):
            parse_csv(str(p))


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


class TestBuildPositionLedger:
    def test_fifo_equity(self, sample_equity_trades):
        ledger = build_position_ledger(sample_equity_trades)
        rel = ledger["RELIANCE"]
        assert rel["quantity"] == 30  # 50 bought - 20 sold
        assert rel["instrument_type"] == "EQUITY"

    def test_mf_per_lot_tracking(self, sample_mf_trades):
        ledger = build_position_ledger(sample_mf_trades)
        mf = ledger["119551"]
        assert len(mf["lots"]) == 2
        assert mf["total_quantity"] == pytest.approx(395.8)


class TestBuildCashFlows:
    def test_buy_is_negative_flow(self, sample_equity_trades):
        flows = build_cash_flows(sample_equity_trades)
        buys = [f for f in flows if f["amount"] < 0]
        assert len(buys) == 2  # RELIANCE buy + HDFCBANK buy

    def test_sell_is_positive_flow(self, sample_equity_trades):
        flows = build_cash_flows(sample_equity_trades)
        sells = [f for f in flows if f["amount"] > 0]
        assert len(sells) == 1

    def test_sorted_by_date(self, sample_equity_trades):
        flows = build_cash_flows(sample_equity_trades)
        dates = [f["date"] for f in flows]
        assert dates == sorted(dates)


class TestDetectSipPatterns:
    def test_detects_monthly_sip(self, sample_mf_trades):
        patterns = detect_sip_patterns(sample_mf_trades)
        assert len(patterns) >= 1
        assert patterns[0]["scheme_code"] == "119551"
        assert patterns[0]["frequency"] == "monthly"
```

- [x] **Step 2: Run tests — verify fail**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/core/test_csv_parser.py -v`
Expected: FAIL (module not found)

- [x] **Step 3: Implement csv_parser.py — parse_csv function**

Create `portfolio_doctor/core/csv_parser.py`. Implement `parse_csv(csv_path) -> list[dict]`:
- Read CSV with pandas
- Validate required columns: `date`, `instrument_type`, `symbol`, `action`, `quantity`, `price`
- Parse dates to `datetime.date`
- Normalize `instrument_type` to uppercase
- Normalize `action` to uppercase
- Cast `quantity` and `price` to float
- Sort by date ascending
- Raise `ValueError` if required columns missing

- [x] **Step 4: Implement validate_trades function**

Add `validate_trades(trades: list[dict]) -> list[str]` to `csv_parser.py`:
- Track running quantity per symbol
- Warn if sell quantity exceeds held quantity
- Warn on duplicate rows (same date/symbol/action/qty/price)
- Warn (don't reject) on weekend dates
- Return list of warning strings

- [x] **Step 5: Implement build_position_ledger function**

Add `build_position_ledger(trades: list[dict]) -> dict` to `csv_parser.py`:
- For EQUITY: FIFO cost basis tracking. Each position has `quantity`, `avg_cost`, `invested`, `instrument_type`
- For MF: per-lot tracking. Each purchase is a separate lot `{"date", "quantity", "price", "amount"}`. Sells consume oldest lots first (FIFO). Position has `lots`, `total_quantity`, `instrument_type`
- Return dict keyed by symbol

- [x] **Step 6: Implement build_cash_flows function**

Add `build_cash_flows(trades: list[dict]) -> list[dict]` to `csv_parser.py`:
- BUY/SIP/SWITCH_IN = negative cash flow (money goes out)
- SELL/SWP/SWITCH_OUT = positive cash flow (money comes back)
- Each entry: `{"date": date, "amount": float, "symbol": str, "action": str}`
- Sorted by date ascending

Note: The spec places `compute_cash_flows` under portfolio_engine, but cash flow
construction is pure parsing (no pricing data needed), so it lives in csv_parser.
`portfolio_engine.compute_cash_flows` is a re-export alias:
```python
from portfolio_doctor.core.csv_parser import build_cash_flows as compute_cash_flows
```

- [x] **Step 7: Implement detect_sip_patterns function**

Add `detect_sip_patterns(trades: list[dict]) -> list[dict]` to `csv_parser.py`:
- Filter MF trades with action "SIP"
- Group by scheme code
- For each group: check if trades are ~monthly (25–35 day gaps), similar amounts (within 20%)
- Return list of `{"scheme_code", "scheme_name", "frequency", "avg_amount", "start_date", "end_date", "total_sips"}`

- [x] **Step 7.5: Implement symbol validation at ingest time**

Add `validate_symbols(trades: list[dict]) -> list[str]` to `csv_parser.py`:
- For EQUITY trades: call `shared.nse_utils.nse_to_yf(symbol)` and do a lightweight
  yfinance ticker check (`yf.Ticker(ticker).fast_info`) to confirm the symbol exists.
  Add warning (not error) on failure — user may have delisted stocks.
- For MF trades: call `shared.mf_client.validate_scheme_code(symbol)`. Warn if invalid.
  If `scheme_name` is provided, cross-check it matches AMFI's name (fuzzy — warn on mismatch).
- Return list of warning strings (merged into `validate_trades` warnings).
- This runs during `ingest_client_trades` after `parse_csv` and before `build_position_ledger`.

Note: Symbol validation requires network calls, so keep it separate from pure `validate_trades`.
Test with mocked yfinance/mftool.

- [x] **Step 8: Run tests — verify pass**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/core/test_csv_parser.py -v`
Expected: All PASSED

- [x] **Step 9: Commit**

```bash
git add portfolio_doctor/core/csv_parser.py tests/portfolio_doctor/
git commit -m "feat: add csv_parser — parse, validate, build trade ledger and cash flows"
```

---

## Task 8: Portfolio Engine — Holdings, Returns, XIRR, Allocation

**Files:**
- Create: `portfolio_doctor/core/portfolio_engine.py`
- Create: `tests/portfolio_doctor/core/test_portfolio_engine.py`

The math layer. Computes returns, portfolio value series, allocation, turnover, tax drag.

- [ ] **Step 1: Write tests**

Create `tests/portfolio_doctor/core/test_portfolio_engine.py`:

```python
import pytest
from datetime import date
from portfolio_doctor.core.portfolio_engine import (
    compute_holdings,
    compute_xirr,
    compute_portfolio_value_series,
    compute_sector_allocation,
    compute_turnover,
    compute_returns,
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


class TestComputePortfolioValueSeries:
    def test_returns_daily_values(self, sample_equity_trades):
        price_data = {
            "RELIANCE": {"2020-01-15": 1500, "2020-01-16": 1510, "2020-01-17": 1520},
            "HDFCBANK": {"2020-01-15": 850, "2020-01-16": 855, "2020-01-17": 860},
        }
        # Only test that the function returns a list of date/value pairs
        # and that values increase with prices
        series = compute_portfolio_value_series(
            sample_equity_trades[:1], price_data,
            start_date=date(2020, 1, 15), end_date=date(2020, 1, 17)
        )
        assert len(series) >= 1


class TestComputeTurnover:
    def test_calculates_ratio(self):
        trades = [
            {"date": date(2020, 1, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1500, "instrument_type": "EQUITY", "amount": 75000},
            {"date": date(2020, 6, 1), "symbol": "RELIANCE", "action": "SELL",
             "quantity": 50, "price": 1800, "instrument_type": "EQUITY", "amount": 90000},
        ]
        ratio = compute_turnover(trades, avg_portfolio_value=100000)
        assert ratio == pytest.approx(0.9)  # 90000 sells / 100000 avg
```

- [ ] **Step 2: Run tests — verify fail**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/core/test_portfolio_engine.py -v`
Expected: FAIL

- [ ] **Step 3: Implement portfolio_engine.py — compute_holdings**

Create `portfolio_doctor/core/portfolio_engine.py`.

`compute_holdings(trades, as_of_date)`: Filters trades up to `as_of_date`.
For each symbol, tracks running position using FIFO for equity, per-lot for MF.
Returns dict of symbols → `{"quantity", "avg_cost", "invested", "instrument_type", "lots" (MF only)}`.
Excludes positions with zero quantity.

- [ ] **Step 4: Implement compute_xirr**

`compute_xirr(cash_flows: list[tuple[date, float]]) -> float`:
- Uses `scipy.optimize.brentq` to solve for the rate
- Cash flows: negative = money out, positive = money in
- The last entry should be the current portfolio value as a positive inflow
- Returns annualized rate as a decimal (0.15 = 15%)
- Returns 0.0 if cannot solve

- [ ] **Step 5: Implement compute_returns**

`compute_returns(trades, current_prices, as_of_date)`:
- Computes per-position returns (absolute ₹, %)
- Builds cash flow timeline and adds current value as terminal inflow
- Calls `compute_xirr` for portfolio-level XIRR
- Computes time-weighted return (TWR): chain daily portfolio returns from value series
- Computes annualized return: `(1 + total_return) ^ (365 / days) - 1`
- Accounts for brokerage/transaction costs in actual returns (sum `brokerage` field from trades)
- Returns `{"positions": [...], "portfolio_xirr", "time_weighted_return", "annualized_return", "total_invested", "current_value", "absolute_return", "return_pct", "total_brokerage"}`

- [ ] **Step 6: Implement compute_portfolio_value_series**

`compute_portfolio_value_series(trades, price_data, start_date, end_date)`:
- Walk day-by-day from first trade to end_date
- At each date, compute total portfolio value from held positions × closing prices
- `price_data` is `{symbol: {date_str: close_price}}`
- Skip dates with no price data (weekends/holidays)
- Returns list of `{"date": str, "value": float}`

- [ ] **Step 7: Implement compute_sector_allocation, compute_turnover, compute_tax_drag**

- `compute_sector_allocation(holdings, sector_map)`: Maps symbols to sectors. MFs tagged by type (equity MF, debt MF, hybrid). Returns `{"sectors": {sector: weight_pct}, "types": {type: weight_pct}}`
- `compute_turnover(trades, avg_portfolio_value)`: Sums all SELL trade amounts from `trades`, divides by `avg_portfolio_value`. Matches spec signature — the engine owns aggregation.
- `compute_tax_drag(trades, price_data)`: Estimate STCG (15%) and LTCG (10% above ₹1L) on realized gains. Equity-oriented: held <1yr = STCG, >1yr = LTCG. Subtract cumulative brokerage from the CSV `brokerage` field. Returns `{"stcg_estimated", "ltcg_estimated", "total_tax_drag", "total_brokerage"}`

- [ ] **Step 8: Run tests — verify pass**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/core/test_portfolio_engine.py -v`
Expected: All PASSED

- [ ] **Step 9: Commit**

```bash
git add portfolio_doctor/core/portfolio_engine.py tests/portfolio_doctor/core/test_portfolio_engine.py
git commit -m "feat: add portfolio_engine — holdings, XIRR, value series, allocation"
```

---

## Task 9: Behavioral Engine — All 9 Detectors + Composite

**Files:**
- Create: `portfolio_doctor/core/behavioral_engine.py`
- Create: `tests/portfolio_doctor/core/test_behavioral_engine.py`

Detects behavioral patterns, scores them, quantifies cost. Each detector is a
standalone function returning a structured result dict.

- [ ] **Step 1: Write tests for timing detectors**

Create `tests/portfolio_doctor/core/test_behavioral_engine.py`:

```python
import pytest
from datetime import date
from portfolio_doctor.core.behavioral_engine import (
    detect_panic_selling,
    detect_fomo_buying,
    detect_disposition_effect,
    detect_overtrading,
    detect_concentration_risk,
    detect_sip_discipline,
    detect_herd_behavior,
    detect_anchoring_bias,
    detect_regular_plan_waste,
    compute_behavioral_composite,
)


class TestPanicSelling:
    def test_detects_sell_during_crash(self):
        trades = [
            {"date": date(2020, 1, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1500, "instrument_type": "EQUITY"},
            {"date": date(2020, 3, 23), "symbol": "RELIANCE", "action": "SELL",
             "quantity": 50, "price": 900, "instrument_type": "EQUITY"},
        ]
        nifty_data = {
            "2020-01-01": 12200, "2020-02-01": 12000,
            "2020-03-01": 11200, "2020-03-23": 8000,
        }
        result = detect_panic_selling(trades, nifty_data)
        assert result["pattern"] == "panic_selling"
        assert result["score"] < 0
        assert len(result["instances"]) >= 1

    def test_no_panic_in_normal_market(self):
        trades = [
            {"date": date(2020, 1, 1), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1500, "instrument_type": "EQUITY"},
            {"date": date(2020, 6, 1), "symbol": "RELIANCE", "action": "SELL",
             "quantity": 50, "price": 1600, "instrument_type": "EQUITY"},
        ]
        nifty_data = {
            "2020-01-01": 12200, "2020-06-01": 12500,
        }
        result = detect_panic_selling(trades, nifty_data)
        assert len(result["instances"]) == 0
        assert result["score"] >= 0


class TestDispositionEffect:
    def test_detects_holding_losers_longer(self):
        trades = [
            {"date": date(2019, 1, 1), "symbol": "WINNER", "action": "BUY",
             "quantity": 10, "price": 100, "instrument_type": "EQUITY"},
            {"date": date(2019, 3, 1), "symbol": "WINNER", "action": "SELL",
             "quantity": 10, "price": 130, "instrument_type": "EQUITY"},
            {"date": date(2019, 1, 1), "symbol": "LOSER", "action": "BUY",
             "quantity": 10, "price": 100, "instrument_type": "EQUITY"},
            {"date": date(2020, 6, 1), "symbol": "LOSER", "action": "SELL",
             "quantity": 10, "price": 80, "instrument_type": "EQUITY"},
        ]
        result = detect_disposition_effect(trades)
        assert result["pattern"] == "disposition_effect"
        assert result["score"] < 0


class TestConcentrationRisk:
    def test_detects_single_stock_overweight(self):
        holdings = {
            "RELIANCE": {"value": 800000},
            "TCS": {"value": 100000},
            "INFY": {"value": 100000},
        }
        result = detect_concentration_risk(holdings, total_value=1000000)
        assert result["pattern"] == "concentration_risk"
        assert result["score"] < 0
        assert result["severity"] in ("medium", "high")


class TestOvertrading:
    def test_detects_frequent_round_trips(self):
        trades = []
        for i in range(6):
            trades.append({"date": date(2020, 1, 1 + i*5), "symbol": "RELIANCE",
                           "action": "BUY", "quantity": 10, "price": 1500,
                           "instrument_type": "EQUITY"})
            trades.append({"date": date(2020, 1, 3 + i*5), "symbol": "RELIANCE",
                           "action": "SELL", "quantity": 10, "price": 1510,
                           "instrument_type": "EQUITY"})
        result = detect_overtrading(trades, total_days=30)
        assert result["pattern"] == "overtrading"
        assert result["score"] < 0


class TestSipDiscipline:
    def test_maintained_through_crash_is_positive(self):
        sip_patterns = [{"scheme_code": "119551", "start_date": date(2019, 6, 1),
                         "end_date": date(2020, 12, 1), "total_sips": 18}]
        nifty_data = {"2020-03-01": 8500, "2020-03-23": 7500,
                      "2019-12-01": 12000, "2020-06-01": 10000}
        result = detect_sip_discipline(sip_patterns, nifty_data)
        assert result["score"] > 0


class TestBehavioralComposite:
    def test_returns_weighted_score(self):
        detector_results = [
            {"pattern": "panic_selling", "score": -0.5, "severity": "medium",
             "instances": [], "cost_estimate": 10000, "evidence_summary": ""},
            {"pattern": "fomo_buying", "score": 0.0, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
            {"pattern": "disposition_effect", "score": -0.3, "severity": "medium",
             "instances": [], "cost_estimate": 5000, "evidence_summary": ""},
            {"pattern": "overtrading", "score": -0.2, "severity": "low",
             "instances": [], "cost_estimate": 2000, "evidence_summary": ""},
            {"pattern": "concentration_risk", "score": 0.0, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
            {"pattern": "herd_behavior", "score": 0.0, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
            {"pattern": "anchoring_bias", "score": 0.0, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
            {"pattern": "sip_discipline", "score": 0.8, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
            {"pattern": "regular_plan_waste", "score": 0.0, "severity": "low",
             "instances": [], "cost_estimate": 0, "evidence_summary": ""},
        ]
        composite = compute_behavioral_composite(detector_results)
        assert -1.0 <= composite["composite_score"] <= 1.0
        assert "top_issues" in composite
        assert composite["top_issues"][0]["cost_estimate"] == 10000  # panic is costliest
```

- [ ] **Step 2: Run tests — verify fail**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/core/test_behavioral_engine.py -v`
Expected: FAIL

- [ ] **Step 3: Implement timing detectors**

Create `portfolio_doctor/core/behavioral_engine.py` with:

**`detect_panic_selling(trades, nifty_data)`**: For each SELL trade, check if Nifty was >10% below its recent 52-week high at the trade date. Score = `-0.3 * (drawdown / 20)` capped at -1.0. Include `cost_estimate` = post-sell recovery × quantity.

**`detect_fomo_buying(trades, nifty_data, stock_dma_data=None)`**: For each BUY, check if stock price was >20% above its 200 DMA or Nifty was near ATH (<2% from peak). Score by subsequent 3-month drawdown from buy price. Negative score = bad FOMO.

All detectors return the standard result dict:
```python
{"pattern": str, "score": float, "severity": str,
 "instances": list, "cost_estimate": float, "evidence_summary": str}
```

- [ ] **Step 4: Implement disposition + overtrading detectors**

**`detect_disposition_effect(trades)`**: Compare avg holding period (days) of winning sells vs losing sells. If winners held significantly shorter than losers, negative score. Ratio = avg_loser_days / avg_winner_days. Score = `-(ratio - 1) * 0.3` capped.

**`detect_overtrading(trades, total_days)`**: Count trades per month. Flag months with >10 trades. Calculate round-trip trades (buy+sell same stock within 30 days). Score = `-0.2 * (round_trips / total_sells)`.
v1 scope: round-trip count and frequency. Churn cost as % of returns (spec §3) deferred to v2.

- [ ] **Step 5: Implement concentration + herd + anchoring detectors**

**`detect_concentration_risk(holdings, total_value)`**: Max single-stock weight, top-5 concentration. Score: single stock >40% = -0.8; >30% = -0.5; >20% = -0.3.
v1 scope: point-in-time weight snapshot. Sector concentration over time (spec §3) deferred to v2.

**`detect_herd_behavior(trades, stock_price_data)`**: For each BUY, check if the stock ran >30% in the prior month. Score by frequency of herd buys.

**`detect_anchoring_bias(trades)`**: Find sells at ±2% of original buy price (breakeven sells). Score by frequency.

- [ ] **Step 6: Implement SIP detectors + composite**

**`detect_sip_discipline(sip_patterns, nifty_data)`**: Check SIP consistency during market drawdowns. SIPs maintained during crash = +1.0. SIPs stopped = -0.5. No SIPs = neutral.

**`detect_regular_plan_waste(trades)`**: Flag MF holdings in regular plans where direct plan exists. Estimate cumulative expense ratio drag (~0.5-1.0% pa).

**`compute_behavioral_composite(detector_results) -> dict`**: Apply weighted average with spec weights (timing 25%, disposition 20%, overtrading 20%, concentration 15%, herd+anchoring 10%, SIP 10%). Return `{"composite_score", "severity", "top_issues": [...top 3 by cost]}`.

- [ ] **Step 7: Run tests — verify pass**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/core/test_behavioral_engine.py -v`
Expected: All PASSED

- [ ] **Step 8: Commit**

```bash
git add portfolio_doctor/core/behavioral_engine.py tests/portfolio_doctor/core/test_behavioral_engine.py
git commit -m "feat: add behavioral_engine — 9 detectors + composite behavioral score"
```

---

## Task 10: Alternatives Engine — 5 Scenario Comparisons

**Files:**
- Create: `portfolio_doctor/core/alternatives_engine.py`
- Create: `tests/portfolio_doctor/core/test_alternatives_engine.py`

Same cash flows, different vehicles. Each scenario returns structured comparison data.

- [ ] **Step 1: Write tests**

Create `tests/portfolio_doctor/core/test_alternatives_engine.py`:

```python
import pytest
from datetime import date
from portfolio_doctor.core.alternatives_engine import (
    simulate_nifty_sip,
    simulate_buy_and_hold,
    simulate_mf_sip,
    run_all_scenarios,
)


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
        assert result["scenario"] == "nifty_50_sip"
        assert result["total_invested"] == 100500
        assert result["final_value"] > 0

    def test_handles_missing_nav_dates(self):
        cash_flows = [{"date": date(2020, 1, 15), "amount": -50000}]
        nifty_nav = {"2020-01-16": 100.0, "2026-03-31": 200.0}
        result = simulate_nifty_sip(cash_flows, nifty_nav, end_date=date(2026, 3, 31))
        assert "error" not in result or result.get("units_purchased", 0) > 0


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
        assert result["scenario"] == "buy_and_hold"
        # Buy & hold: 50 shares × 2500 = 125000
        assert result["final_value"] == 125000


class TestRunAllScenarios:
    def test_returns_all_scenarios(self):
        cash_flows = [{"date": date(2020, 1, 15), "amount": -75000}]
        trades = [
            {"date": date(2020, 1, 15), "symbol": "RELIANCE", "action": "BUY",
             "quantity": 50, "price": 1500, "instrument_type": "EQUITY"},
        ]
        # run_all_scenarios needs price data dicts — test with minimal stubs
        result = run_all_scenarios(
            cash_flows=cash_flows,
            trades=trades,
            actual_return={"xirr": 0.12, "final_value": 90000, "total_invested": 75000},
            nifty_nav={"2020-01-15": 100.0, "2026-03-31": 180.0},
            mf_navs={},
            current_prices={"RELIANCE": 1800.0},
            end_date=date(2026, 3, 31),
        )
        assert len(result) >= 2  # at least nifty_sip + buy_and_hold
```

- [ ] **Step 2: Run tests — verify fail**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/core/test_alternatives_engine.py -v`
Expected: FAIL

- [ ] **Step 3: Implement nifty_sip + buy_and_hold scenarios**

Create `portfolio_doctor/core/alternatives_engine.py`:

**`simulate_nifty_sip(cash_flows, nifty_nav, end_date)`**:
- For each negative cash flow (investment), use the same amount to "buy" Nifty units at that date's NAV
- Find nearest available NAV date if exact date missing
- Final value = total units × latest NAV
- Compute XIRR using `portfolio_engine.compute_xirr`
- Return standard scenario result dict (see spec section 3)

**`simulate_buy_and_hold(trades, current_prices)`**:
- Take only BUY trades, ignore all SELLs
- Total held = sum of all bought quantities per symbol
- Final value = sum(quantity × current_price)
- Return scenario result dict

- [ ] **Step 4: Implement MF SIP scenarios + model portfolios**

**`simulate_mf_sip(cash_flows, mf_nav, scheme_code, end_date)`**:
- Same logic as nifty_sip but uses mutual fund NAVs
- Called for each of the 4 popular MF schemes from the spec

**`simulate_model_portfolio(cash_flows, equity_nav, debt_nav, equity_pct, end_date)`**:
- Split each cash flow: equity_pct goes to equity NAV, rest to debt NAV
- Combine final values
- Used for 100% equity, 70/30, 50/50

**`simulate_no_reentry(trades, current_prices)`**:
- For stocks bought → sold → bought again: hold from first buy only
- Returns value if client never re-entered after first buy

- [ ] **Step 5: Implement run_all_scenarios orchestrator**

**`run_all_scenarios(...)`**: Calls each scenario function, catches errors per scenario,
computes `vs_actual` for each (return difference, value difference, interpretation).
Returns `list[dict]` of all scenario results.

Exact scenario list for the UI (5 rows in Section D bar chart):
1. `nifty_50_sip` — UTI Nifty 50 Index Direct (scheme 120716) as TRI proxy
2. `popular_mf_sip` — best-performing of schemes 120716, 122639, 118989, 119065 (return the best + mention others in metadata)
3. `model_70_30` — 70% equity (Nifty proxy) / 30% debt (HDFC Liquid, scheme 119062)
4. `buy_and_hold` — same stocks, same buy timing, never sell
5. `no_reentry` — for stocks with buy→sell→buy patterns: hold from first buy

The 100% equity and 50/50 model portfolios are computed but included as metadata rows, not primary bars. This keeps the UI clean at 5 scenarios per spec §4.

- [ ] **Step 6: Run tests — verify pass**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/core/test_alternatives_engine.py -v`
Expected: All PASSED

- [ ] **Step 7: Commit**

```bash
git add portfolio_doctor/core/alternatives_engine.py tests/portfolio_doctor/core/test_alternatives_engine.py
git commit -m "feat: add alternatives_engine — 5 what-if scenario comparisons"
```

---

## Task 11: MCP Tools — portfolio_tools.py (ingest + overview)

**Files:**
- Create: `portfolio_doctor/tools/portfolio_tools.py`

Tools layer: thin wrappers that orchestrate engines and manage file storage.
Follows the three-layer pattern (no MCP imports here).

- [ ] **Step 1: Implement ingest_client_trades**

Create `portfolio_doctor/tools/portfolio_tools.py`:

```python
"""
Portfolio Doctor tools — portfolio ingestion and overview.

Orchestrates csv_parser and portfolio_engine. Manages file I/O to
data/portfolios/{client_name}/.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from portfolio_doctor.core.csv_parser import (
    parse_csv,
    validate_trades,
    validate_symbols,
    build_position_ledger,
    build_cash_flows,
    detect_sip_patterns,
)

PORTFOLIO_DIR = Path("data/portfolios")


def _client_dir(client_name: str) -> Path:
    d = PORTFOLIO_DIR / client_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_json(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _load_json(path: Path) -> dict | list:
    with open(path) as f:
        return json.load(f)


def ingest_client_trades(csv_path: str, client_name: str) -> dict:
    """
    Parse and validate a client's trading CSV, store processed data.

    Returns validation summary with trade count, date range, symbols, etc.
    """
    try:
        trades = parse_csv(csv_path)
        warnings = validate_trades(trades)
        symbol_warnings = validate_symbols(trades)
        warnings.extend(symbol_warnings)
        ledger = build_position_ledger(trades)
        cash_flows = build_cash_flows(trades)
        sip_patterns = detect_sip_patterns(trades)

        cdir = _client_dir(client_name)
        _save_json(cdir / "trades.json", trades)
        _save_json(cdir / "positions.json", ledger)
        _save_json(cdir / "cashflows.json", cash_flows)
        _save_json(cdir / "sip_patterns.json", sip_patterns)

        symbols = sorted(set(t["symbol"] for t in trades))
        equity_count = sum(1 for s, p in ledger.items() if p.get("instrument_type") == "EQUITY")
        mf_count = sum(1 for s, p in ledger.items() if p.get("instrument_type") == "MF")

        return {
            "client_name": client_name,
            "trade_count": len(trades),
            "date_range": {
                "first": str(trades[0]["date"]) if trades else None,
                "last": str(trades[-1]["date"]) if trades else None,
            },
            "symbols": symbols,
            "equity_positions": equity_count,
            "mf_positions": mf_count,
            "capital_deployed": sum(abs(cf["amount"]) for cf in cash_flows if cf["amount"] < 0),
            "sip_patterns_detected": len(sip_patterns),
            "warnings": warnings,
            "status": "ingested",
        }
    except Exception as e:
        return {"error": str(e), "client_name": client_name}
```

- [ ] **Step 2: Implement get_portfolio_overview**

Add to `portfolio_tools.py`:

`get_portfolio_overview(client_name)`: Loads stored trades and positions. Fetches current prices via `shared/price_history.py` and `shared/mf_client.py`. Calls `portfolio_engine.compute_returns`, `compute_sector_allocation`, `compute_turnover`, `compute_tax_drag`. Returns structured overview dict.

The function should:
- Load `trades.json` and `positions.json` from the client directory
- Fetch current prices for all equity holdings via yfinance
- Fetch current NAVs for all MF holdings via mftool
- Get sector info via yfinance `.info` for allocation mapping
- Call portfolio_engine functions and assemble result
- Cache results to `overview.json`

- [ ] **Step 3: Commit**

```bash
git add portfolio_doctor/tools/portfolio_tools.py
git commit -m "feat: add portfolio_tools — ingest_client_trades and portfolio_overview"
```

---

## Task 12: MCP Tools — behavioral_tools.py + alternative_tools.py

**Files:**
- Create: `portfolio_doctor/tools/behavioral_tools.py`
- Create: `portfolio_doctor/tools/alternative_tools.py`

- [ ] **Step 1: Implement behavioral_tools.py**

Create `portfolio_doctor/tools/behavioral_tools.py`:

`get_behavioral_audit(client_name)`:
- Load trades from client dir
- Fetch Nifty price history via `shared/price_history.py` (needed for panic/FOMO detection)
- Fetch stock price data for holdings (needed for herd detection, DMA context)
- Call all 9 detectors from `behavioral_engine`
- Call `compute_behavioral_composite`
- Save results to `behavioral_audit.json`
- Return: all 9 detector results + composite score + top 3 costliest behaviors

- [ ] **Step 2: Implement alternative_tools.py**

Create `portfolio_doctor/tools/alternative_tools.py`:

`get_alternative_scenarios(client_name)`:
- Load trades and cash flows from client dir
- Load portfolio_overview results (or compute if missing)
- Fetch Nifty NAV history (use UTI Nifty 50 Index Direct scheme 120716 via mftool as TRI proxy)
- Fetch popular MF NAVs (schemes 120716, 122639, 118989, 119065)
- Fetch HDFC Liquid Fund NAV (scheme 119062) for debt leg
- Call `run_all_scenarios` from alternatives_engine
- Save results to `alternatives.json`
- Return all scenario comparisons

- [ ] **Step 3: Commit**

```bash
git add portfolio_doctor/tools/behavioral_tools.py portfolio_doctor/tools/alternative_tools.py
git commit -m "feat: add behavioral_tools and alternative_tools"
```

---

## Task 13: MCP Tools — report_tools.py (action plan + full report)

**Files:**
- Create: `portfolio_doctor/tools/report_tools.py`
- Create: `tests/portfolio_doctor/tools/test_report_tools.py`

- [ ] **Step 1: Write test for action_plan logic**

Create `tests/portfolio_doctor/tools/test_report_tools.py`:

```python
from portfolio_doctor.tools.report_tools import build_action_plan


def test_generates_start_stop_keep():
    behavioral = {
        "composite_score": -0.4,
        "detectors": [
            {"pattern": "panic_selling", "score": -0.7, "severity": "high",
             "cost_estimate": 45000, "evidence_summary": "Sold during March 2020 crash"},
            {"pattern": "sip_discipline", "score": 0.8, "severity": "low",
             "cost_estimate": 0, "evidence_summary": "SIPs maintained through crash"},
        ],
    }
    alternatives = [
        {"scenario": "nifty_50_sip", "vs_actual": {"value_difference": 48000}},
    ]
    plan = build_action_plan(behavioral, alternatives)
    assert "start" in plan
    assert "stop" in plan
    assert "keep" in plan
```

- [ ] **Step 2: Run test — verify fail**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/tools/test_report_tools.py -v`
Expected: FAIL

- [ ] **Step 3: Implement report_tools.py**

Create `portfolio_doctor/tools/report_tools.py`:

**`build_action_plan(behavioral_results, alternative_results)`**:
- START: recommendations based on what alternatives outperformed (e.g., "Start a Nifty 50 SIP")
  + recommendations to fix behavioral issues (e.g., "Set stop-loss rules to prevent panic selling")
- STOP: costly behaviors from detectors, sorted by cost_estimate
- KEEP: positive behaviors (detector score > 0)
- Each recommendation includes quantified ₹ cost/benefit

**`get_action_plan(client_name)`**: Loads or computes behavioral_audit and alternatives. Calls `build_action_plan`. Returns structured result.

**`get_full_report_data(client_name)`**: Aggregates all analysis — calls any tools not yet cached. Returns single JSON blob with all sections for canvas rendering. Includes pre-transformed scores (0-10 scale for display).

Canvas JSON schema (maps to spec §5 sections A–F):
```python
{
    # Section A: Client Snapshot
    "snapshot": {
        "client_name": str, "trading_since": str, "duration_years": float,
        "total_invested": float, "current_value": float, "xirr": float,
        "instrument_count": {"equity": int, "mf": int},
        "behavioral_score_0_10": float, "turnover_ratio": float,
        "tax_drag_estimate": float,
    },
    # Section B: Equity Curve + Behavioral Markers
    "equity_curve": {
        "actual": [{"date": str, "value": float}, ...],
        "nifty_sip": [{"date": str, "value": float}, ...],
        "markers": [{"date": str, "type": "panic_sell|fomo_buy|good_decision",
                      "symbol": str, "detail": str}, ...],
    },
    # Section C: Behavioral Radar + Detail Cards
    "behavioral": {
        "radar": {
            "timing_discipline": float,      # 0-10
            "holding_discipline": float,
            "diversification": float,
            "trading_discipline": float,
            "crowd_independence": float,
            "sip_consistency": float,
        },
        "top_issues": [{"pattern": str, "score_0_10": float,
                         "severity": str, "cost_estimate": float,
                         "instances": list, "evidence_summary": str}, ...],
    },
    # Section D: Alternative Scenarios
    "alternatives": {
        "scenarios": [{"scenario": str, "total_invested": float,
                        "final_value": float, "xirr": float,
                        "vs_actual_value_diff": float}, ...],
    },
    # Section E: Allocation
    "allocation": {
        "sectors": [{"name": str, "weight_pct": float}, ...],
        "types": [{"name": str, "weight_pct": float}, ...],
        "holdings": [{"symbol": str, "weight_pct": float, "return_pct": float,
                       "holding_days": int}, ...],
    },
    # Section F: Action Plan
    "action_plan": {
        "start": [{"action": str, "benefit_inr": float}, ...],
        "stop": [{"action": str, "cost_inr": float}, ...],
        "keep": [{"action": str, "note": str}, ...],
    },
}
```

- [ ] **Step 4: Run test — verify pass**

Run: `.venv/bin/python -m pytest tests/portfolio_doctor/tools/test_report_tools.py -v`
Expected: PASSED

- [ ] **Step 5: Commit**

```bash
git add portfolio_doctor/tools/report_tools.py tests/portfolio_doctor/tools/test_report_tools.py
git commit -m "feat: add report_tools — action plan and full report aggregation"
```

---

## Task 14: MCP Server — portfolio_doctor/server/app.py + .mcp.json

**Files:**
- Create: `portfolio_doctor/server/app.py`
- Modify: `.mcp.json`

- [ ] **Step 1: Create portfolio_doctor/server/app.py**

Follow the same pattern as `server/app.py`. Register 6 tools with rich docstrings.
Use the system prompt from spec section 4.

```python
from mcp.server.fastmcp import FastMCP
from portfolio_doctor.tools.portfolio_tools import (
    ingest_client_trades,  # calls validate_symbols internally after parse_csv
    get_portfolio_overview,
)
from portfolio_doctor.tools.behavioral_tools import get_behavioral_audit
from portfolio_doctor.tools.alternative_tools import get_alternative_scenarios
from portfolio_doctor.tools.report_tools import get_action_plan, get_full_report_data

mcp = FastMCP(
    "portfolio-doctor",
    instructions="""
You are a portfolio behavioral analyst for Indian retail investors and traders.
You help financial advisors analyze their clients' trading history to identify
behavioral patterns, quantify the cost of mistakes, and provide actionable
improvement recommendations.

AVAILABLE TOOLS:

  ingest_trades(csv_path, client_name)
    → START HERE. Always call this first when given a new client CSV.

  portfolio_overview(client_name)
    → "How has this client done?" — holdings, returns, allocation, turnover.

  behavioral_audit(client_name)
    → "What mistakes is this client making?" — 9 behavioral detectors,
      each scored -1.0 to +1.0 with evidence and cost estimates.

  compare_alternatives(client_name)
    → "Would they have been better off with an index fund?" — 5 scenarios,
      same money, same dates, different vehicles.

  action_plan(client_name)
    → "What should this client change?" — Start/Stop/Keep framework,
      personalized, quantified in ₹.

  full_report_data(client_name)
    → "Give me everything" — aggregated JSON for canvas report.

CONVERSATION FLOW:
  1. Advisor provides CSV → ingest_trades()
  2. Quick look → portfolio_overview()
  3. Deep diagnosis → behavioral_audit()
  4. "What if" → compare_alternatives()
  5. Recommendations → action_plan()
  6. Full presentation → full_report_data() → render as canvas

RESPONSE GUIDELINES:
  • Present monetary values in ₹ with Indian commas (₹1,45,000)
  • Quantify behavioral costs in rupees — "panic selling cost ₹45,000"
  • Lead with differences, not absolutes: "₹48,000 more" not "14.8% XIRR"
  • Be empathetic, not judgmental — real people's money decisions
  • Flag regular-vs-direct MF savings opportunity
  • Frame recommendations as forward-looking actions, not past mistakes
""",
)


@mcp.tool()
def ingest_trades(csv_path: str, client_name: str) -> dict:
    """
    Parse and validate a client's trading history CSV.

    START HERE — always call this first when given a new client CSV file.

    Args:
      csv_path:     Path to the CSV file on disk.
      client_name:  Identifier for this client (used for data storage).

    Expected CSV columns:
      date (YYYY-MM-DD), instrument_type (EQUITY/MF), symbol (NSE symbol or
      AMFI scheme code), action (BUY/SELL/SIP/SWP/SWITCH_IN/SWITCH_OUT),
      quantity, price. Optional: scheme_name, amount, brokerage, notes.

    Returns validation summary: trade count, date range, unique symbols,
    capital deployed, instrument mix, any warnings.
    """
    return ingest_client_trades(csv_path, client_name)


@mcp.tool()
def portfolio_overview(client_name: str) -> dict:
    """
    Get portfolio overview — holdings, returns, allocation, turnover.

    Requires: ingest_trades() called first for this client.

    Returns current holdings with per-position returns, total portfolio
    XIRR, sector allocation, equity curve summary, turnover ratio,
    and estimated tax drag.

    Use when asked: "How has this client done?", "What's the portfolio
    performance?", "Show me the client's holdings."
    """
    return get_portfolio_overview(client_name)


@mcp.tool()
def behavioral_audit(client_name: str) -> dict:
    """
    Run behavioral analysis — 9 detectors scoring trading psychology.

    Requires: ingest_trades() called first.

    Detects: panic selling, FOMO buying, disposition effect, concentration
    risk, overtrading, herd behavior, anchoring bias, SIP discipline,
    regular plan waste. Each detector scored -1.0 (severe) to +1.0 (excellent)
    with specific trade instances and estimated cost in ₹.

    Returns all detector results with per-detector scores (-1.0 to +1.0),
    composite behavioral score (-1.0 to +1.0), and top 3 costliest behaviors
    with evidence. Note: 0-10 scale is only used in full_report_data() for display.

    Use when asked: "What mistakes is this client making?",
    "What behavioral patterns do you see?", "Why are returns poor?"
    """
    return get_behavioral_audit(client_name)


@mcp.tool()
def compare_alternatives(client_name: str) -> dict:
    """
    Compare actual portfolio against 5 alternative scenarios.

    Requires: ingest_trades() called first.

    Scenarios: Nifty 50 SIP, popular MF SIPs, 70/30 model portfolio,
    buy-and-hold same stocks, same stocks without re-entry.
    All use the SAME cash flows on the SAME dates — only vehicle changes.

    Returns side-by-side returns, XIRR, value differences vs actual.

    Use when asked: "Would they have been better off with an index fund?",
    "How does a simple SIP compare?", "What if they just held?"
    """
    return get_alternative_scenarios(client_name)


@mcp.tool()
def action_plan(client_name: str) -> dict:
    """
    Generate personalized recommendations in Start/Stop/Keep framework.

    Requires: behavioral_audit + compare_alternatives (calls them if needed).

    Each recommendation is quantified in ₹ — "Stop panic selling (cost
    you ₹45,000)", "Start a Nifty SIP (would have earned ₹48,000 more)".

    Use when asked: "What should this client change?", "What are the
    recommendations?", "How can they improve?"
    """
    return get_action_plan(client_name)


@mcp.tool()
def full_report_data(client_name: str) -> dict:
    """
    Aggregate ALL analysis into a single structured JSON for canvas rendering.

    Calls any tools not yet run for this client. Returns complete data blob
    with: client snapshot, equity curve + behavioral markers, behavioral
    radar scores, alternative comparisons, allocation breakdown, and
    action plan. All scores pre-transformed to 0-10 scale for display.

    Use when asked: "Give me the full report", "Show me everything",
    "Create the presentation for this client."
    """
    return get_full_report_data(client_name)


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 2: Update .mcp.json**

Replace `.mcp.json` with:
```json
{
  "mcpServers": {
    "india-markets": {
      "command": ".venv/bin/python",
      "args": ["-m", "server.app"],
      "env": { "KITE_SSL_VERIFY": "false" }
    },
    "portfolio-doctor": {
      "command": ".venv/bin/python",
      "args": ["-m", "portfolio_doctor.server.app"],
      "env": {}
    }
  }
}
```

- [ ] **Step 3: Verify server starts**

Run: `cd /Users/samkit.sheth/Documents/github/finance_chat && .venv/bin/python -c "from portfolio_doctor.server.app import mcp; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add portfolio_doctor/server/app.py .mcp.json
git commit -m "feat: add portfolio-doctor MCP server with 6 tools"
```

---

## Task 15: Update .cursor/rules and Project Memory

**Files:**
- Modify: `.cursor/rules/project-architecture.mdc`
- Create: `.cursor/rules/portfolio-doctor-patterns.mdc`

- [ ] **Step 1: Update project-architecture.mdc**

Add a new "Portfolio Doctor MCP" section after the existing "Built Layers" table.
Update the "Key Decisions" and "Directory Layout" sections.

Add to top of file, after the india-markets "Built Layers" table:

```markdown
## Portfolio Doctor MCP

Second MCP server for behavioral portfolio analysis. Shares code with
india-markets via the `shared/` package.

| Component | File | What it does |
|-----------|------|-------------|
| CSV Parser | `portfolio_doctor/core/csv_parser.py` | Parse, validate, build trade ledger (FIFO equity, per-lot MF) |
| Portfolio Engine | `portfolio_doctor/core/portfolio_engine.py` | Holdings, returns, XIRR, value series, allocation, tax drag |
| Behavioral Engine | `portfolio_doctor/core/behavioral_engine.py` | 9 behavioral detectors + composite score |
| Alternatives Engine | `portfolio_doctor/core/alternatives_engine.py` | 5 "what if" scenario comparisons |
| MCP Server | `portfolio_doctor/server/app.py` | 6 tools: ingest, overview, audit, alternatives, action plan, full report |

### Shared Utilities

Code shared between india-markets and portfolio-doctor lives in `shared/`:

| File | Source | What it does |
|------|--------|-------------|
| `shared/yf_client.py` | Extracted from `core/macro_client.py` | yfinance session, SSL bypass, caching, `yf_latest()` |
| `shared/nse_utils.py` | Extracted from `core/fundamentals_client.py` | `nse_to_yf()` symbol mapping |
| `shared/price_history.py` | New | Batch historical OHLC for any NSE stock |
| `shared/mf_client.py` | New | MF NAV history via mftool |
```

Update "Directory Layout" to show the new structure:

```markdown
## Directory Layout

```
shared/        ← Shared utilities (yfinance, symbol mapping, price history, MF NAVs)
core/          ← india-markets: HTTP sessions, auth, instrument caches, signal scoring
tools/         ← india-markets: business logic and derived signals
server/app.py  ← india-markets MCP server
portfolio_doctor/
├── core/      ← Analysis engines (csv_parser, portfolio, behavioral, alternatives)
├── tools/     ← Portfolio Doctor business logic
└── server/    ← Portfolio Doctor MCP server
scripts/       ← Cron jobs, backfill, one-off utilities
data/daily/    ← india-markets daily snapshots (gitignored)
data/portfolios/ ← Client portfolio data (gitignored)
tests/         ← Unit tests for shared/ and portfolio_doctor/
```
```

Update "Key Decisions":
- Change `**No portfolio tracking** — pure market analysis tool` to `**No portfolio tracking in india-markets** — pure market analysis; portfolio features live in portfolio-doctor MCP`
- Add:
```markdown
- **Two MCPs, shared code** — portfolio-doctor reuses yfinance/mftool via `shared/` package
- **Client data is local** — portfolio data in `data/portfolios/` (gitignored, sensitive)
- **FIFO for equity, per-lot for MF** — matches Indian tax treatment conventions
```

Update "Adding a New Layer" to mention portfolio-doctor pattern:
```markdown
### Portfolio Doctor tools follow the same pattern:
1. Engine in `portfolio_doctor/core/<name>_engine.py`
2. Tool wrapper in `portfolio_doctor/tools/<name>_tools.py`
3. Register in `portfolio_doctor/server/app.py`
```

- [ ] **Step 2: Create .cursor/rules/portfolio-doctor-patterns.mdc**

```markdown
---
description: Patterns for portfolio-doctor MCP — applies when editing portfolio_doctor/ or shared/
globs: portfolio_doctor/**/*.py, shared/*.py
alwaysApply: false
---

# Portfolio Doctor Patterns

## Architecture

Portfolio Doctor follows the same three-layer pattern as india-markets:
```
portfolio_doctor/core/    ← Engines (pure computation, no I/O beyond file reads)
portfolio_doctor/tools/   ← Orchestration (fetches data, calls engines, manages file cache)
portfolio_doctor/server/  ← @mcp.tool() wrappers with docstrings
```

## Shared Code (shared/)

Code reused across both MCPs. Neither MCP's core/ should import from the other.

- `shared/yf_client.py` — yfinance session + caching (replaces inline code in core/macro_client.py)
- `shared/nse_utils.py` — NSE symbol mapping (replaces inline code in core/fundamentals_client.py)
- `shared/price_history.py` — batch OHLC for portfolio valuation
- `shared/mf_client.py` — mutual fund NAV history via mftool

## Client Data Storage

Processed data lives in `data/portfolios/{client_name}/`:
- `trades.json` — parsed and validated trades
- `positions.json` — current position ledger
- `cashflows.json` — unified cash flow timeline
- `sip_patterns.json` — detected SIP patterns
- `overview.json` — cached portfolio overview
- `behavioral_audit.json` — cached behavioral analysis
- `alternatives.json` — cached alternative scenarios

Tools check for cached files before recomputing.

## Behavioral Detector Pattern

Every detector returns the same structure:
```python
{
    "pattern": "detector_name",
    "score": float,         # -1.0 (severe) to +1.0 (excellent)
    "severity": str,        # "low" / "medium" / "high"
    "instances": list,      # specific triggering trades
    "cost_estimate": float, # estimated INR cost
    "evidence_summary": str
}
```

## MF Identifiers

Mutual funds use AMFI scheme codes (e.g. 119551), NOT fund names.
Validate scheme codes via `shared/mf_client.validate_scheme_code()`.

## XIRR Calculation

Use `scipy.optimize.brentq` via `portfolio_engine.compute_xirr()`.
Cash flow convention: negative = money out (investment), positive = money in (redemption/current value).

## Error Handling

Same as india-markets: return `{"error": str}` dict on failure, never raise.
```

- [ ] **Step 3: Run full test suite one final time**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All PASSED

- [ ] **Step 4: Commit**

```bash
git add .cursor/rules/project-architecture.mdc .cursor/rules/portfolio-doctor-patterns.mdc
git commit -m "docs: update cursor rules with portfolio-doctor architecture and patterns"
```

---

## Summary

| Task | What it builds | Commits |
|------|---------------|---------|
| 1 | Test infra + dependencies | 1 |
| 2 | Extract shared/yf_client.py | 1 |
| 3 | Extract shared/nse_utils.py | 1 |
| 4 | shared/price_history.py | 1 |
| 5 | shared/mf_client.py | 1 |
| 6 | Portfolio Doctor scaffolding | 1 |
| 7 | CSV parser (parse, validate, ledger, cash flows, SIP detection) | 1 |
| 8 | Portfolio engine (holdings, XIRR, value series, allocation) | 1 |
| 9 | Behavioral engine (9 detectors + composite) | 1 |
| 10 | Alternatives engine (5 scenarios) | 1 |
| 11 | portfolio_tools.py (ingest + overview) | 1 |
| 12 | behavioral_tools.py + alternative_tools.py | 1 |
| 13 | report_tools.py (action plan + full report) | 1 |
| 14 | MCP server + .mcp.json | 1 |
| 15 | .cursor/rules updates | 1 |
| **Total** | | **15 commits** |

### Dependency order

```
Task 1 (infra)
  └→ Task 2 (yf_client extraction)
      └→ Task 3 (nse_utils extraction)
          ├→ Task 4 (price_history) ─┐
          └→ Task 5 (mf_client) ────┤
                                     └→ Task 6 (scaffolding)
                                         └→ Task 7 (csv_parser)
                                             └→ Task 8 (portfolio_engine)
                                                 ├→ Task 9 (behavioral_engine)
                                                 └→ Task 10 (alternatives_engine)
                                                     └→ Task 11 (portfolio_tools)
                                                         └→ Task 12 (behavioral + alternative tools)
                                                             └→ Task 13 (report_tools)
                                                                 └→ Task 14 (MCP server)
                                                                     └→ Task 15 (rules)
```

Tasks 4 and 5 can be built in parallel. Tasks 9 and 10 can be built in parallel.
All other tasks are sequential.
