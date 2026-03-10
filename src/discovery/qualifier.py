"""Score podcast prospects using Claude."""

from __future__ import annotations

import json
from typing import Optional

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential


VALID_CATEGORIES = {
    "b2b_sales_gtm",
    "mainstream_business",
    "tech_ai",
    "wellness_mental_health",
    "personal_development",
}


def score_prospect(
    prospect_data: dict,
    guest_profile: str,
    scoring_criteria: dict,
    model: str = "claude-opus-4-6",
    client: Optional[anthropic.Anthropic] = None,
) -> tuple[int, str, str]:
    """Score a podcast prospect 0-100 for fit with the guest profile.
    Returns (score, reasoning_text, category)."""
    if client is None:
        client = anthropic.Anthropic()

    prompt = _build_prompt(prospect_data, guest_profile, scoring_criteria)
    response_text = _call_claude(client, model, prompt)

    try:
        data = _extract_json(response_text)
        score = max(0, min(100, int(data.get("score", 0))))
        reasoning = data.get("reasoning", response_text[:500])
        category = data.get("category", "b2b_sales_gtm")
        if category not in VALID_CATEGORIES:
            category = "b2b_sales_gtm"
    except Exception:
        # Fallback: try to extract a number from the text
        import re
        m = re.search(r"\b([0-9]{1,3})\b", response_text)
        score = int(m.group(1)) if m else 50
        reasoning = response_text[:500]
        category = "b2b_sales_gtm"

    return score, reasoning, category


def filter_prospects(
    prospects: list[dict],
    min_score: int,
) -> tuple[list[dict], list[dict]]:
    """Split into (qualified, rejected) sorted by score desc."""
    qualified = sorted(
        [p for p in prospects if p.get("qualification_score", 0) >= min_score],
        key=lambda x: x.get("qualification_score", 0),
        reverse=True,
    )
    rejected = [p for p in prospects if p.get("qualification_score", 0) < min_score]
    return qualified, rejected


def _build_prompt(prospect_data: dict, guest_profile: str, scoring_criteria: dict) -> str:
    episodes = prospect_data.get("recent_episodes", [])
    episode_text = ""
    if episodes:
        titles = [e.get("title", "") for e in episodes[:5]]
        episode_text = "Recent episodes:\n" + "\n".join(f"- {t}" for t in titles if t)

    criteria_text = ""
    for crit, weight in scoring_criteria.items():
        crit_label = crit.replace("_", " ").title()
        criteria_text += f"- {crit_label} (weight: {weight}/100)\n"

    return f"""You are a podcast booking specialist. Score this podcast for guest fit and assign it a category.

GUEST PROFILE:
{guest_profile}

PODCAST DETAILS:
- Name: {prospect_data.get('podcast_name', 'Unknown')}
- URL: {prospect_data.get('podcast_url', '')}
- Category (scraped): {prospect_data.get('category', '')}
- Description: {prospect_data.get('description', '')[:300]}
- Host: {prospect_data.get('host_name', 'Unknown')}
- Estimated Audience: {prospect_data.get('estimated_audience_size', 'Unknown')}
{episode_text}

SCORING CRITERIA (must total 100):
{criteria_text}

Score this podcast 0-100 for how well the guest profile fits. Consider:
- Is the podcast audience who would benefit from the guest's expertise?
- Does the podcast cover topics the guest speaks on?
- Is the podcast active and reputable?
- Would the guest's story resonate with this audience?

Also assign ONE category from this list (used to select the right email template):
- "b2b_sales_gtm"         — B2B sales, SaaS, GTM, RevOps, startup/founder shows
- "mainstream_business"   — General business (All In, Masters of Scale, HBR, How I Built This, etc.)
- "tech_ai"               — Tech, AI, product, engineering-adjacent shows
- "wellness_mental_health" — Corporate wellness, burnout, mental health, executive health shows
- "personal_development"  — Mindset, personal growth, entrepreneurship mindset, author interview shows

Respond with ONLY valid JSON in this exact format:
{{
  "score": <integer 0-100>,
  "reasoning": "<2-3 sentences explaining the score>",
  "category": "<one of the five category keys above>",
  "criterion_scores": {{
    "audience_relevance": <int>,
    "episode_cadence": <int>,
    "audience_size_proxy": <int>,
    "topic_fit": <int>
  }}
}}"""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _call_claude(client: anthropic.Anthropic, model: str, prompt: str) -> str:
    msg = client.messages.create(
        model=model,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _extract_json(text: str) -> dict:
    """Extract JSON from Claude response, handling markdown code fences."""
    import re
    # Strip markdown fences
    text = re.sub(r"```(?:json)?\n?", "", text).strip()
    # Find JSON object
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    return json.loads(text)
