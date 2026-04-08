# Budget Rules

These rules are HARD LIMITS. The system reads this file before any budget-related action. No automation can override these.

---

## Hard Caps (Non-Negotiable)

| Rule | Limit | Action if Violated |
|------|-------|--------------------|
| Maximum daily spend (all ad sets combined) | **€120/day** | Pause all ad sets immediately + Telegram alert |
| Maximum single ad set budget | **€60/day** | Block the change + Telegram alert |
| Maximum budget increase per change | **25%** | Block any increase larger than this |
| Minimum time between budget changes | **24 hours** per ad set | Skip if changed within 24h |
| Maximum number of auto budget changes per day | **1** | Skip additional changes |

## Default Budgets

| Ad Set | Default Budget | Purpose |
|--------|---------------|---------|
| Scale | €55/day | Proven winners at higher volume |
| Test | €22/day | New creative testing |
| Retarget | €5/day | Warm audience follow-up |
| **Total** | **€82/day** | |

## What Went Wrong (April 8, 2026)

The `auto_scale_pre_webinar()` function was supposed to increase budgets by 25% once per day. But:
1. The state file (`.scale_state.json`) didn't persist on GitHub Actions — each run was a fresh environment
2. The function ran **every hour** instead of once per day
3. 25% compounding hourly: €45 → €56 → €70 → €88 → ... → **€7,937/day** in 4 days
4. No hard cap existed to stop this
5. The API couldn't decrease budgets because the change was too dramatic — had to be done manually
6. The ad account got disabled due to payment failure from the overspend

**Cost of this bug: ~€200 wasted at €16+ CPL instead of normal €3-5 CPL.**

## How Auto-Scaling Must Work (If Ever Re-Enabled)

1. ALWAYS check current budget against the hard cap BEFORE increasing
2. NEVER increase if new budget would exceed €60/day per ad set
3. NEVER increase if total daily spend across all ad sets would exceed €120
4. Log every budget change with timestamp, old value, new value
5. Send Telegram alert for EVERY budget change
6. Use Supabase (not local files) to track state — local files don't persist on GitHub Actions

## Emergency Procedures

If spending goes wrong:
1. **Auto-pause**: The system should auto-pause all ad sets if daily spend exceeds €150 (2x the normal max)
2. **Telegram alert**: Immediate notification with the amount
3. **Manual override**: If API can't fix it, send clear instructions to fix in Ads Manager
4. **Account spending limit**: Always keep a €500 limit set in Meta's payment settings as the last line of defense

---

*This file is read by auto_rules.py before any budget operation. These limits cannot be overridden by any automation.*
