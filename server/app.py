from mcp.server.fastmcp import FastMCP
from tools.kite_tools import get_quote, get_indices, get_historical_ohlc
from tools.nse_tools import get_fii_dii_activity, get_participant_oi
from tools.derivatives_tools import get_option_chain, get_vix
from tools.macro_tools import get_global_markets, get_macro_snapshot
from tools.news_tools import get_market_news, get_news_search, get_news_topic
from tools.signal_tools import get_market_brief

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

Layer 6 — Signal Scoring & Market Brief:
  • One-call aggregation of ALL layers into a single scored brief
  • Every signal normalized to -1.0 (bearish) → 0.0 (neutral) → +1.0 (bullish)
  • Graduated intensity — e.g. FII -187k contracts scores -0.87, not just "bearish"
  • Market regime detection: EXTREME FEAR / FEAR / EXODUS / GREED / SIDEWAYS / EXPIRY / NORMAL
  • Regime-aware default weights (which layer matters most right now)
  • Inter-signal conflict flagging (e.g. FII cash buying + futures short)
  • Default composite score with the weights used
  • YOU adjust weights based on the user's question type and time horizon

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
      US 10Y & 2Y yields + yield curve steepness
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

CURRENT LIMITATIONS:
  • GIFT Nifty pre-market indicator — requires NSE IFSC data feed
  • Multi-day regime detection (e.g. "FII selling for 5 days") — requires
    historical lookback; currently uses single-day data only
  • Event calendar awareness (RBI meeting day, Budget day) — planned
  • 200 DMA regime detection — planned (requires historical OHLC call)

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
    Get today's FII/FPI and DII cash market activity from NSE.

    Returns buy value, sell value, and net (all in ₹ crores) for both
    FII/FPI and DII, plus a directional signal.

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

    Note: Intraday values are provisional; final figures available after 3:45 PM IST.
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
def market_brief() -> dict:
    """
    Get a comprehensive scored market brief — all layers in one call.

    Fetches Layers 1–5 in parallel, normalizes every signal to a common
    -1.0 (bearish) → 0.0 (neutral) → +1.0 (bullish) scale, detects the
    current market regime, flags inter-signal conflicts, and computes
    a regime-aware composite score.

    Returns:
      nifty:          Nifty 50 spot, today's change %, days to nearest expiry
      regime:         Current market regime (FEAR / GREED / SIDEWAYS / EXPIRY /
                      EXODUS / NORMAL) with triggers and suggested focus layer
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


if __name__ == "__main__":
    mcp.run()
