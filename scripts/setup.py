"""
Client onboarding wizard for the Meta Ads Automation System.

Walks an agency through the complete setup for a new client:
  1. Business details (name, website, funnel)
  2. Meta API connection (with step-by-step instructions)
  3. Telegram notifications (with bot creation guide)
  4. Performance targets & budget
  5. Auto-generates AD_SYSTEM.md from client config
  6. Tests all connections
  7. Initialises the database

Usage::

    # Interactive wizard (recommended for first-time setup)
    python -m scripts.setup

    # Re-generate AD_SYSTEM.md from existing client_config.yaml
    python -m scripts.setup --from-config

    # Skip connection tests (offline setup)
    python -m scripts.setup --skip-tests
"""

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt, IntPrompt, FloatPrompt
from rich.table import Table
from rich.rule import Rule
from rich.text import Text

logger = logging.getLogger(__name__)
console = Console()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
_ENV_EXAMPLE = _PROJECT_ROOT / ".env.example"
_CONFIG_FILE = _PROJECT_ROOT / "client_config.yaml"
_AD_SYSTEM_FILE = _PROJECT_ROOT / "AD_SYSTEM.md"


# ======================================================================
# .env helpers
# ======================================================================

def _read_env_value(key: str) -> str:
    if not _ENV_FILE.exists():
        return ""
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip()
    return ""


def _update_env_value(key: str, value: str) -> None:
    lines = _ENV_FILE.read_text().splitlines() if _ENV_FILE.exists() else []
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
    _ENV_FILE.write_text("\n".join(new_lines) + "\n")


def _ensure_env_file() -> None:
    if _ENV_FILE.exists():
        return
    if _ENV_EXAMPLE.exists():
        shutil.copy(_ENV_EXAMPLE, _ENV_FILE)
    else:
        _ENV_FILE.touch()


def _load_config() -> Dict[str, Any]:
    if _CONFIG_FILE.exists():
        return yaml.safe_load(_CONFIG_FILE.read_text()) or {}
    return {}


def _save_config(config: Dict[str, Any]) -> None:
    _CONFIG_FILE.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))


# ======================================================================
# Step 1: Welcome
# ======================================================================

def _step_welcome() -> None:
    console.print()
    console.print(Panel(
        "[bold white]Meta Ads Automation System[/bold white]\n"
        "[dim]Client Onboarding Wizard[/dim]\n\n"
        "This wizard will walk you through setting up a new client.\n"
        "It takes about 5 minutes. You'll need:\n\n"
        "  1. A Meta (Facebook) Ads account\n"
        "  2. A Meta Developer App (we'll help you create one)\n"
        "  3. Optionally: a Telegram account for notifications\n",
        border_style="cyan",
        title="Welcome",
    ))


# ======================================================================
# Step 2: Business Details
# ======================================================================

def _step_business(config: Dict[str, Any]) -> Dict[str, Any]:
    console.print(Rule("[bold cyan]Step 1: Business Details[/bold cyan]"))
    console.print("[dim]Tell us about your client's business.[/dim]\n")

    biz = config.get("business", {})
    biz["name"] = Prompt.ask(
        "  Business name",
        default=biz.get("name", ""),
    )
    biz["website"] = Prompt.ask(
        "  Website URL",
        default=biz.get("website", ""),
    )
    biz["industry"] = Prompt.ask(
        "  Industry [dim](education/ecommerce/saas/agency/other)[/dim]",
        default=biz.get("industry", ""),
    )
    biz["description"] = Prompt.ask(
        "  One-line description [dim](what does this client sell?)[/dim]",
        default=biz.get("description", ""),
    )
    config["business"] = biz

    # Funnel
    console.print("\n[bold]Funnel Setup:[/bold]")
    funnel = config.get("funnel", {})

    funnel_types = {
        "1": "webinar",
        "2": "lead_magnet",
        "3": "direct_sale",
        "4": "booking",
        "5": "free_trial",
    }
    console.print("  [dim]What type of funnel?[/dim]")
    console.print("    1. Webinar / Live event")
    console.print("    2. Lead magnet (free guide, checklist, etc.)")
    console.print("    3. Direct sale (product/service page)")
    console.print("    4. Booking (consultation, demo call)")
    console.print("    5. Free trial (SaaS)")

    current_type = funnel.get("type", "webinar")
    current_num = next(
        (k for k, v in funnel_types.items() if v == current_type), "1"
    )
    choice = Prompt.ask("  Choice", default=current_num, choices=list(funnel_types.keys()))
    funnel["type"] = funnel_types[choice]

    funnel["landing_page_url"] = Prompt.ask(
        "  Landing page URL [dim](where do ads send traffic?)[/dim]",
        default=funnel.get("landing_page_url", ""),
    )

    cta_map = {
        "webinar": ("Save My Spot", "SIGN_UP"),
        "lead_magnet": ("Get Free Guide", "SIGN_UP"),
        "direct_sale": ("Shop Now", "SHOP_NOW"),
        "booking": ("Book a Call", "LEARN_MORE"),
        "free_trial": ("Start Free Trial", "SIGN_UP"),
    }
    default_cta, default_cta_type = cta_map.get(funnel["type"], ("Learn More", "LEARN_MORE"))

    funnel["cta_text"] = Prompt.ask(
        "  CTA button text",
        default=funnel.get("cta_text", default_cta),
    )
    funnel["cta_type"] = default_cta_type
    funnel["offer_name"] = Prompt.ask(
        "  Offer name [dim](what are you promoting in the ads?)[/dim]",
        default=funnel.get("offer_name", ""),
    )
    funnel["offer_price"] = Prompt.ask(
        "  Offer price shown in ads [dim](e.g. 'Free', '$49')[/dim]",
        default=funnel.get("offer_price", "Free"),
    )

    config["funnel"] = funnel
    console.print("  [green]Business details saved.[/green]\n")
    return config


# ======================================================================
# Step 3: Meta API
# ======================================================================

def _step_meta(config: Dict[str, Any]) -> Dict[str, Any]:
    console.print(Rule("[bold cyan]Step 2: Meta Ads API[/bold cyan]"))

    token = _read_env_value("META_ACCESS_TOKEN")
    account_id = _read_env_value("META_AD_ACCOUNT_ID")

    if token and account_id:
        console.print(f"  [green]Already configured:[/green]")
        console.print(f"    Account: {account_id}")
        console.print(f"    Token:   ...{token[-8:]}")
        if not Confirm.ask("  Re-configure Meta API?", default=False):
            return config

    console.print(Panel(
        "[bold]How to get your Meta API credentials:[/bold]\n\n"
        "1. Go to [cyan]developers.facebook.com[/cyan]\n"
        "2. Click 'My Apps' -> 'Create App'\n"
        "3. Choose 'Other' -> 'Business' type\n"
        "4. Add the 'Marketing API' product\n"
        "5. Go to Tools -> Graph API Explorer\n"
        "6. Select your app, then click 'Generate Access Token'\n"
        "7. Select permissions: ads_management, ads_read, pages_read_engagement\n"
        "8. Click 'Generate Access Token' and copy it\n\n"
        "[bold]To find your Ad Account ID:[/bold]\n"
        "  Go to Meta Ads Manager -> look in the URL for 'act_XXXXXXXXX'\n"
        "  Or: Business Settings -> Ad Accounts\n",
        border_style="yellow",
        title="Meta API Setup Guide",
    ))

    new_token = Prompt.ask("  META_ACCESS_TOKEN [dim](paste your token)[/dim]")
    new_account = Prompt.ask("  META_AD_ACCOUNT_ID [dim](e.g. act_123456789)[/dim]")

    if new_token:
        _update_env_value("META_ACCESS_TOKEN", new_token)
    if new_account:
        _update_env_value("META_AD_ACCOUNT_ID", new_account)

    page_id = Prompt.ask(
        "  META_PAGE_ID [dim](optional, press Enter to skip)[/dim]",
        default="",
    )
    if page_id:
        _update_env_value("META_PAGE_ID", page_id)

    app_id = Prompt.ask(
        "  META_APP_ID [dim](optional, for token refresh)[/dim]",
        default="",
    )
    app_secret = Prompt.ask(
        "  META_APP_SECRET [dim](optional, for token refresh)[/dim]",
        default="",
    )
    if app_id:
        _update_env_value("META_APP_ID", app_id)
    if app_secret:
        _update_env_value("META_APP_SECRET", app_secret)

    console.print("  [green]Meta credentials saved.[/green]\n")
    return config


# ======================================================================
# Step 4: Telegram
# ======================================================================

def _step_telegram(config: Dict[str, Any]) -> Dict[str, Any]:
    console.print(Rule("[bold cyan]Step 3: Telegram Notifications[/bold cyan]"))
    console.print("[dim]Get hourly ad performance updates on your phone.[/dim]\n")

    notif = config.get("notifications", {})
    tg = notif.get("telegram", {})

    if not Confirm.ask("  Set up Telegram notifications?", default=True):
        tg["enabled"] = False
        notif["telegram"] = tg
        config["notifications"] = notif
        console.print("  [dim]Skipped. You can set this up later.[/dim]\n")
        return config

    console.print(Panel(
        "[bold]How to create a Telegram bot (2 minutes):[/bold]\n\n"
        "1. Open Telegram and search for [cyan]@BotFather[/cyan]\n"
        "2. Send [cyan]/newbot[/cyan]\n"
        "3. Choose a name (e.g. 'Acme Ads Bot')\n"
        "4. Choose a username (e.g. 'acme_ads_bot')\n"
        "5. BotFather gives you a token like:\n"
        "   [green]123456789:ABCdefGHI-jklMNOpqrSTUvwxYZ[/green]\n"
        "6. Copy that token\n\n"
        "[bold]To get your Chat ID:[/bold]\n"
        "1. Send any message to your new bot\n"
        "2. Open: [cyan]https://api.telegram.org/bot<TOKEN>/getUpdates[/cyan]\n"
        "3. Find 'chat':{'id': [green]YOUR_CHAT_ID[/green]}\n",
        border_style="yellow",
        title="Telegram Setup Guide",
    ))

    bot_token = Prompt.ask("  Bot token")
    chat_id = Prompt.ask("  Chat ID")

    if bot_token and chat_id:
        tg["enabled"] = True
        tg["bot_token"] = bot_token
        tg["chat_id"] = chat_id
        _update_env_value("TELEGRAM_BOT_TOKEN", bot_token)
        _update_env_value("TELEGRAM_CHAT_ID", chat_id)
        console.print("  [green]Telegram configured.[/green]\n")
    else:
        tg["enabled"] = False
        console.print("  [yellow]Incomplete — Telegram disabled.[/yellow]\n")

    notif["telegram"] = tg
    config["notifications"] = notif
    return config


# ======================================================================
# Step 5: Performance Targets
# ======================================================================

def _step_targets(config: Dict[str, Any]) -> Dict[str, Any]:
    console.print(Rule("[bold cyan]Step 4: Performance Targets & Budget[/bold cyan]"))
    console.print("[dim]Set the guardrails for automated ad management.[/dim]\n")

    targets = config.get("targets", {})

    currencies = {"1": "USD", "2": "EUR", "3": "GBP", "4": "ILS", "5": "other"}
    console.print("  Currency: 1=USD  2=EUR  3=GBP  4=ILS  5=Other")
    current_currency = targets.get("currency", "USD")
    default_choice = next(
        (k for k, v in currencies.items() if v == current_currency), "1"
    )
    c_choice = Prompt.ask("  Choice", default=default_choice)
    if c_choice == "5":
        targets["currency"] = Prompt.ask("  Enter currency code (e.g. CAD, AUD)")
    else:
        targets["currency"] = currencies.get(c_choice, "USD")

    sym = targets["currency"]

    targets["cpl"] = float(Prompt.ask(
        f"  Max cost per lead ({sym})",
        default=str(targets.get("cpl", 5.0)),
    ))
    targets["cpa"] = float(Prompt.ask(
        f"  Max cost per acquisition/sale ({sym})",
        default=str(targets.get("cpa", 50.0)),
    ))
    targets["target_roas"] = float(Prompt.ask(
        "  Minimum ROAS (e.g. 4.0 = 4x return)",
        default=str(targets.get("target_roas", 4.0)),
    ))
    targets["monthly_budget"] = float(Prompt.ask(
        f"  Monthly ad budget ({sym})",
        default=str(targets.get("monthly_budget", 2000)),
    ))
    targets["daily_budget_cap"] = float(Prompt.ask(
        f"  Emergency daily cap ({sym}) [dim](auto-pause if exceeded)[/dim]",
        default=str(targets.get("daily_budget_cap", 120)),
    ))

    config["targets"] = targets

    # Save to .env too
    _update_env_value("TARGET_CPL", str(targets["cpl"]))
    _update_env_value("TARGET_CPA", str(targets["cpa"]))
    _update_env_value("TARGET_ROAS", str(targets["target_roas"]))
    _update_env_value("MONTHLY_BUDGET", str(targets["monthly_budget"]))
    _update_env_value("CURRENCY", targets["currency"])

    console.print("  [green]Targets saved.[/green]\n")
    return config


# ======================================================================
# Step 6: AI API Key
# ======================================================================

def _step_ai_key(config: Dict[str, Any]) -> Dict[str, Any]:
    console.print(Rule("[bold cyan]Step 5: AI Configuration[/bold cyan]"))
    console.print("[dim]Required for creative generation and ad analysis.[/dim]\n")

    anthropic_key = _read_env_value("ANTHROPIC_API_KEY")
    if anthropic_key and anthropic_key != "sk-ant-your-key":
        console.print(f"  [green]Anthropic API key configured:[/green] ...{anthropic_key[-8:]}")
        if not Confirm.ask("  Update it?", default=False):
            return config

    console.print(Panel(
        "[bold]Get your Anthropic API key:[/bold]\n\n"
        "1. Go to [cyan]console.anthropic.com[/cyan]\n"
        "2. Sign up or log in\n"
        "3. Go to API Keys -> Create Key\n"
        "4. Copy the key (starts with sk-ant-)\n",
        border_style="yellow",
        title="Anthropic API Setup",
    ))

    key = Prompt.ask("  ANTHROPIC_API_KEY [dim](paste your key)[/dim]", default="")
    if key:
        _update_env_value("ANTHROPIC_API_KEY", key)
        console.print("  [green]API key saved.[/green]\n")
    else:
        console.print("  [dim]Skipped. Creative generation won't work without this.[/dim]\n")

    return config


# ======================================================================
# Step 7: Generate AD_SYSTEM.md
# ======================================================================

def _generate_ad_system(config: Dict[str, Any]) -> None:
    """Auto-generate AD_SYSTEM.md from client_config.yaml."""
    biz = config.get("business", {})
    funnel = config.get("funnel", {})
    audience = config.get("audience", {})
    targets = config.get("targets", {})
    brand = config.get("brand", {})
    angles = config.get("ad_angles", [])
    proof = config.get("proof_points", [])
    campaigns = config.get("campaigns", {})
    adsets = config.get("adsets", {})

    biz_name = biz.get("name", "Your Business")
    currency = targets.get("currency", "USD")
    sym = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "ILS": "\u20aa"}.get(currency, currency + " ")
    landing = funnel.get("landing_page_url", "https://yourdomain.com")
    cta_text = funnel.get("cta_text", "Sign Up")
    cta_type = funnel.get("cta_type", "SIGN_UP")
    offer = funnel.get("offer_name", "our offer")
    funnel_type = funnel.get("type", "webinar")
    never_show = funnel.get("never_show", ["product prices", "checkout links"])

    # Build funnel diagram based on type
    funnel_diagrams = {
        "webinar": f"""```
Meta Ads (cold traffic)
    |
{offer} ({landing})
    |
Live Webinar / Event
    |
Offer reveal + conversion
    |
Post-event email nurture
    |
Paid product
```""",
        "lead_magnet": f"""```
Meta Ads (cold traffic)
    |
{offer} ({landing})
    |
Email nurture sequence
    |
Sales page / offer
    |
Conversion
```""",
        "direct_sale": f"""```
Meta Ads (cold traffic)
    |
Product page ({landing})
    |
Add to cart / Purchase
```""",
        "booking": f"""```
Meta Ads (cold traffic)
    |
{offer} ({landing})
    |
Booking / consultation call
    |
Close deal
```""",
        "free_trial": f"""```
Meta Ads (cold traffic)
    |
{offer} ({landing})
    |
Free trial signup
    |
Onboarding + upgrade
```""",
    }

    funnel_diagram = funnel_diagrams.get(funnel_type, funnel_diagrams["lead_magnet"])

    # Audience table
    segments = audience.get("segments", [])
    segment_rows = ""
    for seg in segments:
        segment_rows += (
            f"| {seg.get('name', '')} | {seg.get('percentage', 0)}% | "
            f"Age {seg.get('age_min', 25)}-{seg.get('age_max', 45)}, "
            f"{seg.get('description', '')} |\n"
        )

    countries = ", ".join(audience.get("countries", ["US"]))
    excluded = ", ".join(audience.get("excluded_countries", [])) or "None"
    placements = ", ".join(audience.get("placements", ["feeds"]))

    # Angles table
    angle_rows = ""
    for i, angle in enumerate(angles, 1):
        angle_rows += (
            f"| {i} | {angle.get('name', '')} | "
            f"{angle.get('hook', '')} | {angle.get('why_it_works', '')} |\n"
        )

    # Proof points
    proof_lines = "\n".join(f"- {p}" for p in proof) if proof else "- (Add your proof points)"

    # Never show rules
    never_lines = "\n".join(f"- Do NOT show {n} in ads" for n in never_show)

    # Colors
    colors = brand.get("colors", {})
    bg = colors.get("background", "#0a0a0a")
    accent = colors.get("accent", "#c8ff00")
    text_color = colors.get("text", "#ffffff")

    content = f"""# Ad System -- Source of Truth for {biz_name}

This file is auto-generated from `client_config.yaml`.
To update, edit client_config.yaml and run: `python -m scripts.setup --from-config`

---

## 1. The Funnel

{funnel_diagram}

### Rules
{never_lines}
- The CTA is always "{cta_text}"
- The CTA type in Meta is: `{cta_type}`
- The link is always: `{landing}`

---

## 2. Target Audience

| Segment | % of Spend | Profile |
|---------|-----------|---------|
{segment_rows}
### Geographic Targeting
- Primary: {countries}
- Excluded: {excluded}
- Placements: {placements}

---

## 3. Brand Design System

| Element | Value |
|---------|-------|
| Background | `{bg}` |
| Accent | `{accent}` |
| Text | `{text_color}` |
| Font | {brand.get('font_style', 'Bold sans-serif')} |
| Visual feel | {brand.get('visual_feel', 'Clean and professional')} |

### Creative Restrictions
{"".join(chr(10) + '- ' + r for r in brand.get('creative_restrictions', []))}

---

## 4. Ad Copy Structure

| Field | Rules |
|-------|-------|
| **Primary Text** | 3-8 lines, ends with CTA link |
| **Headline** | Short, punchy, under 40 chars |
| **Description** | Short value prop |
| **CTA Button** | `{cta_type}` |
| **URL** | `{landing}` |

---

## 5. Proven Ad Angles

| # | Angle | Hook | Why It Works |
|---|-------|------|-------------|
{angle_rows}
---

## 6. Performance Targets

| Metric | Target |
|--------|--------|
| CPL (Cost Per Lead) | {sym}{targets.get('cpl', 5):.0f} |
| CPA (Cost Per Acquisition) | {sym}{targets.get('cpa', 50):.0f} |
| Target ROAS | {targets.get('target_roas', 4.0):.1f}x |
| CTR minimum | {targets.get('ctr_min', 1.5):.1f}% |
| Monthly Budget | {sym}{targets.get('monthly_budget', 2000):,.0f} |
| Daily Cap | {sym}{targets.get('daily_budget_cap', 120):,.0f} |

### Budget Allocation (70/20/10)
- **70% Scale**: Proven winners
- **20% Iterate**: Variations of winners
- **10% Test**: New concepts

---

## 7. Campaign Structure in Meta

| Campaign | ID | Purpose |
|----------|-----|---------|
| Scale | `{campaigns.get('scale', 'TBD')}` | Proven winners |
| Iterate | `{campaigns.get('iterate', 'TBD')}` | Variations |
| Test | `{campaigns.get('test', 'TBD')}` | New concepts |
| Retarget | `{campaigns.get('retarget', 'TBD')}` | Retargeting |

---

## 8. Credibility / Proof Points

{proof_lines}

---

## 9. Quality Gate (before pushing to Meta)

1. Typo check -- read every word in generated images
2. URL check -- must link to `{landing}`
3. CTA check -- must be `{cta_type}`
4. Brand check -- image uses brand template
5. Show the user -- always get approval before publishing

---

*Auto-generated from client_config.yaml*
"""

    _AD_SYSTEM_FILE.write_text(content)


# ======================================================================
# Step 8: Test connections
# ======================================================================

def _step_test_meta() -> bool:
    console.print(Rule("[bold cyan]Testing: Meta API[/bold cyan]"))

    from importlib import reload
    import config.settings
    reload(config.settings)
    from config.settings import META_ACCESS_TOKEN

    if not META_ACCESS_TOKEN or META_ACCESS_TOKEN == "your_access_token":
        console.print("  [yellow]Skipping (no token configured).[/yellow]")
        return False

    try:
        from api.meta_client import MetaClient
        client = MetaClient()
        result = client.health_check()

        if result.get("ok"):
            console.print(f"  [green]Connected![/green]")
            console.print(f"    Account: {result.get('account_name', 'N/A')}")
            console.print(f"    Status:  {result.get('account_status', 'N/A')}")
            console.print(f"    Currency: {result.get('currency', 'N/A')}")
            return True
        else:
            console.print(f"  [red]Failed:[/red] {result.get('error', 'Unknown')}")
            return False
    except Exception as exc:
        console.print(f"  [red]Failed:[/red] {exc}")
        return False


def _step_test_telegram(config: Dict[str, Any]) -> bool:
    console.print(Rule("[bold cyan]Testing: Telegram[/bold cyan]"))

    tg = config.get("notifications", {}).get("telegram", {})
    if not tg.get("enabled"):
        console.print("  [dim]Skipping (not configured).[/dim]")
        return False

    try:
        import requests
        token = tg.get("bot_token", "")
        chat_id = tg.get("chat_id", "")
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": "Meta Ads Bot connected! You'll receive hourly performance updates here.",
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            console.print("  [green]Message sent! Check your Telegram.[/green]")
            return True
        else:
            console.print(f"  [red]Failed:[/red] {resp.text[:200]}")
            return False
    except Exception as exc:
        console.print(f"  [red]Failed:[/red] {exc}")
        return False


# ======================================================================
# Step 9: Init database
# ======================================================================

def _step_init_db() -> None:
    console.print(Rule("[bold cyan]Initialising Database[/bold cyan]"))
    try:
        from data.db import init_db
        from config.settings import DB_PATH
        init_db()
        console.print(f"  [green]Database ready:[/green] {DB_PATH}")
    except Exception as exc:
        console.print(f"  [red]Failed:[/red] {exc}")


# ======================================================================
# Summary
# ======================================================================

def _step_summary(config: Dict[str, Any], meta_ok: bool, tg_ok: bool) -> None:
    console.print()

    biz = config.get("business", {})
    targets = config.get("targets", {})
    currency = targets.get("currency", "USD")

    t = Table(title=f"Setup Complete: {biz.get('name', 'New Client')}")
    t.add_column("Component", style="cyan")
    t.add_column("Status")

    t.add_row("Business", f"[green]{biz.get('name', '')}[/green]")
    t.add_row("Funnel", f"[green]{config.get('funnel', {}).get('type', '')}[/green]")
    t.add_row("Meta API", "[green]Connected[/green]" if meta_ok else "[yellow]Not tested[/yellow]")
    t.add_row("Telegram", "[green]Connected[/green]" if tg_ok else "[dim]Not configured[/dim]")
    t.add_row("Database", "[green]Ready[/green]")
    t.add_row("AD_SYSTEM.md", "[green]Generated[/green]")
    t.add_row("Target CPL", f"{currency} {targets.get('cpl', 0):.2f}")
    t.add_row("Target ROAS", f"{targets.get('target_roas', 0):.1f}x")
    t.add_row("Monthly Budget", f"{currency} {targets.get('monthly_budget', 0):,.0f}")

    console.print(t)

    console.print("\n[bold green]You're all set![/bold green]\n")
    console.print("Next steps:")
    console.print("  1. [cyan]python -m scripts.daily_run --dry-run[/cyan]  Preview a daily run")
    console.print("  2. [cyan]streamlit run dashboard.py[/cyan]             Open the dashboard")
    console.print("  3. [cyan]python -m scripts.daily_run[/cyan]            Run for real")
    console.print()
    console.print("[dim]Edit client_config.yaml anytime, then re-run:[/dim]")
    console.print("[dim]  python -m scripts.setup --from-config[/dim]")
    console.print()


# ======================================================================
# Main
# ======================================================================

def run_setup(from_config: bool = False, skip_tests: bool = False) -> None:
    """Full setup wizard."""
    _ensure_env_file()
    config = _load_config()

    if from_config:
        # Just regenerate AD_SYSTEM.md from existing config
        console.print("[cyan]Regenerating AD_SYSTEM.md from client_config.yaml...[/cyan]")
        _generate_ad_system(config)
        console.print("[green]Done.[/green] AD_SYSTEM.md updated.")
        return

    _step_welcome()

    config = _step_business(config)
    config = _step_meta(config)
    config = _step_telegram(config)
    config = _step_targets(config)
    config = _step_ai_key(config)

    # Save config
    _save_config(config)
    console.print("[green]client_config.yaml saved.[/green]\n")

    # Generate AD_SYSTEM.md
    console.print(Rule("[bold cyan]Generating AD_SYSTEM.md[/bold cyan]"))
    _generate_ad_system(config)
    console.print("  [green]AD_SYSTEM.md generated from your config.[/green]\n")

    # Tests
    meta_ok = False
    tg_ok = False
    if not skip_tests:
        meta_ok = _step_test_meta()
        tg_ok = _step_test_telegram(config)
    else:
        console.print("[dim]Skipping connection tests.[/dim]\n")

    _step_init_db()
    _step_summary(config, meta_ok, tg_ok)


def main() -> None:
    """CLI entry point."""
    import click

    @click.command()
    @click.option("--from-config", is_flag=True, help="Regenerate AD_SYSTEM.md from existing config")
    @click.option("--skip-tests", is_flag=True, help="Skip connection tests")
    def cli(from_config: bool, skip_tests: bool) -> None:
        """Meta Ads client onboarding wizard."""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        run_setup(from_config=from_config, skip_tests=skip_tests)

    cli()


if __name__ == "__main__":
    main()
