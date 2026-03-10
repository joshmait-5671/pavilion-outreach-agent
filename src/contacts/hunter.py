"""Hunter.io API integration for finding booking contact emails."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

HUNTER_DOMAIN_SEARCH = "https://api.hunter.io/v2/domain-search"
HUNTER_EMAIL_VERIFY = "https://api.hunter.io/v2/email-verifier"

BOOKING_ROLE_KEYWORDS = [
    "podcast", "booking", "producer", "host", "media",
    "marketing", "communications", "pr", "content", "editor",
]


def find_contact_via_hunter(
    domain: str,
    api_key: str,
    min_confidence: int = 70,
    role_keywords: Optional[list[str]] = None,
) -> Optional[dict]:
    """Search Hunter.io for a booking contact at the given domain."""
    if role_keywords is None:
        role_keywords = BOOKING_ROLE_KEYWORDS

    params = {"domain": domain, "api_key": api_key, "limit": 100}

    try:
        result = _hunter_domain_search(params)
    except Exception:
        return None

    emails = result.get("data", {}).get("emails", [])
    if not emails:
        return None

    # Score each email by role match and confidence
    candidates = []
    for email_obj in emails:
        email = email_obj.get("value", "")
        confidence = email_obj.get("confidence", 0)
        first = email_obj.get("first_name", "")
        last = email_obj.get("last_name", "")
        position = (email_obj.get("position") or "").lower()
        department = (email_obj.get("department") or "").lower()

        if confidence < min_confidence:
            continue

        # Score role match
        role_score = 0
        for kw in role_keywords:
            if kw in position or kw in department:
                role_score += 1

        # Prefer generic/department emails if person-specific not found
        is_generic = email_obj.get("type") == "generic"

        candidates.append({
            "email": email,
            "name": f"{first} {last}".strip() or "",
            "position": position,
            "confidence": confidence,
            "role_score": role_score,
            "is_generic": is_generic,
        })

    if not candidates:
        return None

    # Sort: role_score desc, confidence desc
    candidates.sort(key=lambda x: (x["role_score"], x["confidence"]), reverse=True)
    best = candidates[0]

    return {
        "name": best["name"],
        "email": best["email"],
        "role": best["position"],
        "confidence": best["confidence"],
        "source": "hunter",
    }


def verify_email_hunter(email: str, api_key: str) -> dict:
    """Verify an email address via Hunter.io."""
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                HUNTER_EMAIL_VERIFY,
                params={"email": email, "api_key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
        return {
            "status": data.get("data", {}).get("status", "unknown"),
            "score": data.get("data", {}).get("score", 0),
        }
    except Exception:
        return {"status": "unknown", "score": 0}


def extract_domain_from_url(url: str) -> str:
    """Extract the root domain from a podcast URL."""
    parsed = urlparse(url)
    netloc = parsed.netloc.replace("www.", "")
    # For subdomains like "show.buzzsprout.com", use the full domain
    # But strip common podcast hosting platforms and get the show's own domain
    HOSTING_PLATFORMS = {
        "buzzsprout.com", "libsyn.com", "podbean.com", "transistor.fm",
        "simplecast.com", "anchor.fm", "spotify.com", "apple.com",
        "soundcloud.com", "audioboom.com", "blubrry.com", "captivate.fm",
        "podcastpage.io", "podcasthosting.com",
    }
    for platform in HOSTING_PLATFORMS:
        if netloc.endswith(platform):
            return ""  # Can't look up generic hosting domain
    return netloc


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _hunter_domain_search(params: dict) -> dict:
    with httpx.Client(timeout=15) as client:
        resp = client.get(HUNTER_DOMAIN_SEARCH, params=params)
        resp.raise_for_status()
        return resp.json()
