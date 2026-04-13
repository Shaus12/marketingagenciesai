"""
Facebook Page setup utility.

Checks which Pages are accessible via your Meta access token,
and creates a new one if none are found.

Usage::

    python -m scripts.page_setup
"""

import logging
import sys
from pathlib import Path
from typing import Any, Optional

import requests
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
_GRAPH_BASE = "https://graph.facebook.com/v21.0"

# Default page category ID for "Advertising/Marketing" — safe default
_DEFAULT_CATEGORY = 2200


# ======================================================================
# .env helpers (reused from setup.py pattern)
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


# ======================================================================
# Graph API helpers
# ======================================================================


def _graph_get(path: str, token: str, params: Optional[dict] = None) -> dict:
    """GET request to the Graph API. Returns parsed JSON."""
    p = {"access_token": token}
    if params:
        p.update(params)
    resp = requests.get(f"{_GRAPH_BASE}/{path.lstrip('/')}", params=p, timeout=30)
    return resp.json()


def _graph_post(path: str, token: str, data: Optional[dict] = None) -> dict:
    """POST request to the Graph API. Returns parsed JSON."""
    payload = {"access_token": token}
    if data:
        payload.update(data)
    resp = requests.post(f"{_GRAPH_BASE}/{path.lstrip('/')}", data=payload, timeout=30)
    return resp.json()


# ======================================================================
# Page discovery
# ======================================================================


def fetch_user_pages(token: str) -> list:
    """Fetch all Pages the token has access to via /me/accounts."""
    pages = []
    result = _graph_get("/me/accounts", token, {"fields": "id,name,category,fan_count,access_token"})

    if "error" in result:
        console.print(f"  [red]API error:[/red] {result['error'].get('message', result['error'])}")
        return pages

    data = result.get("data", [])
    pages.extend(data)

    # Follow pagination
    while "paging" in result and "next" in result["paging"]:
        next_url = result["paging"]["next"]
        resp = requests.get(next_url, timeout=30)
        result = resp.json()
        pages.extend(result.get("data", []))

    return pages


def fetch_token_permissions(token: str) -> list[str]:
    """Return the list of permissions granted on this token."""
    result = _graph_get("/me/permissions", token)
    if "error" in result or "data" not in result:
        return []
    return [
        p["permission"]
        for p in result["data"]
        if p.get("status") == "granted"
    ]


# ======================================================================
# Page creation
# ======================================================================


def create_page(token: str, name: str, category: int = _DEFAULT_CATEGORY) -> Optional[dict]:
    """
    Attempt to create a new Facebook Page via /me/accounts.

    Requires `pages_manage_metadata` (and typically `pages_show_list`)
    to be granted on the token.
    """
    console.print(f"\n  Creating page [bold]{name}[/bold] (category {category})…")
    result = _graph_post(
        "/me/accounts",
        token,
        {
            "name": name,
            "category": str(category),
        },
    )

    if "error" in result:
        err = result["error"]
        console.print(f"  [red]Could not create page:[/red] {err.get('message', err)}")
        console.print(
            "\n  [yellow]Tip:[/yellow] Page creation via API requires your token to have\n"
            "  [bold]pages_manage_metadata[/bold] permission and may need a verified app.\n"
            "  If this fails, create the page manually at [link]https://facebook.com/pages/create[/link]\n"
            "  then re-run this script."
        )
        return None

    page_id = result.get("id")
    if page_id:
        console.print(f"  [green]Page created![/green] ID: {page_id}")
        return {"id": page_id, "name": name, "category": str(category)}
    return None


# ======================================================================
# Main logic
# ======================================================================


def run_page_setup() -> None:
    console.print(Panel(
        "[bold]Meta Ads — Facebook Page Setup[/bold]",
        border_style="cyan",
    ))

    token = _read_env_value("META_ACCESS_TOKEN")
    if not token:
        console.print("[red]META_ACCESS_TOKEN not set in .env — aborting.[/red]")
        sys.exit(1)

    # ── 1. Check current permissions ──────────────────────────────────
    console.print("\n[bold cyan]Step 1:[/bold cyan] Checking token permissions…")
    perms = fetch_token_permissions(token)
    if perms:
        has_pages_show = "pages_show_list" in perms
        has_pages_manage = "pages_manage_metadata" in perms
        console.print(f"  Granted permissions: {', '.join(sorted(perms))}")
        if not has_pages_show:
            console.print("  [yellow]Warning:[/yellow] 'pages_show_list' is not granted — page listing may be empty.")
        if not has_pages_manage:
            console.print("  [yellow]Warning:[/yellow] 'pages_manage_metadata' is not granted — page creation will likely fail.")
    else:
        console.print("  [yellow]Could not read permissions (token may be a System User token).[/yellow]")

    # ── 2. Fetch existing pages ────────────────────────────────────────
    console.print("\n[bold cyan]Step 2:[/bold cyan] Fetching accessible Pages…")
    pages = fetch_user_pages(token)

    if pages:
        t = Table(title="Accessible Pages")
        t.add_column("#", style="dim", width=4)
        t.add_column("Page ID", style="cyan")
        t.add_column("Name")
        t.add_column("Category")
        t.add_column("Fans", justify="right")
        for i, p in enumerate(pages, 1):
            t.add_row(
                str(i),
                p.get("id", ""),
                p.get("name", ""),
                p.get("category", ""),
                str(p.get("fan_count", "—")),
            )
        console.print(t)

        # ── 3a. Let user pick a page ──────────────────────────────────
        current = _read_env_value("META_PAGE_ID")
        if len(pages) == 1:
            chosen = pages[0]
            console.print(f"\n  Only one page found — selecting [bold]{chosen['name']}[/bold] (ID: {chosen['id']})")
        else:
            from rich.prompt import Prompt
            choice = Prompt.ask(
                f"  Enter the number of the page to use [1-{len(pages)}]",
                default="1",
            )
            try:
                idx = int(choice) - 1
                chosen = pages[max(0, min(idx, len(pages) - 1))]
            except ValueError:
                chosen = pages[0]

        page_id = chosen["id"]
        _update_env_value("META_PAGE_ID", page_id)
        console.print(f"\n  [green]META_PAGE_ID updated to {page_id}[/green]")

    else:
        # ── 3b. No pages found — try to create one ────────────────────
        console.print("  [yellow]No pages found for this token.[/yellow]")
        console.print("\n[bold cyan]Step 3:[/bold cyan] Creating a new Facebook Page…")

        from rich.prompt import Prompt, Confirm
        page_name = Prompt.ask("  Page name", default="My Business Page")

        console.print("\n  Common category IDs:")
        console.print("    2200 — Advertising/Marketing")
        console.print("    2201 — Consulting/Business Services")
        console.print("    2256 — Education")
        console.print("    2204 — Technology")
        cat_str = Prompt.ask("  Category ID", default=str(_DEFAULT_CATEGORY))
        try:
            category = int(cat_str)
        except ValueError:
            category = _DEFAULT_CATEGORY

        new_page = create_page(token, page_name, category)

        if new_page:
            _update_env_value("META_PAGE_ID", new_page["id"])
            console.print(f"\n  [green]META_PAGE_ID set to {new_page['id']}[/green]")
        else:
            console.print(
                "\n  [bold red]Automatic page creation failed.[/bold red]\n\n"
                "  Please do ONE of the following:\n\n"
                "  [cyan]Option A[/cyan] — Create a page manually:\n"
                "    1. Go to https://facebook.com/pages/create\n"
                "    2. Create a Business/Brand page\n"
                "    3. Copy the Page ID from the page URL or About section\n"
                "    4. Set META_PAGE_ID=<your-page-id> in your .env file\n\n"
                "  [cyan]Option B[/cyan] — Regenerate your access token with page permissions:\n"
                "    1. Go to https://developers.facebook.com/tools/explorer\n"
                "    2. Add 'pages_show_list' and 'pages_manage_ads' permissions\n"
                "    3. Generate a new token and update META_ACCESS_TOKEN in .env\n"
                "    4. Re-run this script\n"
            )
            sys.exit(1)

    # ── 4. Verify the page is reachable ───────────────────────────────
    console.print("\n[bold cyan]Step 4:[/bold cyan] Verifying page access…")
    page_id = _read_env_value("META_PAGE_ID")
    result = _graph_get(f"/{page_id}", token, {"fields": "id,name,fan_count,verification_status"})

    if "error" in result:
        console.print(f"  [red]Cannot reach page {page_id}:[/red] {result['error'].get('message', '')}")
        console.print("  [dim]The page ID is saved but may need additional permissions to use in ads.[/dim]")
    else:
        console.print(f"  [green]Page verified![/green]")
        console.print(f"  Name:   {result.get('name', 'N/A')}")
        console.print(f"  ID:     {result.get('id', page_id)}")
        console.print(f"  Fans:   {result.get('fan_count', 'N/A')}")
        console.print(f"  Status: {result.get('verification_status', 'N/A')}")

    console.print("\n[bold green]Done![/bold green] Your .env now has a valid META_PAGE_ID.\n")


def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_page_setup()


if __name__ == "__main__":
    main()
