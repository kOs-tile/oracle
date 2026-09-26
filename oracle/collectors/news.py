"""
ORACLE News Collector
=====================
Fetches and classifies headlines from multiple sources:
  - CryptoPanic API   (crypto-specific news with built-in sentiment signals)
  - NewsAPI           (general tech/finance headlines)
  - Fallback RSS      (CoinDesk, CoinTelegraph) when API keys absent

Sentiment classification uses keyword heuristics (no external ML dependency).
Refresh interval: 5 minutes (configurable via REFRESH_INTERVAL_NEWS).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional
from xml.etree import ElementTree as ET

import httpx
from loguru import logger

from oracle.config import get_settings
from oracle.models import NewsItem, NewsState, Sentiment

# ── Sentiment keywords ────────────────────────────────────────────────────────

POSITIVE_KEYWORDS = frozenset(
    {
        "surge", "soar", "rally", "bullish", "record", "breakout", "adoption",
        "upgrade", "approve", "approved", "launch", "partnership", "buy",
        "all-time high", "ath", "growth", "gain", "profit", "win", "bull",
        "outperform", "beat", "milestone", "expand", "invest", "long",
        "bullrun", "pump", "moon", "optimistic", "positive", "rebound",
        "recover", "recovery", "rise", "risen", "boom", "strong",
    }
)

NEGATIVE_KEYWORDS = frozenset(
    {
        "crash", "drop", "fall", "dump", "bearish", "hack", "exploit",
        "scam", "fraud", "ban", "regulation", "restrict", "restrict",
        "collapse", "liquidat", "short", "fear", "panic", "plunge", "sink",
        "warning", "risk", "threat", "violation", "loss", "lose", "lost",
        "downgrade", "fail", "crisis", "bubble", "sell-off", "recession",
        "inflation", "debt", "default", "investigation", "lawsuit", "fine",
        "penalty", "negative", "concern", "worry", "uncertain",
    }
)


def classify_sentiment(text: str) -> Sentiment:
    """Classify headline sentiment via keyword matching."""
    lower = text.lower()
    pos_hits = sum(1 for kw in POSITIVE_KEYWORDS if kw in lower)
    neg_hits = sum(1 for kw in NEGATIVE_KEYWORDS if kw in lower)
    if pos_hits > neg_hits:
        return Sentiment.POSITIVE
    elif neg_hits > pos_hits:
        return Sentiment.NEGATIVE
    return Sentiment.NEUTRAL


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


# ── CryptoPanic ───────────────────────────────────────────────────────────────

CRYPTOPANIC_URL = "https://cryptopanic.com/api/free/v1/posts/"


async def fetch_cryptopanic(
    client: httpx.AsyncClient,
    limit: int = 20,
) -> list[NewsItem]:
    """Fetch crypto news from CryptoPanic API."""
    settings = get_settings()
    if not settings.cryptopanic_api_key:
        logger.debug("[news] No CryptoPanic key — skipping")
        return []

    params = {
        "auth_token": settings.cryptopanic_api_key,
        "public": "true",
        "kind": "news",
        "filter": "hot",
        "regions": "en",
    }

    try:
        resp = await client.get(CRYPTOPANIC_URL, params=params, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning(f"[news] CryptoPanic fetch failed: {exc}")
        return []

    items: list[NewsItem] = []
    for post in data.get("results", [])[:limit]:
        title = post.get("title", "")
        # CryptoPanic provides a 'votes' object that implies bullish/bearish
        votes: dict = post.get("votes", {})
        bullish = votes.get("positive", 0)
        bearish = votes.get("negative", 0)
        if bullish > bearish * 1.5:
            sentiment = Sentiment.POSITIVE
        elif bearish > bullish * 1.5:
            sentiment = Sentiment.NEGATIVE
        else:
            sentiment = classify_sentiment(title)

        currencies = [c["code"] for c in post.get("currencies", [])]
        items.append(
            NewsItem(
                title=title,
                url=post.get("url"),
                source=post.get("source", {}).get("title"),
                published_at=_parse_iso(post.get("published_at")),
                sentiment=sentiment,
                currencies=currencies,
                kind=post.get("kind", "news"),
                categories=["crypto"],
            )
        )

    logger.debug(f"[news] CryptoPanic returned {len(items)} items")
    return items


# ── NewsAPI ───────────────────────────────────────────────────────────────────

NEWSAPI_URL = "https://newsapi.org/v2/top-headlines"


async def fetch_newsapi(
    client: httpx.AsyncClient,
    query: str = "cryptocurrency OR bitcoin OR AI OR stock market",
    limit: int = 10,
) -> list[NewsItem]:
    """Fetch general headlines from NewsAPI."""
    settings = get_settings()
    if not settings.newsapi_key:
        logger.debug("[news] No NewsAPI key — skipping")
        return []

    params = {
        "apiKey": settings.newsapi_key,
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": limit,
    }

    try:
        resp = await client.get(NEWSAPI_URL, params=params, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning(f"[news] NewsAPI fetch failed: {exc}")
        return []

    items: list[NewsItem] = []
    for article in data.get("articles", [])[:limit]:
        title = article.get("title") or ""
        if "[Removed]" in title:
            continue
        items.append(
            NewsItem(
                title=title,
                url=article.get("url"),
                source=article.get("source", {}).get("name"),
                published_at=_parse_iso(article.get("publishedAt")),
                sentiment=classify_sentiment(title + " " + (article.get("description") or "")),
                categories=["general"],
                summary=article.get("description"),
            )
        )

    logger.debug(f"[news] NewsAPI returned {len(items)} items")
    return items


# ── RSS Fallback ──────────────────────────────────────────────────────────────

RSS_FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "CoinTelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
}


async def fetch_rss_fallback(
    client: httpx.AsyncClient,
    limit: int = 10,
) -> list[NewsItem]:
    """Fetch headlines from public RSS feeds as a fallback."""
    import asyncio

    async def _fetch_one(name: str, url: str) -> list[NewsItem]:
        try:
            resp = await client.get(url, timeout=10.0, follow_redirects=True)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            items: list[NewsItem] = []
            for entry in root.iter("item"):
                title_el = entry.find("title")
                link_el = entry.find("link")
                pub_el = entry.find("pubDate")
                if title_el is None or title_el.text is None:
                    continue
                title = title_el.text.strip()
                items.append(
                    NewsItem(
                        title=title,
                        url=link_el.text.strip() if link_el is not None and link_el.text else None,
                        source=name,
                        published_at=None,  # RSS pubDate parsing is locale-dependent
                        sentiment=classify_sentiment(title),
                        categories=["crypto"],
                    )
                )
            logger.debug(f"[news] RSS {name}: {len(items)} items")
            return items[:limit]
        except Exception as exc:
            logger.warning(f"[news] RSS {name} failed: {exc}")
            return []

    tasks = [_fetch_one(name, url) for name, url in RSS_FEEDS.items()]
    results = await asyncio.gather(*tasks)
    combined = [item for sublist in results for item in sublist]
    # Deduplicate by title similarity (simple)
    seen: set[str] = set()
    unique: list[NewsItem] = []
    for item in combined:
        key = re.sub(r"[^a-z0-9]", "", item.title.lower())[:60]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:limit]


# ── Trending Topics ───────────────────────────────────────────────────────────

def _extract_trending(headlines: list[NewsItem]) -> list[str]:
    """Extract pseudo-trending topics from headline keywords."""
    from collections import Counter

    STOP_WORDS = {
        "the", "a", "an", "in", "on", "of", "to", "and", "or", "for",
        "is", "are", "was", "were", "has", "have", "had", "will", "be",
        "with", "from", "by", "at", "as", "its", "it", "this", "that",
        "new", "says", "amid", "after", "over", "could", "may", "than",
    }

    word_counter: Counter = Counter()
    for item in headlines:
        words = re.findall(r"\b[A-Za-z]{3,}\b", item.title)
        for w in words:
            if w.lower() not in STOP_WORDS and len(w) > 2:
                word_counter[w.upper()] += 1

    return [w for w, _ in word_counter.most_common(10)]


# ── Main Entrypoint ───────────────────────────────────────────────────────────


async def collect_news() -> NewsState:
    """Main entry point — returns a fully populated NewsState."""
    import asyncio

    settings = get_settings()
    async with httpx.AsyncClient() as client:
        crypto_task = asyncio.create_task(fetch_cryptopanic(client))
        general_task = asyncio.create_task(fetch_newsapi(client))
        rss_task = asyncio.create_task(fetch_rss_fallback(client))

        crypto_items, general_items, rss_items = await asyncio.gather(
            crypto_task, general_task, rss_task
        )

    # Merge crypto sources (CryptoPanic + RSS fallback)
    all_crypto = crypto_items if crypto_items else rss_items
    all_general = general_items

    all_headlines = all_crypto + all_general
    pos = sum(1 for h in all_headlines if h.sentiment == Sentiment.POSITIVE)
    neg = sum(1 for h in all_headlines if h.sentiment == Sentiment.NEGATIVE)
    neu = len(all_headlines) - pos - neg

    dominant: Sentiment
    if pos > neg and pos > neu:
        dominant = Sentiment.POSITIVE
    elif neg > pos and neg > neu:
        dominant = Sentiment.NEGATIVE
    else:
        dominant = Sentiment.NEUTRAL

    trending = _extract_trending(all_headlines)

    logger.info(
        f"[news] {len(all_crypto)} crypto + {len(all_general)} general headlines | "
        f"sentiment: +{pos}/-{neg}/~{neu} | dominant: {dominant.value}"
    )

    return NewsState(
        crypto_headlines=all_crypto[:10],
        general_headlines=all_general[:10],
        trending_topics=trending,
        dominant_sentiment=dominant,
        positive_count=pos,
        negative_count=neg,
        neutral_count=neu,
    )
