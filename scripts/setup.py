"""
First-time setup wizard for the Meta Ads Management System.

Walks the user through credential configuration, connection testing,
database initialisation, and an optional historical data backfill.

Usage::

    python -m scripts.setup
"""

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console()

# Project root (parent of the ``scripts`` directory)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
_ENV_EXAMPLE = _PROJECT_ROOT / ".env.example"


# ======================================================================
# Helper utilities
# ======================================================================


def _env_exists() -> bool:
    """Check whether a ``.env`` file is present in the project root."""
    return _ENV_FILE.exists()


def _read_env_value(key: str) -> str:
    """Read a single value from the existing ``.env`` file (simple parser)."""
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
    """Set or update a key-value pair in the ``.env`` file.

    Preserves comments and other lines. Appends the key if it does not
    already exist.
    """
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


# ======================================================================
# Setup steps
# ======================================================================


def _step_env_file() -> None:
    """Step 1: Ensure a .env file exists."""
    console.print("\n[bold cyan]Step 1:[/bold cyan] Environment file")

    if _env_exists():
        console.print("  [green].env file found.[/green]")
    else:
        if _ENV_EXAMPLE.exists():
            shutil.copy(_ENV_EXAMPLE, _ENV_FILE)
            console.print("  [green]Copied .env.example -> .env[/green]")
        else:
            _ENV_FILE.touch()
            console.print("  [green]Created empty .env file.[/green]")
        console.print("  [dim]Fill in your credentials in .env before continuing.[/dim]")


def _step_meta_credentials() -> None:
    """Step 2: Check / prompt for Meta API credentials."""
    console.print("\n[bold cyan]Step 2:[/bold cyan] Meta Marketing API credentials")

    token = _read_env_value("META_ACCESS_TOKEN")
    account = _read_env_value("META_AD_ACCOUNT_ID")

    if token and account:
        console.print(f"  [green]META_ACCESS_TOKEN:[/green]  ...{token[-8:]}")
        console.print(f"  [green]META_AD_ACCOUNT_ID:[/green] {account}")
    else:
        console.print("  [yellow]Meta credentials are not set.[/yellow]")
        if Confirm.ask("  Would you like to enter them now?", default=True):
            new_token = Prompt.ask("  META_ACCESS_TOKEN")
            new_account = Prompt.ask("  META_AD_ACCOUNT_ID (e.g. act_123456)")
            app_id = Prompt.ask("  META_APP_ID (optional, press Enter to skip)", default="")
            app_secret = Prompt.ask("  META_APP_SECRET (optional, press Enter to skip)", default="")

            if new_token:
                _update_env_value("META_ACCESS_TOKEN", new_token)
            if new_account:
                _update_env_value("META_AD_ACCOUNT_ID", new_account)
            if app_id:
                _update_env_value("META_APP_ID", app_id)
            if app_secret:
                _update_env_value("META_APP_SECRET", app_secret)

            console.print("  [green]Meta credentials saved to .env[/green]")
        else:
            console.print("  [dim]Skipping. Edit .env manually later.[/dim]")


def _step_supabase_credentials() -> None:
    """Step 3: Check / prompt for Supabase credentials."""
    console.print("\n[bold cyan]Step 3:[/bold cyan] Supabase credentials (optional)")

    url = _read_env_value("SUPABASE_URL")
    key = _read_env_value("SUPABASE_SERVICE_KEY")

    if url and key:
        console.print(f"  [green]SUPABASE_URL:[/green] {url[:40]}...")
        console.print(f"  [green]SUPABASE_SERVICE_KEY:[/green] ...{key[-8:]}")
    else:
        console.print("  [yellow]Supabase is not configured (community features will be disabled).[/yellow]")
        if Confirm.ask("  Would you like to configure Supabase now?", default=False):
            new_url = Prompt.ask("  SUPABASE_URL (e.g. https://xxx.supabase.co)")
            new_key = Prompt.ask("  SUPABASE_SERVICE_KEY")

            if new_url:
                _update_env_value("SUPABASE_URL", new_url)
            if new_key:
                _update_env_value("SUPABASE_SERVICE_KEY", new_key)

            console.print("  [green]Supabase credentials saved to .env[/green]")
        else:
            console.print("  [dim]Skipping. Community features will be unavailable.[/dim]")


def _step_test_meta() -> bool:
    """Step 4: Test the Meta API connection."""
    console.print("\n[bold cyan]Step 4:[/bold cyan] Testing Meta API connection")

    # Reload settings to pick up any .env changes we just made
    from importlib import reload
    import config.settings
    reload(config.settings)

    from config.settings import META_ACCESS_TOKEN

    if not META_ACCESS_TOKEN:
        console.print("  [yellow]Skipping (no access token configured).[/yellow]")
        return False

    try:
        from api.meta_client import MetaClient
        client = MetaClient()
        result = client.health_check()

        if result.get("ok"):
            console.print(f"  [green]Connected![/green]")
            console.print(f"  Account: {result.get('account_name', 'N/A')}")
            console.print(f"  Status:  {result.get('account_status', 'N/A')}")
            console.print(f"  Currency: {result.get('currency', 'N/A')}")
            console.print(f"  Timezone: {result.get('timezone', 'N/A')}")
            return True
        else:
            console.print(f"  [red]Connection failed:[/red] {result.get('error', 'Unknown error')}")
            return False
    except Exception as exc:
        console.print(f"  [red]Connection failed:[/red] {exc}")
        return False


def _step_test_supabase() -> bool:
    """Step 5: Test the Supabase connection."""
    console.print("\n[bold cyan]Step 5:[/bold cyan] Testing Supabase connection")

    from importlib import reload
    import config.settings
    reload(config.settings)

    from config.settings import SUPABASE_URL, SUPABASE_SERVICE_KEY

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        console.print("  [dim]Skipping (Supabase not configured).[/dim]")
        return False

    try:
        from community.supabase_client import SupabaseClient
        client = SupabaseClient()
        result = client.health_check()

        if result.get("ok"):
            console.print("  [green]Connected to Supabase![/green]")
            return True
        else:
            console.print(f"  [red]Connection failed:[/red] {result.get('error', 'Unknown error')}")
            return False
    except Exception as exc:
        console.print(f"  [red]Connection failed:[/red] {exc}")
        return False


def _step_init_database() -> None:
    """Step 6: Initialise the SQLite database."""
    console.print("\n[bold cyan]Step 6:[/bold cyan] Initialising database")

    try:
        from data.db import init_db
        from config.settings import DB_PATH

        init_db()
        console.print(f"  [green]Database ready at:[/green] {DB_PATH}")
    except Exception as exc:
        console.print(f"  [red]Database initialisation failed:[/red] {exc}")


def _step_business_targets() -> None:
    """Step 7: Configure business targets."""
    console.print("\n[bold cyan]Step 7:[/bold cyan] Business targets")

    current_cpa = _read_env_value("TARGET_CPA") or "30.0"
    current_roas = _read_env_value("TARGET_ROAS") or "3.0"
    current_budget = _read_env_value("MONTHLY_BUDGET") or "3000"
    current_currency = _read_env_value("CURRENCY") or "EUR"

    console.print(f"  Current targets: CPA={current_cpa}, ROAS={current_roas}, "
                  f"Budget={current_budget}/mo, Currency={current_currency}")

    if Confirm.ask("  Would you like to update business targets?", default=False):
        new_cpa = Prompt.ask("  Target CPA (max cost per acquisition)", default=current_cpa)
        new_roas = Prompt.ask("  Target ROAS (minimum acceptable)", default=current_roas)
        new_budget = Prompt.ask("  Monthly ad budget", default=current_budget)
        new_currency = Prompt.ask("  Currency code", default=current_currency)

        _update_env_value("TARGET_CPA", new_cpa)
        _update_env_value("TARGET_ROAS", new_roas)
        _update_env_value("MONTHLY_BUDGET", new_budget)
        _update_env_value("CURRENCY", new_currency)

        console.print("  [green]Business targets saved to .env[/green]")
    else:
        console.print("  [dim]Keeping current targets.[/dim]")


def _step_backfill(meta_ok: bool) -> None:
    """Step 8: Optionally run the initial data backfill."""
    console.print("\n[bold cyan]Step 8:[/bold cyan] Historical data backfill")

    if not meta_ok:
        console.print("  [dim]Skipping (Meta API not connected).[/dim]")
        return

    if Confirm.ask("  Would you like to pull historical data now? (90 days)", default=False):
        try:
            from scripts.backfill import run_backfill
            run_backfill(days=90)
        except Exception as exc:
            console.print(f"  [red]Backfill failed:[/red] {exc}")
            console.print("  [dim]You can run this later with: ads backfill --days 90[/dim]")
    else:
        console.print("  [dim]Skipping. Run 'ads backfill --days 90' later.[/dim]")


def _step_summary(meta_ok: bool, supabase_ok: bool) -> None:
    """Step 9: Print a setup summary."""
    console.print()

    t = Table(title="Setup Summary")
    t.add_column("Component", style="cyan")
    t.add_column("Status")

    t.add_row(".env file", "[green]Ready[/green]" if _env_exists() else "[red]Missing[/red]")
    t.add_row("Meta API", "[green]Connected[/green]" if meta_ok else "[yellow]Not tested[/yellow]")
    t.add_row("Supabase", "[green]Connected[/green]" if supabase_ok else "[dim]Not configured[/dim]")
    t.add_row("SQLite DB", "[green]Initialised[/green]")

    from config.settings import TARGET_CPA, TARGET_ROAS, MONTHLY_BUDGET, CURRENCY
    t.add_row("Target CPA", f"{CURRENCY} {TARGET_CPA:.2f}")
    t.add_row("Target ROAS", f"{TARGET_ROAS:.1f}x")
    t.add_row("Monthly Budget", f"{CURRENCY} {MONTHLY_BUDGET:,.0f}")

    console.print(t)

    console.print("\n[bold green]Setup complete![/bold green]")
    console.print("\nNext steps:")
    console.print("  1. [cyan]ads health[/cyan]      — Verify all connections")
    console.print("  2. [cyan]ads pull[/cyan]         — Pull yesterday's data")
    console.print("  3. [cyan]ads status[/cyan]       — View account summary")
    console.print("  4. [cyan]ads report daily[/cyan] — Generate your first report")


# ======================================================================
# Main entry point
# ======================================================================


def run_setup() -> None:
    """Execute the full setup wizard."""
    console.print(Panel(
        "[bold]Meta Ads Management System[/bold]\n"
        "First-time Setup Wizard",
        border_style="cyan",
    ))

    _step_env_file()
    _step_meta_credentials()
    _step_supabase_credentials()
    meta_ok = _step_test_meta()
    supabase_ok = _step_test_supabase()
    _step_init_database()
    _step_business_targets()
    _step_backfill(meta_ok)
    _step_summary(meta_ok, supabase_ok)


def main() -> None:
    """Standalone entry point: ``python -m scripts.setup``."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    run_setup()


if __name__ == "__main__":
    main()
