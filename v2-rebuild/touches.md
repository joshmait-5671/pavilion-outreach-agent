# Sam Jacobs Podcast Outreach — v2 Touches

**Voice:** Playboy with the Economist at the Waverly Inn. Confident, well-read, dry. Knows the score, doesn't perform it. Speaks to peers, not prospects.

**Banned:**
- "Hope this finds you well"
- "Just wanted to drop you a quick note"
- "Looking forward to connecting!"
- Em-dash overload (one per email max)
- Triple parallel constructions
- "Not X. Not Y. The Z."
- Three exclamation points
- "Looking forward to" anywhere

**Voice guideposts:**
- A New Yorker piece's cold open
- The way a magazine editor pitches a freelance writer
- "I assume you're busy too" implied throughout
- Brief is confidence; brevity is the message

---

## Touch 1 · Day 0 · The Report Drop

**Subject options (pick one per send, A/B testable):**
- A: `Quick read — 244 GTM teams on AI`
- B: `New Pavilion research, in case it's useful`
- C: `What 244 GTM leaders said about AI (a few surprises)`

**Body:**

> Hi {first_name},
>
> Pavilion just put out our AI Pulse Report — 244 GTM teams across startups, mid-market, and enterprise, on how AI is actually being used right now (not how the analysts say it is).
>
> A few things worth flagging:
>
> • 95% of teams are using AI more than six months ago. 46% say their top blocker is that nobody owns it.
> • Claude is named the most impactful GTM tool by 51%. ChatGPT, 11%.
> • 82% of teams want autonomous agents next, before the foundation is fully ready.
> • Career optimism (7.9 / 10) and job-security anxiety (5.1 / 10) are running parallel — same person feels both.
>
> Report's here: [{{ report_url }}]({{ report_url }})
>
> If something in it earns a thread for {{ podcast_name }}, our CEO Sam Jacobs sees this data from 10,000 GTM leaders in real time and has takes that don't sound like everyone else's. Topline host, WSJ-bestselling author of *Kind Folks Finish First*.
>
> No pressure either way. Just thought you might want a look.
>
> Josh
> Head of Marketing, Pavilion

**Personalization variables (filled in by Claude per prospect):**
- `{first_name}` — booker / host first name
- `{podcast_name}` — podcast name
- `{report_url}` — fixed for the campaign
- *Optional swap-in:* a one-line connector to their show if the audience match is obvious (e.g., for a wellness show: replace bullet 4 with the optimism/anxiety stat as the lead since it's the one that maps)

---

## Touch 2 · Day 7 · Tied to Their Show

**Subject options:**
- A: `Re: AI report — your {{ recent_topic }} ep`
- B: `Saw your ep on {{ recent_topic }} — quick note`

**Body:**

> Hi {first_name},
>
> Caught your recent episode on {{ recent_episode_topic }}. Wanted to flag something from the AI Pulse Report I sent that maps to it directly:
>
> {{ specific_data_point_tied_to_their_episode }}
>
> Sam's view on this in particular tends to surprise people — partly because he's running the data and the community at the same time, and partly because he doesn't think the conventional wisdom is right.
>
> If having him on to riff would be useful, the door's open. He's at one a week, low-fi setup, ready in 48 hours of notice.
>
> If not, no further follow-up. Just wanted to put the option on the table while it's fresh.
>
> Josh

**Personalization (Claude generates per prospect):**
- `{recent_episode_topic}` — pull from their recent feed (last 3 eps)
- `{specific_data_point_tied_to_their_episode}` — a specific stat or finding from the AI Pulse Report that lines up with what they covered. E.g., for a sales podcast: "57% of teams expect SDR roles to be the most disrupted by AI, but Account Exec roles only 15%. The volume-based work is going first."

---

## Touch 3 · Day 14 · Soft Close + Calendar

**Subject:**
- `One more thing`

**Body:**

> Hi {first_name},
>
> Last note from us. Putting a calendar link out there in case the timing wasn't right last week:
>
> {{ calendar_link }}
>
> If a different angle would land better for {{ podcast_name }}, I'm happy to think about it. Otherwise, hope the report was useful and good luck with the rest of the season.
>
> Josh

---

## Notes for the model when personalizing

- Use {first_name} only — never "Mr./Ms.", never "Hi {first_name} {last_name}".
- Don't change the structure, just the personalization variables. The voice depends on the rhythm of the bullets and the brevity of the close.
- If you can't find a recent episode for Touch 2, swap the opener to: "Following up on the AI Pulse Report I sent. One stat that's been getting reactions: {{ specific_data_point }}."
- One em-dash maximum per email. Period.

---

## What we're betting on

The old approach was: cold pitch → hope they say yes. The new approach is: send something genuinely useful → mention Sam as a follow-on → let them come to us. The math:

- Old reply rate (estimate): ~2-3% on cold pitches.
- New reply rate (target): 8-12% on the first send because the report is genuinely interesting.
- Conversion of replies → bookings: should hold or improve because they're already engaged with our content before we ask.

If we get 10x the volume and 3x the engagement, that's a 30x outcome on what was already running.
