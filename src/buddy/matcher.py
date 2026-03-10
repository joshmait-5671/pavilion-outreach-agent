"""AI Buddy matching algorithm."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import uuid


@dataclass
class BuddyRequest:
    row_index: int          # Row number in the Google Sheet (for writing back)
    name: str
    email: str
    function: str
    chapter: str
    ai_level: str           # "Just starting out" | "Using it regularly" | "Building with it"
    ai_level_rank: int      # 1 / 2 / 3
    is_member: bool
    notes: str = ""
    status: str = "Unmatched"


@dataclass
class ProposedMatch:
    match_id: str
    person_a: BuddyRequest
    person_b: BuddyRequest
    match_basis: str        # e.g. "Function + Chapter + Same AI level"
    match_score: int        # Higher = better match
    approval_status: str = "Pending Approval"


_LEVEL_RANKS = {
    "Just starting out": 1,
    "Using it regularly": 2,
    "Building with it": 3,
}


def parse_requests(rows: list[dict]) -> list[BuddyRequest]:
    """Convert sheet rows into BuddyRequest objects. Skips already-matched rows."""
    requests = []
    for i, row in enumerate(rows, start=2):  # Row 2 = first data row (row 1 = header)
        if row.get("Status", "").strip().lower() in ("matched", "opted out", ""):
            continue
        level = row.get("AI Experience Level", "Just starting out").strip()
        requests.append(BuddyRequest(
            row_index=i,
            name=row.get("Name", "").strip(),
            email=row.get("Email", "").strip(),
            function=row.get("Function", "").strip(),
            chapter=row.get("Chapter / Location", "Remote / No chapter").strip(),
            ai_level=level,
            ai_level_rank=_LEVEL_RANKS.get(level, 1),
            is_member=row.get("Pavilion Member?", "No").strip().lower() in ("yes", "y", "true", "1"),
            notes=row.get("Anything specific you want help with?", "").strip(),
            status=row.get("Status", "Unmatched").strip(),
        ))
    return requests


def _level_gap(a: BuddyRequest, b: BuddyRequest) -> int:
    return abs(a.ai_level_rank - b.ai_level_rank)


def _same_chapter(a: BuddyRequest, b: BuddyRequest) -> bool:
    remote = "remote"
    if remote in a.chapter.lower() or remote in b.chapter.lower():
        return False
    return a.chapter.strip().lower() == b.chapter.strip().lower()


def _same_function(a: BuddyRequest, b: BuddyRequest) -> bool:
    return a.function.strip().lower() == b.function.strip().lower()


def _good_member_mix(a: BuddyRequest, b: BuddyRequest, prefer_mix: bool) -> bool:
    """If prefer_mix is True, reward member+non-member pairs."""
    if not prefer_mix:
        return True
    return a.is_member != b.is_member  # one member, one non-member


def _score_pair(a: BuddyRequest, b: BuddyRequest, prefer_mix: bool, max_level_gap: int) -> tuple[int, str]:
    """
    Score a potential pair. Returns (score, match_basis_description).
    Higher score = better match. Returns (-1, "") if disqualified.
    """
    if a.email == b.email:
        return -1, ""

    gap = _level_gap(a, b)
    if gap > max_level_gap:
        return -1, ""

    score = 0
    basis_parts = []

    # Function match (required)
    if _same_function(a, b):
        score += 40
        basis_parts.append(f"Function ({a.function})")
    else:
        return -1, ""  # Function match is required

    # Chapter / geo match
    if _same_chapter(a, b):
        score += 30
        basis_parts.append(f"Chapter ({a.chapter})")
    else:
        basis_parts.append("Remote match")

    # AI level match
    if gap == 0:
        score += 20
        basis_parts.append("Same AI level")
    elif gap == 1:
        score += 10
        basis_parts.append("Adjacent AI level")

    # Member / non-member mix bonus
    if prefer_mix and a.is_member != b.is_member:
        score += 10
        basis_parts.append("Member + non-member")

    return score, " · ".join(basis_parts)


def run_matching(
    requests: list[BuddyRequest],
    prefer_mix: bool = True,
    max_level_gap: int = 1,
) -> list[ProposedMatch]:
    """
    Greedy matching: find the highest-scoring pair for each unmatched person.
    Returns list of ProposedMatch objects.
    """
    unmatched = list(requests)
    matched_emails: set[str] = set()
    proposed: list[ProposedMatch] = []

    # Score all pairs
    scored_pairs: list[tuple[int, str, BuddyRequest, BuddyRequest]] = []
    for i, a in enumerate(unmatched):
        for b in unmatched[i + 1:]:
            score, basis = _score_pair(a, b, prefer_mix, max_level_gap)
            if score > 0:
                scored_pairs.append((score, basis, a, b))

    # Sort by score descending — best pairs first
    scored_pairs.sort(key=lambda x: x[0], reverse=True)

    # Greedy assign — once someone is matched, skip them
    for score, basis, a, b in scored_pairs:
        if a.email in matched_emails or b.email in matched_emails:
            continue
        matched_emails.add(a.email)
        matched_emails.add(b.email)
        proposed.append(ProposedMatch(
            match_id=str(uuid.uuid4())[:8].upper(),
            person_a=a,
            person_b=b,
            match_basis=basis,
            match_score=score,
        ))

    return proposed


def describe_unmatched(requests: list[BuddyRequest], matched_emails: set[str]) -> list[BuddyRequest]:
    """Return people who couldn't be matched this round."""
    return [r for r in requests if r.email not in matched_emails]
