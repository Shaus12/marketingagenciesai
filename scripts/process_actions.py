"""
Process ads action queue from Supabase.

Reads pending actions from `ads_action_queue`, executes them against
the Meta Graph API, and updates the status.

Can be run standalone or triggered from GitHub Actions.

Usage::
    python -m scripts.process_actions
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "")
GRAPH_BASE = "https://graph.facebook.com/v21.0"

SUPABASE_URL = os.getenv("SUPABASE_URL_BACKOFFICE", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY_BACKOFFICE", "")


def _sb_headers() -> Dict[str, str]:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }


def _meta_post(entity_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """POST to Meta Graph API."""
    data["access_token"] = META_ACCESS_TOKEN
    r = requests.post(f"{GRAPH_BASE}/{entity_id}", data=data, timeout=15)
    return r.json()


def _update_action(action_id: str, status: str, result: str) -> None:
    """Update an action's status in Supabase."""
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/ads_action_queue?id=eq.{action_id}",
        headers=_sb_headers(),
        json={
            "status": status,
            "result": result,
            "processed_at": datetime.now(tz=timezone.utc).isoformat(),
        },
        timeout=10,
    )


def _get_pending_actions() -> List[Dict[str, Any]]:
    """Fetch all pending actions from the queue."""
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/ads_action_queue",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        },
        params={
            "status": "eq.pending",
            "order": "requested_at.asc",
        },
        timeout=10,
    )
    if r.status_code == 200:
        return r.json()
    return []


# ============================================================
# Action handlers
# ============================================================


def handle_pause_ad(action: Dict[str, Any]) -> str:
    entity_id = action.get("entity_id", "")
    result = _meta_post(entity_id, {"status": "PAUSED"})
    if "error" in result:
        raise RuntimeError(result["error"].get("message", "Unknown error"))
    return f"Ad {entity_id} paused successfully"


def handle_activate_ad(action: Dict[str, Any]) -> str:
    entity_id = action.get("entity_id", "")
    result = _meta_post(entity_id, {"status": "ACTIVE"})
    if "error" in result:
        raise RuntimeError(result["error"].get("message", "Unknown error"))
    return f"Ad {entity_id} activated successfully"


def handle_pause_adset(action: Dict[str, Any]) -> str:
    entity_id = action.get("entity_id", "")
    result = _meta_post(entity_id, {"status": "PAUSED"})
    if "error" in result:
        raise RuntimeError(result["error"].get("message", "Unknown error"))
    return f"Ad set {entity_id} paused successfully"


def handle_activate_adset(action: Dict[str, Any]) -> str:
    entity_id = action.get("entity_id", "")
    result = _meta_post(entity_id, {"status": "ACTIVE"})
    if "error" in result:
        raise RuntimeError(result["error"].get("message", "Unknown error"))
    return f"Ad set {entity_id} activated successfully"


def handle_pause_campaign(action: Dict[str, Any]) -> str:
    entity_id = action.get("entity_id", "")
    result = _meta_post(entity_id, {"status": "PAUSED"})
    if "error" in result:
        raise RuntimeError(result["error"].get("message", "Unknown error"))
    return f"Campaign {entity_id} paused successfully"


def handle_activate_campaign(action: Dict[str, Any]) -> str:
    entity_id = action.get("entity_id", "")
    result = _meta_post(entity_id, {"status": "ACTIVE"})
    if "error" in result:
        raise RuntimeError(result["error"].get("message", "Unknown error"))
    return f"Campaign {entity_id} activated successfully"


def handle_update_budget(action: Dict[str, Any]) -> str:
    entity_id = action.get("entity_id", "")
    params = action.get("params", {})
    if isinstance(params, str):
        params = json.loads(params)
    new_budget = params.get("new_budget")
    if not new_budget:
        raise RuntimeError("new_budget not specified in params")
    result = _meta_post(entity_id, {"daily_budget": str(int(new_budget))})
    if "error" in result:
        raise RuntimeError(result["error"].get("message", "Unknown error"))
    return f"Budget updated to €{int(new_budget)/100:.2f}/day for {entity_id}"


def handle_refresh_sync(action: Dict[str, Any]) -> str:
    from scripts.sync_to_supabase import run_sync
    summary = run_sync()
    errors = summary.get("errors", [])
    if errors:
        return f"Sync completed with {len(errors)} errors: {errors[0]}"
    return f"Sync completed in {summary.get('elapsed_seconds', '?')}s"


def handle_generate_creative(action: Dict[str, Any]) -> str:
    params = action.get("params", {})
    if isinstance(params, str):
        params = json.loads(params)
    prompt = params.get("prompt", "")
    if not prompt:
        raise RuntimeError("prompt not specified in params")
    # Import the ad generator
    from scripts.generate_ads import generate_image, save_to_pipeline
    url = generate_image(prompt)
    if not url:
        raise RuntimeError("Image generation failed")
    return f"Creative generated: {url}"


# Action type → handler mapping
HANDLERS = {
    "pause_ad": handle_pause_ad,
    "activate_ad": handle_activate_ad,
    "pause_adset": handle_pause_adset,
    "activate_adset": handle_activate_adset,
    "pause_campaign": handle_pause_campaign,
    "activate_campaign": handle_activate_campaign,
    "update_budget": handle_update_budget,
    "refresh_sync": handle_refresh_sync,
    "generate_creative": handle_generate_creative,
}


def process_all() -> Dict[str, Any]:
    """Process all pending actions in the queue."""
    actions = _get_pending_actions()
    logger.info("Found %d pending actions", len(actions))

    results = {"processed": 0, "failed": 0, "skipped": 0}

    for action in actions:
        action_id = action["id"]
        action_type = action.get("action_type", "")
        entity_name = action.get("entity_name", action.get("entity_id", "?"))

        handler = HANDLERS.get(action_type)
        if not handler:
            logger.warning("Unknown action type: %s", action_type)
            _update_action(action_id, "failed", f"Unknown action type: {action_type}")
            results["skipped"] += 1
            continue

        logger.info("Processing: %s → %s", action_type, entity_name)
        _update_action(action_id, "processing", "")

        try:
            result_msg = handler(action)
            _update_action(action_id, "completed", result_msg)
            logger.info("  ✅ %s", result_msg)
            results["processed"] += 1
        except Exception as exc:
            error_msg = str(exc)
            _update_action(action_id, "failed", error_msg)
            logger.error("  ❌ %s", error_msg)
            results["failed"] += 1

        time.sleep(0.5)

    return results


if __name__ == "__main__":
    if not META_ACCESS_TOKEN or not SUPABASE_URL:
        logger.error("Missing META_ACCESS_TOKEN or SUPABASE_URL_BACKOFFICE")
        exit(1)

    results = process_all()
    print(f"\nProcessed: {results['processed']} | Failed: {results['failed']} | Skipped: {results['skipped']}")
