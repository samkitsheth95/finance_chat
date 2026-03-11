import os
import ssl
import urllib3
import requests
from kiteconnect import KiteConnect
from dotenv import load_dotenv

load_dotenv()

# When behind a corporate proxy with SSL inspection, bypass certificate verification.
# Controlled by KITE_SSL_VERIFY=false in .env or the MCP server env config.
if os.getenv("KITE_SSL_VERIFY", "true").lower() == "false":
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    ssl._create_default_https_context = ssl._create_unverified_context

    # Patch requests.Session.send so verify=False applies to every outgoing
    # HTTPS request in this process — including kiteconnect's internal session.
    _original_send = requests.Session.send

    def _unverified_send(self, request, **kwargs):
        kwargs["verify"] = False
        return _original_send(self, request, **kwargs)

    requests.Session.send = _unverified_send

_kite: KiteConnect | None = None
_instruments_cache: dict[str, list] = {}


def get_kite() -> KiteConnect:
    """
    Returns a singleton KiteConnect instance.
    Assumes KITE_API_KEY and KITE_ACCESS_TOKEN are set in .env.
    Access token is generated manually each morning via the Kite login flow.
    """
    global _kite

    if _kite is not None:
        return _kite

    api_key = os.getenv("KITE_API_KEY")
    access_token = os.getenv("KITE_ACCESS_TOKEN")

    if not api_key:
        raise EnvironmentError(
            "KITE_API_KEY is not set. Add it to your .env file.\n"
            "Get it from https://developers.kite.trade"
        )
    if not access_token:
        raise EnvironmentError(
            "KITE_ACCESS_TOKEN is not set. Add it to your .env file.\n"
            "Generate a fresh token each morning using the Kite login flow."
        )

    _kite = KiteConnect(api_key=api_key)
    _kite.set_access_token(access_token)
    return _kite


def get_instruments(exchange: str) -> list:
    """
    Returns the full instruments list for an exchange.
    Cached in memory after the first call — downloading takes ~2s.
    """
    global _instruments_cache

    if exchange not in _instruments_cache:
        kite = get_kite()
        _instruments_cache[exchange] = kite.instruments(exchange)

    return _instruments_cache[exchange]


def resolve_instrument_token(exchange: str, tradingsymbol: str) -> int:
    """
    Looks up the instrument token for a given exchange + tradingsymbol.
    Used for historical data API calls.
    """
    instruments = get_instruments(exchange)

    for inst in instruments:
        if inst["tradingsymbol"] == tradingsymbol.upper():
            return inst["instrument_token"]

    raise ValueError(
        f"Symbol '{tradingsymbol}' not found on {exchange}. "
        f"Check the exact tradingsymbol on kite.zerodha.com/instruments"
    )
