"""
Core settings for the Meta Ads Management System.

Loads from two sources (in priority order):
  1. client_config.yaml — business/funnel/target configuration
  2. .env — API keys and credentials (never committed)
"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

# --- Load client config if it exists ---
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "client_config.yaml"
_CLIENT_CONFIG: dict = {}

if _CONFIG_PATH.exists():
    _CLIENT_CONFIG = yaml.safe_load(_CONFIG_PATH.read_text()) or {}


def _cfg(section: str, key: str, default=""):
    """Read a value from client_config.yaml nested sections."""
    return _CLIENT_CONFIG.get(section, {}).get(key, default)


# --- Meta Marketing API (always from .env) ---
META_APP_ID = os.getenv("META_APP_ID", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "")  # format: act_123456
META_PAGE_ID = os.getenv("META_PAGE_ID", "")
META_PAGE_ACCESS_TOKEN = os.getenv("META_PAGE_ACCESS_TOKEN", "")

# --- Supabase ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# --- Kie.ai ---
KIE_AI_API_KEY = os.getenv("KIE_AI_API_KEY", "")

# --- Telegram (config yaml > .env) ---
TELEGRAM_BOT_TOKEN = (
    _cfg("notifications", "telegram") and _CLIENT_CONFIG.get("notifications", {}).get("telegram", {}).get("bot_token")
) or os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = (
    _cfg("notifications", "telegram") and _CLIENT_CONFIG.get("notifications", {}).get("telegram", {}).get("chat_id")
) or os.getenv("TELEGRAM_CHAT_ID", "")

# --- Echoes App ---
ECHOES_FB_APP_ID = os.getenv("ECHOES_FB_APP_ID", "")

# --- Slack ---
SLACK_WEBHOOK_URL = (
    _CLIENT_CONFIG.get("notifications", {}).get("slack", {}).get("webhook_url")
) or os.getenv("SLACK_WEBHOOK_URL", "")

# --- Email ---
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_TO = (
    _CLIENT_CONFIG.get("notifications", {}).get("email", {}).get("to")
) or os.getenv("EMAIL_TO", "")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")

# --- Database ---
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ads.db")

# --- Business Targets (client_config.yaml > .env > defaults) ---
TARGET_CPA = float(_cfg("targets", "cpa", 0) or os.getenv("TARGET_CPA", "50.0"))
TARGET_CPL = float(_cfg("targets", "cpl", 0) or os.getenv("TARGET_CPL", "5.0"))
TARGET_ROAS = float(_cfg("targets", "target_roas", 0) or os.getenv("TARGET_ROAS", "4.0"))
MONTHLY_BUDGET = float(_cfg("targets", "monthly_budget", 0) or os.getenv("MONTHLY_BUDGET", "2000"))
CURRENCY = _cfg("targets", "currency", "") or os.getenv("CURRENCY", "USD")
DAILY_BUDGET_CAP = float(_cfg("targets", "daily_budget_cap", 0) or os.getenv("DAILY_BUDGET_CAP", "120"))

# --- Budget Allocation (client_config.yaml > defaults) ---
_budget_split = _CLIENT_CONFIG.get("budget_split", {})
SCALE_BUDGET_PCT = (_budget_split.get("scale", 70) or 70) / 100
ITERATE_BUDGET_PCT = (_budget_split.get("iterate", 20) or 20) / 100
TEST_BUDGET_PCT = (_budget_split.get("test", 10) or 10) / 100

# --- Business Info (from client config) ---
BUSINESS_NAME = _cfg("business", "name", "")
LANDING_PAGE_URL = _cfg("funnel", "landing_page_url", "")
CTA_TYPE = _cfg("funnel", "cta_type", "SIGN_UP")

# --- Supabase Table Mapping (YourBrand) ---
SUPABASE_TABLES = {
    # Community content
    "posts": os.getenv("SUPABASE_TABLE_POSTS", "community_posts"),
    "comments": os.getenv("SUPABASE_TABLE_COMMENTS", "community_comments"),
    "post_likes": os.getenv("SUPABASE_TABLE_POST_LIKES", "community_post_likes"),
    "discussions": os.getenv("SUPABASE_TABLE_DISCUSSIONS", "lesson_discussions"),

    # User data
    "users": os.getenv("SUPABASE_TABLE_USERS", "profiles"),
    "user_roles": os.getenv("SUPABASE_TABLE_USER_ROLES", "user_roles"),

    # Products & purchases
    "boxes": os.getenv("SUPABASE_TABLE_BOXES", "boxes"),
    "box_purchases": os.getenv("SUPABASE_TABLE_BOX_PURCHASES", "box_purchases"),
    "course_purchases": os.getenv("SUPABASE_TABLE_COURSE_PURCHASES", "course_purchases"),
    "custom_deals": os.getenv("SUPABASE_TABLE_CUSTOM_DEALS", "custom_deals"),

    # Content
    "videos": os.getenv("SUPABASE_TABLE_VIDEOS", "videos"),
    "free_content": os.getenv("SUPABASE_TABLE_FREE_CONTENT", "free_content"),
    "course_modules": os.getenv("SUPABASE_TABLE_COURSE_MODULES", "course_modules"),
    "course_lessons": os.getenv("SUPABASE_TABLE_COURSE_LESSONS", "course_lessons"),

    # Testimonials & proof
    "testimonials": os.getenv("SUPABASE_TABLE_TESTIMONIALS", "testimonials"),
    "text_testimonials": os.getenv("SUPABASE_TABLE_TEXT_TESTIMONIALS", "text_testimonials"),

    # Funnel & tracking
    "free_signups": os.getenv("SUPABASE_TABLE_FREE_SIGNUPS", "free_signup_tracking"),
    "abandoned_signups": os.getenv("SUPABASE_TABLE_ABANDONED", "abandoned_signup_tracking"),
    "page_visits": os.getenv("SUPABASE_TABLE_VISITS", "page_visits"),
    "email_sequence": os.getenv("SUPABASE_TABLE_EMAIL_SEQ", "free_signup_email_sequence"),

    # Accelerator
    "accelerator_forms": os.getenv("SUPABASE_TABLE_ACCEL_FORMS", "accelerator_form_starts"),
    "accelerator_sessions": os.getenv("SUPABASE_TABLE_ACCEL_SESSIONS", "accelerator_sessions"),

    # Community products & engagement
    "community_products": os.getenv("SUPABASE_TABLE_COMMUNITY_PRODUCTS", "community_products"),
    "playbook_submissions": os.getenv("SUPABASE_TABLE_PLAYBOOK", "playbook_submissions"),
}

# --- Timing ---
DATA_PULL_HOUR = 6          # Hour (24h) to run daily data pull
REPORT_HOUR = 7             # Hour (24h) to send daily report
COMMUNITY_PULSE_DAY = 0     # Day of week for community pulse (0=Monday)
BACKFILL_DAYS = 90          # Days of historical data to pull on first run
