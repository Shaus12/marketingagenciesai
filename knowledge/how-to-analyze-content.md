# How to Analyze Content

This file defines HOW the system thinks about content. Every analysis pipeline reads this before doing anything.

**Model:** Use Opus 4.6 for analysis. This is strategic thinking, not bulk generation.

---

## The Purpose of Analysis

We are NOT summarizing videos. We are NOT extracting random quotes.

We are answering one question: **"What in this content can make someone stop, feel something, and take action?"**

Every output of the analysis must pass this test: would a real person scroll-stop for this? Would they share it? Would they click? If the answer is "it's fine" — it's not good enough. "Fine" gets scrolled past.

---

## What Makes Content Worth Repurposing

Not everything should be repurposed. A 15-minute tutorial about Supabase setup might be a great YouTube video but a terrible Instagram Reel. The system must judge:

### Repurpose if:
- The moment contains a **specific, surprising insight** (not generic advice)
- The moment **names a real pain** the audience recognizes instantly
- The moment contains **a number or stat** that reframes how they think
- The moment is **contrarian** — says something most people disagree with
- The moment tells **a personal story** with a lesson (not just "I did this")
- The moment makes someone think **"I need to send this to someone"**

### Don't repurpose if:
- It's generic advice anyone could give ("validate your idea before building")
- It's a technical explanation without emotional weight
- It requires watching 3 minutes of context to understand
- It's a list of features or steps (no tension, no insight)
- It sounds like every other AI creator on the internet

---

## How to Find Hooks

A hook is the first 1-3 seconds of a clip or the first line of a post. It earns the next second.

### What makes a hook work (ranked by our data):

1. **Pain call-out** — "You're 200 prompts deep. The app was supposed to take 2 hours but it's been 2 days." This works because the audience feels SEEN. They've lived this.

2. **Stat shock** — "90% of AI builders never make a single euro." Works because it's specific and scary. Our best-performing ad format at €X.XX CPL.

3. **Contrarian challenge** — "Stop watching AI tutorials." Works because it breaks the pattern. They were about to scroll, but this says the opposite of what they expect.

4. **Specific transformation** — "I built 25 apps. 3 made money. The difference wasn't the code." Works because it's personal, specific, and creates a curiosity gap.

### What doesn't work as a hook:
- Questions without tension ("Want to build an AI product?")
- Generic benefits ("Learn how to monetize AI")
- Self-introductions ("Hey, I'm the founder and today we're going to...")
- Hype language ("This is going to blow your mind")

---

## How to Identify Clip-Worthy Moments

A clip is 15-30 seconds that works as a standalone piece of content. Not every good moment makes a good clip.

### A clip must have:
1. **A hook in the first 2 seconds** — the moment must start strong, not build up to something
2. **A complete thought** — the viewer must get the insight without needing context from earlier in the video
3. **An emotional beat** — surprise, frustration, relief, challenge. Something that makes them feel.
4. **Natural ending** — either a punchline, a shift in energy, or a pause that feels like a conclusion

### Scoring clips (1-10):
- **9-10**: Could run as a paid ad with no editing. Scroll-stopping hook + complete insight + emotional resonance.
- **7-8**: Strong moment, might need a text overlay or minor context to work standalone.
- **5-6**: Interesting but needs surrounding context. Maybe useful as a longer Instagram carousel or LinkedIn post.
- **1-4**: Not standalone. Might be useful as a quote card but not as a clip.

---

## Platform-Specific Thinking

Not every piece of content belongs everywhere. The system must match content to platform:

### Instagram Reels (our best ad placement — €2.21 CPL)
- Vertical 9:16
- 15-30 seconds max
- Needs hook in first 1 second
- Captions mandatory
- Energy: direct, punchy, no warmup
- Works best: pain call-outs, contrarian takes, specific results

### Instagram Feed (static posts)
- Square or 4:5 vertical
- Quote cards, carousel slides
- Needs to be visually striking (dark background + lime accent = our brand)
- Caption does the heavy lifting — image stops the scroll, caption delivers the value
- Works best: reframing insights, data points, provocative statements

### LinkedIn
- Text-first platform — the post IS the content
- Professional but personal. "I" not "we."
- Data-driven insights perform best
- Opening line is everything — LinkedIn truncates after 2 lines
- Works best: lessons learned, data from real experience, industry observations

### Twitter/X
- One thought. One punch.
- Under 200 characters ideal
- No emojis. No hashtags. Just the thought.
- Works best: contrarian one-liners, specific numbers, reframes

### YouTube Shorts
- Vertical 9:16, under 60 seconds
- Can be slightly longer and more detailed than Reels
- Hook + teach + punchline structure
- Works best: quick tutorials, "stop doing X" takes, before/after

### Meta Ads
- Must connect to a pain point from the positioning bible
- Must NOT sell the product — sell the webinar or free value
- Must pass the quality gate (AD_RULES.md)
- Use Opus 4.6 to judge if the moment is ad-worthy

---

## Quality Standard

Before any output is saved, ask:

1. **Would the founder actually post this?** — If it sounds generic, AI-generated, or like every other creator — it fails.
2. **Does it sound like the founder?** — Direct, honest, specific, slightly Dutch-blunt. Not salesy, not motivational-speaker, not guru.
3. **Is there a real insight?** — Not "building is hard" (obvious) but "I built 25 apps before 3 made money — the difference wasn't the code" (specific, personal, surprising).
4. **Would someone screenshot this and send it to a friend?** — That's the bar for quote cards and social posts.

---

## Learning Loop

After content is posted and we see performance:
- Update `performance.json` with what worked
- Add notes to this file about WHY it worked
- Remove patterns that consistently underperform
- This file should get smarter every month

### Lessons learned so far:
- Pain call-out hooks outperform everything else in ads (€X.XX CPL)
- "Stop doing X" contrarian hooks work on both YouTube (96K views) and Meta
- Generic proof/social proof ("55 products shipped") gets clicks but zero leads
- Specific personal stories ("25 apps, 3 made money") create massive curiosity gaps
- Feature lists never work as hooks — always lead with the pain, never the solution

---

*This file is read by every analysis pipeline. Update it when you learn something new about what works.*
