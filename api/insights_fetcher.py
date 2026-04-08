"""
Pull performance data from the Meta Marketing API.

Provides campaign-, ad-set-, and ad-level insights as well as creative
metadata.  All methods return plain dicts / lists so downstream code
(rules engine, reports, pandas analysis) never touches SDK objects.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.adcreative import AdCreative
from facebook_business.exceptions import FacebookRequestError

from api.meta_client import MetaClient
from config.settings import BACKFILL_DAYS

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------
# Standard insight fields requested on every pull
# -----------------------------------------------------------------
INSIGHT_FIELDS: list[str] = [
    "campaign_id",
    "campaign_name",
    "adset_id",
    "adset_name",
    "ad_id",
    "ad_name",
    "spend",
    "impressions",
    "reach",
    "frequency",
    "clicks",
    "ctr",
    "cpc",
    "cpm",
    "actions",
    "cost_per_action_type",
    "action_values",
    "video_p25_watched_actions",
    "video_p50_watched_actions",
    "video_p75_watched_actions",
    "video_p100_watched_actions",
    "video_play_actions",
]

# Fields for creative metadata
CREATIVE_FIELDS: list[str] = [
    "id",
    "name",
    "body",
    "title",
    "image_url",
    "image_hash",
    "video_id",
    "thumbnail_url",
    "effective_object_story_id",
    "object_story_spec",
    "call_to_action_type",
    "status",
]


def _time_range(date_start: str, date_end: str) -> dict[str, str]:
    """Build the ``time_range`` param dict Meta expects.

    Parameters
    ----------
    date_start : str
        Start date in ``YYYY-MM-DD`` format.
    date_end : str
        End date in ``YYYY-MM-DD`` format.
    """
    return {"since": date_start, "until": date_end}


def _parse_actions(actions: list[dict[str, Any]] | None) -> dict[str, float]:
    """Flatten the ``actions`` list into ``{action_type: value}``."""
    if not actions:
        return {}
    return {a["action_type"]: float(a.get("value", 0)) for a in actions}


def _parse_cost_per_action(
    cost_per_action: list[dict[str, Any]] | None,
) -> dict[str, float]:
    """Flatten ``cost_per_action_type`` into ``{action_type: cost}``."""
    if not cost_per_action:
        return {}
    return {a["action_type"]: float(a.get("value", 0)) for a in cost_per_action}


def _parse_action_values(
    action_values: list[dict[str, Any]] | None,
) -> dict[str, float]:
    """Flatten ``action_values`` into ``{action_type: value}``."""
    if not action_values:
        return {}
    return {a["action_type"]: float(a.get("value", 0)) for a in action_values}


def _parse_video_metric(
    entries: list[dict[str, Any]] | None,
) -> int:
    """Sum the values inside a video metric list (e.g. video_p25_watched)."""
    if not entries:
        return 0
    return sum(int(e.get("value", 0)) for e in entries)


def _normalise_row(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw insight row into a clean, flat dict.

    Numeric strings are cast to ``float`` / ``int`` and the nested
    ``actions`` / ``cost_per_action_type`` / ``action_values`` lists
    are flattened into prefixed keys.
    """
    out: dict[str, Any] = {}

    # Scalar fields
    for key in (
        "campaign_id", "campaign_name",
        "adset_id", "adset_name",
        "ad_id", "ad_name",
        "date_start", "date_stop",
    ):
        out[key] = row.get(key, "")

    # Numeric fields (Meta returns strings)
    for key in ("spend", "impressions", "reach", "clicks", "ctr", "cpc", "cpm"):
        raw = row.get(key, 0)
        try:
            out[key] = float(raw)
        except (TypeError, ValueError):
            out[key] = 0.0

    out["frequency"] = float(row.get("frequency", 0) or 0)

    # Actions breakdown
    out["actions"] = _parse_actions(row.get("actions"))
    out["cost_per_action"] = _parse_cost_per_action(row.get("cost_per_action_type"))
    out["action_values"] = _parse_action_values(row.get("action_values"))

    # Convenience shortcuts
    out["conversions"] = out["actions"].get("offsite_conversion.fb_pixel_purchase", 0)
    out["leads"] = out["actions"].get("lead", 0)
    out["link_clicks"] = out["actions"].get("link_click", 0)
    purchase_value = out["action_values"].get(
        "offsite_conversion.fb_pixel_purchase", 0
    )
    out["purchase_value"] = purchase_value
    out["roas"] = purchase_value / out["spend"] if out["spend"] > 0 else 0.0
    out["cpa"] = (
        out["cost_per_action"].get("offsite_conversion.fb_pixel_purchase", 0)
        or (out["spend"] / out["conversions"] if out["conversions"] > 0 else 0.0)
    )

    # Video metrics
    out["video_p25"] = _parse_video_metric(row.get("video_p25_watched_actions"))
    out["video_p50"] = _parse_video_metric(row.get("video_p50_watched_actions"))
    out["video_p75"] = _parse_video_metric(row.get("video_p75_watched_actions"))
    out["video_p100"] = _parse_video_metric(row.get("video_p100_watched_actions"))
    out["video_plays"] = _parse_video_metric(row.get("video_play_actions"))

    # Hook & hold rates (if video data available)
    if out["impressions"] > 0 and out["video_plays"] > 0:
        out["hook_rate"] = (out["video_plays"] / out["impressions"]) * 100
    else:
        out["hook_rate"] = 0.0

    if out["video_plays"] > 0 and out["video_p75"] > 0:
        out["hold_rate"] = (out["video_p75"] / out["video_plays"]) * 100
    else:
        out["hold_rate"] = 0.0

    return out


# ==================================================================
# Public API
# ==================================================================


def fetch_campaign_insights(
    date_start: str,
    date_end: str,
) -> list[dict[str, Any]]:
    """Fetch campaign-level insights for the given date range.

    Parameters
    ----------
    date_start : str
        ``YYYY-MM-DD``
    date_end : str
        ``YYYY-MM-DD``

    Returns
    -------
    list[dict]
        One normalised dict per campaign per day.
    """
    client = MetaClient()
    account = client.get_account()

    params = {
        "time_range": _time_range(date_start, date_end),
        "time_increment": 1,  # daily breakdown
        "level": "campaign",
    }

    # Filter fields to campaign-relevant ones (no ad_id etc.)
    fields = [
        f for f in INSIGHT_FIELDS
        if f not in ("adset_id", "adset_name", "ad_id", "ad_name")
    ]

    try:
        cursor = client.rate_limited_request(
            account.get_insights, fields=fields, params=params
        )
        raw_rows = client.exhaust_pagination(cursor)
        logger.info(
            "Fetched %d campaign-level rows for %s to %s",
            len(raw_rows), date_start, date_end,
        )
        return [_normalise_row(r) for r in raw_rows]
    except FacebookRequestError as exc:
        logger.error(
            "Failed to fetch campaign insights: [%s] %s",
            exc.api_error_code(), exc.api_error_message(),
        )
        raise


def fetch_adset_insights(
    date_start: str,
    date_end: str,
) -> list[dict[str, Any]]:
    """Fetch ad-set-level insights for the given date range.

    Parameters
    ----------
    date_start : str
        ``YYYY-MM-DD``
    date_end : str
        ``YYYY-MM-DD``

    Returns
    -------
    list[dict]
        One normalised dict per ad set per day.
    """
    client = MetaClient()
    account = client.get_account()

    params = {
        "time_range": _time_range(date_start, date_end),
        "time_increment": 1,
        "level": "adset",
    }

    fields = [
        f for f in INSIGHT_FIELDS
        if f not in ("ad_id", "ad_name")
    ]

    try:
        cursor = client.rate_limited_request(
            account.get_insights, fields=fields, params=params
        )
        raw_rows = client.exhaust_pagination(cursor)
        logger.info(
            "Fetched %d ad-set-level rows for %s to %s",
            len(raw_rows), date_start, date_end,
        )
        return [_normalise_row(r) for r in raw_rows]
    except FacebookRequestError as exc:
        logger.error(
            "Failed to fetch adset insights: [%s] %s",
            exc.api_error_code(), exc.api_error_message(),
        )
        raise


def fetch_ad_insights(
    date_start: str,
    date_end: str,
) -> list[dict[str, Any]]:
    """Fetch ad-level insights (most granular) for the given date range.

    Parameters
    ----------
    date_start : str
        ``YYYY-MM-DD``
    date_end : str
        ``YYYY-MM-DD``

    Returns
    -------
    list[dict]
        One normalised dict per ad per day.
    """
    client = MetaClient()
    account = client.get_account()

    params = {
        "time_range": _time_range(date_start, date_end),
        "time_increment": 1,
        "level": "ad",
    }

    try:
        cursor = client.rate_limited_request(
            account.get_insights, fields=INSIGHT_FIELDS, params=params
        )
        raw_rows = client.exhaust_pagination(cursor)
        logger.info(
            "Fetched %d ad-level rows for %s to %s",
            len(raw_rows), date_start, date_end,
        )
        return [_normalise_row(r) for r in raw_rows]
    except FacebookRequestError as exc:
        logger.error(
            "Failed to fetch ad insights: [%s] %s",
            exc.api_error_code(), exc.api_error_message(),
        )
        raise


def fetch_ad_creatives(
    campaign_id: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch creative details (thumbnail, video URL, body text, etc.).

    Parameters
    ----------
    campaign_id : str, optional
        If given, only return creatives attached to ads in this campaign.
        Otherwise return all creatives in the account.

    Returns
    -------
    list[dict]
        Creative metadata dicts.
    """
    client = MetaClient()
    account = client.get_account()

    try:
        if campaign_id:
            # Get ads from the specific campaign, then their creatives
            campaign = Campaign(campaign_id)
            ads_cursor = client.rate_limited_request(
                campaign.get_ads, fields=["id", "creative"]
            )
            ads = client.exhaust_pagination(ads_cursor)

            creatives: list[dict[str, Any]] = []
            for ad_data in ads:
                creative_ref = ad_data.get("creative")
                if not creative_ref:
                    continue
                creative_id = (
                    creative_ref.get("id")
                    if isinstance(creative_ref, dict)
                    else str(creative_ref)
                )
                if not creative_id:
                    continue
                try:
                    creative_obj = AdCreative(creative_id)
                    info = client.rate_limited_request(
                        creative_obj.api_get, fields=CREATIVE_FIELDS
                    )
                    creatives.append(dict(info))
                except FacebookRequestError as inner_exc:
                    logger.warning(
                        "Could not fetch creative %s: %s",
                        creative_id, inner_exc.api_error_message(),
                    )
            logger.info(
                "Fetched %d creatives for campaign %s", len(creatives), campaign_id
            )
            return creatives
        else:
            cursor = client.rate_limited_request(
                account.get_ad_creatives, fields=CREATIVE_FIELDS
            )
            results = client.exhaust_pagination(cursor)
            logger.info("Fetched %d creatives from account", len(results))
            return results

    except FacebookRequestError as exc:
        logger.error(
            "Failed to fetch creatives: [%s] %s",
            exc.api_error_code(), exc.api_error_message(),
        )
        raise


def backfill(days: int = BACKFILL_DAYS) -> dict[str, list[dict[str, Any]]]:
    """Pull historical data for the last *days* days at all levels.

    Splits the range into 30-day chunks to stay within Meta's limits
    on a single insights request.

    Parameters
    ----------
    days : int
        Number of historical days to fetch (default from settings).

    Returns
    -------
    dict
        ``{"campaigns": [...], "adsets": [...], "ads": [...]}``
    """
    today = datetime.now(tz=timezone.utc).date()
    start = today - timedelta(days=days)

    all_campaigns: list[dict[str, Any]] = []
    all_adsets: list[dict[str, Any]] = []
    all_ads: list[dict[str, Any]] = []

    # Process in 30-day windows to avoid API timeouts / limits
    chunk_days = 30
    chunk_start = start

    while chunk_start < today:
        chunk_end = min(chunk_start + timedelta(days=chunk_days - 1), today)
        ds = chunk_start.isoformat()
        de = chunk_end.isoformat()

        logger.info("Backfilling chunk %s to %s …", ds, de)

        try:
            all_campaigns.extend(fetch_campaign_insights(ds, de))
        except Exception:
            logger.exception("Campaign backfill failed for %s–%s", ds, de)

        try:
            all_adsets.extend(fetch_adset_insights(ds, de))
        except Exception:
            logger.exception("Adset backfill failed for %s–%s", ds, de)

        try:
            all_ads.extend(fetch_ad_insights(ds, de))
        except Exception:
            logger.exception("Ad backfill failed for %s–%s", ds, de)

        chunk_start = chunk_end + timedelta(days=1)

    logger.info(
        "Backfill complete: %d campaign rows, %d adset rows, %d ad rows",
        len(all_campaigns), len(all_adsets), len(all_ads),
    )

    return {
        "campaigns": all_campaigns,
        "adsets": all_adsets,
        "ads": all_ads,
    }
