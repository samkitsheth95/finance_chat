"""
Layer 5 — News & Sentiment Tools

Aggregates headlines from Indian financial RSS feeds, BBC, and Google News.
Categorizes by market-relevant topics and flags event risk for Claude to interpret.

Three public functions:
  get_market_news()        → latest headlines from RSS feeds (Indian financial + BBC)
  get_news_search(query)   → keyword search via Google News (free, real-time)
  get_news_topic(topic)    → Google News by topic (BUSINESS, WORLD, etc.)

Claude performs sentiment scoring — these tools provide structured, categorized
headlines with enough context for Claude to assess directional impact.
"""

from __future__ import annotations

import re
from datetime import datetime

from core.news_client import fetch_all_rss, gnews_search, gnews_topic


# ---------------------------------------------------------------------------
# Category and event risk keyword maps
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "rbi_policy": [
        "rbi", "reserve bank", "rate cut", "rate hike", "repo rate",
        "monetary policy", "mpc meeting", "inflation target",
        "standing deposit", "reverse repo",
    ],
    "fii_flows": [
        "fii", "fpi", "foreign institutional", "foreign portfolio",
        "dii", "institutional investor", "foreign fund",
    ],
    "crude_energy": [
        "crude oil", "oil price", "opec", "petroleum", "brent crude",
        "energy price", "natural gas", "fuel price",
    ],
    "us_fed": [
        "federal reserve", "fed rate", "powell", "fomc", "us interest rate",
        "us treasury", "wall street", "us inflation", "us jobs",
        "us payroll", "dot plot",
    ],
    "geopolitical": [
        "geopolitical", "war ", "conflict", "sanction", "military",
        "nuclear", "missile", "attack", "terror", "ceasefire",
        "invasion", "coup", "protest", "escalat",
    ],
    "earnings": [
        "quarterly result", "earnings", "profit after tax", "revenue growth",
        "q1 result", "q2 result", "q3 result", "q4 result",
        "guidance", "margin expansion", "margin contraction",
    ],
    "ipo_listing": [
        "ipo", "listing gain", "listing loss", "debut", "public offer",
        "public issue", "allotment", "subscription",
    ],
    "rupee_forex": [
        "rupee", "usdinr", "forex reserve", "dollar index", "currency",
        "exchange rate", " inr ", "depreciat", "appreciat",
    ],
    "nifty_market": [
        "nifty", "sensex", "bank nifty", "market crash", "market rally",
        "bull run", "bear market", "correction", "circuit breaker",
    ],
}

_EVENT_RISK_KEYWORDS: list[str] = [
    "war ", "sanctions", "default", "crash", "emergency", "terrorist",
    "nuclear", "invasion", "recession", "crisis", "collapse", "shutdown",
    "downgrade", "ban ", "freeze", "pandemic", "circuit breaker",
    "flash crash", "martial law", "coup", "escalation", "black swan",
]


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------

def get_market_news() -> dict:
    """
    Aggregate latest market headlines from Indian financial RSS feeds and BBC.

    Sources: Economic Times (Markets + Economy), Moneycontrol, Livemint,
    BBC World, BBC Business, BBC Asia.

    Headlines are deduplicated, categorized by topic, and flagged for event risk.

    Returns:
        {
          "headlines":             list of headline dicts with categories + event_risk flag,
          "event_risk_count":      int,
          "event_risk_headlines":  list of titles flagged as high-impact events,
          "sources_fetched":       int,
          "total_headlines":       int,
          "as_of":                 str,
        }
    """
    try:
        raw_entries = fetch_all_rss()
    except Exception as e:
        return {"error": f"Failed to fetch RSS feeds: {e}"}

    if not raw_entries:
        return {
            "headlines": [],
            "event_risk_count": 0,
            "event_risk_headlines": [],
            "sources_fetched": 0,
            "total_headlines": 0,
            "note": "No headlines retrieved — RSS feeds may be unreachable",
            "as_of": _now(),
        }

    unique = _deduplicate(raw_entries)
    _enrich(unique)
    unique.sort(key=lambda e: e.get("published", ""), reverse=True)
    headlines = unique[:60]

    event_risk = [h for h in headlines if h.get("event_risk")]
    sources = {h["source"] for h in headlines}

    return {
        "headlines": headlines,
        "event_risk_count": len(event_risk),
        "event_risk_headlines": [h["title"] for h in event_risk],
        "sources_fetched": len(sources),
        "total_headlines": len(headlines),
        "as_of": _now(),
    }


def get_news_search(query: str, period: str = "7d") -> dict:
    """
    Search Google News for headlines on a specific topic.

    Uses the gnews package (Google News RSS wrapper) — free, no API key,
    real-time results with no delay.

    Args:
        query:  Free-text search string. Examples:
                "Iran crude oil", "Fed rate decision", "Adani", "RBI MPC"
        period: Time window — "1d" (today), "7d" (week), "1m" (month).
                Default "7d".

    Returns:
        {
          "query":          str,
          "headlines":      list of headline dicts,
          "total_results":  int,
          "source":         "google_news",
          "as_of":          str,
        }
    """
    try:
        articles = gnews_search(query, period=period, max_results=20)
    except Exception as e:
        return {"error": f"Failed to search Google News for '{query}': {e}"}

    _enrich(articles)

    return {
        "query": query,
        "period": period,
        "headlines": articles,
        "total_results": len(articles),
        "source": "google_news",
        "as_of": _now(),
    }


def get_news_topic(topic: str = "BUSINESS") -> dict:
    """
    Fetch Google News by major topic (India edition).

    Available topics: WORLD, NATION, BUSINESS, TECHNOLOGY,
    ENTERTAINMENT, SPORTS, SCIENCE, HEALTH.

    Args:
        topic: One of the supported topic names (case-insensitive).

    Returns:
        {
          "topic":          str,
          "headlines":      list of headline dicts,
          "total_results":  int,
          "source":         "google_news",
          "as_of":          str,
        }
    """
    topic_upper = topic.strip().upper()
    try:
        articles = gnews_topic(topic_upper, max_results=20)
    except Exception as e:
        return {"error": f"Failed to fetch Google News topic '{topic}': {e}"}

    _enrich(articles)

    return {
        "topic": topic_upper,
        "headlines": articles,
        "total_results": len(articles),
        "source": "google_news",
        "as_of": _now(),
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _enrich(entries: list[dict]) -> None:
    """Add categories and event_risk flag to each entry in-place."""
    for entry in entries:
        text = f"{entry.get('title', '')} {entry.get('summary', '')}".lower()
        entry["categories"] = _categorize(text)
        entry["event_risk"] = _is_event_risk(text)


def _deduplicate(entries: list[dict]) -> list[dict]:
    """Remove duplicate headlines by normalized title."""
    seen: set[str] = set()
    unique: list[dict] = []
    for entry in entries:
        norm = _normalize_title(entry.get("title", ""))
        if norm and norm not in seen:
            seen.add(norm)
            unique.append(entry)
    return unique


def _normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    if not title:
        return ""
    text = re.sub(r"[^\w\s]", "", title.lower())
    return re.sub(r"\s+", " ", text).strip()


def _categorize(text: str) -> list[str]:
    """Return category tags that match keywords in the text."""
    return [
        cat for cat, keywords in _CATEGORY_KEYWORDS.items()
        if any(kw in text for kw in keywords)
    ]


def _is_event_risk(text: str) -> bool:
    """Check whether text contains high-impact event risk keywords."""
    return any(kw in text for kw in _EVENT_RISK_KEYWORDS)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
