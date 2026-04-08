"""
Alex Hormozi frameworks encoded as configuration.
Used by the creative module and copy generators.
"""


# ============================================================
# VALUE EQUATION
# Value = (Dream Outcome x Perceived Likelihood) / (Time Delay x Effort)
# ============================================================
VALUE_EQUATION = {
    "dream_outcome": {
        "weight": 0.35,
        "description": "What transformation does the customer want?",
        "signals": [
            "specific_result_mentioned",
            "emotional_outcome",
            "measurable_goal",
        ],
    },
    "perceived_likelihood": {
        "weight": 0.30,
        "description": "Do they believe it will work for THEM?",
        "signals": [
            "has_testimonial",
            "has_specific_proof",
            "has_before_after",
            "has_social_proof_count",
        ],
    },
    "time_delay": {
        "weight": 0.20,
        "description": "How fast do they get results? (lower = better)",
        "signals": [
            "specific_timeframe",
            "fast_result_claim",
            "immediate_value",
        ],
    },
    "effort_sacrifice": {
        "weight": 0.15,
        "description": "How hard is it? (lower = better)",
        "signals": [
            "easy_steps",
            "no_prior_knowledge",
            "done_for_you",
            "minimal_time_commitment",
        ],
    },
}


# ============================================================
# AD STRUCTURE: PROOF-PROMISE-PLAN
# ============================================================
AD_STRUCTURE = {
    "hook": {
        "duration_seconds": (0, 3),
        "purpose": "Pattern interrupt + call out your audience",
        "rules": [
            "Must stop the scroll in under 2 seconds",
            "Target audience must self-identify immediately",
            "Use unexpected visual or statement",
        ],
    },
    "promise": {
        "duration_seconds": (3, 8),
        "purpose": "Specific outcome with timeframe",
        "rules": [
            "Promise a SPECIFIC result, not vague help",
            "Include a timeframe if possible",
            "Use numbers and specifics",
        ],
    },
    "proof": {
        "duration_seconds": (8, 18),
        "purpose": "Testimonial, screenshot, result, before/after",
        "rules": [
            "Raw > edited testimonials",
            "Specific results > generic praise",
            "Show, don't just tell",
        ],
    },
    "bridge": {
        "duration_seconds": (18, 25),
        "purpose": "Connect their problem to your solution",
        "rules": [
            "Max 3 steps",
            "Make it sound easy and logical",
            "Address the #1 objection",
        ],
    },
    "cta": {
        "duration_seconds": (25, 30),
        "purpose": "Stupid simple next step, zero friction",
        "rules": [
            "One clear action only",
            "Remove all friction",
            "Give a reason to act NOW",
        ],
    },
}


# ============================================================
# HOOK CATEGORIES (for systematic testing)
# ============================================================
HOOK_CATEGORIES = {
    "question": {
        "template": "Are you still struggling with {pain_point}?",
        "when_to_use": "When community data shows frequent questions about a topic",
        "examples": [
            "Are you still {doing_thing_wrong}?",
            "Want to know why {thing} isn't working?",
            "What if I told you {surprising_fact}?",
        ],
    },
    "objection": {
        "template": "Everyone says {objection}, but here's what actually happens...",
        "when_to_use": "When community data shows common objections or skepticism",
        "examples": [
            "I used to think {objection} too...",
            "'{objection}' — I hear this every day. Here's the truth.",
            "Stop believing {myth}. Here's why.",
        ],
    },
    "shock_stat": {
        "template": "{percentage}% of {audience} don't know this about {topic}",
        "when_to_use": "When you have data that contradicts common belief",
        "examples": [
            "{percentage}% of {audience} get this wrong",
            "I analyzed {number} {things} and found something shocking",
            "This one stat changed how I think about {topic}",
        ],
    },
    "callout": {
        "template": "If you're a {specific_persona}, watch this",
        "when_to_use": "When targeting a specific segment of your audience",
        "examples": [
            "Hey {persona} — this is for you",
            "If you {specific_behavior}, stop and watch this",
            "Attention {persona}: this changes everything",
        ],
    },
    "proof": {
        "template": "{name} went from {before} to {after} in {timeframe}",
        "when_to_use": "When you have a strong success story from the community",
        "examples": [
            "{name} achieved {result} in just {timeframe}",
            "From {before_state} to {after_state} — here's how",
            "Watch how {name} {achieved_thing}",
        ],
    },
    "contrarian": {
        "template": "Stop doing {common_advice}. Do this instead.",
        "when_to_use": "When community discussions show frustration with standard advice",
        "examples": [
            "Everything you've been told about {topic} is wrong",
            "The worst advice in {niche}: '{bad_advice}'",
            "Why {popular_thing} is actually hurting your {outcome}",
        ],
    },
    "curiosity": {
        "template": "I discovered something about {topic} that nobody talks about",
        "when_to_use": "General use — creates an open loop",
        "examples": [
            "There's a secret about {topic} that {authority} won't tell you",
            "I found one thing that changed everything about {topic}",
            "The hidden reason why {problem} keeps happening",
        ],
    },
    "transformation": {
        "template": "I went from {before} to {after}. Here's the one thing that changed.",
        "when_to_use": "When the dream outcome is aspirational",
        "examples": [
            "{timeframe} ago I was {before}. Now I'm {after}.",
            "This is what {result} looks like (and how to get there)",
            "The exact {thing} that took me from {before} to {after}",
        ],
    },
}


# ============================================================
# COPY RULES
# ============================================================
COPY_RULES = {
    "reading_level": "3rd grade",  # Hormozi: simple words, short sentences
    "max_words_per_sentence": 12,
    "tone": "conversational, direct, confident",
    "forbidden_words": [
        "utilize", "leverage", "synergy", "optimize", "paradigm",
        "revolutionary", "game-changing", "disruptive", "innovative",
    ],
    "power_words": [
        "free", "new", "proven", "secret", "simple", "fast",
        "guaranteed", "discover", "instant", "exclusive",
    ],
    "cta_rules": [
        "One action only — never give two choices",
        "Remove every possible friction point",
        "Tell them EXACTLY what to do: 'Click the link below'",
        "Give a reason to act now, not later",
    ],
}


# ============================================================
# VOLUME TESTING TARGETS (Hormozi: Volume Negates Luck)
# ============================================================
VOLUME_TARGETS = {
    "hooks_per_body": 10,           # Record 10 hooks per ad body
    "angles_per_batch": 6,          # 6 different angles per testing batch
    "hooks_per_angle": 5,           # 5 hooks per angle
    "ads_per_batch": 30,            # 6 angles × 5 hooks = 30 ads
    "format_multiplier": 2,         # Double with format variations = 60
    "min_ads_per_week": 5,          # Minimum new ads entering test pipeline
    "community_ads_per_week": 3,    # Ads sourced from community data
}
