"""
Daily performance report — fetches Meta insights and sends to Telegram.

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
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount

logger = logging.getLogger(__name__)

# -- Config ----------------------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "")


def _load_client_config() -> dict:
    try:
        import yaml
        from pathlib import Path
        config_path = Path(__file__).resolve().parent.parent / "client_config.yaml"
        if config_path.exists():
            return yaml.safe_load(config_path.read_text()) or {}
    except Exception:
        pass
    return {}


_CONFIG = _load_client_config()
_BIZ_NAME = _CONFIG.get("business", {}).get("name", "Meta Ads")
_CURRENCY = _CONFIG.get("targets", {}).get("currency", "USD")
_SYM = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "ILS": "\u20aa"}.get(_CURRENCY, _CURRENCY + " ")
_TARGET_CPL = _CONFIG.get("targets", {}).get("cpl", 5.0)


# -- Telegram --------------------------------------------------------------

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


# -- Meta insights ---------------------------------------------------------

def _init_meta():
    FacebookAdsApi.init(
        app_id=os.getenv("META_APP_ID"),
        app_secret=os.getenv("META_APP_SECRET"),
        access_token=os.getenv("META_ACCESS_TOKEN"),
    )


def fetch_campaign_insights(campaign_id: str = None, days: int = 1) -> dict:
    """Fetch account-level insights. If campaign_id given, fetch for that campaign."""
    _init_meta()
    end = date.today()
    start = end - timedelta(days=days - 1)

    account = AdAccount(AD_ACCOUNT_ID)
    insights = account.get_insights(params={
        "time_range": {"since": str(start), "until": str(end)},
        "fields": [
            "spend", "impressions", "clicks", "ctr", "cpm",
            "actions", "cost_per_action_type",
        ],
        "level": "account",
    })

    rows = list(insights)
    if not rows:
        return {}

    row = dict(rows[0])

    conversions = 0
    cpa = 0.0
    for action in row.get("actions", []):
        if action.get("action_type") in (
            "lead", "offsite_conversion.fb_pixel_purchase",
            "mobile_app_install", "app_install", "complete_registration",
        ):
            conversions += int(action.get("value", 0))
    for cost in row.get("cost_per_action_type", []):
        if cost.get("action_type") in (
            "lead", "offsite_conversion.fb_pixel_purchase",
            "mobile_app_install", "app_install", "complete_registration",
        ):
            cpa = float(cost.get("value", 0))

    spend = float(row.get("spend", 0))

    return {
        "spend": spend,
        "impressions": int(row.get("impressions", 0)),
        "clicks": int(row.get("clicks", 0)),
        "ctr": float(row.get("ctr", 0)),
        "cpm": float(row.get("cpm", 0)),
        "conversions": conversions,
        "cpa": cpa,
        "days": days,
        "start": str(start),
        "end": str(end),
    }


def format_report(stats: dict) -> str:
    if not stats:
        return f"No data yet for {_BIZ_NAME}."

    days_label = "Today" if stats["days"] == 1 else f"Last {stats['days']} days"

    lines = [
        f"*{_BIZ_NAME} — {days_label}*",
        f"_{stats['start']} to {stats['end']}_\n",
        f"Spend: {_SYM}{stats['spend']:.2f}",
        f"Impressions: {stats['impressions']:,}",
        f"Clicks: {stats['clicks']:,} ({stats['ctr']:.2f}% CTR)",
        f"Conversions: {stats['conversions']}",
        f"CPA: {_SYM}{stats['cpa']:.2f}" if stats["cpa"] > 0 else "CPA: --",
    ]

    if stats["conversions"] > 0 and stats["cpa"] > 0:
        if stats["cpa"] <= _TARGET_CPL:
            lines.append(f"\nBelow target ({_SYM}{_TARGET_CPL}) — looking good.")
        else:
            lines.append(f"\nAbove target ({_SYM}{_TARGET_CPL}) — monitor closely.")

    return "\n".join(lines)


# -- Entry point -----------------------------------------------------------

def run(days: int = 1):
    logging.basicConfig(level=logging.WARNING)
    stats = fetch_campaign_insights(days=days)
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
