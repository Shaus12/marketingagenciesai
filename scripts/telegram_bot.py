"""
Telegram bot for managing Meta Ads — powered by Claude.

Chat naturally, ask about performance, and control campaigns from Telegram.
The AI understands intent — just say "show me stats" or "switch to account X".

Usage:
    python -m scripts.telegram_bot
"""

import json
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

# -- Config ----------------------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
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


_CLIENT_CONFIG = _load_client_config()
_BIZ_NAME = _CLIENT_CONFIG.get("business", {}).get("name", "your business")
_CURRENCY = _CLIENT_CONFIG.get("targets", {}).get("currency", "USD")
_CURRENCY_SYM = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "ILS": "\u20aa"}.get(_CURRENCY, _CURRENCY + " ")
_MONTHLY_BUDGET = _CLIENT_CONFIG.get("targets", {}).get("monthly_budget", 0)
_TARGET_CPL = _CLIENT_CONFIG.get("targets", {}).get("cpl", 5.0)
_TARGET_ROAS = _CLIENT_CONFIG.get("targets", {}).get("target_roas", 4.0)
_FUNNEL_TYPE = _CLIENT_CONFIG.get("funnel", {}).get("type", "")
_LANDING_URL = _CLIENT_CONFIG.get("funnel", {}).get("landing_page_url", "")


# -- Available tools for Claude --------------------------------------------

TOOLS_DESCRIPTION = """You have access to these tools. When the user's message matches one, respond ONLY with the exact JSON action. No extra text.

TOOLS:
1. get_all_stats - Show performance across ALL ad accounts (default when user asks generally)
   Trigger: user asks for stats, performance, results, "how are my ads", "מה התוצאות", weekly/daily results — unless they specify a single account
   Response: {"action": "all_stats", "days": 1}  (use days=7 for weekly)

2. get_stats - Show today's performance for the CURRENT account only
   Trigger: user specifically asks about the current account, or says "this account"
   Response: {"action": "stats"}

3. get_week - Show last 7 days for the CURRENT account only
   Trigger: user specifically asks about this account's weekly stats
   Response: {"action": "week"}

4. list_accounts - Show all ad accounts with buttons to switch
   Trigger: user asks to see accounts, switch account, change account, list accounts
   Response: {"action": "accounts"}

5. switch_account - Switch to a specific ad account
   Trigger: user says "switch to act_XXX" or mentions a specific account ID
   Response: {"action": "switch", "account_id": "act_XXXXXXXX"}

6. pause_campaigns - Pause all active campaigns
   Trigger: user asks to pause, stop, turn off campaigns
   Response: {"action": "pause"}

7. activate_campaigns - Activate paused campaigns
   Trigger: user asks to activate, turn on, resume, start campaigns
   Response: {"action": "activate"}

IMPORTANT: When the user asks generally about results/performance (e.g. "מה התוצאות שלי" / "how are campaigns doing" / "show me results"), ALWAYS use all_stats to show ALL accounts. Only use stats/week when they explicitly ask about a single/current account.

If the user's message does NOT match any tool, respond normally as a helpful ads assistant. Do NOT output JSON in that case — just reply in plain text."""

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
- Current ad account: {AD_ACCOUNT_ID}

Keep answers under 200 words unless the user asks for detail.

{TOOLS_DESCRIPTION}"""


# -- Telegram helpers ------------------------------------------------------

def send(chat_id: str, text: str, reply_markup: dict = None) -> None:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json=payload,
            timeout=10,
        )
    except Exception as e:
        logger.error("Failed to send message: %s", e)


def answer_callback(callback_query_id: str, text: str = "") -> None:
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
        json={"callback_query_id": callback_query_id, "text": text},
        timeout=10,
    )


def get_updates(offset: int) -> list:
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 30, "limit": 10,
                    "allowed_updates": json.dumps(["message", "callback_query"])},
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


def _get_account_name() -> str:
    """Get the current ad account's name."""
    try:
        _init_meta()
        account = AdAccount(AD_ACCOUNT_ID)
        info = account.api_get(fields=["name"])
        return info.get("name", AD_ACCOUNT_ID)
    except Exception:
        return AD_ACCOUNT_ID


def get_today_stats() -> str:
    _init_meta()
    from datetime import date
    account = AdAccount(AD_ACCOUNT_ID)
    today = date.today()
    acc_name = _get_account_name()

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
            return f"No data yet today for *{acc_name}* (`{AD_ACCOUNT_ID}`)."

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
        for cost in row.get("cost_per_action_type", []):
            if cost.get("action_type") in ("lead", "offsite_conversion.fb_pixel_purchase", "mobile_app_install", "app_install"):
                cpa = float(cost.get("value", 0))

        lines = [
            f"*{acc_name} — Today*",
            f"_Account: {AD_ACCOUNT_ID}_",
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
    _init_meta()
    from datetime import date, timedelta
    account = AdAccount(AD_ACCOUNT_ID)
    end = date.today()
    start = end - timedelta(days=6)
    acc_name = _get_account_name()

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
            return f"No data for the last 7 days for *{acc_name}*."

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
            f"*{acc_name} — Last 7 Days*",
            f"_Account: {AD_ACCOUNT_ID}_",
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


def get_all_accounts_stats(days: int = 1) -> str:
    """Fetch stats across ALL accessible ad accounts."""
    _init_meta()
    from datetime import date, timedelta
    token = os.getenv("META_ACCESS_TOKEN", "")

    # Get all accounts
    r = requests.get(
        "https://graph.facebook.com/v21.0/me/adaccounts",
        params={"access_token": token, "fields": "id,name,account_status", "limit": 50},
        timeout=10,
    )
    accounts = [a for a in r.json().get("data", []) if a.get("account_status") == 1]

    if not accounts:
        return "No active ad accounts found."

    end = date.today()
    start = end - timedelta(days=days - 1)
    period = "Today" if days == 1 else f"Last {days} days"

    lines = [f"*{_BIZ_NAME} — {period}*", f"_{start} to {end}_\n"]
    total_spend = 0.0
    total_conversions = 0
    total_clicks = 0
    accounts_with_data = 0

    for acc in accounts:
        acc_id = acc["id"]
        acc_name = acc.get("name", acc_id)
        try:
            account = AdAccount(acc_id)
            insights = account.get_insights(params={
                "time_range": {"since": str(start), "until": str(end)},
                "fields": ["spend", "impressions", "clicks", "ctr", "actions", "cost_per_action_type"],
                "level": "account",
            })
            rows = list(insights)
            if not rows:
                continue

            accounts_with_data += 1
            row = dict(rows[0])
            spend = float(row.get("spend", 0))
            impressions = int(row.get("impressions", 0))
            clicks = int(row.get("clicks", 0))
            ctr = float(row.get("ctr", 0))

            conversions = 0
            cpa = 0.0
            for action in row.get("actions", []):
                if action.get("action_type") in ("lead", "offsite_conversion.fb_pixel_purchase", "mobile_app_install", "app_install", "complete_registration", "offsite_conversion.fb_pixel_lead"):
                    conversions += int(action.get("value", 0))
            if conversions > 0 and spend > 0:
                cpa = spend / conversions

            total_spend += spend
            total_conversions += conversions
            total_clicks += clicks

            # Performance verdict
            verdict = ""
            if conversions > 0 and cpa > 0:
                if cpa <= _TARGET_CPL:
                    verdict = " ✅"
                else:
                    verdict = " ⚠️"

            lines.append(f"*{acc_name}*{verdict}")
            lines.append(f"  Spend: {_CURRENCY_SYM}{spend:.2f} | Clicks: {clicks:,} ({ctr:.2f}% CTR)")
            conv_text = f"  Conversions: {conversions}"
            if cpa > 0:
                conv_text += f" | CPA: {_CURRENCY_SYM}{cpa:.2f}"
            lines.append(conv_text)
            lines.append("")

        except Exception as e:
            logger.warning("Skipping %s: %s", acc_id, str(e)[:50])
            continue

    if accounts_with_data == 0:
        return f"No data for any account ({period})."

    # Summary
    lines.append("---")
    lines.append(f"*Total across {accounts_with_data} accounts:*")
    lines.append(f"  Spend: {_CURRENCY_SYM}{total_spend:.2f}")
    lines.append(f"  Clicks: {total_clicks:,}")
    lines.append(f"  Conversions: {total_conversions}")
    if total_conversions > 0:
        avg_cpa = total_spend / total_conversions
        lines.append(f"  Avg CPA: {_CURRENCY_SYM}{avg_cpa:.2f}")
        if avg_cpa <= _TARGET_CPL:
            lines.append(f"\n✅ Overall below target ({_CURRENCY_SYM}{_TARGET_CPL})")
        else:
            lines.append(f"\n⚠️ Overall above target ({_CURRENCY_SYM}{_TARGET_CPL})")

    return "\n".join(lines)


def list_accounts_with_buttons(chat_id: str) -> None:
    """List all ad accounts as inline buttons."""
    _init_meta()
    token = os.getenv("META_ACCESS_TOKEN", "")
    r = requests.get(
        "https://graph.facebook.com/v21.0/me/adaccounts",
        params={"access_token": token, "fields": "id,name,account_status", "limit": 50},
        timeout=10,
    )
    data = r.json().get("data", [])
    if not data:
        send(chat_id, "No ad accounts found.")
        return

    status_map = {1: "Active", 2: "Disabled", 3: "Unsettled", 7: "Pending"}
    buttons = []
    for acc in data:
        status = status_map.get(acc.get("account_status"), "?")
        name = acc.get("name", acc["id"])
        current = " [NOW]" if acc["id"] == AD_ACCOUNT_ID else ""
        label = f"{name} ({status}){current}"
        buttons.append([{"text": label, "callback_data": f"switch:{acc['id']}"}])

    send(
        chat_id,
        f"*Select an ad account:*\n_Current: `{AD_ACCOUNT_ID}`_",
        reply_markup={"inline_keyboard": buttons},
    )


def switch_account(new_account_id: str) -> str:
    global AD_ACCOUNT_ID
    new_account_id = new_account_id.strip()
    if not new_account_id.startswith("act_"):
        new_account_id = f"act_{new_account_id}"

    AD_ACCOUNT_ID = new_account_id
    os.environ["META_AD_ACCOUNT_ID"] = new_account_id

    # Update .env file
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    try:
        lines = open(env_path).readlines()
        with open(env_path, "w") as f:
            for line in lines:
                if line.startswith("META_AD_ACCOUNT_ID="):
                    f.write(f"META_AD_ACCOUNT_ID={new_account_id}\n")
                else:
                    f.write(line)
    except Exception as e:
        logger.error("Could not update .env: %s", e)

    # Get new account name
    acc_name = _get_account_name()
    return f"Switched to *{acc_name}* (`{new_account_id}`)."


# -- AI chat (Claude) -----------------------------------------------------

_history: dict[str, list] = {}


def ask_claude(chat_id: str, user_message: str) -> dict:
    """Ask Claude — returns either a tool action dict or a text reply string."""
    if chat_id not in _history:
        _history[chat_id] = []

    _history[chat_id].append({"role": "user", "content": user_message})
    messages = _history[chat_id][-20:]

    try:
        if not ANTHROPIC_API_KEY:
            return {"text": "No ANTHROPIC_API_KEY configured in .env."}

        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        reply = resp.content[0].text
        _history[chat_id].append({"role": "assistant", "content": reply})

        # Check if Claude returned a tool action
        reply_stripped = reply.strip()
        if reply_stripped.startswith("{") and reply_stripped.endswith("}"):
            try:
                action = json.loads(reply_stripped)
                if "action" in action:
                    return action
            except json.JSONDecodeError:
                pass

        return {"text": reply}
    except Exception as e:
        return {"text": f"AI error: {e}"}


# -- Command handler ------------------------------------------------------

HELP_TEXT = f"""*{_BIZ_NAME} Ads Bot*

*Commands:*
/all — all accounts performance (today)
/all7 — all accounts (last 7 days)
/stats — current account today
/week — current account last 7 days
/activate — turn campaigns ON
/pause — turn campaigns OFF
/accounts — list & switch ad accounts
/help — this message

Or just *chat naturally* — ask "מה התוצאות שלי?", "show me results", "switch account", etc."""


def handle_message(chat_id: str, text: str) -> None:
    text = text.strip()

    # Slash commands
    if text.startswith("/all7"):
        send(chat_id, "Fetching all accounts (7 days)...")
        send(chat_id, get_all_accounts_stats(days=7))
    elif text.startswith("/all"):
        send(chat_id, "Fetching all accounts...")
        send(chat_id, get_all_accounts_stats(days=1))
    elif text.startswith("/stats"):
        send(chat_id, get_today_stats())
    elif text.startswith("/week"):
        send(chat_id, get_week_stats())
    elif text.startswith("/activate"):
        send(chat_id, set_campaign_status("ACTIVE"))
    elif text.startswith("/pause"):
        send(chat_id, set_campaign_status("PAUSED"))
    elif text.startswith("/accounts"):
        list_accounts_with_buttons(chat_id)
    elif text.startswith("/start") or text.startswith("/help"):
        send(chat_id, HELP_TEXT)
    else:
        # Natural language — let Claude decide
        result = ask_claude(chat_id, text)

        if isinstance(result, dict) and "action" in result:
            execute_action(chat_id, result)
        else:
            send(chat_id, result.get("text", str(result)))


def execute_action(chat_id: str, action: dict) -> None:
    """Execute a tool action returned by Claude."""
    act = action.get("action")
    if act == "all_stats":
        days = action.get("days", 1)
        send(chat_id, f"Fetching all accounts ({days} day{'s' if days > 1 else ''})...")
        send(chat_id, get_all_accounts_stats(days=days))
    elif act == "stats":
        send(chat_id, get_today_stats())
    elif act == "week":
        send(chat_id, get_week_stats())
    elif act == "accounts":
        list_accounts_with_buttons(chat_id)
    elif act == "switch":
        account_id = action.get("account_id", "")
        if account_id:
            send(chat_id, switch_account(account_id))
        else:
            list_accounts_with_buttons(chat_id)
    elif act == "pause":
        send(chat_id, set_campaign_status("PAUSED"))
    elif act == "activate":
        send(chat_id, set_campaign_status("ACTIVE"))
    else:
        send(chat_id, "I didn't understand that action. Try /help.")


def handle_callback(callback_query: dict) -> None:
    """Handle inline button presses."""
    cb_id = callback_query.get("id", "")
    data = callback_query.get("data", "")
    chat_id = str(callback_query.get("message", {}).get("chat", {}).get("id", ""))

    if not chat_id:
        return

    if data.startswith("switch:"):
        account_id = data.split(":", 1)[1]
        result = switch_account(account_id)
        answer_callback(cb_id, f"Switched to {account_id}")
        send(chat_id, result)
    else:
        answer_callback(cb_id)


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

            # Handle inline button callbacks
            if "callback_query" in update:
                handle_callback(update["callback_query"])
                continue

            # Handle text messages
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
