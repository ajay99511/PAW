"""
Web Search Tool — focused search and scrape for the Podcast Agent.

Uses DuckDuckGo for web search (no API key required) and httpx + BeautifulSoup
for lightweight URL scraping. Designed for surgical content extraction, not
broad crawling.

Usage:
    from packages.tools.web_search import search_web, scrape_url, search_and_scrape

    results = await search_web("rust concurrency basics", max_results=5)
    text = await scrape_url("https://doc.rust-lang.org/book/ch16-00-concurrency.html")
    enriched = await search_and_scrape("rust thread safety", max_urls=3)
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

_SCRAPE_TIMEOUT = 15  # seconds
_MAX_CONTENT_CHARS = 5000
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# Tags whose content is noise, not body text
_STRIP_TAGS = {
    "script", "style", "nav", "header", "footer",
    "aside", "form", "button", "iframe", "noscript",
    "svg", "img", "video", "audio",
}


# ── Public API ───────────────────────────────────────────────────────


async def search_web(
    query: str,
    max_results: int = 5,
) -> list[dict[str, str]]:
    """
    Search DuckDuckGo and return results.

    Returns:
        List of dicts with 'title', 'url', 'snippet' keys.
    """
    try:
        from duckduckgo_search import DDGS

        results: list[dict[str, str]] = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
        logger.info("Web search '%s': %d results", query, len(results))
        return results

    except Exception as exc:
        logger.error("Web search failed for '%s': %s", query, exc)
        return []


async def scrape_url(
    url: str,
    max_chars: int = _MAX_CONTENT_CHARS,
) -> str:
    """
    Fetch a URL and extract clean body text.

    Strips navigation, ads, scripts, and other non-content elements.
    Truncates to max_chars to keep context windows manageable.

    Returns:
        Clean text content, or empty string on failure.
    """
    try:
        async with httpx.AsyncClient(
            timeout=_SCRAPE_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove noise tags
        for tag in soup.find_all(_STRIP_TAGS):
            tag.decompose()

        # Extract text
        text = soup.get_text(separator="\n", strip=True)

        # Collapse excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)

        # Truncate
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[…truncated]"

        logger.info("Scraped %s: %d chars", url, len(text))
        return text

    except Exception as exc:
        logger.warning("Failed to scrape %s: %s", url, exc)
        return ""


async def search_and_scrape(
    query: str,
    max_urls: int = 3,
    max_chars_per_url: int = _MAX_CONTENT_CHARS,
) -> list[dict[str, Any]]:
    """
    Search + scrape: find URLs via DuckDuckGo, then extract content.

    Returns:
        List of dicts with 'title', 'url', 'snippet', 'content' keys.
        'content' holds the scraped full text (or empty on failure).
    """
    search_results = await search_web(query, max_results=max_urls + 2)

    enriched: list[dict[str, Any]] = []
    scraped_count = 0

    for result in search_results:
        if scraped_count >= max_urls:
            break

        url = result.get("url", "")
        if not url:
            continue

        content = await scrape_url(url, max_chars=max_chars_per_url)
        enriched.append({
            **result,
            "content": content,
        })

        if content:
            scraped_count += 1

    logger.info(
        "search_and_scrape '%s': %d results, %d scraped",
        query, len(enriched), scraped_count,
    )
    return enriched
