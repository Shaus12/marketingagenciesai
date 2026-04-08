"""
Telegram notification system for YourBrand Ads.

Sends performance updates, AI analyst briefings, alerts,
and strategic recommendations directly to Telegram.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send_message(text: str, parse_mode: str = "Markdown") -> bool:
    """Send a message to the configured Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — skipping notification")
        return False

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if r.json().get("ok"):
            return True
        else:
            logger.error("Telegram send failed: %s", r.json().get("description", ""))
            return False
    except Exception:
        logger.exception("Telegram send error")
        return False


# ============================================================
# NOTIFICATION TYPES
# ============================================================


def send_performance_update(dashboard: Dict[str, Any]) -> bool:
    """Send a compact performance summary (every 4 hours)."""
    spend_today = float(dashboard.get("today_spend", 0))
    conv_today = int(dashboard.get("today_conversions", 0))
    cpa_today = float(dashboard.get("today_cpa", 0))
    roas_today = float(dashboard.get("today_roas", 0))
    spend_week = float(dashboard.get("week_spend", 0))
    conv_week = int(dashboard.get("week_conversions", 0))
    active = int(dashboard.get("active_ads_count", 0))
    status = dashboard.get("overall_status", "unknown")

    status_emoji = {"healthy": "🟢", "needs_attention": "🟡", "critical": "🔴", "no_data": "⚪"}.get(status, "❓")

    text = (
        f"{status_emoji} *YourBrand Ads Update*\n\n"
        f"*Today*\n"
        f"  Spend: €{spend_today:.2f}\n"
        f"  Conversions: {conv_today}\n"
    )

    if conv_today > 0:
        text += f"  CPA: €{cpa_today:.2f}\n"
        text += f"  ROAS: {roas_today:.1f}x\n"

    text += (
        f"\n*This Week*\n"
        f"  Spend: €{spend_week:.2f}\n"
        f"  Conversions: {conv_week}\n"
        f"\n_{active} active ads_"
    )

    return send_message(text)


def send_ai_briefing(briefing: Dict[str, Any]) -> bool:
    """Send the AI analyst briefing summary."""
    grade = briefing.get("performance_grade", "?")
    summary = briefing.get("summary", "No summary available")

    grade_emoji = {"A": "🏆", "B": "👍", "C": "😐", "D": "⚠️", "F": "🚨"}.get(grade, "❓")

    text = f"{grade_emoji} *AI Analyst — Grade: {grade}*\n\n{summary}\n"

    # Auto-actions taken
    actions = briefing.get("actions_taken", [])
    if isinstance(actions, str):
        actions = json.loads(actions)
    if actions:
        text += "\n*Auto-Actions Taken:*\n"
        for a in actions[:5]:
            text += f"  ✅ {a.get('action_type', '?')}: {a.get('entity_name', '?')}\n"
            text += f"      _{a.get('reason', '')[:80]}_\n"

    # Suggestions
    suggested = briefing.get("actions_suggested", [])
    if isinstance(suggested, str):
        suggested = json.loads(suggested)
    if suggested:
        text += "\n*Recommendations:*\n"
        for s in suggested[:5]:
            priority = s.get("priority", "?")
            p_emoji = {"critical": "🔴", "high": "🟠", "medium": "🔵", "low": "⚪"}.get(priority, "•")
            text += f"  {p_emoji} {s.get('action', '?')[:80]}\n"

    # Patterns
    patterns = briefing.get("patterns_detected", [])
    if isinstance(patterns, str):
        patterns = json.loads(patterns)
    if patterns:
        text += "\n*Patterns:*\n"
        for p in patterns[:3]:
            text += f"  💡 {p[:80]}\n"

    # Creative briefs
    briefs = briefing.get("next_creative_briefs", [])
    if isinstance(briefs, str):
        briefs = json.loads(briefs)
    if briefs:
        text += "\n*New Creatives to Make:*\n"
        for b in briefs[:3]:
            text += f"  🎨 {b.get('concept', '?')[:60]}\n"

    return send_message(text)


def send_alert(alert_type: str, title: str, message: str, severity: str = "warning") -> bool:
    """Send an alert notification."""
    emoji = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️", "positive": "🎉"}.get(severity, "❗")

    text = (
        f"{emoji} *Ad Alert: {title}*\n\n"
        f"{message}\n"
    )

    return send_message(text)


def send_ad_killed(ad_name: str, reason: str) -> bool:
    """Notify when an ad is automatically paused."""
    return send_message(
        f"⏸️ *Ad Paused*\n\n"
        f"_{ad_name}_\n\n"
        f"Reason: {reason}"
    )


def send_ad_scaled(ad_name: str, old_budget: float, new_budget: float, reason: str) -> bool:
    """Notify when an ad's budget is increased."""
    return send_message(
        f"📈 *Budget Scaled*\n\n"
        f"_{ad_name}_\n"
        f"€{old_budget:.0f}/day → €{new_budget:.0f}/day\n\n"
        f"Reason: {reason}"
    )


def send_new_winner(ad_name: str, metric: str, value: str) -> bool:
    """Notify when a new winning ad is found."""
    return send_message(
        f"🏆 *New Winner Found!*\n\n"
        f"_{ad_name}_\n"
        f"{metric}: {value}\n\n"
        f"Consider scaling this ad and creating variations."
    )


def send_daily_summary(
    dashboard: Dict[str, Any],
    briefing: Optional[Dict[str, Any]] = None,
) -> bool:
    """Send a comprehensive daily summary (morning report)."""
    spend_today = float(dashboard.get("today_spend", 0))
    spend_week = float(dashboard.get("week_spend", 0))
    spend_month = float(dashboard.get("month_spend", 0))
    conv_week = int(dashboard.get("week_conversions", 0))
    active = int(dashboard.get("active_ads_count", 0))

    cpa_week = spend_week / conv_week if conv_week > 0 else 0

    text = (
        f"☀️ *Daily Ads Report*\n"
        f"_{datetime.now(tz=timezone.utc).strftime('%A, %B %d')}_\n\n"
        f"*Spend*\n"
        f"  Yesterday: €{spend_today:.2f}\n"
        f"  This week: €{spend_week:.2f}\n"
        f"  This month: €{spend_month:.2f}\n\n"
        f"*Results*\n"
        f"  Conversions (7d): {conv_week}\n"
    )

    if conv_week > 0:
        text += f"  CPA (7d): €{cpa_week:.2f}\n"

    text += f"\n  Active ads: {active}\n"

    if briefing:
        grade = briefing.get("performance_grade", "?")
        text += f"\n*AI Grade: {grade}*\n"
        summary = briefing.get("summary", "")
        if summary:
            text += f"_{summary[:200]}_\n"

    return send_message(text)


def send_weekly_report(
    total_spend: float,
    total_conversions: int,
    avg_cpa: float,
    avg_roas: float,
    top_ad: str,
    worst_ad: str,
    recommendations: List[str],
) -> bool:
    """Send weekly strategic report."""
    text = (
        f"📊 *Weekly Ads Report*\n\n"
        f"*This Week*\n"
        f"  Total spend: €{total_spend:.2f}\n"
        f"  Conversions: {total_conversions}\n"
        f"  Avg CPA: €{avg_cpa:.2f}\n"
        f"  Avg ROAS: {avg_roas:.1f}x\n\n"
        f"*Top Performer*\n  🏆 {top_ad}\n\n"
        f"*Worst Performer*\n  ⚠️ {worst_ad}\n\n"
    )

    if recommendations:
        text += "*Recommendations:*\n"
        for r in recommendations[:5]:
            text += f"  → {r}\n"

    return send_message(text)
