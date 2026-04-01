"""
NSE symbol utilities shared across MCPs.

Maps NSE trading symbols to Yahoo Finance tickers.
"""


def nse_to_yf(symbol: str) -> str:
    """Map NSE trading symbol to Yahoo Finance ticker.

    Handles NSE: and BSE: prefixes, bare symbols, and already-suffixed tickers.
    BSE symbols get .BO suffix; everything else defaults to .NS.
    """
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
