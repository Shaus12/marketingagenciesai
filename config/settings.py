"""
Core settings for the Meta Ads Management System.
All values are loaded from .env or can be overridden here.
"""

import os
from dotenv import load_dotenv

load_dotenv()


# --- Meta Marketing API ---
META_APP_ID = os.getenv("META_APP_ID", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "")  # format: act_123456

# --- Supabase ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# --- Anthropic ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# --- Slack ---
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# --- Email ---
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")

# --- Database ---
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ads.db")

# --- Business Targets (FILL THESE IN) ---
# YourBrand.ai — AI product building platform
# Products: Free Webinar → Box (€297) → Pro Program (€497-997) → 1-on-1 (€2K-5K)
TARGET_CPA = float(os.getenv("TARGET_CPA", "50.0"))        # Max cost per acquisition (Pro sale)
TARGET_CPL = float(os.getenv("TARGET_CPL", "5.0"))          # Max cost per webinar lead
TARGET_ROAS = float(os.getenv("TARGET_ROAS", "4.0"))        # Minimum acceptable ROAS
MONTHLY_BUDGET = float(os.getenv("MONTHLY_BUDGET", "2000"))  # Starting monthly ad spend
CURRENCY = os.getenv("CURRENCY", "EUR")

# --- Budget Allocation (Hormozi 70/20/10) ---
SCALE_BUDGET_PCT = 0.70    # Proven winners
ITERATE_BUDGET_PCT = 0.20  # Adjacent variations
TEST_BUDGET_PCT = 0.10     # Wild new concepts

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
