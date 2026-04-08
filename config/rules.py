"""
Kill / Scale / Alert rules for the automated rules engine.
Based on 2026 Meta best practices + Hormozi scaling discipline.
"""

from config.settings import TARGET_CPA, TARGET_ROAS


# ============================================================
# KILL RULES — Auto-pause ads that meet these criteria
# ============================================================
KILL_RULES = [
    {
        "name": "high_spend_no_conversions",
        "description": "Ad spent more than 1.5x target CPA with zero conversions",
        "condition": lambda ad: (
            ad["spend"] > TARGET_CPA * 1.5
            and ad["conversions"] == 0
            and ad["is_learning_phase_complete"]
        ),
        "action": "pause",
        "severity": "critical",
    },
    {
        "name": "negative_roas_after_learning",
        "description": "Ad has ROAS below 1.0 after spending 2x target CPA (post-learning)",
        "condition": lambda ad: (
            ad["spend"] > TARGET_CPA * 2
            and ad["roas"] < 1.0
            and ad["is_learning_phase_complete"]
        ),
        "action": "pause",
        "severity": "critical",
    },
    {
        "name": "ctr_collapse",
        "description": "CTR dropped more than 30% vs 7-day average",
        "condition": lambda ad: (
            ad["ctr_vs_7d_avg_pct"] < -30
            and ad["spend"] > TARGET_CPA * 0.5
        ),
        "action": "pause",
        "severity": "warning",
    },
    {
        "name": "cpa_too_high",
        "description": "CPA exceeds 2x target for 3+ consecutive days",
        "condition": lambda ad: (
            ad["cpa"] > TARGET_CPA * 2
            and ad["days_above_target_cpa"] >= 3
            and ad["conversions"] > 0
        ),
        "action": "pause",
        "severity": "critical",
    },
]


# ============================================================
# SCALE RULES — Budget increase suggestions
# ============================================================
SCALE_RULES = [
    {
        "name": "consistent_performer",
        "description": "ROAS >20% above target for 3 consecutive days",
        "condition": lambda ad: (
            ad["roas"] > TARGET_ROAS * 1.2
            and ad["consecutive_days_above_target"] >= 3
            and ad["is_learning_phase_complete"]
        ),
        "action": "increase_budget_20pct",
        "cooldown_hours": 72,  # Wait 72h between budget changes
    },
    {
        "name": "high_volume_winner",
        "description": "50+ conversions/week at or below target CPA",
        "condition": lambda ad: (
            ad["conversions_7d"] >= 50
            and ad["cpa"] <= TARGET_CPA
        ),
        "action": "increase_budget_20pct",
        "cooldown_hours": 48,
    },
    {
        "name": "graduation_to_scale",
        "description": "Test creative beats current best CPA by >15%",
        "condition": lambda ad: (
            ad["campaign_type"] == "test"
            and ad["cpa"] < ad["best_scale_cpa"] * 0.85
            and ad["conversions"] >= 10
        ),
        "action": "graduate_to_scale",
        "cooldown_hours": 0,
    },
]


# ============================================================
# ALERT RULES — Notify but don't auto-act
# ============================================================
ALERT_RULES = [
    {
        "name": "creative_fatigue",
        "description": "Ad set frequency exceeds 4.0",
        "condition": lambda ad: ad["frequency"] > 4.0,
        "severity": "warning",
    },
    {
        "name": "hook_rate_declining",
        "description": "Hook rate dropped >10% over 5 days (creative fatiguing)",
        "condition": lambda ad: ad.get("hook_rate_5d_trend_pct", 0) < -10,
        "severity": "warning",
    },
    {
        "name": "budget_overspend",
        "description": "Daily spend exceeds daily budget by >10%",
        "condition": lambda ad: ad.get("spend_vs_daily_budget_pct", 0) > 10,
        "severity": "info",
    },
    {
        "name": "new_winner_found",
        "description": "New creative outperforms current best by >30%",
        "condition": lambda ad: (
            ad["campaign_type"] == "test"
            and ad.get("cpa_vs_best_pct", 0) < -30
            and ad["conversions"] >= 5
        ),
        "severity": "positive",
    },
    {
        "name": "learning_phase_exit",
        "description": "Campaign exited learning phase",
        "condition": lambda ad: ad.get("just_exited_learning", False),
        "severity": "info",
    },
    {
        "name": "account_cpa_rising",
        "description": "Account-level CPA rose >15% week-over-week",
        "condition": lambda ad: ad.get("account_cpa_wow_pct", 0) > 15,
        "severity": "warning",
    },
]


# ============================================================
# CREATIVE SCORING THRESHOLDS
# ============================================================
CREATIVE_THRESHOLDS = {
    "hook_rate": {"poor": 15, "okay": 20, "good": 30, "great": 35},
    "hold_rate": {"poor": 25, "okay": 35, "good": 45, "great": 60},
    "ctr": {"poor": 0.8, "okay": 1.2, "good": 1.5, "great": 2.5},
    "cpa_vs_target": {"great": 0.7, "good": 1.0, "okay": 1.3, "poor": 2.0},
    "roas_vs_target": {"poor": 0.5, "okay": 0.8, "good": 1.0, "great": 1.5},
}


# ============================================================
# BUDGET CHANGE LIMITS
# ============================================================
MAX_BUDGET_INCREASE_PCT = 20       # Never increase budget more than 20% at once
MIN_HOURS_BETWEEN_CHANGES = 48     # Minimum hours between budget adjustments
LEARNING_PHASE_BUFFER_HOURS = 72   # Don't touch budgets for 72h after launch
