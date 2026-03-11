"""
NSE session client — manages the browser session required by NSE's public API.

NSE blocks direct API calls without a prior page visit (cookie acquisition).
This module primes a session against the NSE home page before each API call
and centralises all NSE HTTP logic, keeping tools/nse_tools.py free of it.

SSL note:
  If KITE_SSL_VERIFY=false is set in .env, core/kite_client.py patches
  requests.Session.send globally so verify=False applies here automatically.
  This covers corporate proxies that intercept HTTPS with a self-signed cert.
"""

import requests

# Trigger the global SSL bypass patch in kite_client if KITE_SSL_VERIFY=false.
# Import is for side effects only — the patch applies process-wide.
import core.kite_client  # noqa: F401

_NSE_HEADERS = {
    "accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "accept-language": "en-US,en;q=0.9,en-IN;q=0.8",
    "cache-control": "max-age=0",
    "sec-ch-ua": '"Chromium";v="129", "Not=A?Brand";v="8"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "upgrade-insecure-requests": "1",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
}


def nse_fetch(url: str) -> dict | list:
    """
    Fetch a JSON endpoint from NSE using a fresh browser session.

    NSE requires cookies from the home page before the API endpoint will
    respond. A new session is created per call to avoid stale cookies.

    Args:
        url: Full NSE API URL, e.g.
             'https://www.nseindia.com/api/fiidiiTradeReact'

    Returns:
        Parsed JSON response as dict or list.

    Raises:
        requests.HTTPError:   On non-2xx response.
        requests.Timeout:     If any request exceeds its timeout.
        requests.SSLError:    If SSL verification fails — set KITE_SSL_VERIFY=false
                              in .env if you are behind a proxy with SSL inspection.
    """
    session = requests.Session()
    session.get("https://www.nseindia.com", headers=_NSE_HEADERS, timeout=15)
    session.get(
        "https://www.nseindia.com/market-data/live-equity-market",
        headers=_NSE_HEADERS,
        timeout=10,
    )
    response = session.get(url, headers=_NSE_HEADERS, timeout=10)
    response.raise_for_status()
    return response.json()
