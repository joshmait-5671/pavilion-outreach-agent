"""
enrich_contacts.py
------------------
Aggressive contact enrichment for podcast prospects.

Strategy (in priority order):
1. Pull from existing raw_scrape_data (already scraped but never applied)
2. iTunes Lookup API → RSS feed URL → <itunes:email> (for Apple Podcast URLs)
3. RSS feed direct → <itunes:email>, <managingEditor>, <author>
4. Scrape podcast's own domain: /contact, /booking, /pitch, /work-with-us, /advertise, /about, /guest
5. DuckDuckGo search: "[podcast name] podcast booking email contact"

Writes results to DB and prints a full report.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from typing import Optional
from urllib.parse import quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup

DB_PATH = "data/outreach.db"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}

NOISE_RE = re.compile(
    r"(example\.com|test\.com|@2x\.|\.png|\.jpg|\.jpeg|\.gif|\.svg|"
    r"noreply|no-reply|sentry\.io|wix\.com|squarespace\.com|wordpress\.com|"
    r"duckduckgo\.com|google\.com|bing\.com|yahoo\.com|github\.com|"
    r"cloudflare\.com|amazonaws\.com|netlify\.com|vercel\.com|"
    r"podcastaddict\.com|listennotes\.com|podscan\.fm|buzzsprout\.com|"
    r"anchor\.fm|spotify\.com|apple\.com|feedburner\.com|"
    r"ringmaster\.com|transistor\.fm|simplecast\.com|libsyn\.com|"
    r"podbean\.com|captivate\.fm|castos\.com|megaphone\.fm|"
    r"joinpavilion\.com|pavilion\.com|"
    r"privacy@|legal@|dmca@|abuse@)"
)

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

PREFERRED_KW = ["booking", "podcast", "guest", "media", "pitch",
                "press", "contact", "hello", "hi", "info", "show", "host"]
DEPRIORITIZE_KW = ["support", "help", "sales", "billing", "legal", "privacy"]

CONTACT_PATHS = [
    "/contact", "/contact-us", "/booking", "/book",
    "/pitch", "/pitch-us", "/guest", "/be-a-guest",
    "/work-with-us", "/advertise", "/about", "/about-us",
    "/submit", "/apply"
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_emails(text: str) -> list[str]:
    seen: set[str] = set()
    result = []
    for e in EMAIL_RE.findall(text):
        el = e.lower()
        if not NOISE_RE.search(el) and el not in seen:
            seen.add(el)
            result.append(e)
    return result


def pick_best_email(emails: list[str]) -> Optional[str]:
    if not emails:
        return None
    scored = []
    for email in emails:
        el = email.lower()
        local = el.split("@")[0]
        score = 0
        for kw in PREFERRED_KW:
            if kw in local:
                score += 2
        for kw in DEPRIORITIZE_KW:
            if kw in local:
                score -= 1
        scored.append((score, email))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored else None


def get(url: str, timeout: int = 10) -> Optional[str]:
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=HEADERS) as c:
            r = c.get(url)
            if r.status_code == 200:
                return r.text
    except Exception:
        pass
    return None


def get_domain(url: str) -> Optional[str]:
    try:
        p = urlparse(url)
        host = p.netloc.lower().replace("www.", "")
        if host and "." in host:
            return host
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Strategy 1: raw_scrape_data already has emails
# ---------------------------------------------------------------------------

def from_scrape_data(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    try:
        d = json.loads(raw)
        emails = d.get("booking_emails", [])
        if emails:
            best = pick_best_email([e for e in emails if not NOISE_RE.search(e.lower())])
            if best:
                return {"email": best, "source": "existing_scrape"}
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Strategy 2+3: iTunes Lookup → RSS → <itunes:email>
# ---------------------------------------------------------------------------

def get_rss_url_from_apple(apple_url: str) -> Optional[str]:
    """Use iTunes Search API to find the RSS feed URL."""
    m = re.search(r"/id(\d+)", apple_url)
    if not m:
        return None
    apple_id = m.group(1)
    time.sleep(0.5)
    data = get(f"https://itunes.apple.com/lookup?id={apple_id}&entity=podcast")
    if not data:
        return None
    try:
        j = json.loads(data)
        results = j.get("results", [])
        if results:
            return results[0].get("feedUrl")
    except Exception:
        pass
    return None


def email_from_rss(rss_url: str) -> Optional[dict]:
    """Pull contact email from RSS feed."""
    time.sleep(0.5)
    text = get(rss_url)
    if not text:
        return None
    soup = BeautifulSoup(text, "xml")

    # <itunes:email> — most reliable, required for Apple Podcasts
    itunes_email = soup.find("itunes:email")
    if itunes_email and itunes_email.text.strip():
        e = itunes_email.text.strip().lower()
        if not NOISE_RE.search(e):
            return {"email": itunes_email.text.strip(), "source": "rss_itunes_email"}

    # <managingEditor>
    editor = soup.find("managingEditor")
    if editor and editor.text.strip():
        emails = extract_emails(editor.text)
        if emails:
            return {"email": emails[0], "source": "rss_managing_editor"}

    # Any email in the channel header (not episode descriptions)
    channel = soup.find("channel")
    if channel:
        # Only look at direct channel children, not item descendants
        channel_text = ""
        for child in channel.children:
            tag = getattr(child, "name", None)
            if tag and tag != "item":
                channel_text += child.get_text(" ")
        emails = extract_emails(channel_text)
        best = pick_best_email(emails)
        if best:
            return {"email": best, "source": "rss_channel"}

    return None


def from_apple_url(apple_url: str) -> Optional[dict]:
    rss_url = get_rss_url_from_apple(apple_url)
    if not rss_url:
        return None
    result = email_from_rss(rss_url)
    if result:
        result["rss_url"] = rss_url
    return result


# ---------------------------------------------------------------------------
# Strategy 4: Scrape contact/booking pages on the podcast's domain
# ---------------------------------------------------------------------------

def from_website_scrape(base_url: str) -> Optional[dict]:
    parsed = urlparse(base_url)
    # Ensure we're on the real site, not apple/spotify
    if any(x in parsed.netloc for x in ["apple.com", "spotify.com", "art19.com",
                                          "ivy.fm", "podscan.fm", "listennotes.com"]):
        return None

    domain_base = f"{parsed.scheme}://{parsed.netloc}"
    all_emails = []

    # Try each contact path
    for path in CONTACT_PATHS:
        time.sleep(0.3)
        html = get(domain_base + path)
        if html:
            emails = extract_emails(html)
            all_emails.extend(emails)
            if emails:
                break  # Found something, no need to keep scraping paths

    best = pick_best_email(list(dict.fromkeys(all_emails)))
    if best:
        return {"email": best, "source": "website_contact_page"}
    return None


# ---------------------------------------------------------------------------
# Strategy 5: Web search
# ---------------------------------------------------------------------------

def from_web_search(podcast_name: str, host_name: Optional[str]) -> Optional[dict]:
    queries = [
        f'"{podcast_name}" podcast booking contact email',
        f'"{podcast_name}" podcast guest pitch email',
    ]
    if host_name:
        queries.append(f'"{host_name}" podcast contact email')

    all_emails = []
    for query in queries[:2]:
        time.sleep(2)
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        html = get(url, timeout=15)
        if not html:
            continue

        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(" ")
        emails = extract_emails(text)
        all_emails.extend(emails)

        # Check first result page
        first_link = soup.select_one(".result__title a")
        if first_link and first_link.get("href"):
            time.sleep(1)
            page = get(first_link["href"])
            if page:
                all_emails.extend(extract_emails(page))

        if all_emails:
            break

    best = pick_best_email(list(dict.fromkeys(all_emails)))
    if best:
        return {"email": best, "source": "web_search"}
    return None


# ---------------------------------------------------------------------------
# Main enrichment loop
# ---------------------------------------------------------------------------

def enrich_all(dry_run: bool = False):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, podcast_name, podcast_url, host_name, raw_scrape_data
        FROM prospects
        WHERE (booking_contact_email IS NULL OR booking_contact_email = '')
        ORDER BY id
    """)
    prospects = cur.fetchall()

    total = len(prospects)
    found = 0
    results = []

    print(f"\n{'='*60}")
    print(f"Enriching {total} prospects with missing email addresses")
    print(f"{'='*60}\n")

    for i, (pid, name, url, host, raw) in enumerate(prospects, 1):
        name_short = (name or "")[:50]
        print(f"[{i}/{total}] {name_short}")
        result = None

        # Strategy 1: already in scrape data
        result = from_scrape_data(raw)
        if result:
            print(f"  ✓ Found via existing scrape: {result['email']}")

        # Strategy 2/3: Apple Podcasts URL → iTunes API → RSS
        if not result and url and "apple.com" in url:
            print(f"  → Apple URL, trying iTunes lookup...")
            result = from_apple_url(url)
            if result:
                print(f"  ✓ Found via RSS feed: {result['email']}")

        # Strategy 3b: Non-Apple URL but check for RSS anyway
        if not result and url and "apple.com" not in url:
            # Try common RSS paths
            parsed = urlparse(url)
            if parsed.netloc and not any(x in parsed.netloc for x in
                                          ["spotify.com", "art19.com", "ivy.fm",
                                           "podscan.fm", "listennotes.com"]):
                for rss_path in ["/feed", "/rss", "/feed.xml", "/rss.xml", "/podcast.rss"]:
                    rss_url = f"{parsed.scheme}://{parsed.netloc}{rss_path}"
                    r = email_from_rss(rss_url)
                    if r:
                        result = r
                        print(f"  ✓ Found via RSS: {result['email']}")
                        break

        # Strategy 4: Scrape contact/booking pages
        if not result and url:
            result = from_website_scrape(url)
            if result:
                print(f"  ✓ Found via contact page: {result['email']}")

        # Strategy 5: Web search
        if not result:
            result = from_web_search(name, host)
            if result:
                print(f"  ✓ Found via web search: {result['email']}")

        if not result:
            print(f"  ✗ No email found")
            results.append({"id": pid, "name": name, "url": url, "email": None, "source": None})
        else:
            found += 1
            results.append({"id": pid, "name": name, "url": url,
                            "email": result["email"], "source": result["source"]})
            if not dry_run:
                cur.execute("""
                    UPDATE prospects
                    SET booking_contact_email = ?,
                        contact_source = ?,
                        contact_found_at = datetime('now'),
                        updated_at = datetime('now')
                    WHERE id = ?
                """, (result["email"], result["source"], pid))
                conn.commit()

    # Final report
    print(f"\n{'='*60}")
    print(f"ENRICHMENT COMPLETE")
    print(f"{'='*60}")
    print(f"Total prospects: {total}")
    print(f"Emails found:    {found} ({round(found/total*100)}%)")
    print(f"Still missing:   {total - found}")
    print()

    # Source breakdown
    source_counts: dict[str, int] = {}
    for r in results:
        s = r["source"] or "not_found"
        source_counts[s] = source_counts.get(s, 0) + 1

    print("Sources:")
    for s, c in sorted(source_counts.items(), key=lambda x: -x[1]):
        print(f"  {s}: {c}")

    print()
    print("MISSING (needs manual research):")
    for r in results:
        if not r["email"]:
            print(f"  - {r['name'][:60]} | {r['url']}")

    if dry_run:
        print("\n[DRY RUN] No changes written to DB.")

    conn.close()
    return found, total


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("[DRY RUN MODE — no DB writes]")
    enrich_all(dry_run=dry_run)
