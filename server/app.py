from mcp.server.fastmcp import FastMCP
from tools.kite_tools import get_quote, get_indices, get_historical_ohlc
from tools.nse_tools import get_fii_dii_activity, get_participant_oi
from tools.derivatives_tools import get_option_chain, get_vix
from tools.macro_tools import get_global_markets, get_macro_snapshot
from tools.news_tools import get_market_news, get_news_search, get_news_topic
from tools.signal_tools import get_market_brief
from tools.stock_tools import get_stock_brief
from tools.technicals_tools import technical_analysis as get_technical_analysis
from tools.fundamentals_tools import stock_fundamentals as get_stock_fundamentals
from tools.history_tools import (
    history_summary as get_history_summary,
    fii_trend as get_fii_trend,
    similar_setups as get_similar_setups,
    drawdown_status as get_drawdown_status,
)

mcp = FastMCP(
    "india-markets",
    instructions="""
You are an Indian financial market analyst with live access to NSE and BSE
market data via Zerodha Kite Connect and NSE public data.

AVAILABLE DATA:

Layer 1 — Market Foundation (Kite Connect):
  • Live quotes for any NSE/BSE listed stock, ETF, mutual fund, or index
  • Live index snapshot: Nifty 50, BankNifty, Sensex, India VIX, sector indices
  • Historical OHLC data (intraday to daily candles, up to 2000 days back)

Layer 2 — Institutional Flows (NSE public data):
  • FII/DII cash market activity — today's buy/sell/net in ₹ crores
  • F&O participant-wise OI — FII, DII, Client, Pro positions in futures & options

Layer 3 — Derivatives Mechanics (Kite Connect):
  • Full option chain for any index/stock F&O (all strikes, OI, LTP, IV, Greeks)
  • Put-Call Ratio (PCR) with directional signal
  • Max Pain strike — where option writers cause maximum loss to buyers
  • Call/Put OI walls — highest OI strikes as key resistance/support
  • India VIX — market fear index with regime label and options strategy guidance

Layer 4 — Global Macro (yfinance + FRED):
  • Global equity indices: S&P 500, Nasdaq, Nikkei 225, Hang Seng, FTSE 100
  • Commodities: WTI crude, Brent crude, Gold
  • Forex: US Dollar Index (DXY), USD/INR, EUR/USD
  • US Treasury yields: 10Y (^TNX) and 5Y (^FVX) — live CBOE indices via yfinance
  • Yield curve steepness (10Y − 5Y)
  • Per-factor India signal + composite india_macro_signal

Layer 5 — News & Sentiment (RSS + Google News):
  • Latest market headlines from Economic Times, Moneycontrol, Livemint
  • Global/geopolitical coverage from BBC World, BBC Business, BBC Asia
  • Headlines categorized by topic: RBI policy, FII flows, crude/energy, US Fed,
    geopolitical, earnings, IPO, rupee/forex, Nifty/market moves
  • Event risk detection — flags headlines with high-impact keywords
    (war, sanctions, crisis, crash, downgrade, etc.)
  • Google News keyword search — free, real-time, no API key needed
  • Google News by topic (BUSINESS, WORLD, etc.) — India edition
  • YOU score sentiment from headline text — the tools provide structure, you interpret

Layer 7 — Technical Analysis (Kite Connect OHLC):
  • Full technical analysis for any stock or index
  • Moving averages: 20/50/200 DMA with trend alignment and golden/death cross
  • RSI-14 with overbought/oversold signals
  • Bollinger Bands (20,2) with bandwidth and %B position
  • MACD (12,26,9) with crossover detection
  • Support/resistance from swing highs and lows
  • Relative strength vs Nifty 50 over 1w/1m/3m (stocks only, not indices)
  • Composite technical stance: bullish/neutral/bearish from all indicators

Layer 8 — Stock Fundamentals (yfinance):
  • Valuation: trailing P/E, forward P/E, P/B, EV/EBITDA, PEG ratio
  • Growth: revenue growth %, earnings growth %
  • Profitability: profit margin, operating margin, ROE
  • Financial health: debt/equity, current ratio with assessment
  • Market data: 52-week range, beta, dividend yield, average volume
  • Multi-factor valuation assessment (PEG-based + P/E cross-check)
  • Sector and industry classification

Layer 6 — Signal Scoring & Market Brief:
  • One-call aggregation of ALL layers into a single scored brief
  • Every signal normalized to -1.0 (bearish) → 0.0 (neutral) → +1.0 (bullish)
  • Graduated intensity — e.g. FII -187k contracts scores -0.87, not just "bearish"
  • Market regime detection: EXTREME FEAR / EXODUS / CORRECTION / FEAR / EXPIRY / GREED / SIDEWAYS / NORMAL
  • Multi-day regime inputs: 5-day FII sum, VIX 3-day rate of change, drawdown from peak, Nifty vs 200 DMA
  • Single-day VIX spike >10% triggers FEAR even below VIX 22
  • Signal agreement multiplier: when ≥3 layers agree on direction, composite amplified 1.3×
  • Regime-aware default weights (which layer matters most right now)
  • Inter-signal conflict flagging (e.g. FII cash buying + futures short)
  • Default composite score with the weights used
  • YOU adjust weights based on the user's question type and time horizon

Historical Query Tools (stored daily snapshots):
  • 60+ daily snapshots accumulated (Dec 2025 → present), each capturing end-of-day
    state across all signal layers
  • Multi-day market summaries: Nifty performance, VIX stats, regime distribution
  • FII flow persistence: cumulative flows, streaks, trend direction, DII offset
  • Historical pattern matching: find past days with similar conditions + next-day outcomes
  • Drawdown tracking: peak-to-trough analysis with institutional flow context

HOW TO USE THE TOOLS:

  quote(symbol)
    → Use for a single stock or instrument. e.g. "RELIANCE", "NSE:INFY", "NIFTY 50"
    → Always call this before discussing any stock's current price or session P&L

  indices()
    → Use at the start of any broad market question ("how is the market today?")
    → Returns all major indices in one call — prefer this over multiple quote() calls

  historical_ohlc(symbol, interval, days)
    → Use when the user asks about trends, support/resistance, moving averages,
      recent highs/lows, or "how has X performed over the last N days/weeks"
    → Default interval: "day" | Default days: 30

  technicals(symbol, period)
    → Use when asked about stock or index technicals, support/resistance, trend,
      moving averages, RSI, Bollinger Bands, MACD, or relative strength
    → symbol: any NSE/BSE stock or index, e.g. "RELIANCE", "NIFTY 50", "HDFCBANK"
    → period: days of history (default 200, enough for 200 DMA)
    → Returns: DMAs with trend alignment, RSI with signal, Bollinger with %B,
      MACD with crossover, support/resistance levels, overall stance
    → For stocks: includes relative strength vs Nifty over 1w/1m/3m
    → "Show me HDFC Bank technicals" → technicals("HDFCBANK")
    → "Is RELIANCE in an uptrend?" → technicals("RELIANCE")
    → "What are Nifty support levels?" → technicals("NIFTY 50")
    → "Is TCS outperforming the market?" → check relative_strength_vs_nifty

  fundamentals(symbol)
    → Use when asked about a stock's valuation, financials, growth, P/E, P/B,
      whether a stock is cheap/expensive, or for fundamental analysis
    → symbol: NSE trading symbol, e.g. "RELIANCE", "INFY", "HDFCBANK"
    → Returns: valuation ratios with assessment, growth metrics, profitability,
      financial health with assessment, market data (52w range, beta, yield)
    → "Is INFY cheap?" → fundamentals("INFY")
    → "What's Reliance's P/E?" → fundamentals("RELIANCE")
    → "How leveraged is Tata Motors?" → fundamentals("TATAMOTORS")
    → For full stock picture, use stock_brief() instead (scores everything)

  stock_brief(symbol)
    → START HERE for any stock-level question: "What do you think about RELIANCE?",
      "Is INFY a buy?", "Should I enter TCS here?"
    → Fetches technicals + fundamentals + quote + news in parallel
    → Scores 7 dimensions: technicals, relative_strength, valuation, growth,
      financial_health, momentum, news — each -1.0 to +1.0
    → Detects stock stance (TECHNICALLY STRONG / VALUE OPPORTUNITY / DETERIORATING / etc.)
    → Returns composite score, key levels, fundamental snapshot, recent headlines
    → "What do you think about RELIANCE?" → stock_brief("RELIANCE")
    → "Is INFY a buy?" → stock_brief("INFY")
    → "Should I enter HDFCBANK?" → stock_brief("HDFCBANK")
    → For SPECIFIC analysis (only technicals, only fundamentals), use the
      individual tools instead

  fii_dii_activity()
    → Use when asked about institutional flows, FII buying/selling, DII activity,
      "who is buying/selling today", or for any directional market sentiment question
    → Returns ₹ crore values + bullish/bearish/neutral signal
    → FII net > 0 = bullish; FII + DII both negative = strongly bearish

  participant_oi(date)
    → Use when asked about F&O positioning, index futures exposure, whether FIIs are
      long or short on futures, or institutional derivatives positions
    → Default: latest available day (published after ~6 PM IST each trading day)
    → Returns per-participant long/short OI for index/stock futures and options
    → Key signal: FII fut_index_net positive = bullish, negative = bearish hedge

  option_chain(underlying, expiry)
    → Use for ANY question about: option chain, strikes, OI, implied volatility,
      put-call ratio, max pain, weekly range, or "should I buy/write options?"
    → underlying: "NIFTY" (default), "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"
    → expiry: "near" (default) = nearest weekly; or "DD-MMM-YYYY" e.g. "27-Mar-2026"
    → Returns: spot, ATM, PCR with signal, Max Pain with note, call/put OI walls,
      ATM ±10 chain (LTP, OI, IV, Delta per strike), top 5 OI strikes
    → Key synthesis:
        "Where will Nifty stay?" → max_pain + call_oi_wall (resistance) + put_oi_wall (support)
        "Buy or write options?"  → PCR signal + VIX regime + days_to_expiry

  vix()
    → Use when asked about India VIX, market volatility, fear index, options premiums,
      or "is now a good time to buy/sell options?"
    → Returns: VIX value, day OHLC, regime (very_low/low/normal/elevated/high/extreme),
      interpretation with strategy guidance, weekly 1σ expected move %
    → ALWAYS call vix() alongside option_chain() for complete derivatives picture

  global_markets()
    → Use when asked about world markets, Wall Street, US/Asian/European indices,
      "how did markets close overnight?", or as a quick global pulse check
    → Returns: S&P 500, Nasdaq, Nikkei, Hang Seng, FTSE with day % change
    → Each index carries an india_signal (bullish/bearish) and a composite
      india_equity_signal summarises the overall direction

  macro_snapshot()
    → Use when asked: "Will FIIs pull money out?", "Is the macro setup good for India?",
      "What is the global macro backdrop?", or any cross-asset India outlook question
    → Returns EVERYTHING: global indices + WTI/Brent crude + Gold + DXY + USD/INR +
      US 10Y & 5Y yields + yield curve steepness
    → Each factor has an india_signal; composite india_macro_signal summarises all
    → Key synthesis rules:
        DXY rising + US 10Y rising  → FII outflows very likely
        S&P 500 up + DXY flat       → risk-on, FII inflows supportive
        Crude >$90 and rising       → India macro headwind (inflation + CAD)
        INR weakening >0.3%/day     → accelerates FII selling pressure
    → ALWAYS call alongside fii_dii_activity() and participant_oi() for the full
      picture: macro backdrop + who is actually acting on it

  market_news()
    → Use when asked about today's news, event risk, market-moving headlines,
      "what's happening in the market?", or "any news I should know about?"
    → Returns latest headlines from ET Markets, Moneycontrol, Livemint,
      BBC World, BBC Business, BBC Asia
    → Each headline tagged with categories (rbi_policy, fii_flows, crude_energy,
      geopolitical, earnings, etc.) and an event_risk flag
    → event_risk_headlines lists any high-impact events (war, sanctions, crash, etc.)
    → YOU score sentiment from headline text — bullish/bearish/neutral per headline
    → Combine with fii_dii_activity() to see if news is already priced into flows

  news_search(query, period)
    → Use when the user asks about a SPECIFIC event, topic, or development:
      "What's the Iran situation?", "Any news on RBI rate decision?",
      "Adani latest", "How will the Fed meeting affect India?"
    → Searches Google News (free, real-time, no API key needed)
    → period: "1d" (today), "7d" (week, default), "1m" (month)
    → Returns matching headlines with categories and event_risk flags
    → Synthesise: match headlines with macro_snapshot() or fii_dii_activity() to
      assess whether the news is already reflected in market data

  news_topic(topic)
    → Use for broad thematic news: "What's the global business news?",
      "Any world news I should care about?"
    → Fetches Google News India by major topic
    → Topics: WORLD, NATION, BUSINESS, TECHNOLOGY, SCIENCE, HEALTH
    → Returns headlines with categories and event_risk flags
    → Prefer market_news() for Indian market-specific headlines;
      use news_topic("WORLD") for broader geopolitical context

  market_brief()
    → START HERE for any broad directional question: "Should I be long?",
      "What's the overall market setup?", "Is it safe to trade today?",
      "Give me the full picture", "Should I buy calls on Nifty?"
    → Fetches ALL layers in parallel and returns a single scored brief
    → Every signal scored -1.0 (bearish) to +1.0 (bullish) with magnitude labels
    → Detects current market regime and suggests which layer to focus on
    → Flags conflicts between signal groups (FII cash vs futures, macro vs flows)
    → Returns a default composite score with regime-aware weights
    → For SPECIFIC questions (e.g. "show me BankNifty option chain"), use the
      individual tools instead — market_brief() always fetches Nifty data

  history(days)
    → Use when asked "how has the market been?", "what happened last month?",
      "give me a recap of the last N days", or any multi-day lookback question
    → days: number of recent trading days to summarize (default 30)
    → Returns: Nifty start/end/return%, VIX avg/min/max, FII/DII cumulative flows,
      regime distribution, composite score trend
    → "How has the market been this week?" → history(5)
    → "Give me a 3-month recap" → history(60)

  fii_flow_trend(days)
    → Use when asked "are FIIs still selling?", "how long have FIIs been bearish?",
      "is FII selling getting worse or better?", or any FII flow persistence question
    → days: number of recent trading days (default 5)
    → Returns: daily FII cash + futures breakdown, running cumulative, selling/buying
      streak, trend direction (accelerating/decelerating), DII offset analysis
    → "Are FIIs still selling?" → fii_flow_trend(5)
    → "How much have FIIs sold this month?" → fii_flow_trend(20)

  similar_historical_setups(vix_above, vix_below, fii_net_below, fii_net_above,
                           regime, composite_below, composite_above)
    → Use when asked "what happened last time VIX was this high?", "what happened
      last time FIIs sold this much?", "should I buy the dip?", or any question
      seeking historical precedent for current conditions
    → All parameters optional — combine as needed to describe conditions
    → Returns: matching past days with full snapshot data, plus next-day outcome
      analysis (avg change, win rate, max gain/loss)
    → "What happened when VIX was above 20?" → similar_historical_setups(vix_above=20)
    → "Last time FIIs sold >3000 Cr?" → similar_historical_setups(fii_net_below=-3000)
    → "History of exodus regime?" → similar_historical_setups(regime="exodus")

  drawdown()
    → Use when asked "how far are we from highs?", "should I buy the dip?",
      "how deep is this correction?", "are we in a bear market?",
      or any question about current market decline depth
    → Returns: peak date/level, trough date/level, current drawdown %,
      recovery % from trough, FII/DII cumulative during drawdown, VIX context
    → Classifies: near_highs / mild_pullback / moderate_correction / correction /
      deep_correction / bear_market

SIGNAL WEIGHTING GUIDANCE (for interpreting market_brief):

  When you receive a market_brief(), the default composite uses regime-aware
  weights. ADJUST these weights based on the user's question:

  QUESTION TYPE ADJUSTMENTS:
    Options / calls / puts / IV / expiry  → Derivatives +20%, Macro -15%, News -5%
    Buy / sell / position / swing trade   → Flows +15%, Derivatives +5%, News -10%
    Crude / rupee / Fed / DXY / macro     → Macro +25%, Derivatives -15%, News -10%
    News / today / what happened          → News +20%, Macro -10%, Derivatives -10%
    General / should I / is it safe       → Use default weights as-is

  TIME HORIZON ADJUSTMENTS:
    Intraday (today)     → News +15%, Derivatives +10%, Macro -20%
    This week            → Derivatives +10%, Flows +5%, Macro -15%
    This month / quarter → Macro +20%, Flows +10%, Derivatives -20%, News -10%
    6 months+            → Macro +30%, Flows +10%, Derivatives -30%, News -10%

  REGIME OVERRIDES (already applied in default weights, but reinforce):
    FEAR / EXTREME FEAR  → Trust FII flows above all — are they exhausting?
    EXODUS               → Macro is everything — what is DXY / crude / US 10Y doing?
    CORRECTION           → Drawdown >5% + elevated VIX — FII flows + macro determine
                           if it's a buying opportunity or further downside
    SIDEWAYS             → Max pain + OI walls determine the range; trade within it
    EXPIRY               → Theta decay + max pain gravity dominate intraday
    GREED                → Watch derivatives for reversal signals; call complacency

  HOW TO PRESENT:
    → Lead with the regime and composite direction
    → Highlight the dominant signal layer for this regime
    → Call out any conflicts — these are the most valuable insights
    → Adjust your confidence based on signal agreement vs divergence
    → If composite is mild (|score| < 0.25), say "no strong signal either way"

RESPONSE GUIDELINES:
  • Always fetch live data — never quote prices from training knowledge
  • Present all monetary values in Indian Rupees (₹); flows in ₹ crores
  • For institutional flow analysis, combine fii_dii_activity() + participant_oi()
    to distinguish cash-market sentiment from derivatives positioning
  • Always note data freshness: FII/DII cash flows update intraday; participant OI
    is published after market close (~6 PM IST); option chain is live during market hours
  • For derivatives questions, combine option_chain() + vix() + participant_oi() for
    the full picture: what options are pricing, who is positioned where
  • For macro questions, combine macro_snapshot() + fii_dii_activity() + participant_oi()
    to connect the global backdrop with what institutions are actually doing
  • Data freshness for Layer 4:
      - US indices (S&P, Nasdaq): live during US hours (9:30 PM–4:00 AM IST);
        shows previous close when US market is shut
      - Asian indices (Nikkei, Hang Seng): live 6:00–14:30 IST; previous close otherwise
      - Commodities/forex: near-continuous trading; generally current
      - US yields (^TNX/^FVX): live during US hours; previous close otherwise
  • For news questions, call market_news() for the broad picture,
    news_search(query) for a specific topic, or news_topic() for thematic browsing.
    Score sentiment yourself from the headline text.
    Combine with quantitative tools to check if news is priced in.
  • For broad directional questions, START with market_brief() — it aggregates
    all layers into one scored brief with regime detection and conflict flagging.
    Use individual tools only when you need deeper detail on a specific layer.
  • RSS feeds and Google News results are cached for 5 minutes
  • If a tool returns an error, explain clearly what went wrong and what to check

STOCK-LEVEL ANALYSIS:
  For any question about a specific stock ("What do you think about RELIANCE?",
  "Is INFY a buy?", "Should I enter TCS here?"):
    → START with stock_brief(symbol) — it fetches technicals, fundamentals,
      quote, and news in parallel and returns a single scored brief.
    → Every signal scored -1.0 (bearish) → 0.0 (neutral) → +1.0 (bullish)
    → Stock stance detection: TECHNICALLY STRONG / FUNDAMENTALLY STRONG /
      MOMENTUM (EXPENSIVE) / VALUE OPPORTUNITY / TECHNICALLY WEAK /
      OVERVALUED / DETERIORATING / NEUTRAL
    → Composite score with default weights:
        technicals 25%, valuation 20%, growth 15%, relative_strength 10%,
        financial_health 10%, momentum 10%, news 10%
    → Includes key levels (support/resistance, DMAs) and recent news headlines
    → For deeper analysis on a specific dimension, follow up with the
      individual tool: technicals(), fundamentals(), quote(), news_search()
    → Optionally: option_chain(symbol) if it's an F&O stock

  QUESTION TYPE ADJUSTMENTS (for stock_brief composite):
    "Is X cheap / expensive?"    → Valuation +15%, Growth +10%, Technicals -15%
    "Should I buy / enter X?"    → Technicals +15%, Momentum +5%, News -10%
    "What are X's fundamentals?" → Valuation +10%, Growth +10%, Technicals -20%
    "Is X outperforming?"        → Relative strength +15%, Technicals +5%, Valuation -20%

CURRENT LIMITATIONS:
  • GIFT Nifty pre-market indicator — requires NSE IFSC data feed
  • Event calendar awareness (RBI meeting day, Budget day) — planned
  • Delivery volume analysis (genuine buying/selling) — planned (B4)
  • Sector/peer comparison — planned (B5)

When a user asks something that requires a future capability, acknowledge what you can
answer now and note what additional context will improve the analysis.
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


@mcp.tool()
def fii_dii_activity() -> dict:
    """
    Get the latest available FII/FPI and DII cash market activity from NSE.

    Returns buy value, sell value, and net (all in ₹ crores) for both
    FII/FPI and DII, plus a directional signal.

    IMPORTANT — Data freshness:
      NSE publishes final FII/DII numbers between 8:30–9:30 PM IST.
      Before that, this returns the PREVIOUS trading day's data.
      Always check the 'date' field to see which day the data is for.
      If 'is_stale' is true, tell the user the data is from a prior day.

    Use when asked about:
      • Institutional buying/selling today
      • FII or DII flows, sentiment, or activity
      • "Who is driving the market today?"
      • Any question about net foreign or domestic institution flows

    Signals:
      strongly_bullish  → FII net > ₹500 cr AND DII also net buyers
      bullish           → FII net > ₹500 cr
      neutral           → FII net between -₹500 cr and +₹500 cr
      bearish           → FII net < -₹500 cr
      strongly_bearish  → FII net < -₹500 cr AND DII also net sellers
    """
    return get_fii_dii_activity()


@mcp.tool()
def participant_oi(date: str = "latest") -> dict:
    """
    Get F&O participant-wise open interest breakdown from NSE archives.

    Args:
      date: Trading date in DD-MM-YYYY format, e.g. "10-03-2026".
            Use "latest" (default) to get the most recent available day.
            NSE publishes data after market close (~6 PM IST).

    Participants: FII, DII, Client (retail), Pro (proprietary desks)

    Returns long/short OI in contracts for:
      • Index futures (fut_index_long / fut_index_short / fut_index_net)
      • Stock futures
      • Index call & put options
      • Stock call & put options
      • Total long/short/net across all segments

    Use when asked about:
      • F&O positioning of FIIs or institutions
      • Whether FIIs are net long or short on index futures
      • Retail (Client) vs institutional positioning divergence
      • Derivatives-based market direction signals

    Key signal: fii_index_futures_signal
      bullish  → FII net index futures position > +50,000 contracts
      bearish  → FII net index futures position < -50,000 contracts
      neutral  → within ±50,000 contracts
    """
    return get_participant_oi(date)


@mcp.tool()
def option_chain(underlying: str = "NIFTY", expiry: str = "near") -> dict:
    """
    Get the full option chain for an index or stock F&O with PCR, Max Pain,
    OI walls, and ATM chain (LTP, OI, IV, Delta for each strike).

    Args:
      underlying: Underlying name — "NIFTY" (default), "BANKNIFTY", "FINNIFTY",
                  "MIDCPNIFTY", or any stock F&O tradingsymbol.
      expiry:     "near" (default) = nearest weekly/monthly expiry.
                  Or exact date in DD-MMM-YYYY format, e.g. "27-Mar-2026".

    Returns:
      spot, ATM strike, days to expiry, lot size
      pcr:               Put-Call Ratio with signal + interpretation
                           strongly_bullish → PCR ≥ 1.3 (extreme put loading)
                           bullish          → PCR 1.0–1.3
                           neutral          → PCR 0.7–1.0
                           bearish          → PCR 0.5–0.7
                           strongly_bearish → PCR < 0.5 (excessive call buying)
      max_pain:          Strike where option writers benefit most, distance from spot
      call_oi_wall:      Highest OI call strike = key resistance level
      put_oi_wall:       Highest OI put strike  = key support level
      top_call/put_strikes: Top 5 strikes by OI for each side
      atm_chain:         ATM ±10 strikes — call/put LTP, OI, IV, Delta per row
      available_expiries: Next 5–6 expiry dates to choose from

    Use when asked:
      • "Where is Nifty likely to stay / expire this week?"
        → Synthesise: max_pain + call_oi_wall (resistance) + put_oi_wall (support)
      • "Should I buy or sell/write options?"
        → Combine with vix() — PCR signal + VIX regime + days_to_expiry
      • "What is the PCR / put-call ratio?"
      • "Show me the option chain for BankNifty March expiry"
      • "What strikes have maximum OI buildup?"
      • "What is the max pain level?"
    """
    return get_option_chain(underlying, expiry)


@mcp.tool()
def vix() -> dict:
    """
    Get India VIX (Fear & Greed index for options) with regime and strategy guidance.

    India VIX is the NSE volatility index: 30-day implied volatility derived from
    Nifty option prices. Higher VIX = more expensive options = more market fear.

    Returns:
      vix, prev_close, change, change_pct
      day_high, day_low
      regime:                  very_low / low / normal / elevated / high / extreme
      interpretation:          Actionable strategy guidance (buy vs write options)
      weekly_move_1sigma_pct:  Expected ±% weekly move implied by current VIX

    Regime thresholds:
      < 12: Very low   — buy options; premiums historically cheap
      12–16: Low       — lean toward buying; limited edge for writers
      16–20: Normal    — balanced; credit spreads and iron condors work well
      20–25: Elevated  — writing earns good premium; use defined-risk spreads
      25–30: High      — buying protection/leverage is valuable; avoid naked writing
      > 30: Extreme    — mean-reversion play; sell vol after spike peaks

    Use when asked:
      • "What is India VIX?" / "How fearful is the market?"
      • "Should I buy or sell options right now?"
      • "Are options cheap or expensive?"
      • "What weekly move is the market pricing in?"
      • Any question about implied volatility, option premiums, or market anxiety

    Always call alongside option_chain() for a complete derivatives picture.
    """
    return get_vix()


@mcp.tool()
def global_markets() -> dict:
    """
    Get a live snapshot of major global equity indices with India market signal.

    Returns S&P 500, Nasdaq Composite, Nikkei 225, Hang Seng, and FTSE 100,
    each with current price, day change (₹ and %), and an india_signal.
    A composite india_equity_signal summarises the overall equity backdrop.

    Use when asked:
      • "How did Wall Street close?"
      • "How are Asian markets today?"
      • "Is the global equity backdrop positive for India?"
      • Any question about US/Asian/European markets in the context of Nifty

    india_signal per index:
      bullish        → index up ≥ 1.5%  — risk-on, FII inflows likely
      mildly_bullish → up 0.4–1.5%
      neutral        → within ±0.4%
      mildly_bearish → down 0.4–1.5%
      bearish        → down ≥ 1.5%      — risk-off, FII selling pressure

    Data freshness:
      S&P / Nasdaq  — live 9:30 PM–4:00 AM IST; previous close otherwise
      Nikkei        — live ~6:00–14:30 IST; previous close otherwise
      Hang Seng     — live ~7:00–14:30 IST; previous close otherwise
    """
    return get_global_markets()


@mcp.tool()
def macro_snapshot() -> dict:
    """
    Get the full global macro picture with India-specific impact signals.

    Fetches and interprets all external forces that drive FII flows and
    Indian equity direction in one comprehensive call:

      global_indices:  S&P 500, Nasdaq, Nikkei, Hang Seng, FTSE 100
      commodities:     WTI crude, Brent crude, Gold
      forex:           US Dollar Index (DXY), USD/INR, EUR/USD
      us_yields:       US 10Y (^TNX) & 5Y (^FVX) yield + yield curve steepness

    Each factor carries an india_signal.  A composite india_macro_signal
    summarises the overall picture (bullish / mildly_bullish / neutral /
    mildly_bearish / bearish for Indian equities).

    Use when asked:
      • "Will FIIs pull money out tomorrow?"
      • "Is the macro setup good for India?"
      • "What is the global backdrop for Nifty?"
      • "How do crude prices / DXY / US yields affect India?"
      • "Should I be worried about FII outflows?"

    Key synthesis logic embedded in india_macro_signal:
      DXY rising + US 10Y rising  → FII outflows likely
      S&P up + DXY flat           → risk-on, FII inflows supportive
      Crude rising sharply        → India macro headwind (import bill + inflation)
      USD/INR rising >0.3%        → INR weakness amplifies FII selling

    Always combine with fii_dii_activity() + participant_oi() to see how
    institutions are actually positioned versus what macro is implying.
    """
    return get_macro_snapshot()


@mcp.tool()
def market_news() -> dict:
    """
    Get latest market headlines from Indian financial RSS feeds and BBC.

    Sources: Economic Times (Markets + Economy), Moneycontrol, Livemint,
    BBC World, BBC Business, BBC Asia.

    Each headline is:
      • Categorized by topic (rbi_policy, fii_flows, crude_energy,
        us_fed, geopolitical, earnings, ipo_listing, rupee_forex, nifty_market)
      • Flagged for event risk (war, sanctions, crash, crisis, etc.)

    Returns:
      headlines:             Up to 60 latest headlines, newest first
                             Each has: title, source, published, link, summary,
                             categories (list), event_risk (bool)
      event_risk_count:      Number of headlines flagged as event risk
      event_risk_headlines:  Titles of flagged headlines
      sources_fetched:       Number of distinct news sources
      total_headlines:       Total headlines returned

    Use when asked:
      • "Is there any event risk today?"
      • "What's in the news today?"
      • "Any market-moving headlines?"
      • "What should I be aware of before trading?"

    Sentiment scoring:
      YOU interpret sentiment from each headline's text and summary.
      Look for: directional language (surge, plunge, rally, crash),
      policy signals (hawkish, dovish), and geopolitical escalation.

    Combine with fii_dii_activity() to see if news is already priced
    into institutional flows. Combine with macro_snapshot() to check
    whether global events match headline narrative.
    """
    return get_market_news()


@mcp.tool()
def news_search(query: str, period: str = "7d") -> dict:
    """
    Search Google News for headlines on a specific topic, event, or development.

    Free, real-time, no API key needed. Uses Google News India edition.

    Args:
      query:  Free-text search string. Examples:
                "Iran crude oil"
                "Fed rate decision"
                "RBI MPC"
                "Adani"
                "China Taiwan"
      period: Time window for results:
                "1d"  — today only (breaking news)
                "7d"  — past week (default, best for most questions)
                "1m"  — past month (for developing stories)

    Returns:
      query:          The search string used
      headlines:      Matching articles with title, source, published, link, summary,
                      categories (list), event_risk (bool)
      total_results:  Number of matching headlines
      source:         "google_news"

    Use when asked:
      • "What's happening with Iran / crude / the Fed?"
      • "Any news on [specific company]?"
      • "How does the [event] affect Indian markets?"
      • "Latest on RBI rate decision"

    Synthesise: combine headlines with quantitative tools (macro_snapshot,
    fii_dii_activity, vix) to assess whether the news is already reflected
    in market positioning and prices.
    """
    return get_news_search(query, period)


@mcp.tool()
def news_topic(topic: str = "BUSINESS") -> dict:
    """
    Get Google News headlines by major topic (India edition).

    Args:
      topic: One of: WORLD, NATION, BUSINESS, TECHNOLOGY,
             ENTERTAINMENT, SPORTS, SCIENCE, HEALTH.
             Default: "BUSINESS".

    Returns:
      topic:          The topic fetched
      headlines:      Articles with title, source, published, link, summary,
                      categories (list), event_risk (bool)
      total_results:  Number of headlines
      source:         "google_news"

    Use when asked:
      • "What's the business news today?" → news_topic("BUSINESS")
      • "Any world news I should care about?" → news_topic("WORLD")
      • "What's happening in tech?" → news_topic("TECHNOLOGY")

    Prefer market_news() for Indian market-specific headlines from
    financial RSS feeds. Use news_topic() for broader thematic coverage.
    """
    return get_news_topic(topic)


@mcp.tool()
def technicals(symbol: str, period: int = 200) -> dict:
    """
    Get full technical analysis for any stock or index.

    Computes 20/50/200 DMA, RSI-14, Bollinger Bands (20,2), MACD (12,26,9),
    support/resistance, and relative strength vs Nifty (for stocks).

    Args:
      symbol: NSE/BSE symbol. e.g. "RELIANCE", "NIFTY 50", "NSE:INFY"
      period: Days of history for calculations (default 200).
              200 is enough for 200 DMA. Max 2000.

    Returns:
      current_price:   Latest closing price
      dma:             20/50/200 DMA values, above/below flags, distance %,
                       golden/death cross, trend alignment (strong_uptrend →
                       strong_downtrend)
      rsi:             RSI-14 value + overbought/oversold/neutral signal
      bollinger:       Upper/middle/lower bands, bandwidth %, %B position,
                       overbought/oversold/within_bands signal
      macd:            MACD line, signal line, histogram, crossover detection,
                       bullish/bearish trend
      support_resistance: Up to 3 resistance and 3 support levels from
                       recent swing highs/lows, plus period high/low
      technical_stance: Composite signal (bullish/neutral/bearish) from
                       all indicators above
      relative_strength_vs_nifty: (stocks only) 1-week, 1-month, 3-month
                       stock return vs Nifty return + outperformance %

    Use when asked:
      • "Show me HDFC Bank technicals" → technicals("HDFCBANK")
      • "Is RELIANCE in an uptrend?" → technicals("RELIANCE")
      • "What's Nifty support level?" → technicals("NIFTY 50")
      • "Is TCS outperforming the market?" → check relative_strength_vs_nifty
      • "Where are the moving averages for BankNifty?" → technicals("NIFTY BANK")
      • Any question about DMA, RSI, Bollinger, MACD, or trend analysis
    """
    return get_technical_analysis(symbol, period)


@mcp.tool()
def fundamentals(symbol: str) -> dict:
    """
    Get fundamental analysis for an NSE-listed stock.

    Fetches valuation ratios, growth metrics, profitability, financial health,
    and market data from Yahoo Finance.

    Args:
      symbol: NSE trading symbol. e.g. "RELIANCE", "INFY", "HDFCBANK"

    Returns:
      valuation:        Trailing P/E, forward P/E, P/B, EV/EBITDA, PEG ratio,
                        multi-factor assessment (undervalued → overvalued)
      growth:           Revenue growth %, earnings growth %
      profitability:    Profit margin %, operating margin %, ROE %
      financial_health: Debt/equity, current ratio, health assessment
                        (strong/healthy/adequate/moderate_leverage/highly_leveraged)
      market_data:      52-week high/low/range, beta, dividend yield %,
                        book value, average 10-day volume
      Also: sector, industry, market cap in ₹ crores, company name

    Use when asked:
      • "Is INFY cheap?" → fundamentals("INFY")
      • "What's Reliance's P/E ratio?" → fundamentals("RELIANCE")
      • "How leveraged is Tata Motors?" → fundamentals("TATAMOTORS")
      • "What's HDFC Bank's ROE?" → fundamentals("HDFCBANK")
      • "Does TCS pay dividends?" → fundamentals("TCS")
      • Any question about valuation, financials, growth, or stock fundamentals

    For a complete stock view, combine with technicals() + quote().
    Data source: Yahoo Finance (.NS tickers). Cached for 5 minutes.
    """
    return get_stock_fundamentals(symbol)


@mcp.tool()
def market_brief() -> dict:
    """
    Get a comprehensive scored market brief — all layers in one call.

    Fetches Layers 1–5 in parallel, normalizes every signal to a common
    -1.0 (bearish) → 0.0 (neutral) → +1.0 (bullish) scale, detects the
    current market regime, flags inter-signal conflicts, and computes
    a regime-aware composite score.

    Returns:
      nifty:          Nifty 50 spot, today's change %, days to nearest expiry
      regime:         Current market regime with triggers and suggested focus layer:
                      EXTREME FEAR (VIX>30) / EXODUS (FII single-day <-5000 Cr or
                      5-day <-10000 Cr) / CORRECTION (>5% drawdown + VIX rising) /
                      FEAR (VIX>22 or VIX spiked >10% today or VIX 3-day surge >25%) /
                      EXPIRY / GREED / SIDEWAYS / NORMAL
      multiday_context: FII 5-day sum, VIX 3-day change %, drawdown from peak %,
                      Nifty distance from 200 DMA % (from stored snapshots + technicals)
      signals:        Per-layer scored signals:
                        derivatives: PCR, max pain distance, VIX, OI walls
                        flows:       FII cash, DII cash, FII index futures net
                        macro:       India macro composite, DXY, crude, US 10Y, USD/INR, S&P
                        news:        Event risk density
                      Each signal has: score (-1→+1), magnitude, direction, raw value, note
                      Each layer has: layer_score (average of its sub-signals)
      conflicts:      Divergences between signal groups (e.g. FII cash buying but
                      futures short; macro bearish but FII still buying)
      composite:      Weighted composite score, magnitude, direction, weights used,
                      per-layer scores. Default weights are regime-aware.
      data_issues:    Any layers that failed to fetch (null if all OK)

    Use when asked:
      • "What's the overall market setup?"
      • "Should I be long or short Nifty?"
      • "Is it safe to trade / buy calls / go long today?"
      • "Give me the full picture before I trade"
      • "What are the signals saying?"
      • Any broad directional or sentiment question

    IMPORTANT: This tool fetches NIFTY data. For BankNifty, stock-specific,
    or custom expiry questions, use option_chain() + vix() directly.

    After receiving results, ADJUST the default weights based on:
      1. Question type (options → derivatives heavy; macro → macro heavy)
      2. Time horizon (intraday → news+derivatives; monthly → macro+flows)
      3. See SIGNAL WEIGHTING GUIDANCE in the system prompt
    """
    return get_market_brief()


@mcp.tool()
def history(days: int = 30) -> dict:
    """
    Summarize market conditions over the most recent N trading days.

    Uses stored daily snapshots (60+ days accumulated since Dec 2025).

    Args:
      days: Number of recent trading days to summarize. Default: 30.

    Returns:
      period:       Start/end dates, trading days covered, total snapshots available
      nifty:        Start/end close, period return %, high/low, avg day range
      vix:          Current, average, min, max over the period
      fii_flows:    Cumulative net, avg daily, positive/negative day counts,
                    current selling/buying streak
      dii_flows:    Cumulative net, avg daily
      composite:    Current score, avg/min/max over period
      regimes:      Count of each regime over the period (normal, fear, exodus, etc.)

    Use when asked:
      • "How has the market been this month / this week / last N days?"
      • "Give me a recap of the last 2 weeks"
      • "What's the market trend over the past month?"
      • "How many days has it been bearish?"
    """
    return get_history_summary(days)


@mcp.tool()
def fii_flow_trend(days: int = 5) -> dict:
    """
    FII flow trend over the most recent N trading days.

    Shows daily FII cash + futures breakdown, running cumulative, streak
    analysis, and whether DII is absorbing FII selling.

    Args:
      days: Number of recent trading days. Default: 5.

    Returns:
      daily:     Per-day: FII cash net, DII cash net, FII futures net,
                 Nifty change %, running FII cumulative
      summary:   Cumulative FII cash, avg daily, selling/buying streak days,
                 trend direction (accelerating_selling / decelerating_selling /
                 accelerating_buying / steady)
      dii_offset: Cumulative DII cash, whether DII is absorbing FII selling
      fii_futures: Latest FII futures net position + signal

    Use when asked:
      • "Are FIIs still selling?"
      • "How long have FIIs been bearish?"
      • "Is FII selling getting worse or better?"
      • "How much have FIIs sold this month?"
      • "Is DII absorbing the FII selling?"
    """
    return get_fii_trend(days)


@mcp.tool()
def similar_historical_setups(
    vix_above: float | None = None,
    vix_below: float | None = None,
    fii_net_below: float | None = None,
    fii_net_above: float | None = None,
    regime: str | None = None,
    composite_below: float | None = None,
    composite_above: float | None = None,
) -> dict:
    """
    Find past trading days where conditions matched the given filters.

    Searches all stored daily snapshots and returns matching days with
    their market state + what happened the next trading day.

    Args:
      vix_above:       Only days where VIX > this value
      vix_below:        Only days where VIX < this value
      fii_net_below:    Only days where FII net < this (₹ Cr). e.g. -3000
      fii_net_above:    Only days where FII net > this (₹ Cr). e.g. 1000
      regime:           Only days with this regime (fear, exodus, greed, normal, etc.)
      composite_below:  Only days where composite score < this
      composite_above:  Only days where composite score > this

    All parameters are optional — combine as needed.

    Returns:
      filters:              The filter criteria used
      matches_found:        Number of matching days
      matches:              Up to 20 most recent matches, each with:
                             date, nifty_close, nifty_change_pct, vix, fii_net,
                             regime, composite_score, next_day outcome
      next_day_outcomes:    Statistical summary across all matches:
                             avg next-day change %, win rate, max gain/loss

    Use when asked:
      • "What happened last time VIX spiked above 25?"
        → similar_historical_setups(vix_above=25)
      • "History when FIIs sold more than ₹3000 Cr?"
        → similar_historical_setups(fii_net_below=-3000)
      • "What happened in past exodus regimes?"
        → similar_historical_setups(regime="exodus")
      • "Should I buy the dip?" — combine with drawdown()
        → similar_historical_setups(composite_below=-0.3)
    """
    return get_similar_setups(
        vix_above=vix_above,
        vix_below=vix_below,
        fii_net_below=fii_net_below,
        fii_net_above=fii_net_above,
        regime=regime,
        composite_below=composite_below,
        composite_above=composite_above,
    )


@mcp.tool()
def drawdown() -> dict:
    """
    Current drawdown analysis from recent Nifty highs.

    Looks back across all stored daily snapshots to find the all-time peak,
    calculates drawdown depth, identifies the trough, and provides institutional
    flow context during the drawdown period.

    Returns:
      status:           near_highs / mild_pullback / moderate_correction /
                        correction / deep_correction / bear_market
      peak:             Nifty close + date of the all-time high in stored data
      trough:           Nifty close + date of the lowest point since peak,
                        max drawdown % from peak
      current:          Today's Nifty close, drawdown from peak %,
                        recovery from trough % (if bouncing)
      duration:         Trading days since peak, days in drawdown
      during_drawdown:  FII cumulative ₹ Cr, DII cumulative ₹ Cr,
                        VIX at peak vs current vs max during drawdown

    Use when asked:
      • "How far are we from all-time highs?"
      • "How deep is this correction?"
      • "Should I buy the dip?" (combine with similar_historical_setups)
      • "Are we in a bear market?"
      • "How much have FIIs sold during this fall?"
    """
    return get_drawdown_status()


@mcp.tool()
def stock_brief(symbol: str) -> dict:
    """
    Get a comprehensive scored brief for any NSE-listed stock — all dimensions
    in one call.

    Fetches technicals, fundamentals, live quote, and recent news in parallel.
    Scores 7 dimensions to a common -1.0 (bearish) → +1.0 (bullish) scale,
    detects the stock's overall stance, and computes a weighted composite.

    Args:
      symbol: NSE trading symbol. e.g. "RELIANCE", "INFY", "HDFCBANK", "TCS"

    Returns:
      price:          LTP, session change (₹ and %), volume
      stance:         Stock stance with key + label:
                      TECHNICALLY STRONG — good technicals + relative strength
                      FUNDAMENTALLY STRONG — good valuation + growth
                      MOMENTUM (EXPENSIVE) — strong technicals, stretched valuation
                      VALUE OPPORTUNITY — attractive fundamentals, weak price action
                      TECHNICALLY WEAK — poor price action, wait for reversal
                      OVERVALUED — stretched valuation without growth support
                      DETERIORATING — weak technicals + poor fundamentals
                      NEUTRAL — mixed signals
      signals:        Per-dimension scored signals:
                        technicals:       from DMA, RSI, Bollinger, MACD, stance
                        relative_strength: vs Nifty 50 (1w/1m/3m weighted)
                        valuation:        PEG/PE-based assessment
                        growth:           revenue + earnings growth
                        financial_health: debt/equity + current ratio
                        momentum:         session day change
                        news:             event-risk density from recent headlines
                      Each signal has: score (-1→+1), magnitude, direction, note
      composite:      Weighted composite score, magnitude, direction, weights used
                      Default: technicals 25%, valuation 20%, growth 15%,
                      relative_strength 10%, financial_health 10%, momentum 10%, news 10%
      key_levels:     20/50/200 DMA + support + resistance levels
      fundamental_snapshot: sector, industry, market cap, P/E, ROE
      recent_news:    Latest 8 headlines for Claude to interpret sentiment
      data_issues:    Any dimensions that failed to fetch (null if all OK)

    Use when asked:
      • "What do you think about RELIANCE?"
      • "Is INFY a buy at this level?"
      • "Should I enter HDFCBANK here?"
      • "Give me the full picture on TCS"
      • "How does ICICIBANK look?"
      • Any broad stock-level question needing multi-dimensional analysis

    After receiving results, ADJUST the default weights based on:
      1. Question type: valuation questions → boost valuation weight;
         technical questions → boost technicals weight
      2. Time horizon: short-term → technicals + momentum;
         long-term → valuation + growth + financial health
      3. Lead with the stance and composite direction
      4. Highlight the strongest / weakest signal dimensions
      5. Use key_levels for actionable entry/exit guidance
      6. Interpret recent_news headlines for catalysts Claude couldn't auto-score
    """
    return get_stock_brief(symbol)


if __name__ == "__main__":
    mcp.run()
