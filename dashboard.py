"""
Meta Ads Performance Dashboard + Client Setup.

A Streamlit app for marketing agencies. Includes:
  - Web-based client onboarding (no terminal needed)
  - Live ad performance dashboard
  - Automated rule action log

Usage::

    streamlit run dashboard.py
"""

import os
import sqlite3
import subprocess
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st
import pandas as pd
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "ads.db"
CONFIG_PATH = PROJECT_ROOT / "client_config.yaml"
ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
AD_SYSTEM_PATH = PROJECT_ROOT / "AD_SYSTEM.md"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_client_config() -> dict:
    if CONFIG_PATH.exists():
        return yaml.safe_load(CONFIG_PATH.read_text()) or {}
    return {}


def save_client_config(config: dict):
    CONFIG_PATH.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))


def ensure_env_file():
    if not ENV_PATH.exists():
        if ENV_EXAMPLE.exists():
            shutil.copy(ENV_EXAMPLE, ENV_PATH)
        else:
            ENV_PATH.touch()


def read_env_value(key: str) -> str:
    # 1. Check Streamlit Cloud secrets first
    try:
        val = st.secrets.get(key, "")
        if val:
            return str(val)
    except Exception:
        pass
    # 2. Check OS environment variables
    env_val = os.environ.get(key, "")
    if env_val:
        return env_val
    # 3. Fall back to local .env file
    if not ENV_PATH.exists():
        return ""
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip()
    return ""


def update_env_value(key: str, value: str):
    ensure_env_file()
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    found = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        k, _, _ = stripped.partition("=")
        if k.strip() == key:
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(new_lines) + "\n")


def is_setup_complete() -> bool:
    config = load_client_config()
    biz_name = config.get("business", {}).get("name", "")
    token = read_env_value("META_ACCESS_TOKEN")
    return bool(biz_name and token and token != "your_access_token")


# ---------------------------------------------------------------------------
# AD_SYSTEM.md generator
# ---------------------------------------------------------------------------

def generate_ad_system(config: dict):
    from scripts.setup import _generate_ad_system
    _generate_ad_system(config)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def date_n_days_ago(days: int) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def get_account_summary(conn, days: int) -> dict:
    cutoff = date_n_days_ago(days)
    row = conn.execute("""
        SELECT
            COUNT(DISTINCT ad_id) AS active_ads,
            COALESCE(SUM(spend), 0) AS spend,
            COALESCE(SUM(impressions), 0) AS impressions,
            COALESCE(SUM(clicks), 0) AS clicks,
            COALESCE(SUM(conversions), 0) AS conversions,
            COALESCE(SUM(revenue), 0) AS revenue
        FROM ad_insights WHERE date >= ?
    """, (cutoff,)).fetchone()

    spend = row["spend"] or 0
    clicks = row["clicks"] or 0
    impressions = row["impressions"] or 0
    conversions = row["conversions"] or 0
    revenue = row["revenue"] or 0

    return {
        "active_ads": row["active_ads"] or 0,
        "spend": round(spend, 2),
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conversions,
        "revenue": round(revenue, 2),
        "roas": round(revenue / spend, 2) if spend > 0 else 0,
        "cpa": round(spend / conversions, 2) if conversions > 0 else 0,
        "cpl": round(spend / conversions, 2) if conversions > 0 else 0,
        "ctr": round(clicks / impressions * 100, 2) if impressions > 0 else 0,
    }


def get_daily_spend(conn, days: int) -> pd.DataFrame:
    cutoff = date_n_days_ago(days)
    rows = conn.execute("""
        SELECT date, SUM(spend) AS spend, SUM(conversions) AS conversions,
               SUM(revenue) AS revenue, SUM(clicks) AS clicks, SUM(impressions) AS impressions
        FROM ad_insights WHERE date >= ? GROUP BY date ORDER BY date
    """, (cutoff,)).fetchall()
    if not rows:
        return pd.DataFrame(columns=["date", "spend", "conversions", "revenue"])
    return pd.DataFrame([dict(r) for r in rows])


def get_top_ads(conn, days: int, limit: int = 10) -> pd.DataFrame:
    cutoff = date_n_days_ago(days)
    rows = conn.execute("""
        SELECT i.ad_id, a.name AS ad_name,
            ROUND(SUM(i.spend), 2) AS spend, SUM(i.impressions) AS impressions,
            SUM(i.clicks) AS clicks, SUM(i.conversions) AS conversions,
            ROUND(SUM(i.revenue), 2) AS revenue,
            ROUND(SUM(i.revenue) / NULLIF(SUM(i.spend), 0), 2) AS roas,
            ROUND(SUM(i.spend) / NULLIF(SUM(i.conversions), 0), 2) AS cpa,
            ROUND(SUM(i.clicks) * 100.0 / NULLIF(SUM(i.impressions), 0), 2) AS ctr
        FROM ad_insights i JOIN ads a ON a.ad_id = i.ad_id
        WHERE i.date >= ? GROUP BY i.ad_id HAVING SUM(i.spend) > 0
        ORDER BY roas DESC LIMIT ?
    """, (cutoff, limit)).fetchall()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


def get_rule_executions(conn, days: int = 7) -> pd.DataFrame:
    cutoff = date_n_days_ago(days)
    rows = conn.execute("""
        SELECT rule_name, rule_type, entity_id, action_taken, details, executed_at
        FROM rule_executions WHERE executed_at >= ? ORDER BY executed_at DESC LIMIT 50
    """, (cutoff,)).fetchall()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


def get_campaign_breakdown(conn, days: int) -> pd.DataFrame:
    cutoff = date_n_days_ago(days)
    rows = conn.execute("""
        SELECT c.name AS campaign, c.campaign_type AS type, c.status,
            ROUND(SUM(i.spend), 2) AS spend, SUM(i.conversions) AS conversions,
            ROUND(SUM(i.revenue), 2) AS revenue,
            ROUND(SUM(i.revenue) / NULLIF(SUM(i.spend), 0), 2) AS roas
        FROM ad_insights i JOIN ads a ON a.ad_id = i.ad_id
        JOIN campaigns c ON c.campaign_id = a.campaign_id
        WHERE i.date >= ? GROUP BY c.campaign_id ORDER BY spend DESC
    """, (cutoff,)).fetchall()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# Test connections
# ---------------------------------------------------------------------------

def test_meta_connection(token: str, account_id: str) -> dict:
    """Quick test of Meta API credentials without importing the full SDK."""
    import requests
    try:
        resp = requests.get(
            f"https://graph.facebook.com/v21.0/{account_id}",
            params={
                "access_token": token,
                "fields": "name,account_status,currency,timezone_name",
            },
            timeout=10,
        )
        data = resp.json()
        if "error" in data:
            return {"ok": False, "error": data["error"].get("message", "Unknown error")}
        status_map = {1: "Active", 2: "Disabled", 3: "Unsettled", 7: "Pending Review", 100: "Pending Closure"}
        return {
            "ok": True,
            "name": data.get("name", ""),
            "status": status_map.get(data.get("account_status"), str(data.get("account_status", ""))),
            "currency": data.get("currency", ""),
            "timezone": data.get("timezone_name", ""),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def test_telegram_connection(bot_token: str, chat_id: str) -> dict:
    import requests
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": "Meta Ads Bot connected! You'll receive performance updates here."},
            timeout=10,
        )
        if resp.status_code == 200:
            return {"ok": True}
        return {"ok": False, "error": resp.json().get("description", resp.text[:200])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ===========================================================================
# PAGE: Setup Wizard
# ===========================================================================

def page_setup():
    st.title("Client Setup")
    st.markdown("Fill in the details below to configure a new client. No terminal needed.")

    config = load_client_config()

    # --- Tabs for each section ---
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "1. Business", "2. Meta Ads API", "3. Targets & Budget",
        "4. Telegram", "5. Finish & Connect",
    ])

    # ---- TAB 1: Business ----
    with tab1:
        st.subheader("Business Details")
        biz = config.get("business", {})
        funnel = config.get("funnel", {})

        col1, col2 = st.columns(2)
        with col1:
            biz_name = st.text_input("Business name", value=biz.get("name", ""), placeholder="Acme AI Academy")
            biz_website = st.text_input("Website", value=biz.get("website", ""), placeholder="https://acmeai.com")
        with col2:
            biz_industry = st.selectbox(
                "Industry",
                ["education", "ecommerce", "saas", "agency", "coaching", "real estate", "health", "other"],
                index=0 if not biz.get("industry") else
                    ["education", "ecommerce", "saas", "agency", "coaching", "real estate", "health", "other"].index(biz.get("industry", "education")) if biz.get("industry") in ["education", "ecommerce", "saas", "agency", "coaching", "real estate", "health", "other"] else 0,
            )
            biz_desc = st.text_input("One-line description", value=biz.get("description", ""), placeholder="What does this client sell?")

        st.markdown("---")
        st.subheader("Funnel")

        funnel_options = {
            "Webinar / Live event": "webinar",
            "Lead magnet (free guide, checklist)": "lead_magnet",
            "Direct sale (product page)": "direct_sale",
            "Booking (consultation, demo)": "booking",
            "Free trial (SaaS)": "free_trial",
        }
        funnel_labels = list(funnel_options.keys())
        funnel_values = list(funnel_options.values())
        current_funnel = funnel.get("type", "webinar")
        funnel_idx = funnel_values.index(current_funnel) if current_funnel in funnel_values else 0

        funnel_type = st.selectbox("Funnel type", funnel_labels, index=funnel_idx)
        funnel_type_val = funnel_options[funnel_type]

        cta_defaults = {
            "webinar": ("Save My Spot", "SIGN_UP"),
            "lead_magnet": ("Get Free Guide", "SIGN_UP"),
            "direct_sale": ("Shop Now", "SHOP_NOW"),
            "booking": ("Book a Call", "LEARN_MORE"),
            "free_trial": ("Start Free Trial", "SIGN_UP"),
        }
        default_cta_text, default_cta_type = cta_defaults.get(funnel_type_val, ("Learn More", "LEARN_MORE"))

        col1, col2 = st.columns(2)
        with col1:
            landing_url = st.text_input("Landing page URL", value=funnel.get("landing_page_url", ""), placeholder="https://acmeai.com/webinar")
            offer_name = st.text_input("Offer name", value=funnel.get("offer_name", ""), placeholder="Free 60-min Masterclass")
        with col2:
            cta_text = st.text_input("CTA button text", value=funnel.get("cta_text", default_cta_text))
            offer_price = st.text_input("Offer price (shown in ads)", value=funnel.get("offer_price", "Free"))

        if st.button("Save Business Details", type="primary", key="save_biz"):
            config["business"] = {"name": biz_name, "website": biz_website, "industry": biz_industry, "description": biz_desc}
            config["funnel"] = {
                "type": funnel_type_val, "landing_page_url": landing_url,
                "cta_text": cta_text, "cta_type": default_cta_type,
                "offer_name": offer_name, "offer_price": offer_price,
                "never_show": funnel.get("never_show", ["product prices", "checkout links"]),
            }
            save_client_config(config)
            st.success("Business details saved!")

    # ---- TAB 2: Meta API ----
    with tab2:
        st.subheader("Meta Ads API Credentials")

        st.info(
            "**How to get these credentials:**\n\n"
            "1. Go to **developers.facebook.com** → My Apps → Create App (Business type)\n"
            "2. Add the **Marketing API** product\n"
            "3. Go to **Settings → Basic** to find your **App ID** and **App Secret**\n"
            "4. Go to **Tools → Graph API Explorer**, select your app\n"
            "5. Generate an Access Token with permissions: `ads_management`, `ads_read`\n"
            "6. Find your Ad Account ID in the Ads Manager URL: `act_XXXXXXXXX`\n\n"
            "All credentials are stored locally in `.env` and never shared."
        )

        current_token = read_env_value("META_ACCESS_TOKEN")
        current_account = read_env_value("META_AD_ACCOUNT_ID")
        current_app_id = read_env_value("META_APP_ID")
        current_app_secret = read_env_value("META_APP_SECRET")
        current_page_id = read_env_value("META_PAGE_ID")

        st.markdown("##### Required")
        meta_token = st.text_input(
            "Access Token",
            value=current_token if current_token != "your_access_token" else "",
            type="password",
            placeholder="Paste your Meta access token",
        )
        meta_account = st.text_input(
            "Ad Account ID",
            value=current_account if current_account != "act_your_account_id" else "",
            placeholder="act_123456789",
        )

        st.markdown("##### App Credentials (required by most Meta apps)")
        col_app1, col_app2 = st.columns(2)
        with col_app1:
            meta_app_id = st.text_input(
                "App ID",
                value=current_app_id if current_app_id != "your_app_id" else "",
                placeholder="Settings → Basic → App ID",
            )
        with col_app2:
            meta_app_secret = st.text_input(
                "App Secret",
                value=current_app_secret if current_app_secret != "your_app_secret" else "",
                type="password",
                placeholder="Settings → Basic → App Secret",
            )

        st.markdown("##### Facebook Page (needed for creating/publishing ads)")
        meta_page_id = st.text_input(
            "Page ID",
            value=current_page_id if current_page_id not in ("", None, "your_page_id") else "",
            placeholder="Your Facebook Page ID (from Page → About → Page ID)",
            help="Required only when creating ads. Find it at your Facebook Page → About → Page ID.",
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Save Credentials", type="primary", key="save_meta"):
                if meta_token and meta_account:
                    update_env_value("META_ACCESS_TOKEN", meta_token)
                    update_env_value("META_AD_ACCOUNT_ID", meta_account)
                    if meta_app_id:
                        update_env_value("META_APP_ID", meta_app_id)
                    if meta_app_secret:
                        update_env_value("META_APP_SECRET", meta_app_secret)
                    if meta_page_id:
                        update_env_value("META_PAGE_ID", meta_page_id)
                    st.success("Credentials saved!")
                else:
                    st.warning("Access Token and Ad Account ID are required.")
        with col2:
            if st.button("Test Connection", key="test_meta"):
                if meta_token and meta_account:
                    with st.spinner("Testing Meta API..."):
                        result = test_meta_connection(meta_token, meta_account)
                    if result["ok"]:
                        st.success(f"Connected! Account: **{result['name']}** | Status: {result['status']} | Currency: {result['currency']} | Timezone: {result['timezone']}")
                    else:
                        st.error(f"Connection failed: {result['error']}")
                else:
                    st.warning("Enter your credentials first.")

    # ---- TAB 3: Targets ----
    with tab3:
        st.subheader("Performance Targets & Budget")
        st.markdown("These guardrails control when ads get auto-paused or scaled.")

        targets = config.get("targets", {})

        currency = st.selectbox(
            "Currency",
            ["USD", "EUR", "GBP", "ILS", "CAD", "AUD"],
            index=["USD", "EUR", "GBP", "ILS", "CAD", "AUD"].index(targets.get("currency", "USD")) if targets.get("currency", "USD") in ["USD", "EUR", "GBP", "ILS", "CAD", "AUD"] else 0,
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            cpl = st.number_input("Max cost per lead", value=float(targets.get("cpl", 5.0)), step=1.0, format="%.2f")
            cpa = st.number_input("Max cost per acquisition", value=float(targets.get("cpa", 50.0)), step=5.0, format="%.2f")
        with col2:
            target_roas = st.number_input("Minimum ROAS (e.g. 4.0 = 4x)", value=float(targets.get("target_roas", 4.0)), step=0.5, format="%.1f")
            ctr_min = st.number_input("Minimum CTR %", value=float(targets.get("ctr_min", 1.5)), step=0.5, format="%.1f")
        with col3:
            monthly_budget = st.number_input("Monthly ad budget", value=float(targets.get("monthly_budget", 2000)), step=500.0, format="%.0f")
            daily_cap = st.number_input("Emergency daily cap (auto-pause)", value=float(targets.get("daily_budget_cap", 120)), step=10.0, format="%.0f")

        st.markdown("**Budget Allocation (Hormozi 70/20/10)**")
        split = config.get("budget_split", {})
        bcol1, bcol2, bcol3 = st.columns(3)
        with bcol1:
            scale_pct = st.slider("Scale (proven winners) %", 0, 100, int(split.get("scale", 70)))
        with bcol2:
            iterate_pct = st.slider("Iterate (variations) %", 0, 100, int(split.get("iterate", 20)))
        with bcol3:
            test_pct = st.slider("Test (new concepts) %", 0, 100, int(split.get("test", 10)))

        total = scale_pct + iterate_pct + test_pct
        if total != 100:
            st.warning(f"Budget split adds up to {total}% (should be 100%)")

        if st.button("Save Targets", type="primary", key="save_targets"):
            config["targets"] = {
                "cpl": cpl, "cpa": cpa, "target_roas": target_roas, "ctr_min": ctr_min,
                "monthly_budget": monthly_budget, "daily_budget_cap": daily_cap, "currency": currency,
            }
            config["budget_split"] = {"scale": scale_pct, "iterate": iterate_pct, "test": test_pct}
            save_client_config(config)
            update_env_value("TARGET_CPA", str(cpa))
            update_env_value("TARGET_CPL", str(cpl))
            update_env_value("TARGET_ROAS", str(target_roas))
            update_env_value("MONTHLY_BUDGET", str(monthly_budget))
            update_env_value("CURRENCY", currency)
            st.success("Targets saved!")

    # ---- TAB 4: Telegram ----
    with tab4:
        st.subheader("Telegram Notifications")
        st.markdown("Get hourly ad performance updates on your phone.")

        st.info(
            "**How to set up a Telegram bot (2 minutes):**\n\n"
            "1. Open Telegram and search for **@BotFather**\n"
            "2. Send `/newbot` and follow the prompts\n"
            "3. Copy the **bot token** (looks like `123456789:ABCdef...`)\n"
            "4. Send any message to your new bot\n"
            "5. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`\n"
            "6. Find your **chat ID** in the response"
        )

        notif = config.get("notifications", {})
        tg = notif.get("telegram", {})

        tg_token = st.text_input("Bot token", value=tg.get("bot_token", ""), type="password", placeholder="123456789:ABCdefGHI-jklMNOpqrSTUvwxYZ")
        tg_chat = st.text_input("Chat ID", value=str(tg.get("chat_id", "")), placeholder="Your numeric chat ID")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Save Telegram", type="primary", key="save_tg"):
                notif["telegram"] = {"enabled": bool(tg_token and tg_chat), "bot_token": tg_token, "chat_id": tg_chat}
                config["notifications"] = notif
                save_client_config(config)
                if tg_token:
                    update_env_value("TELEGRAM_BOT_TOKEN", tg_token)
                if tg_chat:
                    update_env_value("TELEGRAM_CHAT_ID", tg_chat)
                st.success("Telegram settings saved!")
        with col2:
            if st.button("Send Test Message", key="test_tg"):
                if tg_token and tg_chat:
                    with st.spinner("Sending..."):
                        result = test_telegram_connection(tg_token, tg_chat)
                    if result["ok"]:
                        st.success("Message sent! Check your Telegram.")
                    else:
                        st.error(f"Failed: {result['error']}")
                else:
                    st.warning("Enter bot token and chat ID first.")

    # ---- TAB 5: Finish ----
    with tab5:
        st.subheader("Finish Setup & Pull Data")

        config = load_client_config()
        biz_name = config.get("business", {}).get("name", "")
        has_token = read_env_value("META_ACCESS_TOKEN") not in ("", "your_access_token")
        has_account = read_env_value("META_AD_ACCOUNT_ID") not in ("", "act_your_account_id")

        st.markdown("### Setup Checklist")
        st.checkbox("Business details filled in", value=bool(biz_name), disabled=True)
        st.checkbox("Meta API connected", value=has_token and has_account, disabled=True)
        st.checkbox("Targets configured", value=bool(config.get("targets", {}).get("cpl")), disabled=True)
        st.checkbox("Telegram (optional)", value=config.get("notifications", {}).get("telegram", {}).get("enabled", False), disabled=True)

        st.markdown("---")

        if biz_name and has_token:
            st.markdown("### Generate Config & Pull Data")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Generate AD_SYSTEM.md", type="secondary", key="gen_ad_system"):
                    try:
                        generate_ad_system(config)
                        st.success("AD_SYSTEM.md generated from your config!")
                    except Exception as e:
                        st.error(f"Error: {e}")

            with col2:
                if st.button("Initialize Database", type="secondary", key="init_db"):
                    try:
                        from data.db import init_db
                        init_db()
                        st.success(f"Database ready at `{DB_PATH}`")
                    except Exception as e:
                        st.error(f"Error: {e}")

            st.markdown("---")

            if st.button("Pull Ad Data from Meta (last 24h)", type="primary", key="pull_data"):
                with st.spinner("Pulling data from Meta API... This may take a minute."):
                    try:
                        from data.db import init_db
                        init_db()

                        from importlib import reload
                        import config.settings
                        reload(config.settings)

                        from api.insights_fetcher import fetch_ad_insights
                        from data.db import save_insights, save_campaign, save_adset, save_ad
                        from data.models import AdInsight, CampaignData, AdSetData, AdData

                        yesterday = (datetime.now(tz=timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
                        raw_rows = fetch_ad_insights(yesterday, yesterday)

                        seen_campaigns, seen_adsets, seen_ads = set(), set(), set()
                        for row in raw_rows:
                            cid = row.get("campaign_id", "")
                            asid = row.get("adset_id", "")
                            aid = row.get("ad_id", "")
                            if cid and cid not in seen_campaigns:
                                save_campaign(CampaignData(campaign_id=cid, name=row.get("campaign_name", cid)))
                                seen_campaigns.add(cid)
                            if asid and asid not in seen_adsets:
                                save_adset(AdSetData(adset_id=asid, campaign_id=cid, name=row.get("adset_name", asid)))
                                seen_adsets.add(asid)
                            if aid and aid not in seen_ads:
                                save_ad(AdData(ad_id=aid, adset_id=asid, campaign_id=cid, name=row.get("ad_name", aid)))
                                seen_ads.add(aid)

                        insights = [AdInsight(
                            ad_id=row.get("ad_id", ""), date=row.get("date_start", ""),
                            spend=row.get("spend", 0), impressions=int(row.get("impressions", 0)),
                            reach=int(row.get("reach", 0)), frequency=row.get("frequency", 0),
                            clicks=int(row.get("clicks", 0)), ctr=row.get("ctr", 0),
                            cpc=row.get("cpc", 0), cpm=row.get("cpm", 0),
                            conversions=int(row.get("conversions", 0)), cpa=row.get("cpa", 0),
                            revenue=row.get("purchase_value", 0), roas=row.get("roas", 0),
                        ) for row in raw_rows]

                        if insights:
                            save_insights(insights)

                        st.success(f"Pulled **{len(insights)}** rows. Go to the **Dashboard** tab to see your data!")
                    except Exception as e:
                        st.error(f"Error pulling data: {e}")
                        st.info("Make sure your Meta API credentials are correct (Tab 2).")
        else:
            missing = []
            if not biz_name:
                missing.append("Business name (Tab 1)")
            if not has_token:
                missing.append("Meta API token (Tab 2)")
            st.warning(f"Complete these first: {', '.join(missing)}")


# ===========================================================================
# PAGE: Dashboard
# ===========================================================================

def page_dashboard():
    config = load_client_config()
    biz_name = config.get("business", {}).get("name", "Meta Ads")
    targets = config.get("targets", {})
    currency = targets.get("currency", "USD")
    sym = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "ILS": "\u20aa"}.get(currency, currency + " ")

    st.title(f"{biz_name} -- Ad Performance")

    if not DB_PATH.exists():
        st.warning("No data yet. Go to **Setup** and pull data from Meta.")
        st.stop()

    conn = get_db()

    # Check if there's any data
    row_count = conn.execute("SELECT COUNT(*) as cnt FROM ad_insights").fetchone()["cnt"]
    if row_count == 0:
        st.warning("Database is empty. Go to **Setup > Tab 5** and click 'Pull Ad Data from Meta'.")
        conn.close()
        st.stop()

    # Sidebar
    st.sidebar.header("Settings")
    days = st.sidebar.selectbox("Time range", [1, 3, 7, 14, 30], index=2, format_func=lambda d: f"Last {d} days")

    target_cpl = targets.get("cpl", 5.0)
    target_roas = targets.get("target_roas", 4.0)

    # --- KPI Row ---
    summary = get_account_summary(conn, days)

    st.markdown("### Key Metrics")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Spend", f"{sym}{summary['spend']:,.2f}")
    c2.metric("Revenue", f"{sym}{summary['revenue']:,.2f}")
    c3.metric(
        "ROAS", f"{summary['roas']:.2f}x",
        delta=f"{'above' if summary['roas'] >= target_roas else 'below'} {target_roas}x target",
        delta_color="normal" if summary['roas'] >= target_roas else "inverse",
    )
    c4.metric(
        "CPL", f"{sym}{summary['cpl']:,.2f}",
        delta=f"{'under' if summary['cpl'] <= target_cpl else 'over'} {sym}{target_cpl} target",
        delta_color="normal" if summary['cpl'] <= target_cpl or summary['cpl'] == 0 else "inverse",
    )
    c5.metric("Conversions", f"{summary['conversions']:,}")
    c6.metric("Active Ads", f"{summary['active_ads']}")

    st.divider()

    # --- Charts ---
    daily = get_daily_spend(conn, days)
    if not daily.empty:
        col_left, col_right = st.columns(2)
        with col_left:
            st.markdown("### Daily Spend")
            st.area_chart(daily.set_index("date")[["spend"]], color="#4CAF50")
        with col_right:
            st.markdown("### Daily Conversions")
            st.bar_chart(daily.set_index("date")[["conversions"]], color="#2196F3")

    st.divider()

    # --- Campaign Breakdown ---
    campaigns_df = get_campaign_breakdown(conn, days)
    if not campaigns_df.empty:
        st.markdown("### Campaign Breakdown")
        st.dataframe(campaigns_df, use_container_width=True, hide_index=True, column_config={
            "spend": st.column_config.NumberColumn(f"Spend ({currency})", format="%.2f"),
            "revenue": st.column_config.NumberColumn(f"Revenue ({currency})", format="%.2f"),
            "roas": st.column_config.NumberColumn("ROAS", format="%.2fx"),
        })

    st.divider()

    # --- Top Ads ---
    top = get_top_ads(conn, days)
    if not top.empty:
        st.markdown("### Top Performing Ads")
        st.dataframe(top, use_container_width=True, hide_index=True, column_config={
            "ad_id": st.column_config.TextColumn("Ad ID", width="small"),
            "ad_name": st.column_config.TextColumn("Ad Name", width="large"),
            "spend": st.column_config.NumberColumn(f"Spend ({currency})", format="%.2f"),
            "revenue": st.column_config.NumberColumn(f"Revenue ({currency})", format="%.2f"),
            "roas": st.column_config.NumberColumn("ROAS", format="%.2fx"),
            "cpa": st.column_config.NumberColumn(f"CPA ({currency})", format="%.2f"),
            "ctr": st.column_config.NumberColumn("CTR %", format="%.2f"),
        })

    st.divider()

    # --- Rule Executions ---
    rules_df = get_rule_executions(conn, days)
    if not rules_df.empty:
        st.markdown("### Automated Actions")
        kill_count = len(rules_df[rules_df["rule_type"] == "kill"])
        scale_count = len(rules_df[rules_df["rule_type"] == "scale"])
        alert_count = len(rules_df[rules_df["rule_type"] == "alert"])
        rc1, rc2, rc3 = st.columns(3)
        rc1.metric("Ads Killed", kill_count)
        rc2.metric("Scale Signals", scale_count)
        rc3.metric("Alerts", alert_count)
        st.dataframe(rules_df, use_container_width=True, hide_index=True)
    else:
        st.markdown("### Automated Actions")
        st.info("No automated actions yet. Rules run hourly via the daily pipeline.")

    # --- Sidebar targets ---
    st.sidebar.divider()
    st.sidebar.markdown("### Targets")
    st.sidebar.write(f"CPL target: {sym}{target_cpl}")
    st.sidebar.write(f"ROAS target: {target_roas}x")
    st.sidebar.write(f"Monthly budget: {sym}{targets.get('monthly_budget', 0):,.0f}")

    conn.close()


# ===========================================================================
# Main: Navigation
# ===========================================================================

def main():
    st.set_page_config(
        page_title="Meta Ads Manager",
        page_icon="📊",
        layout="wide",
    )

    # Navigation
    setup_done = is_setup_complete()

    if setup_done:
        page = st.sidebar.radio("Navigation", ["Dashboard", "Setup"], index=0)
    else:
        page = st.sidebar.radio("Navigation", ["Setup", "Dashboard"], index=0)

    if page == "Setup":
        page_setup()
    else:
        page_dashboard()


if __name__ == "__main__":
    main()
