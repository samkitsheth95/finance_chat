from dotenv import load_dotenv
load_dotenv()

from mcp.server.fastmcp import FastMCP
from portfolio_doctor.tools.portfolio_tools import (
    ingest_client_trades,
    get_portfolio_overview,
)
from portfolio_doctor.tools.behavioral_tools import get_behavioral_audit
from portfolio_doctor.tools.alternative_tools import get_alternative_scenarios
from portfolio_doctor.tools.report_tools import get_action_plan, get_full_report_data, generate_report_html

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


@mcp.tool()
def generate_report(client_name: str) -> dict:
    """
    Generate a standalone HTML report for a client.

    Requires: ingest_trades() called first. Runs full_report_data() if
    not already cached, then generates a self-contained HTML file with
    interactive charts (equity curve, behavioral radar, allocation donut)
    and all analysis sections.

    Returns the file path to the generated report.html.
    Open the file in a browser to view.

    Use when asked: "Generate the report", "Create a presentation",
    "Give me the HTML report", "Export the analysis."
    """
    return generate_report_html(client_name)


if __name__ == "__main__":
    mcp.run()
