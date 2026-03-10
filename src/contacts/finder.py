"""Fallback contact finding via web search and page scraping."""

from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import quote_plus, urljoin

import httpx
from bs4 import BeautifulSoup

from src.models import Prospect


def find_contact_for_prospect(
    prospect: Prospect,
    hunter_api_key: Optional[str] = None,
    hunter_confidence_min: int = 70,
    use_hunter: bool = True,
    fallback_to_web: bool = True,
) -> Optional[dict]:
    """Orchestrate Hunter + fallback. Single entry point for contact finding."""
    # 1. Try Hunter.io
    if use_hunter and hunter_api_key:
        from src.contacts.hunter import find_contact_via_hunter, extract_domain_from_url
        domain = extract_domain_from_url(prospect.podcast_url)
        if domain:
            contact = find_contact_via_hunter(
                domain, hunter_api_key, min_confidence=hunter_confidence_min
            )
            if contact:
                return contact

    # 2. Check emails already scraped from the page
    if prospect.raw_scrape_data:
        import json
        try:
            scrape = json.loads(prospect.raw_scrape_data)
            emails = scrape.get("booking_emails", [])
            if emails:
                # Pick the most booking-relevant email
                best = _pick_best_email(emails)
                if best:
                    return {
                        "name": "",
                        "email": best,
                        "role": "",
                        "confidence": None,
                        "source": "scraped_page",
                    }
        except (json.JSONDecodeError, AttributeError):
            pass

    if not fallback_to_web:
        return None

    # 3. Web search for contact
    return _find_via_web_search(
        prospect.podcast_name,
        prospect.podcast_url,
        prospect.host_name,
    )


def find_contact_via_web(
    podcast_name: str,
    podcast_url: str,
    host_name: Optional[str],
    role_keywords: Optional[list[str]] = None,
) -> Optional[dict]:
    """Public interface for web-based contact finding."""
    return _find_via_web_search(podcast_name, podcast_url, host_name)


def _find_via_web_search(
    podcast_name: str,
    podcast_url: str,
    host_name: Optional[str],
) -> Optional[dict]:
    """Search the web for booking/contact email for this podcast."""
    queries = [
        f'"{podcast_name}" podcast booking contact email',
        f'"{podcast_name}" podcast pitch guest submit',
    ]
    if host_name:
        queries.append(f'"{host_name}" podcast email contact')

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    all_emails: list[str] = []

    for query in queries[:2]:  # Limit to 2 queries
        time.sleep(2)
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            with httpx.Client(follow_redirects=True, timeout=15) as client:
                resp = client.get(url, headers=headers)
                soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            continue

        # Extract emails from search result snippets
        text = soup.get_text(" ")
        emails = _extract_emails(text)
        all_emails.extend(emails)

        # Also check the first search result URL
        first_link = soup.select_one(".result__title a")
        if first_link and first_link.get("href"):
            href = first_link["href"]
            # Try to visit that page
            time.sleep(1)
            try:
                with httpx.Client(follow_redirects=True, timeout=10) as client:
                    r2 = client.get(href, headers=headers)
                    more_emails = _extract_emails(r2.text)
                    all_emails.extend(more_emails)
            except Exception:
                pass

    # Also check common contact paths on the podcast's own domain
    for path in ["/contact", "/about", "/book", "/pitch", "/submit"]:
        candidate = podcast_url.rstrip("/") + path
        time.sleep(1)
        try:
            with httpx.Client(follow_redirects=True, timeout=8) as client:
                r = client.get(candidate, headers=headers)
                if r.status_code == 200:
                    more_emails = _extract_emails(r.text)
                    all_emails.extend(more_emails)
        except Exception:
            pass

    if not all_emails:
        return None

    best = _pick_best_email(list(dict.fromkeys(all_emails)))  # dedup preserving order
    if not best:
        return None

    return {
        "name": "",
        "email": best,
        "role": "",
        "confidence": None,
        "source": "web_search",
    }


def _extract_emails(text: str) -> list[str]:
    EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
    NOISE = re.compile(
        r"(example\.com|test\.com|@2x\.|\.png|\.jpg|noreply|no-reply|"
        r"sentry\.io|wix|squarespace|wordpress)"
    )
    seen: set[str] = set()
    result = []
    for e in EMAIL_RE.findall(text):
        el = e.lower()
        if not NOISE.search(el) and el not in seen:
            seen.add(el)
            result.append(e)
    return result


def _pick_best_email(emails: list[str]) -> Optional[str]:
    """Pick the most booking-relevant email from a list."""
    if not emails:
        return None

    PREFERRED_KEYWORDS = ["booking", "podcast", "guest", "media", "pitch", "press", "contact", "hello", "hi", "info"]
    DEPRIORITIZE = ["support", "help", "sales", "billing", "legal"]

    scored = []
    for email in emails:
        el = email.lower()
        local = el.split("@")[0]
        score = 0
        for kw in PREFERRED_KEYWORDS:
            if kw in local:
                score += 2
        for kw in DEPRIORITIZE:
            if kw in local:
                score -= 1
        scored.append((score, email))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored else None
