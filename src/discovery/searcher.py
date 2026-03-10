"""Web search for podcast discovery."""

from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup


def search_for_podcasts(
    queries: list[str],
    max_results_per_query: int = 20,
    serpapi_key: Optional[str] = None,
    delay_seconds: float = 2.0,
) -> list[dict]:
    """Run each query against a search engine. Returns deduped list of results."""
    seen_urls: set[str] = set()
    all_results: list[dict] = []

    for query in queries:
        time.sleep(delay_seconds)
        if serpapi_key:
            results = _fetch_serpapi(query, max_results_per_query, serpapi_key)
        else:
            results = _fetch_duckduckgo(query, max_results_per_query)

        for r in results:
            url = _normalize_url(r.get("url", ""))
            if url and url not in seen_urls and _looks_like_podcast_site(url, r.get("title", "")):
                seen_urls.add(url)
                all_results.append({**r, "url": url, "search_query": query})

    return all_results


def _fetch_duckduckgo(query: str, max_results: int) -> list[dict]:
    """Use ddgs library for reliable DuckDuckGo search results."""
    try:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
        return results
    except Exception:
        return []


def _fetch_serpapi(query: str, max_results: int, api_key: str) -> list[dict]:
    """Use SerpAPI for structured search results."""
    params = {
        "engine": "google",
        "q": query,
        "api_key": api_key,
        "num": min(max_results, 10),
    }
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get("https://serpapi.com/search", params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []

    results = []
    for item in data.get("organic_results", [])[:max_results]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
        })
    return results


def _normalize_url(url: str) -> str:
    """Strip tracking params and normalize."""
    if not url:
        return ""
    # Remove common tracking params
    url = re.sub(r"\?utm_[^&]*(&[^?]*)?$", "", url)
    url = re.sub(r"&utm_[^&]*", "", url)
    # Ensure https
    if url.startswith("http://"):
        url = "https://" + url[7:]
    # Remove trailing slash
    return url.rstrip("/")


def _looks_like_podcast_site(url: str, title: str) -> bool:
    """Filter out clearly non-podcast results."""
    noise_domains = {
        "youtube.com", "twitter.com", "facebook.com", "instagram.com",
        "linkedin.com", "reddit.com", "wikipedia.org", "amazon.com",
        "google.com", "apple.com/news", "itunes.apple.com",
        "open.spotify.com/episode",
    }
    for nd in noise_domains:
        if nd in url:
            return False
    return True
