"""
Layer 5 — News & Sentiment
Raw data-fetch layer for RSS feeds and Google News.

Indian financial RSS:  Economic Times, Moneycontrol, Livemint
Global / geopolitical: BBC World, BBC Business, BBC Asia
Keyword search:        GNews (Google News RSS wrapper — free, no API key, real-time)

Caching:
  RSS feeds cached for _RSS_CACHE_TTL seconds (5 min).
  GNews results cached for _GNEWS_CACHE_TTL seconds (5 min).
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from html import unescape

import feedparser
import requests
from gnews import GNews

# Trigger the global SSL bypass patch in kite_client if KITE_SSL_VERIFY=false.
import core.kite_client  # noqa: F401

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_RSS_CACHE_TTL = 300    # 5 minutes
_GNEWS_CACHE_TTL = 300  # 5 minutes

RSS_FEEDS: dict[str, dict[str, str]] = {
    # Indian financial
    "et_markets": {
        "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "label": "Economic Times Markets",
    },
    "et_economy": {
        "url": "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms",
        "label": "Economic Times Economy",
    },
    "moneycontrol": {
        "url": "https://www.moneycontrol.com/rss/latestnews.xml",
        "label": "Moneycontrol",
    },
    "livemint": {
        "url": "https://www.livemint.com/rss/markets",
        "label": "Livemint Markets",
    },
    # BBC — global / geopolitical / real-time event coverage
    "bbc_world": {
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "label": "BBC World",
    },
    "bbc_business": {
        "url": "https://feeds.bbci.co.uk/news/business/rss.xml",
        "label": "BBC Business",
    },
    "bbc_asia": {
        "url": "https://feeds.bbci.co.uk/news/world/asia/rss.xml",
        "label": "BBC Asia",
    },
}

_HTTP_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
}

# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------

_rss_cache: dict[str, tuple[list[dict], float]] = {}
_gnews_cache: dict[str, tuple[list[dict], float]] = {}


# ---------------------------------------------------------------------------
# RSS feeds
# ---------------------------------------------------------------------------

def fetch_rss_feed(feed_key: str) -> list[dict]:
    """
    Fetch and parse a single RSS feed.

    Returns list of headline dicts: {title, source, published, link, summary}.
    Uses requests for HTTP (so the global SSL bypass applies), then parses
    the response body with feedparser.
    """
    now = time.monotonic()
    if feed_key in _rss_cache:
        cached, ts = _rss_cache[feed_key]
        if now - ts < _RSS_CACHE_TTL:
            return cached

    feed_config = RSS_FEEDS.get(feed_key)
    if not feed_config:
        return []

    try:
        resp = requests.get(
            feed_config["url"],
            headers=_HTTP_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        parsed = feedparser.parse(resp.text)
    except Exception:
        return _rss_cache.get(feed_key, ([], 0))[0]

    entries: list[dict] = []
    for entry in parsed.entries:
        entries.append({
            "title": entry.get("title", "").strip(),
            "source": feed_config["label"],
            "published": _parse_rss_date(entry),
            "link": entry.get("link", ""),
            "summary": _clean_html(entry.get("summary", "")),
        })

    _rss_cache[feed_key] = (entries, now)
    return entries


def fetch_all_rss() -> list[dict]:
    """Fetch all configured RSS feeds and return merged entries."""
    all_entries: list[dict] = []
    for key in RSS_FEEDS:
        all_entries.extend(fetch_rss_feed(key))
    return all_entries


# ---------------------------------------------------------------------------
# Google News (via gnews package)
# ---------------------------------------------------------------------------

def gnews_search(
    query: str,
    period: str = "7d",
    max_results: int = 20,
) -> list[dict]:
    """
    Search Google News for headlines matching a query.

    Free, no API key, real-time results (no delay).
    Uses the gnews package which wraps Google News RSS.

    Args:
        query:       Search keywords, e.g. "Iran crude oil", "RBI MPC"
        period:      Time window — "1d", "7d", "1m" etc.
        max_results: Max headlines to return (default 20)

    Returns list of headline dicts: {title, source, published, link, summary}.
    """
    cache_key = f"{query}::{period}::{max_results}"
    now = time.monotonic()
    if cache_key in _gnews_cache:
        cached, ts = _gnews_cache[cache_key]
        if now - ts < _GNEWS_CACHE_TTL:
            return cached

    try:
        gn = GNews(
            language="en",
            country="IN",
            period=period,
            max_results=max_results,
        )
        raw_articles = gn.get_news(query)
    except Exception:
        return _gnews_cache.get(cache_key, ([], 0))[0]

    entries = _normalize_gnews(raw_articles)
    _gnews_cache[cache_key] = (entries, now)
    return entries


def gnews_top_news(max_results: int = 20) -> list[dict]:
    """
    Fetch top news from Google News (India edition).
    Useful as a supplement to RSS for breaking stories.
    """
    cache_key = f"__top__::{max_results}"
    now = time.monotonic()
    if cache_key in _gnews_cache:
        cached, ts = _gnews_cache[cache_key]
        if now - ts < _GNEWS_CACHE_TTL:
            return cached

    try:
        gn = GNews(language="en", country="IN", max_results=max_results)
        raw_articles = gn.get_top_news()
    except Exception:
        return _gnews_cache.get(cache_key, ([], 0))[0]

    entries = _normalize_gnews(raw_articles)
    _gnews_cache[cache_key] = (entries, now)
    return entries


def gnews_topic(topic: str = "BUSINESS", max_results: int = 20) -> list[dict]:
    """
    Fetch Google News by major topic (India edition).

    Topics: WORLD, NATION, BUSINESS, TECHNOLOGY, ENTERTAINMENT,
            SPORTS, SCIENCE, HEALTH.
    """
    cache_key = f"__topic__{topic}::{max_results}"
    now = time.monotonic()
    if cache_key in _gnews_cache:
        cached, ts = _gnews_cache[cache_key]
        if now - ts < _GNEWS_CACHE_TTL:
            return cached

    try:
        gn = GNews(language="en", country="IN", max_results=max_results)
        raw_articles = gn.get_news_by_topic(topic)
    except Exception:
        return _gnews_cache.get(cache_key, ([], 0))[0]

    entries = _normalize_gnews(raw_articles or [])
    _gnews_cache[cache_key] = (entries, now)
    return entries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_gnews(articles: list[dict]) -> list[dict]:
    """Convert gnews article dicts to our standard headline format."""
    entries: list[dict] = []
    for a in articles:
        publisher = a.get("publisher", {})
        if isinstance(publisher, dict):
            source = publisher.get("title", "Google News")
        else:
            source = str(publisher) or "Google News"

        entries.append({
            "title": (a.get("title") or "").strip(),
            "source": source,
            "published": a.get("published date", ""),
            "link": a.get("url", ""),
            "summary": (a.get("description") or "").strip(),
        })
    return entries


def _clean_html(text: str) -> str:
    """Strip HTML tags and decode entities to plain text."""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", text)
    return unescape(clean).strip()


def _parse_rss_date(entry) -> str:
    """Extract and normalize the published date from an RSS entry to ISO 8601."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass
    return entry.get("published", "")
