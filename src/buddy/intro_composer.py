"""Claude-powered intro email composer for AI Buddy matches."""

from __future__ import annotations
import anthropic
from src.buddy.matcher import ProposedMatch


def compose_intro(match: ProposedMatch, program_description: str, client: anthropic.Anthropic) -> str:
    """
    Ask Claude to write a warm, specific intro email for this matched pair.
    Returns plain-text email body (no subject line — that's handled separately).
    """
    a = match.person_a
    b = match.person_b

    member_context = ""
    if not a.is_member and not b.is_member:
        member_context = "Neither person is currently a Pavilion member. Include a single natural, non-pushy line at the end mentioning that this program is a small taste of what the Pavilion community is like."
    elif a.is_member != b.is_member:
        non_member = a if not a.is_member else b
        member_context = f"{non_member.name} is not yet a Pavilion member. Include a single natural, non-pushy line at the end mentioning that this program gives non-members a feel for the Pavilion community."

    same_chapter = "Remote / No chapter" not in (a.chapter, b.chapter) and a.chapter.lower() == b.chapter.lower()
    geo_line = f"Both are based in the {a.chapter} area." if same_chapter else f"{a.name} is in {a.chapter}, {b.name} is in {b.chapter}."

    prompt = f"""You are writing a short, warm introduction email on behalf of Josh Mait, Head of Marketing at Pavilion.

You are introducing two people who have been matched through Pavilion's AI Buddy Program.

WHAT THE PROGRAM IS:
{program_description}

PERSON A:
Name: {a.name}
Function: {a.function}
AI Experience: {a.ai_level}
{"Notes: " + a.notes if a.notes else ""}

PERSON B:
Name: {b.name}
Function: {b.function}
AI Experience: {b.ai_level}
{"Notes: " + b.notes if b.notes else ""}

GEO CONTEXT:
{geo_line}

MATCH BASIS:
{match.match_basis}

{member_context}

WRITING INSTRUCTIONS:
- Address both people by first name in the opening line (e.g. "Hey Sarah and Marcus,")
- 3-4 short paragraphs maximum
- Explain what they have in common and why the match makes sense (1 paragraph)
- Describe the program vibe in 2-3 sentences: casual, no pressure, peer-to-peer, no stupid questions, some pairs talk weekly some monthly both are fine
- Give 2-3 concrete examples of when you might reach out to your buddy (e.g. "you just saw a tool demo and want to know if someone's actually used it", "you're figuring out how to use AI for [their function] and want to sanity check your thinking")
- End with a short handoff line — something like "Over to you two."
- Sign off as Josh Mait, Head of Marketing, Pavilion
- Tone: warm but not gushing. Direct. Human. Not corporate. Not startup-chirpy.
- No em dashes. Short sentences. Active voice.
- Do not mention money, pricing, or membership costs.

Output ONLY the email body. No subject line. No extra commentary."""

    msg = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def make_subject(match: ProposedMatch) -> str:
    """Generate a clean subject line for the intro email."""
    a = match.person_a
    b = match.person_b
    first_a = a.name.split()[0]
    first_b = b.name.split()[0]
    return f"Introducing {first_a} and {first_b} — Pavilion AI Buddy"
