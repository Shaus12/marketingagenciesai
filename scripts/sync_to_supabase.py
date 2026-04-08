"""
Sync Meta Ads data into the Supabase "Ads Command Center" tables.

Pulls campaign / ad-set / ad-level insights from the Meta Graph API (v21.0)
and upserts them into the backoffice Supabase instance.  Also generates
alerts, todos, and funnel metrics based on performance rules.

Usage::

    # One-time sync
    python -m scripts.sync_to_supabase

    # Import for use in daily_run
    from scripts.sync_to_supabase import run_sync
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Env & constants
# ---------------------------------------------------------------------------

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)

logger = logging.getLogger(__name__)

# Meta API
META_ACCESS_TOKEN: str = os.getenv("META_ACCESS_TOKEN", "")
META_AD_ACCOUNT_ID: str = os.getenv("META_AD_ACCOUNT_ID", "")  # act_XXXX
GRAPH_API_VERSION: str = "v21.0"
GRAPH_BASE: str = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Supabase (backoffice)
SUPABASE_URL: str = os.getenv("SUPABASE_URL_BACKOFFICE", "").rstrip("/")
SUPABASE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY_BACKOFFICE", "")

# Business targets
TARGET_CPA: float = float(os.getenv("TARGET_CPA", "50.0"))
TARGET_ROAS: float = float(os.getenv("TARGET_ROAS", "4.0"))

# Campaign / ad-set IDs
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CAMPAIGN_IDS: Dict[str, str] = json.loads((_DATA_DIR / "campaign_ids.json").read_text())
ADSET_IDS: Dict[str, str] = json.loads((_DATA_DIR / "adset_ids.json").read_text())

# Reverse lookup: campaign_id -> campaign_type
CAMPAIGN_TYPE_BY_ID: Dict[str, str] = {cid: ctype for ctype, cid in CAMPAIGN_IDS.items()}

# Adset -> campaign type mapping (derived from naming convention)
ADSET_CAMPAIGN_TYPE: Dict[str, str] = {}
for adset_name, adset_id in ADSET_IDS.items():
    for campaign_type in CAMPAIGN_IDS:
        if adset_name.startswith(campaign_type):
            ADSET_CAMPAIGN_TYPE[adset_id] = campaign_type
            break

# ---------------------------------------------------------------------------
# Helpers — Meta Graph API
# ---------------------------------------------------------------------------

_INSIGHT_FIELDS: str = ",".join([
    "ad_id",
    "ad_name",
    "adset_id",
    "adset_name",
    "campaign_id",
    "campaign_name",
    "spend",
    "impressions",
    "reach",
    "frequency",
    "clicks",
    "ctr",
    "cpc",
    "cpm",
    "actions",
    "action_values",
    "cost_per_action_type",
    "video_play_actions",
    "video_p25_watched_actions",
    "video_p50_watched_actions",
    "video_p75_watched_actions",
    "video_p100_watched_actions",
])

_CAMPAIGN_FIELDS: str = ",".join([
    "campaign_id",
    "campaign_name",
    "spend",
    "impressions",
    "clicks",
    "ctr",
    "actions",
    "action_values",
    "cost_per_action_type",
])


def _meta_get(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Issue a GET to the Meta Graph API and return the JSON response.

    Raises on HTTP errors or Meta API errors.
    """
    params = params or {}
    params["access_token"] = META_ACCESS_TOKEN
    resp = requests.get(url, params=params, timeout=120)
    data = resp.json()
    if "error" in data:
        err = data["error"]
        logger.error("Meta API error: %s — %s", err.get("code"), err.get("message"))
        raise RuntimeError(f"Meta API error {err.get('code')}: {err.get('message')}")
    return data


def _extract_conversions(actions: Optional[List[Dict[str, Any]]]) -> int:
    """Extract total conversions from Meta ``actions`` list.

    Looks for offsite_conversion.fb_pixel_purchase, complete_registration,
    or lead action types.
    """
    if not actions:
        return 0
    conversion_types = {
        "offsite_conversion.fb_pixel_purchase",
        "offsite_conversion.fb_pixel_complete_registration",
        "offsite_conversion.fb_pixel_lead",
        "complete_registration",
        "lead",
        "purchase",
        "omni_purchase",
    }
    total = 0
    for action in actions:
        if action.get("action_type") in conversion_types:
            total += int(float(action.get("value", 0)))
    return total


def _extract_revenue(action_values: Optional[List[Dict[str, Any]]]) -> float:
    """Extract revenue from Meta ``action_values``."""
    if not action_values:
        return 0.0
    revenue_types = {
        "offsite_conversion.fb_pixel_purchase",
        "purchase",
        "omni_purchase",
    }
    total = 0.0
    for av in action_values:
        if av.get("action_type") in revenue_types:
            total += float(av.get("value", 0))
    return total


def _extract_cpa(cost_per_action: Optional[List[Dict[str, Any]]]) -> Optional[float]:
    """Extract CPA from ``cost_per_action_type``."""
    if not cost_per_action:
        return None
    target_types = {
        "offsite_conversion.fb_pixel_purchase",
        "offsite_conversion.fb_pixel_complete_registration",
        "offsite_conversion.fb_pixel_lead",
        "complete_registration",
        "lead",
        "purchase",
        "omni_purchase",
    }
    for item in cost_per_action:
        if item.get("action_type") in target_types:
            return float(item.get("value", 0))
    return None


def _extract_video_views(
    video_play_actions: Optional[List[Dict[str, Any]]],
) -> int:
    """Extract 3-second video views."""
    if not video_play_actions:
        return 0
    for v in video_play_actions:
        if v.get("action_type") == "video_view":
            return int(float(v.get("value", 0)))
    return 0


def _extract_video_p_views(
    p_actions: Optional[List[Dict[str, Any]]],
) -> int:
    """Extract video percentage-watched view count."""
    if not p_actions:
        return 0
    for v in p_actions:
        if v.get("action_type") in ("video_view", "video_p25_watched", "video_p50_watched",
                                     "video_p75_watched", "video_p100_watched"):
            return int(float(v.get("value", 0)))
    return 0


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def _today_str() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def _date_n_days_ago(n: int) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Meta API data pulling
# ---------------------------------------------------------------------------


def fetch_campaign_insights(date_preset: str = "last_7d") -> List[Dict[str, Any]]:
    """Fetch campaign-level insights for all campaigns in the ad account.

    Args:
        date_preset: One of ``last_7d``, ``last_30d``, ``today``, etc.

    Returns:
        List of insight dicts.
    """
    url = f"{GRAPH_BASE}/{META_AD_ACCOUNT_ID}/insights"
    params = {
        "level": "campaign",
        "fields": _CAMPAIGN_FIELDS,
        "date_preset": date_preset,
        "limit": 500,
    }
    data = _meta_get(url, params)
    results = data.get("data", [])

    # Handle pagination
    while data.get("paging", {}).get("next"):
        data = _meta_get(data["paging"]["next"])
        results.extend(data.get("data", []))

    return results


def fetch_adset_insights(date_preset: str = "last_7d") -> List[Dict[str, Any]]:
    """Fetch ad-set-level insights."""
    url = f"{GRAPH_BASE}/{META_AD_ACCOUNT_ID}/insights"
    params = {
        "level": "adset",
        "fields": _CAMPAIGN_FIELDS + ",adset_id,adset_name",
        "date_preset": date_preset,
        "limit": 500,
    }
    data = _meta_get(url, params)
    results = data.get("data", [])

    while data.get("paging", {}).get("next"):
        data = _meta_get(data["paging"]["next"])
        results.extend(data.get("data", []))

    return results


def fetch_ad_insights_today() -> List[Dict[str, Any]]:
    """Fetch ad-level insights for today (aggregate)."""
    url = f"{GRAPH_BASE}/{META_AD_ACCOUNT_ID}/insights"
    params = {
        "level": "ad",
        "fields": _INSIGHT_FIELDS,
        "date_preset": "today",
        "limit": 500,
    }
    data = _meta_get(url, params)
    results = data.get("data", [])

    while data.get("paging", {}).get("next"):
        data = _meta_get(data["paging"]["next"])
        results.extend(data.get("data", []))

    return results


def fetch_ad_insights_daily(days: int = 7) -> List[Dict[str, Any]]:
    """Fetch ad-level insights with daily breakdown for the last N days.

    Returns one row per ad per day.
    """
    since = _date_n_days_ago(days)
    until = _today_str()
    url = f"{GRAPH_BASE}/{META_AD_ACCOUNT_ID}/insights"
    params = {
        "level": "ad",
        "fields": _INSIGHT_FIELDS,
        "time_range": json.dumps({"since": since, "until": until}),
        "time_increment": 1,  # daily breakdown
        "limit": 500,
    }
    data = _meta_get(url, params)
    results = data.get("data", [])

    while data.get("paging", {}).get("next"):
        data = _meta_get(data["paging"]["next"])
        results.extend(data.get("data", []))

    return results


def fetch_active_ads() -> List[Dict[str, Any]]:
    """Fetch all ads with status, creative details, and preview URLs."""
    url = f"{GRAPH_BASE}/{META_AD_ACCOUNT_ID}/ads"
    params = {
        "fields": (
            "id,name,status,adset_id,campaign_id,"
            "creative{id,name,body,title,image_url,thumbnail_url,object_story_spec}"
        ),
        "limit": 500,
    }
    data = _meta_get(url, params)
    results = data.get("data", [])

    while data.get("paging", {}).get("next"):
        data = _meta_get(data["paging"]["next"])
        results.extend(data.get("data", []))

    return results


def fetch_campaign_details() -> List[Dict[str, Any]]:
    """Fetch campaign-level details (status, budget, etc.)."""
    url = f"{GRAPH_BASE}/{META_AD_ACCOUNT_ID}/campaigns"
    params = {
        "fields": "id,name,status,daily_budget,lifetime_budget,objective",
        "limit": 500,
    }
    data = _meta_get(url, params)
    results = data.get("data", [])

    while data.get("paging", {}).get("next"):
        data = _meta_get(data["paging"]["next"])
        results.extend(data.get("data", []))

    return results


# ---------------------------------------------------------------------------
# Supabase upsert helpers
# ---------------------------------------------------------------------------


def _supabase_headers() -> Dict[str, str]:
    """Return default headers for the Supabase REST API."""
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }


_UPSERT_CONFLICT_KEYS = {
    "ads_daily_performance": "ad_id,date",
    "ads_campaign_status": "campaign_id",
    "ads_funnel_metrics": "date",
}


def _supabase_upsert(table: str, rows: List[Dict[str, Any]]) -> int:
    """Upsert rows into a Supabase table via the REST API.

    Returns the number of rows sent.
    """
    if not rows:
        return 0

    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = _supabase_headers()
    conflict_key = _UPSERT_CONFLICT_KEYS.get(table)
    if conflict_key:
        url += f"?on_conflict={conflict_key}"
    resp = requests.post(url, headers=headers, json=rows, timeout=30)

    if resp.status_code not in (200, 201, 204):
        logger.error(
            "Supabase upsert to '%s' failed (%d): %s",
            table, resp.status_code, resp.text[:500],
        )
        raise RuntimeError(
            f"Supabase upsert to '{table}' failed ({resp.status_code}): {resp.text[:300]}"
        )

    logger.info("Upserted %d row(s) into '%s'", len(rows), table)
    return len(rows)


def _supabase_select(
    table: str,
    params: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Select rows from a Supabase table via REST API."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.get(url, headers=headers, params=params or {}, timeout=30)
    if resp.status_code != 200:
        logger.warning("Supabase select from '%s' failed (%d): %s",
                       table, resp.status_code, resp.text[:300])
        return []
    return resp.json()


def _supabase_delete(table: str, filters: Dict[str, str]) -> None:
    """Delete rows from a Supabase table matching filters."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.delete(url, headers=headers, params=filters, timeout=30)
    if resp.status_code not in (200, 204):
        logger.warning("Supabase delete from '%s' failed (%d): %s",
                       table, resp.status_code, resp.text[:300])


# ---------------------------------------------------------------------------
# Status / health logic
# ---------------------------------------------------------------------------


def _ad_status_emoji(
    spend: float,
    cpa: Optional[float],
    roas: float,
    conversions: int,
) -> Tuple[str, str]:
    """Determine the status emoji and note for an ad.

    Returns:
        (emoji, note) tuple.
    """
    if spend < 5.0:
        return "\u26aa", "Not enough data yet"

    if conversions == 0:
        if spend > 15:
            return "\U0001f534", f"Spent \u20ac{spend:.0f} with 0 conversions"
        return "\u26aa", "Waiting for first conversion"

    actual_cpa = cpa if cpa is not None else (spend / conversions if conversions else None)
    actual_roas = roas

    cpa_ok = actual_cpa is not None and actual_cpa <= TARGET_CPA
    roas_ok = actual_roas >= TARGET_ROAS
    cpa_slightly_off = actual_cpa is not None and actual_cpa <= TARGET_CPA * 1.2
    roas_slightly_off = actual_roas >= TARGET_ROAS * 0.8

    # Red: CPA > 2x target OR ROAS < 0.5x target
    if (actual_cpa is not None and actual_cpa > TARGET_CPA * 2) or actual_roas < TARGET_ROAS * 0.5:
        note = []
        if actual_cpa is not None and actual_cpa > TARGET_CPA * 2:
            note.append(f"CPA \u20ac{actual_cpa:.0f} > 2x target")
        if actual_roas < TARGET_ROAS * 0.5:
            note.append(f"ROAS {actual_roas:.1f}x < 0.5x target")
        return "\U0001f534", "; ".join(note)

    # Green: both OK
    if cpa_ok and roas_ok:
        return "\U0001f7e2", f"CPA \u20ac{actual_cpa:.0f}, ROAS {actual_roas:.1f}x — on target"

    # Yellow: one slightly off
    if cpa_slightly_off and roas_slightly_off:
        return "\U0001f7e1", f"CPA \u20ac{actual_cpa:.0f}, ROAS {actual_roas:.1f}x — close to target"

    # Yellow for anything in between
    parts = []
    if actual_cpa is not None:
        parts.append(f"CPA \u20ac{actual_cpa:.0f}")
    parts.append(f"ROAS {actual_roas:.1f}x")
    return "\U0001f7e1", " / ".join(parts) + " — needs improvement"


def _overall_status(
    ad_emojis: List[str],
    account_cpa: Optional[float],
) -> Tuple[str, str]:
    """Determine the overall dashboard status.

    Returns:
        (status, reason) tuple.
    """
    if not ad_emojis:
        return "no_data", "No ad data available yet"

    red_count = ad_emojis.count("\U0001f534")
    green_count = ad_emojis.count("\U0001f7e2")
    total = len(ad_emojis)

    # Critical: majority red or CPA > 2x target
    if account_cpa is not None and account_cpa > TARGET_CPA * 2:
        return "critical", f"Account CPA \u20ac{account_cpa:.0f} is more than 2x the \u20ac{TARGET_CPA:.0f} target"

    if total > 0 and red_count / total > 0.5:
        return "critical", f"{red_count}/{total} ads are underperforming (red)"

    # Healthy: majority green and CPA < target
    if account_cpa is not None and account_cpa <= TARGET_CPA and total > 0 and green_count / total >= 0.5:
        return "healthy", f"Account CPA \u20ac{account_cpa:.0f} is below \u20ac{TARGET_CPA:.0f} target"

    # Needs attention
    reasons = []
    if account_cpa is not None and account_cpa > TARGET_CPA:
        reasons.append(f"CPA \u20ac{account_cpa:.0f} above \u20ac{TARGET_CPA:.0f} target")
    if red_count > 0:
        reasons.append(f"{red_count} ad(s) in red")
    return "needs_attention", "; ".join(reasons) if reasons else "Some metrics need improvement"


# ---------------------------------------------------------------------------
# Sync: ads_daily_performance
# ---------------------------------------------------------------------------


def sync_daily_performance(ad_insights: List[Dict[str, Any]]) -> int:
    """Transform Meta ad insights into ads_daily_performance rows and upsert.

    Args:
        ad_insights: Raw insight rows from ``fetch_ad_insights_daily``.

    Returns:
        Number of rows upserted.
    """
    rows: List[Dict[str, Any]] = []

    for row in ad_insights:
        spend = _safe_float(row.get("spend"))
        impressions = _safe_int(row.get("impressions"))
        clicks = _safe_int(row.get("clicks"))
        reach = _safe_int(row.get("reach"))
        frequency = _safe_float(row.get("frequency"))
        ctr = _safe_float(row.get("ctr"))
        cpc = _safe_float(row.get("cpc"))
        cpm = _safe_float(row.get("cpm"))

        conversions = _extract_conversions(row.get("actions"))
        revenue = _extract_revenue(row.get("action_values"))
        cpa = _extract_cpa(row.get("cost_per_action_type"))
        roas = revenue / spend if spend > 0 else 0.0

        video_views_3s = _extract_video_views(row.get("video_play_actions"))
        video_views_15s = _extract_video_p_views(row.get("video_p25_watched_actions"))

        hook_rate = (video_views_3s / impressions * 100) if impressions > 0 else None
        hold_rate = (video_views_15s / video_views_3s * 100) if video_views_3s > 0 else None

        # Determine campaign type
        campaign_id = row.get("campaign_id", "")
        campaign_type = CAMPAIGN_TYPE_BY_ID.get(campaign_id, "unknown")

        emoji, note = _ad_status_emoji(spend, cpa, roas, conversions)

        record = {
            "date": row.get("date_start", _today_str()),
            "ad_id": row.get("ad_id", ""),
            "ad_name": row.get("ad_name", ""),
            "adset_id": row.get("adset_id", ""),
            "adset_name": row.get("adset_name", ""),
            "campaign_id": campaign_id,
            "campaign_type": campaign_type,
            "spend": round(spend, 2),
            "impressions": impressions,
            "reach": reach,
            "frequency": round(frequency, 2),
            "clicks": clicks,
            "ctr": round(ctr, 2),
            "cpc": round(cpc, 2),
            "cpm": round(cpm, 2),
            "conversions": conversions,
            "cpa": round(cpa, 2) if cpa is not None else None,
            "revenue": round(revenue, 2),
            "roas": round(roas, 2),
            "hook_rate": round(hook_rate, 2) if hook_rate is not None else None,
            "hold_rate": round(hold_rate, 2) if hold_rate is not None else None,
            "video_views_3s": video_views_3s,
            "video_views_15s": video_views_15s,
            "status_emoji": emoji,
            "status_note": note,
        }
        rows.append(record)

    return _supabase_upsert("ads_daily_performance", rows)


# ---------------------------------------------------------------------------
# Sync: ads_campaign_status
# ---------------------------------------------------------------------------


def sync_campaign_status(
    campaign_details: List[Dict[str, Any]],
    insights_7d: List[Dict[str, Any]],
    insights_30d: List[Dict[str, Any]],
    today_insights: List[Dict[str, Any]],
) -> int:
    """Build and upsert campaign status rows.

    Args:
        campaign_details: From ``fetch_campaign_details``.
        insights_7d: Campaign-level insights (last 7 days).
        insights_30d: Campaign-level insights (last 30 days).
        today_insights: Campaign-level insights (today).

    Returns:
        Number of rows upserted.
    """
    # Index insights by campaign_id
    i7 = {r["campaign_id"]: r for r in insights_7d if "campaign_id" in r}
    i30 = {r["campaign_id"]: r for r in insights_30d if "campaign_id" in r}
    itoday = {r["campaign_id"]: r for r in today_insights if "campaign_id" in r}

    # Total spend across all campaigns (7d) for budget % calculation
    total_spend_7d = sum(_safe_float(r.get("spend")) for r in insights_7d)

    budget_target_map = {
        "scale": 0.70,
        "iterate": 0.20,
        "test": 0.10,
        "retarget": 0.0,  # retarget is separate from 70/20/10
    }

    rows: List[Dict[str, Any]] = []

    for camp in campaign_details:
        cid = camp.get("id", "")
        cname = camp.get("name", "")
        cstatus = camp.get("status", "PAUSED")
        ctype = CAMPAIGN_TYPE_BY_ID.get(cid, "unknown")

        daily_budget = _safe_float(camp.get("daily_budget")) / 100  # Meta returns cents
        if daily_budget == 0:
            daily_budget = _safe_float(camp.get("lifetime_budget", 0)) / 100

        # 7-day metrics
        c7 = i7.get(cid, {})
        spend_7d = _safe_float(c7.get("spend"))
        conv_7d = _extract_conversions(c7.get("actions"))
        cpa_7d_val = spend_7d / conv_7d if conv_7d > 0 else None
        rev_7d = _extract_revenue(c7.get("action_values"))
        roas_7d_val = rev_7d / spend_7d if spend_7d > 0 else None
        ctr_7d_val = _safe_float(c7.get("ctr"))

        # 30-day metrics
        c30 = i30.get(cid, {})
        spend_30d = _safe_float(c30.get("spend"))
        conv_30d = _extract_conversions(c30.get("actions"))

        # Today metrics
        ct = itoday.get(cid, {})
        spend_today = _safe_float(ct.get("spend"))
        conv_today = _extract_conversions(ct.get("actions"))

        # Health status
        if spend_7d < 5:
            health = "neutral"
            health_reason = "Not enough spend data"
        elif conv_7d == 0 and spend_7d > 30:
            health = "red"
            health_reason = f"Spent \u20ac{spend_7d:.0f} in 7d with 0 conversions"
        elif cpa_7d_val is not None and cpa_7d_val <= TARGET_CPA and roas_7d_val is not None and roas_7d_val >= TARGET_ROAS:
            health = "green"
            health_reason = f"CPA \u20ac{cpa_7d_val:.0f}, ROAS {roas_7d_val:.1f}x — on target"
        elif cpa_7d_val is not None and cpa_7d_val > TARGET_CPA * 2:
            health = "red"
            health_reason = f"CPA \u20ac{cpa_7d_val:.0f} > 2x target"
        elif cpa_7d_val is not None and cpa_7d_val > TARGET_CPA:
            health = "yellow"
            health_reason = f"CPA \u20ac{cpa_7d_val:.0f} above \u20ac{TARGET_CPA:.0f} target"
        else:
            health = "neutral"
            health_reason = "Waiting for more data"

        # Budget allocation %
        budget_pct_actual = (spend_7d / total_spend_7d * 100) if total_spend_7d > 0 else 0.0
        budget_pct_target = budget_target_map.get(ctype, 0.0) * 100

        record = {
            "campaign_id": cid,
            "campaign_name": cname,
            "campaign_type": ctype,
            "status": cstatus,
            "daily_budget": round(daily_budget, 2),
            "spend_today": round(spend_today, 2),
            "spend_7d": round(spend_7d, 2),
            "spend_30d": round(spend_30d, 2),
            "conversions_today": conv_today,
            "conversions_7d": conv_7d,
            "conversions_30d": conv_30d,
            "cpa_7d": round(cpa_7d_val, 2) if cpa_7d_val is not None else None,
            "roas_7d": round(roas_7d_val, 2) if roas_7d_val is not None else None,
            "ctr_7d": round(ctr_7d_val, 2),
            "health_status": health,
            "health_reason": health_reason,
            "budget_pct_actual": round(budget_pct_actual, 1),
            "budget_pct_target": round(budget_pct_target, 1),
            "last_updated_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        rows.append(record)

    return _supabase_upsert("ads_campaign_status", rows)


# ---------------------------------------------------------------------------
# Sync: ads_dashboard
# ---------------------------------------------------------------------------


def sync_dashboard(
    today_ads: List[Dict[str, Any]],
    daily_rows: List[Dict[str, Any]],
    all_ads: List[Dict[str, Any]],
) -> int:
    """Build and upsert the single ads_dashboard row.

    Args:
        today_ads: Ad-level insights for today.
        daily_rows: Ad-level daily insights (7 days).
        all_ads: All ads with their status.

    Returns:
        Number of rows upserted.
    """
    today_str = _today_str()
    yesterday_str = _date_n_days_ago(1)
    week_start = _date_n_days_ago(7)
    month_start = datetime.now(tz=timezone.utc).replace(day=1).strftime("%Y-%m-%d")

    # Today aggregates
    t_spend = sum(_safe_float(r.get("spend")) for r in today_ads)
    t_impressions = sum(_safe_int(r.get("impressions")) for r in today_ads)
    t_clicks = sum(_safe_int(r.get("clicks")) for r in today_ads)
    t_conversions = sum(_extract_conversions(r.get("actions")) for r in today_ads)
    t_revenue = sum(_extract_revenue(r.get("action_values")) for r in today_ads)
    t_cpa = t_spend / t_conversions if t_conversions > 0 else 0.0
    t_roas = t_revenue / t_spend if t_spend > 0 else 0.0
    t_ctr = (t_clicks / t_impressions * 100) if t_impressions > 0 else 0.0

    # Yesterday aggregates (from daily breakdown)
    yesterday_rows = [r for r in daily_rows if r.get("date_start") == yesterday_str]
    y_spend = sum(_safe_float(r.get("spend")) for r in yesterday_rows)
    y_conversions = sum(_extract_conversions(r.get("actions")) for r in yesterday_rows)
    y_revenue = sum(_extract_revenue(r.get("action_values")) for r in yesterday_rows)
    y_cpa = y_spend / y_conversions if y_conversions > 0 else 0.0
    y_roas = y_revenue / y_spend if y_spend > 0 else 0.0

    spend_vs_yesterday = ((t_spend - y_spend) / y_spend * 100) if y_spend > 0 else 0.0

    # Week aggregates
    week_rows = [r for r in daily_rows if r.get("date_start", "") >= week_start]
    w_spend = sum(_safe_float(r.get("spend")) for r in week_rows)
    w_conversions = sum(_extract_conversions(r.get("actions")) for r in week_rows)
    w_revenue = sum(_extract_revenue(r.get("action_values")) for r in week_rows)
    w_cpa = w_spend / w_conversions if w_conversions > 0 else 0.0
    w_roas = w_revenue / w_spend if w_spend > 0 else 0.0

    # Month aggregates
    month_rows = [r for r in daily_rows if r.get("date_start", "") >= month_start]
    m_spend = sum(_safe_float(r.get("spend")) for r in month_rows)
    m_conversions = sum(_extract_conversions(r.get("actions")) for r in month_rows)
    m_revenue = sum(_extract_revenue(r.get("action_values")) for r in month_rows)
    m_roas = m_revenue / m_spend if m_spend > 0 else 0.0

    # Ad counts
    active_count = sum(1 for a in all_ads if a.get("status") == "ACTIVE")
    paused_count = sum(1 for a in all_ads if a.get("status") == "PAUSED")

    # Overall status
    ad_emojis: List[str] = []
    for r in today_ads:
        spend = _safe_float(r.get("spend"))
        conv = _extract_conversions(r.get("actions"))
        rev = _extract_revenue(r.get("action_values"))
        roas = rev / spend if spend > 0 else 0.0
        cpa = spend / conv if conv > 0 else None
        emoji, _ = _ad_status_emoji(spend, cpa, roas, conv)
        ad_emojis.append(emoji)

    account_cpa = t_spend / t_conversions if t_conversions > 0 else None
    status, reason = _overall_status(ad_emojis, account_cpa)

    # Check if there is already a dashboard row to get its ID
    existing = _supabase_select("ads_dashboard", {"limit": "1"})
    row_id = existing[0]["id"] if existing else str(uuid.uuid4())

    dashboard_row = {
        "id": row_id,
        "today_spend": round(t_spend, 2),
        "today_impressions": t_impressions,
        "today_clicks": t_clicks,
        "today_conversions": t_conversions,
        "today_cpa": round(t_cpa, 2),
        "today_roas": round(t_roas, 2),
        "today_ctr": round(t_ctr, 2),
        "yesterday_spend": round(y_spend, 2),
        "yesterday_conversions": y_conversions,
        "yesterday_cpa": round(y_cpa, 2),
        "yesterday_roas": round(y_roas, 2),
        "spend_vs_yesterday_pct": round(spend_vs_yesterday, 1),
        "week_spend": round(w_spend, 2),
        "week_conversions": w_conversions,
        "week_cpa": round(w_cpa, 2),
        "week_roas": round(w_roas, 2),
        "month_spend": round(m_spend, 2),
        "month_conversions": m_conversions,
        "month_revenue": round(m_revenue, 2),
        "month_roas": round(m_roas, 2),
        "overall_status": status,
        "status_reason": reason,
        "active_ads_count": active_count,
        "paused_ads_count": paused_count,
        "last_updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    return _supabase_upsert("ads_dashboard", [dashboard_row])


# ---------------------------------------------------------------------------
# Generate: ads_alerts
# ---------------------------------------------------------------------------


def generate_alerts(
    daily_rows: List[Dict[str, Any]],
    today_ads: List[Dict[str, Any]],
) -> int:
    """Generate alerts based on performance rules.

    Rules:
    - Ad spent > 15 with 0 conversions -> critical "Kill this ad"
    - Ad frequency > 4.0 -> warning "Creative fatigue"
    - Ad ROAS > 3x target for 3+ days -> positive "Scale this winner"
    - Account CPA > target by 20%+ -> warning

    Args:
        daily_rows: Raw daily ad insights from Meta (7d).
        today_ads: Raw today ad insights from Meta.

    Returns:
        Number of alerts upserted.
    """
    alerts: List[Dict[str, Any]] = []
    today_str = _today_str()

    # --- Per-ad alerts ---
    for row in today_ads:
        ad_id = row.get("ad_id", "")
        ad_name = row.get("ad_name", "Unknown")
        spend = _safe_float(row.get("spend"))
        conversions = _extract_conversions(row.get("actions"))
        frequency = _safe_float(row.get("frequency"))

        # Rule 1: High spend, no conversions
        if spend > 15 and conversions == 0:
            alerts.append({
                "type": "kill",
                "severity": "critical",
                "title": f"Ad '{ad_name}' spent \u20ac{spend:.0f} with 0 conversions",
                "message": (
                    f"This ad has spent \u20ac{spend:.2f} today without generating any conversions. "
                    f"Consider pausing it immediately to stop wasting budget."
                ),
                "related_entity_id": ad_id,
                "related_entity_type": "ad",
                "related_entity_name": ad_name,
                "suggested_action": "Pause this ad",
                "status": "new",
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
            })

        # Rule 2: Creative fatigue (frequency > 4)
        if frequency > 4.0:
            alerts.append({
                "type": "fatigue",
                "severity": "warning",
                "title": f"Creative fatigue on '{ad_name}' (frequency {frequency:.1f})",
                "message": (
                    f"Ad '{ad_name}' has a frequency of {frequency:.1f}, meaning the average user "
                    f"has seen it more than 4 times. Performance will degrade. "
                    f"Consider refreshing the creative or narrowing the audience."
                ),
                "related_entity_id": ad_id,
                "related_entity_type": "ad",
                "related_entity_name": ad_name,
                "suggested_action": "Create a new variation or pause this ad",
                "status": "new",
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
            })

    # --- Multi-day ad alerts (ROAS > 3x target for 3+ days) ---
    # Group daily rows by ad_id
    ad_daily: Dict[str, List[Dict[str, Any]]] = {}
    for row in daily_rows:
        aid = row.get("ad_id", "")
        ad_daily.setdefault(aid, []).append(row)

    for ad_id, days_data in ad_daily.items():
        winner_days = 0
        ad_name = days_data[0].get("ad_name", "Unknown") if days_data else "Unknown"
        best_roas = 0.0

        for day in days_data:
            day_spend = _safe_float(day.get("spend"))
            day_rev = _extract_revenue(day.get("action_values"))
            day_roas = day_rev / day_spend if day_spend > 0 else 0.0
            if day_roas > TARGET_ROAS * 3:
                winner_days += 1
                best_roas = max(best_roas, day_roas)

        if winner_days >= 3:
            alerts.append({
                "type": "winner",
                "severity": "positive",
                "title": f"Winner alert: '{ad_name}' has ROAS > {TARGET_ROAS * 3:.0f}x for {winner_days} days",
                "message": (
                    f"Ad '{ad_name}' has achieved ROAS above {TARGET_ROAS * 3:.0f}x on {winner_days} "
                    f"of the last 7 days (peak: {best_roas:.1f}x). This is a proven winner. "
                    f"Consider scaling budget on this ad."
                ),
                "related_entity_id": ad_id,
                "related_entity_type": "ad",
                "related_entity_name": ad_name,
                "suggested_action": "Increase budget by 20-30%",
                "status": "new",
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
            })

    # --- Account-level CPA alert ---
    total_spend = sum(_safe_float(r.get("spend")) for r in today_ads)
    total_conv = sum(_extract_conversions(r.get("actions")) for r in today_ads)
    if total_conv > 0:
        account_cpa = total_spend / total_conv
        if account_cpa > TARGET_CPA * 1.2:
            alerts.append({
                "type": "budget",
                "severity": "warning",
                "title": f"Account CPA \u20ac{account_cpa:.0f} is {((account_cpa / TARGET_CPA) - 1) * 100:.0f}% above target",
                "message": (
                    f"Your account-level CPA is \u20ac{account_cpa:.2f}, which is "
                    f"{((account_cpa / TARGET_CPA) - 1) * 100:.0f}% above your \u20ac{TARGET_CPA:.0f} target. "
                    f"Review underperforming ads and consider pausing the worst performers."
                ),
                "related_entity_id": META_AD_ACCOUNT_ID,
                "related_entity_type": "account",
                "related_entity_name": "Ad Account",
                "suggested_action": "Pause worst-performing ads and reallocate budget",
                "status": "new",
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
            })

    # Only insert new alerts — clear old system alerts for today first
    if alerts:
        _supabase_delete("ads_alerts", {
            "source": "eq.system",
            "created_at": f"gte.{today_str}T00:00:00Z",
        })

    return _supabase_upsert("ads_alerts", alerts)


# ---------------------------------------------------------------------------
# Generate: ads_todos
# ---------------------------------------------------------------------------


def generate_todos(
    all_ads: List[Dict[str, Any]],
    daily_rows: List[Dict[str, Any]],
) -> int:
    """Generate action-item todos based on performance data.

    Rules:
    - < 5 active ads -> "Record more ad creatives"
    - Any ad ROAS > 5x target -> "Create variations of this winner"
    - All test ads running > 7 days -> "Refresh test creatives"
    - Retargeting audiences empty -> "Install Meta Pixel" (no impressions in retarget)

    Args:
        all_ads: All ads with status info.
        daily_rows: Raw daily ad insights from Meta.

    Returns:
        Number of todos upserted.
    """
    todos: List[Dict[str, Any]] = []
    today_str = _today_str()

    active_ads = [a for a in all_ads if a.get("status") == "ACTIVE"]
    active_count = len(active_ads)

    # Rule 1: Less than 5 active ads
    if active_count < 5:
        todos.append({
            "title": f"Record more ad creatives ({active_count} active, need at least 5)",
            "description": (
                f"You currently have {active_count} active ad(s). To properly test and scale, "
                f"you need at least 5 active creatives running. Record new hooks, angles, or formats."
            ),
            "category": "creative",
            "priority": "high" if active_count < 3 else "medium",
            "status": "pending",
            "source": "system",
            "related_metric": f"{active_count} active ads (target: 5+)",
            "due_date": (datetime.now(tz=timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d"),
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        })

    # Rule 2: Any ad with ROAS > 5x target -> create variations
    ad_7d_agg: Dict[str, Dict[str, Any]] = {}
    for row in daily_rows:
        aid = row.get("ad_id", "")
        if aid not in ad_7d_agg:
            ad_7d_agg[aid] = {
                "ad_name": row.get("ad_name", "Unknown"),
                "spend": 0.0,
                "revenue": 0.0,
                "campaign_id": row.get("campaign_id", ""),
            }
        ad_7d_agg[aid]["spend"] += _safe_float(row.get("spend"))
        ad_7d_agg[aid]["revenue"] += _extract_revenue(row.get("action_values"))

    for aid, agg in ad_7d_agg.items():
        if agg["spend"] > 0:
            roas_7d = agg["revenue"] / agg["spend"]
            if roas_7d > TARGET_ROAS * 5:
                todos.append({
                    "title": f"Create variations of winner: '{agg['ad_name']}'",
                    "description": (
                        f"Ad '{agg['ad_name']}' has a 7-day ROAS of {roas_7d:.1f}x "
                        f"(target: {TARGET_ROAS}x). Create 2-3 variations with different hooks "
                        f"or formats to test if you can replicate this success."
                    ),
                    "category": "scaling",
                    "priority": "high",
                    "status": "pending",
                    "source": "system",
                    "related_ad_id": aid,
                    "related_campaign": CAMPAIGN_TYPE_BY_ID.get(agg["campaign_id"], "unknown"),
                    "related_metric": f"ROAS {roas_7d:.1f}x over 7 days",
                    "due_date": (datetime.now(tz=timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%d"),
                    "created_at": datetime.now(tz=timezone.utc).isoformat(),
                    "creative_brief": (
                        f"Take the winning ad '{agg['ad_name']}' and create variations:\n"
                        f"1. Same hook, different format (if video -> static, or vice versa)\n"
                        f"2. Same message, different opening hook\n"
                        f"3. Same visual style, different angle/copy"
                    ),
                })

    # Rule 3: All test ads running > 7 days -> refresh
    test_campaign_id = CAMPAIGN_IDS.get("test", "")
    test_ads_in_daily = [r for r in daily_rows if r.get("campaign_id") == test_campaign_id]
    if test_ads_in_daily:
        test_ad_ids = set(r.get("ad_id", "") for r in test_ads_in_daily)
        # Count unique days per test ad
        test_ad_days: Dict[str, set] = {}
        for r in test_ads_in_daily:
            aid = r.get("ad_id", "")
            test_ad_days.setdefault(aid, set()).add(r.get("date_start", ""))

        all_stale = all(len(days) >= 7 for days in test_ad_days.values()) if test_ad_days else False
        if all_stale and len(test_ad_ids) > 0:
            todos.append({
                "title": "Refresh test creatives — all tests have been running 7+ days",
                "description": (
                    f"All {len(test_ad_ids)} test ad(s) have been running for 7+ days. "
                    f"Test creatives should be rotated regularly to avoid fatigue and keep "
                    f"discovering new winning angles."
                ),
                "category": "creative",
                "priority": "medium",
                "status": "pending",
                "source": "system",
                "related_campaign": "test",
                "related_metric": f"{len(test_ad_ids)} test ads all running 7+ days",
                "due_date": (datetime.now(tz=timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d"),
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
            })

    # Rule 4: Retargeting has no impressions -> pixel not firing
    retarget_campaign_id = CAMPAIGN_IDS.get("retarget", "")
    retarget_rows = [r for r in daily_rows if r.get("campaign_id") == retarget_campaign_id]
    retarget_impressions = sum(_safe_int(r.get("impressions")) for r in retarget_rows)
    if retarget_impressions == 0 and retarget_campaign_id:
        todos.append({
            "title": "Install Meta Pixel on your webinar page",
            "description": (
                "Your retargeting campaigns have 0 impressions, which likely means the Meta Pixel "
                "is not installed or not firing correctly on your webinar registration page. "
                "Without the pixel, retargeting audiences cannot be built."
            ),
            "category": "setup",
            "priority": "critical",
            "status": "pending",
            "source": "system",
            "related_campaign": "retarget",
            "related_metric": "0 retargeting impressions in last 7 days",
            "due_date": today_str,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        })

    # Clear old system-generated todos for today before inserting
    if todos:
        _supabase_delete("ads_todos", {
            "source": "eq.system",
            "status": "eq.pending",
            "created_at": f"gte.{today_str}T00:00:00Z",
        })

    # Normalize all todo dicts to have the same keys (PostgREST requirement)
    if todos:
        all_keys: set = set()
        for t in todos:
            all_keys.update(t.keys())
        for t in todos:
            for k in all_keys:
                t.setdefault(k, None)

    return _supabase_upsert("ads_todos", todos)


# ---------------------------------------------------------------------------
# Generate: ads_funnel_metrics
# ---------------------------------------------------------------------------


def sync_funnel_metrics(today_ads: List[Dict[str, Any]]) -> int:
    """Calculate and upsert today's funnel metrics.

    We can only fill ad-level funnel data from Meta (top of funnel).
    Page visitor / registration / webinar data would come from other sources.

    Args:
        today_ads: Ad-level insights for today.

    Returns:
        Number of rows upserted.
    """
    today_str = _today_str()

    impressions = sum(_safe_int(r.get("impressions")) for r in today_ads)
    clicks = sum(_safe_int(r.get("clicks")) for r in today_ads)
    spend = sum(_safe_float(r.get("spend")) for r in today_ads)
    conversions = sum(_extract_conversions(r.get("actions")) for r in today_ads)
    revenue = sum(_extract_revenue(r.get("action_values")) for r in today_ads)

    # Registrations are the primary conversion event for the funnel
    registrations = conversions
    cost_per_lead = spend / registrations if registrations > 0 else None

    # Sales and revenue from purchase events
    sales = 0
    for r in today_ads:
        actions = r.get("actions") or []
        for a in actions:
            if a.get("action_type") in ("purchase", "omni_purchase",
                                         "offsite_conversion.fb_pixel_purchase"):
                sales += _safe_int(a.get("value"))

    cost_per_sale = spend / sales if sales > 0 else None
    roas = revenue / spend if spend > 0 else None

    row = {
        "date": today_str,
        "ad_impressions": impressions,
        "ad_clicks": clicks,
        "ad_spend": round(spend, 2),
        "registrations": registrations,
        "cost_per_lead": round(cost_per_lead, 2) if cost_per_lead is not None else None,
        "sales": sales,
        "revenue": round(revenue, 2),
        "cost_per_sale": round(cost_per_sale, 2) if cost_per_sale is not None else None,
        "roas": round(roas, 2) if roas is not None else None,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    return _supabase_upsert("ads_funnel_metrics", [row])


# ---------------------------------------------------------------------------
# Sync: ad creative details → ads_creative_pipeline
# ---------------------------------------------------------------------------


def _sync_ad_creatives_to_pipeline(
    all_ads: List[Dict[str, Any]],
    daily_insights: List[Dict[str, Any]],
) -> int:
    """Sync ad creative details (image, copy, performance) to the pipeline table.

    This makes the dashboard self-contained — you can see what each ad
    looks like and says without opening Meta Ads Manager.
    """
    if not all_ads:
        return 0

    # Build 7d performance lookup per ad
    ad_perf: Dict[str, Dict[str, float]] = {}
    for row in daily_insights:
        aid = row.get("ad_id", "")
        if aid not in ad_perf:
            ad_perf[aid] = {"spend": 0, "impressions": 0, "clicks": 0, "conversions": 0, "revenue": 0}
        ad_perf[aid]["spend"] += _safe_float(row.get("spend"))
        ad_perf[aid]["impressions"] += _safe_int(row.get("impressions"))
        ad_perf[aid]["clicks"] += _safe_int(row.get("clicks"))
        ad_perf[aid]["conversions"] += _extract_conversions(row.get("actions"))
        ad_perf[aid]["revenue"] += _extract_revenue(row.get("action_values"))

    rows: List[Dict[str, Any]] = []
    now_iso = datetime.now(tz=timezone.utc).isoformat()

    for ad in all_ads:
        ad_id = ad.get("id", "")
        ad_name = ad.get("name", "")
        status = ad.get("status", "PAUSED")
        campaign_id = ad.get("campaign_id", "")
        creative = ad.get("creative", {})

        # Extract creative details
        creative_id = creative.get("id", "") if isinstance(creative, dict) else ""
        oss = creative.get("object_story_spec", {}) if isinstance(creative, dict) else {}
        link_data = oss.get("link_data", {}) if isinstance(oss, dict) else {}

        image_url = (
            link_data.get("image_url")
            or link_data.get("picture")
            or (creative.get("image_url") if isinstance(creative, dict) else None)
            or (creative.get("thumbnail_url") if isinstance(creative, dict) else None)
            or ""
        )
        primary_text = link_data.get("message", "") if isinstance(link_data, dict) else ""
        headline = link_data.get("name", "") if isinstance(link_data, dict) else ""
        body = creative.get("body", "") if isinstance(creative, dict) else ""
        title = creative.get("title", "") if isinstance(creative, dict) else ""

        # 7d performance
        perf = ad_perf.get(ad_id, {})
        spend = perf.get("spend", 0)
        conversions = perf.get("conversions", 0)
        revenue = perf.get("revenue", 0)
        impressions = perf.get("impressions", 0)
        clicks = perf.get("clicks", 0)

        cpa = spend / conversions if conversions > 0 else None
        roas = revenue / spend if spend > 0 else None
        ctr = (clicks / impressions * 100) if impressions > 0 else None

        # Determine performance verdict
        if spend < 5:
            verdict = None
        elif roas and roas > TARGET_ROAS:
            verdict = "winner"
        elif cpa and cpa < TARGET_CPA:
            verdict = "winner"
        elif cpa and cpa > TARGET_CPA * 2:
            verdict = "loser"
        else:
            verdict = "average"

        # Map status
        pipeline_status = "live" if status == "ACTIVE" else "paused" if status == "PAUSED" else "killed"

        row = {
            "title": ad_name,
            "format": "static",
            "status": pipeline_status,
            "assigned_ad_id": ad_id,
            "image_url": image_url,
            "primary_text": primary_text or body,
            "headline": headline or title,
            "actual_cpa": round(cpa, 2) if cpa is not None else None,
            "actual_roas": round(roas, 2) if roas is not None else None,
            "actual_ctr": round(ctr, 2) if ctr is not None else None,
            "actual_spend": round(spend, 2),
            "performance_verdict": verdict,
            "updated_at": now_iso,
        }
        rows.append(row)

    # Upsert by ad_id — but pipeline table doesn't have a unique on assigned_ad_id
    # So we delete existing rows for these ad IDs first, then insert fresh
    if rows:
        ad_ids = [r["assigned_ad_id"] for r in rows if r["assigned_ad_id"]]
        if ad_ids:
            # Delete existing synced rows for these ads
            for aid in ad_ids:
                _supabase_delete("ads_creative_pipeline", {
                    "assigned_ad_id": f"eq.{aid}",
                    "source": "eq.meta_sync",
                })

        # Mark source as meta_sync so we can distinguish from AI-generated ones
        for r in rows:
            r["source"] = "meta_sync"
            r["source_detail"] = "Auto-synced from Meta Ads"
            if "created_at" not in r:
                r["created_at"] = now_iso

        return _supabase_upsert("ads_creative_pipeline", rows)

    return 0


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def run_sync() -> Dict[str, Any]:
    """Run the full sync: Meta API -> Supabase.

    Steps:
        a. Pull campaign-level insights (7d and 30d)
        b. Pull ad-set-level insights (7d)
        c. Pull ad-level insights (today, 7d with daily breakdown)
        d. Calculate derived metrics (hook_rate, hold_rate, CPA, ROAS)
        e. Upsert into ads_daily_performance
        f. Upsert into ads_campaign_status with health indicators
        g. Upsert the single ads_dashboard row
        h. Generate alerts
        i. Generate todos
        j. Calculate funnel metrics for today

    Returns:
        Summary dict with counts and timing.
    """
    logger.info("=" * 60)
    logger.info("Starting Meta Ads -> Supabase sync")
    logger.info("=" * 60)
    start_time = time.time()

    summary: Dict[str, Any] = {
        "started_at": datetime.now(tz=timezone.utc).isoformat(),
        "errors": [],
    }

    # Validate config
    if not META_ACCESS_TOKEN:
        raise RuntimeError("META_ACCESS_TOKEN not set in environment")
    if not META_AD_ACCOUNT_ID:
        raise RuntimeError("META_AD_ACCOUNT_ID not set in environment")
    if not SUPABASE_URL:
        raise RuntimeError("SUPABASE_URL_BACKOFFICE not set in environment")
    if not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_KEY_BACKOFFICE not set in environment")

    # ------------------------------------------------------------------
    # Step a: Campaign-level insights (7d and 30d)
    # ------------------------------------------------------------------
    logger.info("[1/10] Fetching campaign insights (7d)...")
    try:
        campaign_insights_7d = fetch_campaign_insights("last_7d")
        logger.info("  -> %d campaign rows (7d)", len(campaign_insights_7d))
    except Exception as exc:
        logger.error("  -> Failed: %s", exc)
        campaign_insights_7d = []
        summary["errors"].append(f"campaign_insights_7d: {exc}")

    logger.info("[2/10] Fetching campaign insights (30d)...")
    try:
        campaign_insights_30d = fetch_campaign_insights("last_30d")
        logger.info("  -> %d campaign rows (30d)", len(campaign_insights_30d))
    except Exception as exc:
        logger.error("  -> Failed: %s", exc)
        campaign_insights_30d = []
        summary["errors"].append(f"campaign_insights_30d: {exc}")

    # ------------------------------------------------------------------
    # Step b: Ad-set-level insights (7d)
    # ------------------------------------------------------------------
    logger.info("[3/10] Fetching ad-set insights (7d)...")
    try:
        adset_insights_7d = fetch_adset_insights("last_7d")
        logger.info("  -> %d ad-set rows (7d)", len(adset_insights_7d))
    except Exception as exc:
        logger.error("  -> Failed: %s", exc)
        adset_insights_7d = []
        summary["errors"].append(f"adset_insights_7d: {exc}")

    # ------------------------------------------------------------------
    # Step c: Ad-level insights (today + 7d daily breakdown)
    # ------------------------------------------------------------------
    logger.info("[4/10] Fetching ad insights (today)...")
    try:
        ad_insights_today = fetch_ad_insights_today()
        logger.info("  -> %d ad rows (today)", len(ad_insights_today))
    except Exception as exc:
        logger.error("  -> Failed: %s", exc)
        ad_insights_today = []
        summary["errors"].append(f"ad_insights_today: {exc}")

    logger.info("[5/10] Fetching ad insights (7d daily)...")
    try:
        ad_insights_daily = fetch_ad_insights_daily(days=7)
        logger.info("  -> %d ad-day rows (7d)", len(ad_insights_daily))
    except Exception as exc:
        logger.error("  -> Failed: %s", exc)
        ad_insights_daily = []
        summary["errors"].append(f"ad_insights_daily: {exc}")

    # ------------------------------------------------------------------
    # Step c (cont): Fetch all ads & campaign details
    # ------------------------------------------------------------------
    logger.info("[5.5/10] Fetching ad statuses and campaign details...")
    try:
        all_ads = fetch_active_ads()
        logger.info("  -> %d total ads", len(all_ads))
    except Exception as exc:
        logger.error("  -> Failed: %s", exc)
        all_ads = []
        summary["errors"].append(f"all_ads: {exc}")

    try:
        campaign_details = fetch_campaign_details()
        logger.info("  -> %d campaigns", len(campaign_details))
    except Exception as exc:
        logger.error("  -> Failed: %s", exc)
        campaign_details = []
        summary["errors"].append(f"campaign_details: {exc}")

    # ------------------------------------------------------------------
    # Step d-e: Upsert ads_daily_performance
    # ------------------------------------------------------------------
    logger.info("[6/10] Syncing ads_daily_performance...")
    try:
        daily_count = sync_daily_performance(ad_insights_daily)
        summary["daily_performance_rows"] = daily_count
        logger.info("  -> %d rows upserted", daily_count)
    except Exception as exc:
        logger.error("  -> Failed: %s", exc)
        summary["daily_performance_rows"] = 0
        summary["errors"].append(f"daily_performance: {exc}")

    # ------------------------------------------------------------------
    # Step f: Upsert ads_campaign_status
    # ------------------------------------------------------------------
    logger.info("[7/10] Syncing ads_campaign_status...")
    try:
        # For campaign-level "today" insights we pull separately
        campaign_today = fetch_campaign_insights("today")
        campaign_count = sync_campaign_status(
            campaign_details, campaign_insights_7d, campaign_insights_30d, campaign_today,
        )
        summary["campaign_status_rows"] = campaign_count
        logger.info("  -> %d rows upserted", campaign_count)
    except Exception as exc:
        logger.error("  -> Failed: %s", exc)
        summary["campaign_status_rows"] = 0
        summary["errors"].append(f"campaign_status: {exc}")

    # ------------------------------------------------------------------
    # Step g: Upsert ads_dashboard
    # ------------------------------------------------------------------
    logger.info("[8/10] Syncing ads_dashboard...")
    try:
        dash_count = sync_dashboard(ad_insights_today, ad_insights_daily, all_ads)
        summary["dashboard_rows"] = dash_count
        logger.info("  -> %d row upserted", dash_count)
    except Exception as exc:
        logger.error("  -> Failed: %s", exc)
        summary["dashboard_rows"] = 0
        summary["errors"].append(f"dashboard: {exc}")

    # ------------------------------------------------------------------
    # Step h: Generate alerts
    # ------------------------------------------------------------------
    logger.info("[9/10] Generating alerts...")
    try:
        alert_count = generate_alerts(ad_insights_daily, ad_insights_today)
        summary["alerts_generated"] = alert_count
        logger.info("  -> %d alerts generated", alert_count)
    except Exception as exc:
        logger.error("  -> Failed: %s", exc)
        summary["alerts_generated"] = 0
        summary["errors"].append(f"alerts: {exc}")

    # ------------------------------------------------------------------
    # Step i: Generate todos
    # ------------------------------------------------------------------
    logger.info("[9.5/10] Generating todos...")
    try:
        todo_count = generate_todos(all_ads, ad_insights_daily)
        summary["todos_generated"] = todo_count
        logger.info("  -> %d todos generated", todo_count)
    except Exception as exc:
        logger.error("  -> Failed: %s", exc)
        summary["todos_generated"] = 0
        summary["errors"].append(f"todos: {exc}")

    # ------------------------------------------------------------------
    # Step j: Funnel metrics
    # ------------------------------------------------------------------
    logger.info("[10/10] Syncing funnel metrics...")
    try:
        funnel_count = sync_funnel_metrics(ad_insights_today)
        summary["funnel_rows"] = funnel_count
        logger.info("  -> %d row upserted", funnel_count)
    except Exception as exc:
        logger.error("  -> Failed: %s", exc)
        summary["funnel_rows"] = 0
        summary["errors"].append(f"funnel: {exc}")

    # ------------------------------------------------------------------
    # Step k: Sync ad creative details to pipeline (image, copy, status)
    # ------------------------------------------------------------------
    logger.info("[11/11] Syncing ad creative details to pipeline...")
    try:
        creative_count = _sync_ad_creatives_to_pipeline(all_ads, ad_insights_daily)
        summary["creatives_synced"] = creative_count
        logger.info("  -> %d creatives synced", creative_count)
    except Exception as exc:
        logger.error("  -> Failed: %s", exc)
        summary["creatives_synced"] = 0
        summary["errors"].append(f"creatives: {exc}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    elapsed = time.time() - start_time
    summary["elapsed_seconds"] = round(elapsed, 1)
    summary["success"] = len(summary["errors"]) == 0

    _print_summary(summary)

    return summary


def _print_summary(summary: Dict[str, Any]) -> None:
    """Print a human-readable summary of the sync run."""
    print()
    print("=" * 60)
    print("  META ADS -> SUPABASE SYNC COMPLETE")
    print("=" * 60)
    print()
    print(f"  Time:                  {summary.get('elapsed_seconds', 0):.1f}s")
    print(f"  Daily performance:     {summary.get('daily_performance_rows', 0)} rows")
    print(f"  Campaign status:       {summary.get('campaign_status_rows', 0)} rows")
    print(f"  Dashboard:             {summary.get('dashboard_rows', 0)} row")
    print(f"  Alerts generated:      {summary.get('alerts_generated', 0)}")
    print(f"  Todos generated:       {summary.get('todos_generated', 0)}")
    print(f"  Funnel metrics:        {summary.get('funnel_rows', 0)} row")
    print()

    errors = summary.get("errors", [])
    if errors:
        print(f"  ERRORS ({len(errors)}):")
        for err in errors:
            print(f"    - {err}")
        print()
    else:
        print("  Status: ALL OK")
        print()

    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        result = run_sync()
        if not result["success"]:
            sys.exit(1)
    except Exception:
        logger.exception("Sync failed with unhandled exception")
        sys.exit(1)
