from mcp.server.fastmcp import FastMCP
from tools.kite_tools import get_quote, get_indices, get_historical_ohlc

mcp = FastMCP(
    "india-markets",
    instructions="""
You are an Indian financial market analyst with live access to NSE and BSE
market data via Zerodha Kite Connect.

AVAILABLE DATA (Layer 1 — Market Foundation):
  • Live quotes for any NSE/BSE listed stock, ETF, mutual fund, or index
  • Live index snapshot: Nifty 50, BankNifty, Sensex, India VIX, sector indices
  • Historical OHLC data (intraday to daily candles, up to 2000 days back)

HOW TO USE THE TOOLS:
  get_quote(symbol)
    → Use for a single stock or instrument. e.g. "RELIANCE", "NSE:INFY", "NIFTY 50"
    → Always call this before discussing any stock's current price or session P&L

  get_indices()
    → Use at the start of any broad market question ("how is the market today?")
    → Returns all major indices in one call — prefer this over multiple get_quote calls

  get_historical_ohlc(symbol, interval, days)
    → Use when the user asks about trends, support/resistance, moving averages,
      recent highs/lows, or "how has X performed over the last N days/weeks"
    → Default interval: "day" | Default days: 30
    → For intraday patterns: use "15minute" or "60minute" intervals

RESPONSE GUIDELINES:
  • Always fetch live data — never quote prices from training knowledge
  • Present all prices in Indian Rupees (₹)
  • Always state the change (₹ and %) for the current session
  • For historical analysis, note the period_high, period_low, and trend direction
  • If a tool returns an error, explain clearly what went wrong and what the user
    should check (e.g., symbol format, market hours, token expiry)

CURRENT LIMITATIONS (coming in future layers):
  • FII/DII institutional flows — Layer 2
  • Option chain, Greeks, PCR, Max Pain — Layer 3
  • Global macro: crude oil, DXY, US markets, GIFT Nifty — Layer 4
  • News and geopolitical sentiment — Layer 5
  • Signal scoring and weighting framework — Layer 6

When a user asks something that requires data from a future layer, acknowledge
what you can answer now and note what additional data will improve the answer.
""",
)


@mcp.tool()
def quote(symbol: str) -> dict:
    """
    Get a live quote for any NSE/BSE listed stock, ETF, or index.

    Examples:
      quote("RELIANCE")       → Reliance Industries live price
      quote("NSE:INFY")       → Infosys with explicit exchange
      quote("NIFTY 50")       → Nifty 50 index
      quote("BSE:500325")     → Reliance via BSE scrip code

    Returns live price, OHLC, volume, net change (₹ and %), and bid/ask.
    """
    return get_quote(symbol)


@mcp.tool()
def indices() -> dict:
    """
    Get a live snapshot of all major Indian indices in one call.

    Returns Nifty 50, BankNifty, Sensex, India VIX, Nifty IT, Nifty FMCG,
    Nifty Pharma, Nifty Auto, Nifty Metal, Nifty Midcap 100, and Nifty Next 50.

    Use this at the start of any broad market question instead of
    calling quote() multiple times.
    """
    return get_indices()


@mcp.tool()
def historical_ohlc(
    symbol: str,
    interval: str = "day",
    days: int = 30,
) -> dict:
    """
    Get historical OHLC candlestick data for a stock or index.

    Args:
      symbol:   NSE/BSE symbol. e.g. "RELIANCE", "NSE:INFY", "NIFTY 50"
      interval: Candle size — one of:
                  "minute", "3minute", "5minute", "10minute", "15minute",
                  "30minute", "60minute", "day", "week", "month"
      days:     Calendar days of history. Max varies by interval:
                  minute → 60 days | 60minute → 400 days | day → 2000 days

    Returns candles (date, open, high, low, close, volume) plus
    period_high, period_low, avg_close, and candle count.

    Use cases:
      • "How has Reliance performed this month?" → interval="day", days=30
      • "Show me Nifty's intraday pattern today" → interval="15minute", days=1
      • "What is the 200-day high/low for HDFC Bank?" → interval="day", days=200
    """
    return get_historical_ohlc(symbol, interval, days)


if __name__ == "__main__":
    mcp.run()
