# Ad System — Source of Truth

This file is the single source of truth for all ad creation. Read this FULLY before generating, reviewing, or modifying any ads.

---

## 1. The Funnel (What We're Selling)

**We are NOT selling a product in the ads. We are selling a FREE WEBINAR.**

```
Meta Ads (cold traffic)
    ↓
FREE WEBINAR REGISTRATION (yourdomain.com/webinar)
    ↓
Live 60-min Webinar (teaching + live demo)
    ↓
Offer reveal at minute 45 (€997 AI Agency Launchpad)
    ↓
Post-webinar email nurture (14 days, 7 emails)
    ↓
Conversion to paid product
```

### Critical Rule: NO PRICES IN ADS

- The ads must NEVER show product prices (€497, €997, €247, etc.)
- The ads must NEVER link to /checkout
- The CTA is always "Save My Spot", "Sign Up", or "Register Free"
- The link is always: `https://yourdomain.com/webinar`
- The CTA type in Meta is: `SIGN_UP`
- The webinar is FREE — emphasize this

### What the Ads CAN Show

- The **opportunity** (€500-1,500/mo recurring from AI agents)
- The **proof** (€XXX+ revenue, XX products sold, X,XXX+ builders, XX,XXX+ subs)
- The **testimonials** (real builder quotes)
- The **live demo** hook (I build something real in 15 min)
- The **3-path system** (SaaS, RaaS, Services)
- The **webinar date/time** (currently: [WEBINAR DATE], [TIME])
- "Free", "No credit card", "60 minutes", "Live"

---

## 2. Target Audience

| Segment | % of Spend | Profile |
|---------|-----------|---------|
| Side-Hustle Builder | 60% | Age 25-40, employed, wants side income, no coding skills |
| Agency Operator | 25% | Age 28-45, runs freelance/agency, clients asking for AI |
| Career Changer | 15% | Age 22-35, tech background, wants to monetize AI skills |

### Geographic Targeting
- Primary: Netherlands, Germany, UK, US
- Exclude: UAE (removed — low conversion)
- Placements: Feeds only (no Audience Network)

---

## 3. Brand Design System

### Template Background (REQUIRED)

ALL ad images must use one of these templates as the starting base:

| Template | URL | Use Case |
|----------|-----|----------|
| Grid (primary) | `data/template_grid_v2.png` | Default for most ads |
| Corner Glow | `brand_templates.json → template_corner_glow` | Statement/quote ads |
| Top Accent | `brand_templates.json → template_top_accent` | Structured/list ads |
| Centered Glow | `brand_templates.json → template_centered` | Hero number/stat ads |

### Image Generation Method

Use `fal-ai/nano-banana-pro/edit` with the template as base:
```python
result = fal_client.subscribe(
    "fal-ai/nano-banana-pro/edit",
    arguments={
        "prompt": prompt,
        "image_urls": [TEMPLATE_URL],
        "aspect_ratio": "1:1",
        "resolution": "1K",
        "output_format": "png",
    },
)
```

Do NOT use `fal-ai/nano-banana-2` (text-to-image from scratch) — it won't use the template.

### Colors

| Element | Color | Hex |
|---------|-------|-----|
| Background | Near-black | `#YOUR_BG_COLOR` |
| Primary accent | Electric lime/chartreuse | `#YOUR_ACCENT_COLOR` |
| Text | White | `#ffffff` |
| Muted text | Gray | `#888888` |
| Danger/stop | Red (sparingly) | `#ff3333` |

### Typography

- Font style: Bold sans-serif (Montserrat, Inter, heavy weight)
- Max 3-5 text elements per image
- Large text, readable on mobile at a glance
- No photos, no illustrations, no people, no stock imagery
- Pure typography + brand colors on template background

### Visual Feel

- Dark, premium, techy, direct
- Like a Stripe or Linear landing page hero section turned into an ad
- High contrast for mobile feed readability
- Subtle lime glow behind key text elements
- Lots of negative space

---

## 4. Ad Copy Structure

Each Meta ad has these components:

| Field | Purpose | Rules |
|-------|---------|-------|
| **Image** | Scroll-stopper | Generated on brand template, 1080×1080 |
| **Primary Text** | Main copy above the image | 3-8 lines, ends with "🔗 Save your free spot → yourdomain.com/webinar" |
| **Headline** | Bold text below image | Short, punchy, under 40 chars |
| **Description** | Smaller text below headline | "Free workshop — limited live spots" |
| **CTA Button** | Meta button | Always `SIGN_UP` |
| **URL** | Click destination | Always `https://yourdomain.com/webinar` |

### Primary Text Variants (use these or variations of them)

**Version A — Problem → Solution → Proof:**
```
Building AI products is easy now.
Making money from them? That's the hard part.

I've made €XXX+ from AI products and services.
Not because I'm smarter. Because I have a system.

3 paths that actually work:
→ SaaS (recurring subscriptions)
→ RaaS (sell results, not tools — pays more)
→ AI Services (build for clients, charge monthly)

I'm showing the full system — live.
Plus a live demo where I build something real in 15 min.

Free. 60 minutes. No fluff.

🔗 Save your spot →
```

**Version B — Testimonial → Offer:**
```
"I built a full CRM with Stripe, AI chatbot,
project management... I have no idea how to code."
— real YouTube comment

This is what happens when you follow a system
instead of watching random tutorials.

I'm teaching that system — free.

What you'll have after 60 minutes:
✓ The 3 revenue paths for AI products
✓ A live demo (I build something real on screen)
✓ The "First 10 Customers" playbook
✓ The exact system X,XXX+ builders use

🔗 Free. Link below →
```

**Version C — Direct / Short:**
```
I made €XXX+ with AI products.

Not from coding. From SELLING.

Free workshop where I show you
the exact 3-path system.

Live demo included. 60 minutes.

🔗 Save your spot →
```

---

## 5. Proven Ad Angles (ordered by expected performance)

| # | Angle | Hook | Why It Works |
|---|-------|------|-------------|
| 1 | The Stat | "90% of AI builders never make money" | Curiosity gap, calls out the problem |
| 2 | The Math | "3 clients × €500/mo = €1,500 recurring" | Makes opportunity concrete |
| 3 | The Testimonial | Real builder quotes | Social proof, relatability |
| 4 | The Contrarian | "Stop watching tutorials. Start selling." | Pattern interrupt, the founder's brand voice |
| 5 | The Live Demo | "Watch me build an AI product in 15 min" | Curiosity, proves it's real |
| 6 | The 3 Paths | SaaS / RaaS / Services framework | Educational, structured |
| 7 | The Weekend Promise | "What if your next weekend project made €500/mo?" | Aspirational, low commitment |
| 8 | Social Proof Wall | Multiple YouTube comments stacked | Volume of proof |
| 9 | The Split | "This Weekend → Every Month After" | Before/after transformation |
| 10 | Proof Numbers | €XXX+ / XX products / X,XXX+ builders | Credibility through specifics |

---

## 6. Performance Targets

| Metric | Target |
|--------|--------|
| CPL (Cost Per Lead/Registration) | €3-5 |
| CTR (Click-Through Rate) | >1.5% |
| Webinar Registration Rate | 5-10% of ad viewers |
| Webinar Attendance Rate | 30-50% of registered |
| Webinar → Sale Conversion | 5-15% |
| Target ROAS | 4.0x minimum |
| Monthly Ad Budget | €2,000 starting |

### Budget Allocation (Hormozi 70/20/10)
- **70% Scale**: Proven winners (best performing ads)
- **20% Iterate**: Variations of winners
- **10% Test**: New concepts

---

## 7. Campaign Structure in Meta

| Campaign | ID | Purpose |
|----------|-----|---------|
| Scale | `YOUR_CAMPAIGN_OR_ADSET_ID` | Proven winners at higher budget |
| Iterate | `YOUR_CAMPAIGN_OR_ADSET_ID` | Variations of what works |
| Test | `YOUR_CAMPAIGN_OR_ADSET_ID` | New creative concepts |
| Retarget | `YOUR_CAMPAIGN_OR_ADSET_ID` | Website visitors, video viewers |

| Ad Set | ID | Purpose |
|--------|-----|---------|
| Scale Main | `YOUR_CAMPAIGN_OR_ADSET_ID` | Primary scaling ad set |
| Test Main | `YOUR_CAMPAIGN_OR_ADSET_ID` | Testing new creatives |
| Retarget Website | `YOUR_CAMPAIGN_OR_ADSET_ID` | Website visitor retargeting |

### Standard Flow for New Ads
1. Generate images using brand template
2. Create ads in `test_main` ad set (PAUSED)
3. Review in Ads Manager
4. Activate for testing
5. After 3-5 days: promote winners to `scale_main`

---

## 8. Quality Gate (MANDATORY before pushing to Meta)

Before ANY ad is pushed to Meta, verify ALL of these:

1. **Typo check** — Read every word in the generated image. AI image generators frequently misspell words. If ANY typo is found, regenerate. NEVER push an ad with a typo.
2. **URL check** — Primary text must end with `yourdomain.com/webinar`. Description must include `yourdomain.com/webinar`.
3. **CTA check** — Must be `SIGN_UP`, link must be `https://yourdomain.com/webinar`.
4. **Price check** — No prices (€497, €997, €247, etc.) anywhere in copy or image.
5. **Brand check** — Image uses brand template background, not generated from scratch.
6. **Show the user** — Always display the generated images to the user for review before pushing to Meta.

If any check fails: fix and re-verify. Do NOT push and fix later.

---

## 9. What NOT to Do

- ❌ Show product prices (€497, €997, €247) in ads
- ❌ Link to /checkout — always link to /webinar
- ❌ Use "LEARN_MORE" CTA — use "SIGN_UP"
- ❌ Generate images from scratch without template background
- ❌ Use photos, illustrations, or stock imagery
- ❌ Make income guarantees ("You WILL make €X")
- ❌ Use Audience Network placement
- ❌ Target UAE
- ❌ Run ads without compliance check

---

## 9. Webinar Details (for ad copy reference)

- **Title**: "Stop Building AI Products Nobody Pays For"
- **Host**: the founder (YourBrand founder)
- **Duration**: 60 minutes
- **Format**: Teaching + Live Demo + Q&A
- **Date**: Friday, [WEBINAR DATE] at [TIME]
- **URL**: https://yourdomain.com/webinar
- **Cost**: Free (no credit card required)
- **What attendees learn**:
  - The 3-path monetization system (SaaS, RaaS, Services)
  - Live demo: building a real AI product in 15 minutes
  - The "First 10 Customers" playbook
  - How to price AI services (€500-2,000/month per client)

---

## 10. Credibility Stats (use in ad copy)

- €XXX+ revenue from AI products and services
- XX products sold/shipped
- X,XXX+ builders in the community
- XX,XXX+ YouTube subscribers
- Voice AI Receptionist: #1 selling product (26 sales)
- Dollar-value YouTube titles get 6.1-6.7% engagement rate

---

*Last updated: 2026-04-01*
