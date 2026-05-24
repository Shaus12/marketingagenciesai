"""
Telegram bot for Echoes Ads — powered by Claude via Kie.ai.

You can chat naturally, ask about performance, and control campaigns.

Built-in commands:
  /stats    — today's campaign stats
  /week     — last 7 days summary
  /pause    — pause all active campaigns
  /activate — activate the Echoes App Installs campaign
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

# ── Config ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT   = os.getenv("TELEGRAM_CHAT_ID", "")
KIE_API_KEY     = os.getenv("KIE_AI_API_KEY", "")
AD_ACCOUNT_ID   = os.getenv("META_AD_ACCOUNT_ID", "")
APP_INSTALLS_CAMPAIGN = "120244634251700200"

SYSTEM_PROMPT = """You are an AI ads assistant managing Facebook/Meta campaigns for the iOS app "Echoes: Numerology Map" — a numerology self-discovery app.

You help the user monitor performance, understand metrics, and make decisions about their ad campaigns. Be concise, direct, and use plain language. Use emojis sparingly.

Key facts about the setup:
- Campaign: "Echoes: Numerology Map — App Installs" (OUTCOME_APP_PROMOTION)
- Budget: 20 ILS/day
- Target: iOS users in IL, US, GB, AU, CA — ages 18+
- 2 active ads: "Cosmic Map" (purple cosmic image) and "Hook Text" (image with text overlay)
- Goal: cheap app installs (target CPI under 15 ILS)

When asked about metrics, remind the user they can type /stats for live numbers.
When asked to pause or activate, remind them they can use /pause or /activate commands.
Keep answers under 200 words unless the user asks for detail."""

# ── Telegram helpers ──────────────────────────────────────────────────────

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


# ── Meta helpers ──────────────────────────────────────────────────────────

def _init_meta():
    FacebookAdsApi.init(
        app_id=os.getenv("META_APP_ID"),
        app_secret=os.getenv("META_APP_SECRET"),
        access_token=os.getenv("META_ACCESS_TOKEN"),
    )


def get_today_stats() -> str:
    from scripts.daily_report import fetch_campaign_insights, format_report
    stats = fetch_campaign_insights(APP_INSTALLS_CAMPAIGN, days=1)
    return format_report(stats)


def get_week_stats() -> str:
    from scripts.daily_report import fetch_campaign_insights, format_report
    stats = fetch_campaign_insights(APP_INSTALLS_CAMPAIGN, days=7)
    return format_report(stats)


def set_campaign_status(status: str) -> str:
    _init_meta()
    try:
        campaign = Campaign(APP_INSTALLS_CAMPAIGN)
        campaign.api_update(params={"status": status})
        label = "▶️ activated" if status == "ACTIVE" else "⏸ paused"
        return f"Campaign {label} successfully."
    except FacebookRequestError as e:
        return f"Error: {e.api_error_message()}"


# ── Claude via Kie.ai ─────────────────────────────────────────────────────

# Conversation history per chat (in-memory, resets on bot restart)
_history: dict[str, list] = {}


def ask_claude(chat_id: str, user_message: str) -> str:
    if chat_id not in _history:
        _history[chat_id] = []

    _history[chat_id].append({"role": "user", "content": user_message})

    # Keep last 20 messages to avoid token overflow
    messages = _history[chat_id][-20:]

    try:
        # Prepend system prompt as first message if history is fresh
        full_messages = [{"role": "user", "content": f"[SYSTEM CONTEXT]\n{SYSTEM_PROMPT}\n[END CONTEXT]\n\nUser: {messages[0]['content']}"}] + messages[1:] if len(messages) == 1 else messages

        r = requests.post(
            "https://api.kie.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {KIE_API_KEY}",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-5",
                "max_tokens": 512,
                "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            },
            timeout=30,
        )
        data = r.json()

        if "choices" in data and data["choices"]:
            reply = data["choices"][0].get("message", {}).get("content", "")
        elif "error" in data:
            reply = f"AI error: {data['error'].get('message', 'unknown')}"
        else:
            reply = "Sorry, I didn't get a response. Try again."

        _history[chat_id].append({"role": "assistant", "content": reply})
        return reply

    except Exception as e:
        return f"Connection error: {e}"


# ── Command handler ───────────────────────────────────────────────────────

HELP_TEXT = """*Echoes Ads Bot* 🤖

*Commands:*
/stats — today's performance
/week — last 7 days
/activate — turn campaign ON
/pause — turn campaign OFF
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
        # Route to Claude
        reply = ask_claude(chat_id, text)
        send(chat_id, reply)


# ── Main loop ─────────────────────────────────────────────────────────────

def run():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logger.info("Bot starting — polling for messages...")
    send(TELEGRAM_CHAT, "🤖 Echoes Ads Bot is online. Type /help to see what I can do.")

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

            # Only respond to the configured chat
            if chat_id != TELEGRAM_CHAT:
                logger.warning("Ignoring message from unknown chat %s", chat_id)
                continue

            logger.info("Message from %s: %s", chat_id, text[:60])
            handle_message(chat_id, text)

        time.sleep(1)


if __name__ == "__main__":
    run()
