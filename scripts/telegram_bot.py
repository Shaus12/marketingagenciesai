"""
Telegram bot for managing Meta Ads — powered by Claude.

Chat naturally, ask about performance, and control campaigns from Telegram.

Built-in commands:
  /stats    — today's campaign stats
  /week     — last 7 days summary
  /pause    — pause all active campaigns
  /activate — activate campaigns
  /help     — show available commands

Usage:
    python -m scripts.telegram_bot
"""

import logging
import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.exceptions import FacebookRequestError

logger = logging.getLogger(__name__)

# -- Config (all from environment / client_config.yaml) --------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
KIE_API_KEY = os.getenv("KIE_AI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "")


def _load_client_config() -> dict:
    """Load client_config.yaml for business context."""
    try:
        import yaml
        from pathlib import Path
        config_path = Path(__file__).resolve().parent.parent / "client_config.yaml"
        if config_path.exists():
            return yaml.safe_load(config_path.read_text()) or {}
    except Exception:
        pass
    return {}


_CLIENT_CONFIG = _load_client_config()
_BIZ_NAME = _CLIENT_CONFIG.get("business", {}).get("name", "your business")
_CURRENCY = _CLIENT_CONFIG.get("targets", {}).get("currency", "USD")
_CURRENCY_SYM = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "ILS": "\u20aa"}.get(_CURRENCY, _CURRENCY + " ")
_MONTHLY_BUDGET = _CLIENT_CONFIG.get("targets", {}).get("monthly_budget", 0)
_TARGET_CPL = _CLIENT_CONFIG.get("targets", {}).get("cpl", 5.0)
_TARGET_ROAS = _CLIENT_CONFIG.get("targets", {}).get("target_roas", 4.0)
_FUNNEL_TYPE = _CLIENT_CONFIG.get("funnel", {}).get("type", "")
_LANDING_URL = _CLIENT_CONFIG.get("funnel", {}).get("landing_page_url", "")

SYSTEM_PROMPT = f"""You are an AI ads assistant managing Meta (Facebook/Instagram) campaigns for "{_BIZ_NAME}".

You help the user monitor performance, understand metrics, and make decisions about their ad campaigns. Be concise, direct, and use plain language.

Key facts:
- Business: {_BIZ_NAME}
- Currency: {_CURRENCY}
- Monthly budget: {_CURRENCY_SYM}{_MONTHLY_BUDGET:,.0f}
- Target CPL: {_CURRENCY_SYM}{_TARGET_CPL}
- Target ROAS: {_TARGET_ROAS}x
- Funnel: {_FUNNEL_TYPE}
- Landing page: {_LANDING_URL}

When asked about metrics, remind the user they can type /stats for live numbers.
When asked to pause or activate, remind them they can use /pause or /activate commands.
Keep answers under 200 words unless the user asks for detail."""


# -- Telegram helpers ------------------------------------------------------

def send(chat_id: str, text: str) -> None:
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        timeout=10,
    )


def get_updates(offset: int) -> list:
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 30, "limit": 10},
            timeout=35,
        )
        return r.json().get("result", [])
    except Exception:
        return []


# -- Meta helpers ----------------------------------------------------------

def _init_meta():
    FacebookAdsApi.init(
        app_id=os.getenv("META_APP_ID"),
        app_secret=os.getenv("META_APP_SECRET"),
        access_token=os.getenv("META_ACCESS_TOKEN"),
    )


def _get_active_campaigns() -> list:
    """Get all active campaigns from the ad account."""
    _init_meta()
    account = AdAccount(AD_ACCOUNT_ID)
    campaigns = account.get_campaigns(
        fields=["id", "name", "status", "daily_budget"],
        params={"effective_status": ["ACTIVE"]},
    )
    return [dict(c) for c in campaigns]


def get_today_stats() -> str:
    """Fetch today's stats for all active campaigns."""
    _init_meta()
    from datetime import date, timedelta
    account = AdAccount(AD_ACCOUNT_ID)
    today = date.today()

    try:
        insights = account.get_insights(params={
            "time_range": {"since": str(today), "until": str(today)},
            "fields": [
                "spend", "impressions", "clicks", "ctr", "cpm",
                "actions", "cost_per_action_type",
            ],
            "level": "account",
        })
        rows = list(insights)
        if not rows:
            return f"No data yet today for {_BIZ_NAME}."

        row = dict(rows[0])
        spend = float(row.get("spend", 0))
        impressions = int(row.get("impressions", 0))
        clicks = int(row.get("clicks", 0))
        ctr = float(row.get("ctr", 0))

        # Extract conversions
        conversions = 0
        cpa = 0.0
        for action in row.get("actions", []):
            if action.get("action_type") in ("lead", "offsite_conversion.fb_pixel_purchase", "mobile_app_install", "app_install"):
                conversions += int(action.get("value", 0))
        for cost in row.get("cost_per_action_type", []):
            if cost.get("action_type") in ("lead", "offsite_conversion.fb_pixel_purchase", "mobile_app_install", "app_install"):
                cpa = float(cost.get("value", 0))

        lines = [
            f"*{_BIZ_NAME} — Today*",
            f"_{today}_\n",
            f"Spend: {_CURRENCY_SYM}{spend:.2f}",
            f"Impressions: {impressions:,}",
            f"Clicks: {clicks:,} ({ctr:.2f}% CTR)",
            f"Conversions: {conversions}",
            f"CPA: {_CURRENCY_SYM}{cpa:.2f}" if cpa > 0 else "CPA: --",
        ]

        if conversions > 0 and cpa > 0:
            if cpa <= _TARGET_CPL:
                lines.append(f"\nBelow target ({_CURRENCY_SYM}{_TARGET_CPL}) — looking good.")
            else:
                lines.append(f"\nAbove target ({_CURRENCY_SYM}{_TARGET_CPL}) — monitor closely.")

        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching stats: {e}"


def get_week_stats() -> str:
    """Fetch last 7 days stats."""
    _init_meta()
    from datetime import date, timedelta
    account = AdAccount(AD_ACCOUNT_ID)
    end = date.today()
    start = end - timedelta(days=6)

    try:
        insights = account.get_insights(params={
            "time_range": {"since": str(start), "until": str(end)},
            "fields": [
                "spend", "impressions", "clicks", "ctr",
                "actions", "cost_per_action_type",
            ],
            "level": "account",
        })
        rows = list(insights)
        if not rows:
            return "No data for the last 7 days."

        row = dict(rows[0])
        spend = float(row.get("spend", 0))
        impressions = int(row.get("impressions", 0))
        clicks = int(row.get("clicks", 0))
        ctr = float(row.get("ctr", 0))

        conversions = 0
        cpa = 0.0
        for action in row.get("actions", []):
            if action.get("action_type") in ("lead", "offsite_conversion.fb_pixel_purchase", "mobile_app_install", "app_install"):
                conversions += int(action.get("value", 0))
        if conversions > 0 and spend > 0:
            cpa = spend / conversions

        lines = [
            f"*{_BIZ_NAME} — Last 7 Days*",
            f"_{start} to {end}_\n",
            f"Spend: {_CURRENCY_SYM}{spend:.2f}",
            f"Impressions: {impressions:,}",
            f"Clicks: {clicks:,} ({ctr:.2f}% CTR)",
            f"Conversions: {conversions}",
            f"Avg CPA: {_CURRENCY_SYM}{cpa:.2f}" if cpa > 0 else "CPA: --",
            f"Daily avg: {_CURRENCY_SYM}{spend / 7:.2f}/day",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching weekly stats: {e}"


def set_campaign_status(status: str) -> str:
    """Pause or activate ALL campaigns in the account."""
    _init_meta()
    try:
        account = AdAccount(AD_ACCOUNT_ID)
        target_status = ["ACTIVE"] if status == "PAUSED" else ["PAUSED"]
        campaigns = account.get_campaigns(
            fields=["id", "name"],
            params={"effective_status": target_status},
        )
        changed = []
        for c in campaigns:
            try:
                campaign = Campaign(c["id"])
                campaign.api_update(params={"status": status})
                changed.append(c.get("name", c["id"]))
            except FacebookRequestError as e:
                logger.error("Failed to update %s: %s", c["id"], e.api_error_message())

        if not changed:
            label = "active" if status == "PAUSED" else "paused"
            return f"No {label} campaigns to change."

        action = "Paused" if status == "PAUSED" else "Activated"
        names = "\n".join(f"  - {n}" for n in changed)
        return f"{action} {len(changed)} campaign(s):\n{names}"
    except Exception as e:
        return f"Error: {e}"


# -- AI chat (Claude via Anthropic or Kie.ai) ------------------------------

_history: dict[str, list] = {}


def ask_claude(chat_id: str, user_message: str) -> str:
    if chat_id not in _history:
        _history[chat_id] = []

    _history[chat_id].append({"role": "user", "content": user_message})
    messages = _history[chat_id][-20:]

    # Try Anthropic SDK first, then Kie.ai fallback
    try:
        if ANTHROPIC_API_KEY:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            resp = client.messages.create(
                model="claude-sonnet-4-5-20250514",
                max_tokens=512,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
            reply = resp.content[0].text
        elif KIE_API_KEY:
            r = requests.post(
                "https://api.kie.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {KIE_API_KEY}", "content-type": "application/json"},
                json={"model": "claude-sonnet-4-5", "max_tokens": 512,
                      "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages},
                timeout=30,
            )
            data = r.json()
            if "choices" in data and data["choices"]:
                reply = data["choices"][0].get("message", {}).get("content", "")
            else:
                reply = f"AI error: {data.get('error', {}).get('message', 'unknown')}"
        else:
            reply = "No AI API key configured. Set ANTHROPIC_API_KEY or KIE_AI_API_KEY in your .env file."

        _history[chat_id].append({"role": "assistant", "content": reply})
        return reply
    except Exception as e:
        return f"AI error: {e}"


# -- Command handler ------------------------------------------------------

HELP_TEXT = f"""*{_BIZ_NAME} Ads Bot*

*Commands:*
/stats — today's performance
/week — last 7 days
/activate — turn campaigns ON
/pause — turn campaigns OFF
/help — this message

Or just *chat naturally* — ask me anything about your ads, results, or strategy."""


def handle_message(chat_id: str, text: str) -> None:
    text = text.strip()

    if text.startswith("/stats"):
        send(chat_id, get_today_stats())
    elif text.startswith("/week"):
        send(chat_id, get_week_stats())
    elif text.startswith("/activate"):
        send(chat_id, set_campaign_status("ACTIVE"))
    elif text.startswith("/pause"):
        send(chat_id, set_campaign_status("PAUSED"))
    elif text.startswith("/start") or text.startswith("/help"):
        send(chat_id, HELP_TEXT)
    else:
        reply = ask_claude(chat_id, text)
        send(chat_id, reply)


# -- Main loop ------------------------------------------------------------

def run():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set. Run the setup wizard first.")
        sys.exit(1)

    logger.info("Bot starting for %s — polling for messages...", _BIZ_NAME)
    send(TELEGRAM_CHAT, f"*{_BIZ_NAME} Ads Bot* is online. Type /help to see what I can do.")

    offset = 0
    while True:
        updates = get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text = msg.get("text", "")

            if not chat_id or not text:
                continue

            if TELEGRAM_CHAT and chat_id != TELEGRAM_CHAT:
                logger.warning("Ignoring message from unknown chat %s", chat_id)
                continue

            logger.info("Message from %s: %s", chat_id, text[:60])
            handle_message(chat_id, text)

        time.sleep(1)


if __name__ == "__main__":
    run()
