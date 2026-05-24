# Ad System -- Source of Truth for Demo Agency

This file is auto-generated from `client_config.yaml`.
To update, edit client_config.yaml and run: `python -m scripts.setup --from-config`

---

## 1. The Funnel

```
Meta Ads (cold traffic)
    |
Free Masterclass (https://demo.com/webinar)
    |
Live Webinar / Event
    |
Offer reveal + conversion
    |
Post-event email nurture
    |
Paid product
```

### Rules
- Do NOT show prices in ads
- The CTA is always "Save My Spot"
- The CTA type in Meta is: `SIGN_UP`
- The link is always: `https://demo.com/webinar`

---

## 2. Target Audience

| Segment | % of Spend | Profile |
|---------|-----------|---------|
| Primary | 60% | Age 25-45, Main target audience |
| Secondary | 30% | Age 28-50, Secondary audience |
| Tertiary | 10% | Age 22-40, Exploratory audience |

### Geographic Targeting
- Primary: US, GB
- Excluded: None
- Placements: feeds

---

## 3. Brand Design System

| Element | Value |
|---------|-------|
| Background | `#0a0a0a` |
| Accent | `#c8ff00` |
| Text | `#ffffff` |
| Font | bold sans-serif |
| Visual feel | dark, premium, techy, direct |

### Creative Restrictions

- no stock photos
- no illustrations of people
- no income guarantees

---

## 4. Ad Copy Structure

| Field | Rules |
|-------|-------|
| **Primary Text** | 3-8 lines, ends with CTA link |
| **Headline** | Short, punchy, under 40 chars |
| **Description** | Short value prop |
| **CTA Button** | `SIGN_UP` |
| **URL** | `https://demo.com/webinar` |

---

## 5. Proven Ad Angles

| # | Angle | Hook | Why It Works |
|---|-------|------|-------------|
| 1 | The Stat | 90% of people never make money from X | Curiosity gap |
| 2 | The Math | 3 clients x $500/mo = $1,500 recurring | Makes opportunity concrete |
| 3 | The Testimonial | Real customer quote | Social proof |
| 4 | The Contrarian | Stop doing X. Start doing Y. | Pattern interrupt |

---

## 6. Performance Targets

| Metric | Target |
|--------|--------|
| CPL (Cost Per Lead) | $5 |
| CPA (Cost Per Acquisition) | $50 |
| Target ROAS | 4.0x |
| CTR minimum | 1.5% |
| Monthly Budget | $2,000 |
| Daily Cap | $120 |

### Budget Allocation (70/20/10)
- **70% Scale**: Proven winners
- **20% Iterate**: Variations of winners
- **10% Test**: New concepts

---

## 7. Campaign Structure in Meta

| Campaign | ID | Purpose |
|----------|-----|---------|
| Scale | `` | Proven winners |
| Iterate | `` | Variations |
| Test | `` | New concepts |
| Retarget | `` | Retargeting |

---

## 8. Credibility / Proof Points

- $XXX+ revenue
- XX customers served
- X years in business

---

## 9. Quality Gate (before pushing to Meta)

1. Typo check -- read every word in generated images
2. URL check -- must link to `https://demo.com/webinar`
3. CTA check -- must be `SIGN_UP`
4. Brand check -- image uses brand template
5. Show the user -- always get approval before publishing

---

*Auto-generated from client_config.yaml*
