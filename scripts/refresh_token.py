"""
Daily Kite Access Token Refresh
--------------------------------
Run this each morning before using the finance chat MCP server.

Usage:
    python scripts/refresh_token.py

Steps:
    1. Script prints a login URL — open it in your browser
    2. Log in with Zerodha credentials
    3. You'll be redirected to a URL like:
          https://127.0.0.1/?request_token=XXXX&action=login&status=success
    4. Paste that full redirect URL (or just the request_token) when prompted
    5. Script writes the fresh access token directly to your .env
"""

import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv, set_key

# Resolve paths relative to project root (one level up from scripts/)
PROJECT_ROOT = Path(__file__).parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)

api_key = os.getenv("KITE_API_KEY")
api_secret = os.getenv("KITE_API_SECRET")

if not api_key:
    print("ERROR: KITE_API_KEY not set in .env")
    sys.exit(1)
if not api_secret or api_secret == "your_api_secret_here":
    print("ERROR: KITE_API_SECRET not set in .env")
    sys.exit(1)

# Inline import so the script fails fast with a clear message if kiteconnect missing
try:
    from kiteconnect import KiteConnect
except ImportError:
    print("ERROR: kiteconnect not installed. Run: pip install kiteconnect")
    sys.exit(1)

kite = KiteConnect(api_key=api_key)

# Bypass SSL for corporate proxies with self-signed certificates
if os.getenv("KITE_SSL_VERIFY", "true").lower() == "false":
    import ssl
    import urllib3
    import requests as _requests

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    ssl._create_default_https_context = ssl._create_unverified_context

    _original_send = _requests.Session.send

    def _unverified_send(self, request, **kwargs):
        kwargs["verify"] = False
        return _original_send(self, request, **kwargs)

    _requests.Session.send = _unverified_send

login_url = kite.login_url()
print("\n--- Kite Token Refresh ---")
print(f"\nStep 1: Open this URL in your browser:\n\n  {login_url}\n")
print("Step 2: Log in and paste the full redirect URL (or just the request_token) below.")

raw = input("\nPaste here: ").strip()

# Accept either the full redirect URL or just the bare token
match = re.search(r"request_token=([a-zA-Z0-9]+)", raw)
request_token = match.group(1) if match else raw

try:
    session_data = kite.generate_session(request_token, api_secret=api_secret)
except Exception as e:
    print(f"\nERROR generating session: {e}")
    sys.exit(1)

access_token = session_data["access_token"]

set_key(str(ENV_FILE), "KITE_ACCESS_TOKEN", access_token)

print(f"\nAccess token saved to .env")
print(f"Token: {access_token[:8]}...{access_token[-4:]}")
print("\nRestart the MCP server in Cursor (Cmd+Shift+P → MCP: Restart All Servers)")
