"""Scrape podcast homepages for metadata."""

from __future__ import annotations

import json
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup


def scrape_podcast_page(url: str, timeout: int = 15) -> dict:
    """Visit a podcast homepage and extract metadata. Never raises — returns partial data."""
    result = {
        "podcast_name": "",
        "description": "",
        "host_name": "",
        "category": "",
        "estimated_audience_size": "",
        "booking_emails": [],
        "apple_podcasts_url": "",
        "spotify_url": "",
        "recent_episodes": [],
        "contact_page_url": "",
        "social_links": {},
        "raw_html_snippet": "",
    }

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        result["_error"] = str(e)
        return result

    soup = BeautifulSoup(html, "lxml")

    # Remove script/style noise
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Podcast name
    result["podcast_name"] = _extract_podcast_name(soup, url)

    # Description
    meta_desc = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
    if meta_desc:
        result["description"] = meta_desc.get("content", "")[:500]

    # Host name
    result["host_name"] = _extract_host_name(soup)

    # Emails on page
    result["booking_emails"] = extract_emails_from_page(html)

    # Apple Podcasts and Spotify links
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "podcasts.apple.com" in href and not result["apple_podcasts_url"]:
            result["apple_podcasts_url"] = href
        if "open.spotify.com/show" in href and not result["spotify_url"]:
            result["spotify_url"] = href

    # Contact page
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        if text in ("contact", "contact us", "book", "booking", "pitch us", "submit"):
            href = a["href"]
            if href.startswith("/") or href.startswith("http"):
                result["contact_page_url"] = urljoin(url, href)
                break

    # Social links
    social_map = {
        "twitter.com": "twitter", "x.com": "twitter",
        "instagram.com": "instagram", "linkedin.com": "linkedin",
        "facebook.com": "facebook",
    }
    for a in soup.find_all("a", href=True):
        for domain, name in social_map.items():
            if domain in a["href"] and name not in result["social_links"]:
                result["social_links"][name] = a["href"]

    # Recent episodes (look for episode titles in common patterns)
    result["recent_episodes"] = _extract_recent_episodes(soup)

    # Category hint from Apple Podcasts badge text or page keywords
    result["category"] = _infer_category(soup, result["description"])

    # Estimated audience via review count if Apple Podcasts linked
    result["estimated_audience_size"] = _estimate_audience(soup)

    result["raw_html_snippet"] = str(soup)[:2000]

    # Try contact page if we didn't find emails yet
    if not result["booking_emails"] and result["contact_page_url"]:
        try:
            with httpx.Client(follow_redirects=True, timeout=10) as client:
                resp2 = client.get(result["contact_page_url"], headers=headers)
                more_emails = extract_emails_from_page(resp2.text)
                result["booking_emails"].extend(more_emails)
        except Exception:
            pass

    return result


def extract_emails_from_page(html: str) -> list[str]:
    """Extract email addresses from HTML, filtering false positives."""
    EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
    NOISE_PATTERNS = re.compile(
        r"(example\.com|test\.com|@2x\.|\.png|\.jpg|\.gif|noreply|no-reply|"
        r"sentry\.io|wixpress\.com|squarespace\.com)"
    )

    emails = EMAIL_RE.findall(html)
    seen: set[str] = set()
    result = []
    for e in emails:
        e_lower = e.lower()
        if not NOISE_PATTERNS.search(e_lower) and e_lower not in seen:
            seen.add(e_lower)
            result.append(e)
    return result[:10]  # Cap at 10


def _extract_podcast_name(soup: BeautifulSoup, url: str) -> str:
    # Try OG title, then <title>, then h1
    og = soup.find("meta", {"property": "og:title"})
    if og and og.get("content"):
        return og["content"].strip()
    title = soup.find("title")
    if title:
        t = title.get_text(strip=True)
        # Remove common suffixes like "Home | Podcast Name"
        t = re.split(r"\s*[|\-–—]\s*", t)[0].strip()
        if t:
            return t
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    # Fallback: domain name
    domain = urlparse(url).netloc.replace("www.", "")
    return domain.split(".")[0].title()


def _extract_host_name(soup: BeautifulSoup) -> str:
    """Look for 'hosted by', 'with [Name]', 'by [Name]' patterns."""
    text = soup.get_text(" ", strip=True)[:3000]
    patterns = [
        r"[Hh]osted by\s+([A-Z][a-z]+ (?:[A-Z][a-z]+ )?[A-Z][a-z]+)",
        r"[Ww]ith\s+([A-Z][a-z]+ [A-Z][a-z]+)",
        r"[Bb]y\s+([A-Z][a-z]+ [A-Z][a-z]+)",
        r"[Yy]our host[,:]?\s+([A-Z][a-z]+ [A-Z][a-z]+)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1)
    return ""


def _extract_recent_episodes(soup: BeautifulSoup) -> list[dict]:
    """Extract up to 5 recent episode titles from common podcast site structures."""
    episodes = []
    seen: set[str] = set()

    # Common CSS selectors for episode lists
    selectors = [
        "article h2", "article h3",
        ".episode-title", ".ep-title", ".podcast-episode h3",
        "[class*='episode'] h2", "[class*='episode'] h3",
        "h2.entry-title", "h3.entry-title",
    ]

    for sel in selectors:
        for el in soup.select(sel)[:5]:
            text = el.get_text(strip=True)
            if len(text) > 10 and text not in seen:
                seen.add(text)
                episodes.append({"title": text, "description": ""})
        if len(episodes) >= 5:
            break

    return episodes[:5]


def _infer_category(soup: BeautifulSoup, description: str) -> str:
    """Infer podcast category from page content."""
    text = (soup.get_text(" ", strip=True)[:500] + " " + description).lower()
    CATEGORY_MAP = [
        (["sales", "revenue", "crm", "quota", "b2b sales"], "B2B Sales"),
        (["gtm", "go-to-market", "revenue operations", "revops", "demand gen"], "GTM/Revenue"),
        (["startup", "founder", "entrepreneur", "venture", "fundraising"], "Startup/Founder"),
        (["marketing", "growth", "brand", "content marketing"], "Marketing/Growth"),
        (["leadership", "ceo", "executive", "management"], "Leadership"),
        (["technology", "saas", "software", "ai", "machine learning"], "Technology"),
        (["business", "strategy", "operations"], "Business"),
    ]
    for keywords, category in CATEGORY_MAP:
        if any(kw in text for kw in keywords):
            return category
    return "Business"


def _estimate_audience(soup: BeautifulSoup) -> str:
    """Estimate audience from review counts or social follower mentions."""
    text = soup.get_text(" ", strip=True)
    # Look for patterns like "50,000 listeners", "100k downloads"
    patterns = [
        r"([\d,]+[kKmM]?)\s+(?:listeners|downloads|subscribers|followers)",
        r"([\d,]+)\s+(?:reviews|ratings)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            val = m.group(1).replace(",", "")
            return val
    return ""
