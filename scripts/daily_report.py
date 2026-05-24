"""
Daily performance report for Echoes: Numerology Map ads.
Fetches Meta campaign insights and sends a formatted Telegram message.

Usage:
    python -m scripts.daily_report          # today's stats
    python -m scripts.daily_report --days 7 # last 7 days
"""

import argparse
import logging
import os
import sys
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adaccount import AdAccount

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT   = os.getenv("TELEGRAM_CHAT_ID", "")
AD_ACCOUNT_ID   = os.getenv("META_AD_ACCOUNT_ID", "")
APP_INSTALLS_CAMPAIGN = "120244634251700200"


# ── Telegram helper ───────────────────────────────────────────────────────

def send_telegram(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print(text)
        return False
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT, "text": text, "parse_mode": "Markdown"},
        timeout=10,
    )
    return r.json().get("ok", False)


# ── Meta insights ─────────────────────────────────────────────────────────

def _init_meta():
    FacebookAdsApi.init(
        app_id=os.getenv("META_APP_ID"),
        app_secret=os.getenv("META_APP_SECRET"),
        access_token=os.getenv("META_ACCESS_TOKEN"),
    )


def fetch_campaign_insights(campaign_id: str, days: int = 1) -> dict:
    _init_meta()
    end   = date.today()
    start = end - timedelta(days=days - 1)

    campaign = Campaign(campaign_id)
    insights = campaign.get_insights(params={
        "time_range": {"since": str(start), "until": str(end)},
        "fields": [
            "campaign_name",
            "spend",
            "impressions",
            "clicks",
            "ctr",
            "cpm",
            "actions",
            "cost_per_action_type",
        ],
        "level": "campaign",
    })

    rows = list(insights)
    if not rows:
        return {}

    row = dict(rows[0])

    # Extract app installs from actions list
    installs = 0
    cpi = 0.0
    for action in row.get("actions", []):
        if action.get("action_type") in ("mobile_app_install", "app_install"):
            installs = int(action.get("value", 0))

    for cpa in row.get("cost_per_action_type", []):
        if cpa.get("action_type") in ("mobile_app_install", "app_install"):
            cpi = float(cpa.get("value", 0))

    spend = float(row.get("spend", 0))
    impressions = int(row.get("impressions", 0))
    clicks = int(row.get("clicks", 0))
    ctr = float(row.get("ctr", 0))
    cpm = float(row.get("cpm", 0))

    return {
        "campaign_name": row.get("campaign_name", ""),
        "spend": spend,
        "impressions": impressions,
        "clicks": clicks,
        "ctr": ctr,
        "cpm": cpm,
        "installs": installs,
        "cpi": cpi,
        "days": days,
        "start": str(start),
        "end": str(end),
    }


def fetch_all_campaigns_summary() -> list:
    _init_meta()
    account = AdAccount(AD_ACCOUNT_ID)
    campaigns = account.get_campaigns(fields=["name", "status", "objective"])
    result = []
    for c in campaigns:
        d = dict(c)
        if d.get("status") == "ACTIVE":
            result.append(d)
    return result


# ── Report formatting ─────────────────────────────────────────────────────

def format_report(stats: dict) -> str:
    if not stats:
        return "📊 No data yet — campaign may still be in review or hasn't spent yet."

    days_label = "Today" if stats["days"] == 1 else f"Last {stats['days']} days"
    ctr_fmt    = f"{stats['ctr']:.2f}%"
    cpi_fmt    = f"₪{stats['cpi']:.2f}" if stats["cpi"] else "—"
    spend_fmt  = f"₪{stats['spend']:.2f}"
    cpm_fmt    = f"₪{stats['cpm']:.2f}"

    lines = [
        f"📊 *Echoes Ads Report — {days_label}*",
        f"_{stats['start']} → {stats['end']}_\n",
        f"💰 Spend:       {spend_fmt}",
        f"👁 Impressions: {stats['impressions']:,}",
        f"🖱 Clicks:      {stats['clicks']:,}  ({ctr_fmt} CTR)",
        f"📱 Installs:    {stats['installs']}",
        f"💸 Cost/Install:{cpi_fmt}",
        f"📡 CPM:         {cpm_fmt}",
    ]

    # Simple performance signal
    if stats["installs"] > 0 and stats["cpi"] > 0:
        if stats["cpi"] < 15:
            lines.append("\n✅ CPI looks good — keep scaling.")
        elif stats["cpi"] < 30:
            lines.append("\n⚠️ CPI is moderate — monitor closely.")
        else:
            lines.append("\n🔴 CPI is high — consider pausing weak ad.")
    elif stats["spend"] > 5 and stats["installs"] == 0:
        lines.append("\n⚠️ Spend but no installs yet — may still be in learning phase.")

    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────

def run(days: int = 1):
    logging.basicConfig(level=logging.WARNING)
    stats = fetch_campaign_insights(APP_INSTALLS_CAMPAIGN, days=days)
    report = format_report(stats)
    ok = send_telegram(report)
    if ok:
        print("Report sent to Telegram.")
    else:
        print(report)


def main():
    parser = argparse.ArgumentParser(description="Send daily Meta ads report to Telegram")
    parser.add_argument("--days", type=int, default=1, help="Number of days to report on")
    args = parser.parse_args()
    run(days=args.days)


if __name__ == "__main__":
    main()
