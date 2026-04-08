"""
SQLite database manager for the Meta Ads Management System.

Handles schema creation, CRUD operations for all entities, and computed
metric queries. Uses parameterized queries exclusively and context-managed
connections for safety.
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple

from config.settings import DB_PATH
from data.models import (
    AdData,
    AdInsight,
    AdSetData,
    CampaignData,
    CommunityAngle,
    CreativeTag,
    RuleExecution,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager that yields a sqlite3 connection with row_factory set
    to sqlite3.Row for dict-like access. Commits on success, rolls back on
    exception, and always closes the connection.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------


def init_db() -> None:
    """
    Create all tables and indexes if they do not already exist.
    Safe to call multiple times (idempotent).
    """
    with get_connection() as conn:
        cur = conn.cursor()

        # -- Campaigns --
        cur.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                campaign_id   TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'ACTIVE',
                objective     TEXT DEFAULT '',
                daily_budget  REAL DEFAULT 0.0,
                lifetime_budget REAL DEFAULT 0.0,
                campaign_type TEXT DEFAULT 'test',
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
        """)

        # -- Ad Sets --
        cur.execute("""
            CREATE TABLE IF NOT EXISTS adsets (
                adset_id          TEXT PRIMARY KEY,
                campaign_id       TEXT NOT NULL,
                name              TEXT NOT NULL,
                status            TEXT NOT NULL DEFAULT 'ACTIVE',
                daily_budget      REAL DEFAULT 0.0,
                optimization_goal TEXT DEFAULT '',
                targeting_summary TEXT DEFAULT '',
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id)
            )
        """)

        # -- Ads --
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ads (
                ad_id       TEXT PRIMARY KEY,
                adset_id    TEXT NOT NULL,
                campaign_id TEXT NOT NULL,
                name        TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'ACTIVE',
                creative_id TEXT DEFAULT '',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                FOREIGN KEY (adset_id) REFERENCES adsets(adset_id),
                FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id)
            )
        """)

        # -- Ad Insights (one row per ad per day) --
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ad_insights (
                ad_id            TEXT NOT NULL,
                date             TEXT NOT NULL,
                spend            REAL DEFAULT 0.0,
                impressions      INTEGER DEFAULT 0,
                reach            INTEGER DEFAULT 0,
                frequency        REAL DEFAULT 0.0,
                clicks           INTEGER DEFAULT 0,
                ctr              REAL DEFAULT 0.0,
                cpc              REAL DEFAULT 0.0,
                cpm              REAL DEFAULT 0.0,
                conversions      INTEGER DEFAULT 0,
                cpa              REAL DEFAULT 0.0,
                revenue          REAL DEFAULT 0.0,
                roas             REAL DEFAULT 0.0,
                video_views_3s   INTEGER DEFAULT 0,
                video_views_15s  INTEGER DEFAULT 0,
                video_views_p25  INTEGER DEFAULT 0,
                video_views_p50  INTEGER DEFAULT 0,
                video_views_p75  INTEGER DEFAULT 0,
                video_views_p100 INTEGER DEFAULT 0,
                PRIMARY KEY (ad_id, date),
                FOREIGN KEY (ad_id) REFERENCES ads(ad_id)
            )
        """)

        # -- Creative Tags --
        cur.execute("""
            CREATE TABLE IF NOT EXISTS creative_tags (
                creative_id          TEXT NOT NULL,
                ad_id                TEXT NOT NULL,
                format               TEXT DEFAULT '',
                hook_type            TEXT DEFAULT '',
                angle                TEXT DEFAULT '',
                has_text_overlay     INTEGER DEFAULT 0,
                has_testimonial      INTEGER DEFAULT 0,
                video_length_seconds INTEGER DEFAULT 0,
                body_text            TEXT DEFAULT '',
                headline             TEXT DEFAULT '',
                cta_type             TEXT DEFAULT '',
                source               TEXT DEFAULT 'manual',
                tags                 TEXT DEFAULT '[]',
                created_at           TEXT NOT NULL,
                PRIMARY KEY (creative_id, ad_id)
            )
        """)

        # -- Rule Executions --
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rule_executions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_name     TEXT NOT NULL,
                rule_type     TEXT NOT NULL,
                entity_id     TEXT NOT NULL,
                entity_type   TEXT NOT NULL,
                action_taken  TEXT NOT NULL,
                details       TEXT DEFAULT '',
                executed_at   TEXT NOT NULL
            )
        """)

        # -- Community Angles --
        cur.execute("""
            CREATE TABLE IF NOT EXISTS community_angles (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type       TEXT NOT NULL,
                source_text       TEXT NOT NULL,
                suggested_hook    TEXT DEFAULT '',
                suggested_angle   TEXT DEFAULT '',
                hook_category     TEXT DEFAULT '',
                used_in_ad_id     TEXT DEFAULT '',
                performance_score REAL DEFAULT 0.0,
                created_at        TEXT NOT NULL,
                status            TEXT NOT NULL DEFAULT 'new'
            )
        """)

        # -- Indexes for frequent queries --
        _create_indexes(cur)

        logger.info("Database initialised at %s", DB_PATH)


def _create_indexes(cur: sqlite3.Cursor) -> None:
    """Create performance indexes (idempotent)."""
    indexes = [
        ("idx_campaigns_status",        "campaigns",        "status"),
        ("idx_campaigns_type",          "campaigns",        "campaign_type"),
        ("idx_adsets_campaign_id",      "adsets",           "campaign_id"),
        ("idx_adsets_status",           "adsets",           "status"),
        ("idx_ads_adset_id",            "ads",              "adset_id"),
        ("idx_ads_campaign_id",         "ads",              "campaign_id"),
        ("idx_ads_status",              "ads",              "status"),
        ("idx_insights_ad_id",          "ad_insights",      "ad_id"),
        ("idx_insights_date",           "ad_insights",      "date"),
        ("idx_creative_tags_ad_id",     "creative_tags",    "ad_id"),
        ("idx_creative_tags_format",    "creative_tags",    "format"),
        ("idx_creative_tags_hook_type", "creative_tags",    "hook_type"),
        ("idx_rule_exec_entity",        "rule_executions",  "entity_id"),
        ("idx_rule_exec_type",          "rule_executions",  "rule_type"),
        ("idx_rule_exec_at",            "rule_executions",  "executed_at"),
        ("idx_community_status",        "community_angles", "status"),
    ]
    for name, table, column in indexes:
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"
        )


# ---------------------------------------------------------------------------
# Helper: date range
# ---------------------------------------------------------------------------


def _date_n_days_ago(days: int) -> str:
    """Return ISO date string for N days before today."""
    return (datetime.now(tz=timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


# ===================================================================
#  CAMPAIGN CRUD
# ===================================================================


def save_campaign(data: CampaignData) -> None:
    """
    Insert or update a campaign. Uses upsert semantics:
    if campaign_id already exists, all fields are overwritten.
    """
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO campaigns
                (campaign_id, name, status, objective, daily_budget,
                 lifetime_budget, campaign_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(campaign_id) DO UPDATE SET
                name=excluded.name,
                status=excluded.status,
                objective=excluded.objective,
                daily_budget=excluded.daily_budget,
                lifetime_budget=excluded.lifetime_budget,
                campaign_type=excluded.campaign_type,
                updated_at=excluded.updated_at
            """,
            (
                data.campaign_id, data.name, data.status, data.objective,
                data.daily_budget, data.lifetime_budget, data.campaign_type,
                data.created_at, data.updated_at,
            ),
        )
    logger.debug("Saved campaign %s", data.campaign_id)


def get_campaign(campaign_id: str) -> Optional[CampaignData]:
    """Fetch a single campaign by ID, or None if not found."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM campaigns WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
    if row is None:
        return None
    return CampaignData.from_row(row)


def list_campaigns(
    status: Optional[str] = None,
    campaign_type: Optional[str] = None,
) -> List[CampaignData]:
    """
    List campaigns with optional filters.

    Args:
        status: Filter by campaign status (e.g. "ACTIVE", "PAUSED").
        campaign_type: Filter by type ("scale", "iterate", "test", "retarget").
    """
    query = "SELECT * FROM campaigns WHERE 1=1"
    params: List[Any] = []

    if status is not None:
        query += " AND status = ?"
        params.append(status)
    if campaign_type is not None:
        query += " AND campaign_type = ?"
        params.append(campaign_type)

    query += " ORDER BY updated_at DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [CampaignData.from_row(r) for r in rows]


# ===================================================================
#  AD SET CRUD
# ===================================================================


def save_adset(data: AdSetData) -> None:
    """Insert or update an ad set (upsert on adset_id)."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO adsets
                (adset_id, campaign_id, name, status, daily_budget,
                 optimization_goal, targeting_summary, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(adset_id) DO UPDATE SET
                campaign_id=excluded.campaign_id,
                name=excluded.name,
                status=excluded.status,
                daily_budget=excluded.daily_budget,
                optimization_goal=excluded.optimization_goal,
                targeting_summary=excluded.targeting_summary,
                updated_at=excluded.updated_at
            """,
            (
                data.adset_id, data.campaign_id, data.name, data.status,
                data.daily_budget, data.optimization_goal,
                data.targeting_summary, data.created_at, data.updated_at,
            ),
        )
    logger.debug("Saved adset %s", data.adset_id)


def get_adset(adset_id: str) -> Optional[AdSetData]:
    """Fetch a single ad set by ID, or None if not found."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM adsets WHERE adset_id = ?", (adset_id,)
        ).fetchone()
    if row is None:
        return None
    return AdSetData.from_row(row)


def list_adsets(
    campaign_id: Optional[str] = None,
    status: Optional[str] = None,
) -> List[AdSetData]:
    """
    List ad sets with optional filters.

    Args:
        campaign_id: Filter by parent campaign.
        status: Filter by ad set status.
    """
    query = "SELECT * FROM adsets WHERE 1=1"
    params: List[Any] = []

    if campaign_id is not None:
        query += " AND campaign_id = ?"
        params.append(campaign_id)
    if status is not None:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY updated_at DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [AdSetData.from_row(r) for r in rows]


# ===================================================================
#  AD CRUD
# ===================================================================


def save_ad(data: AdData) -> None:
    """Insert or update an ad (upsert on ad_id)."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO ads
                (ad_id, adset_id, campaign_id, name, status,
                 creative_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ad_id) DO UPDATE SET
                adset_id=excluded.adset_id,
                campaign_id=excluded.campaign_id,
                name=excluded.name,
                status=excluded.status,
                creative_id=excluded.creative_id,
                updated_at=excluded.updated_at
            """,
            (
                data.ad_id, data.adset_id, data.campaign_id, data.name,
                data.status, data.creative_id, data.created_at,
                data.updated_at,
            ),
        )
    logger.debug("Saved ad %s", data.ad_id)


def get_ad(ad_id: str) -> Optional[AdData]:
    """Fetch a single ad by ID, or None if not found."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM ads WHERE ad_id = ?", (ad_id,)
        ).fetchone()
    if row is None:
        return None
    return AdData.from_row(row)


def list_ads(
    campaign_id: Optional[str] = None,
    adset_id: Optional[str] = None,
    status: Optional[str] = None,
) -> List[AdData]:
    """
    List ads with optional filters.

    Args:
        campaign_id: Filter by parent campaign.
        adset_id: Filter by parent ad set.
        status: Filter by ad status.
    """
    query = "SELECT * FROM ads WHERE 1=1"
    params: List[Any] = []

    if campaign_id is not None:
        query += " AND campaign_id = ?"
        params.append(campaign_id)
    if adset_id is not None:
        query += " AND adset_id = ?"
        params.append(adset_id)
    if status is not None:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY updated_at DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [AdData.from_row(r) for r in rows]


# ===================================================================
#  INSIGHTS CRUD
# ===================================================================


def save_insights(insights_list: List[AdInsight]) -> None:
    """
    Bulk upsert ad insights. Each row is keyed on (ad_id, date).
    Existing rows for the same ad + date are fully replaced.

    This is the primary method called by the daily data puller.
    """
    if not insights_list:
        return

    with get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO ad_insights
                (ad_id, date, spend, impressions, reach, frequency,
                 clicks, ctr, cpc, cpm, conversions, cpa, revenue, roas,
                 video_views_3s, video_views_15s, video_views_p25,
                 video_views_p50, video_views_p75, video_views_p100)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ad_id, date) DO UPDATE SET
                spend=excluded.spend,
                impressions=excluded.impressions,
                reach=excluded.reach,
                frequency=excluded.frequency,
                clicks=excluded.clicks,
                ctr=excluded.ctr,
                cpc=excluded.cpc,
                cpm=excluded.cpm,
                conversions=excluded.conversions,
                cpa=excluded.cpa,
                revenue=excluded.revenue,
                roas=excluded.roas,
                video_views_3s=excluded.video_views_3s,
                video_views_15s=excluded.video_views_15s,
                video_views_p25=excluded.video_views_p25,
                video_views_p50=excluded.video_views_p50,
                video_views_p75=excluded.video_views_p75,
                video_views_p100=excluded.video_views_p100
            """,
            [
                (
                    i.ad_id, i.date, i.spend, i.impressions, i.reach,
                    i.frequency, i.clicks, i.ctr, i.cpc, i.cpm,
                    i.conversions, i.cpa, i.revenue, i.roas,
                    i.video_views_3s, i.video_views_15s, i.video_views_p25,
                    i.video_views_p50, i.video_views_p75, i.video_views_p100,
                )
                for i in insights_list
            ],
        )
    logger.info("Saved %d insight rows", len(insights_list))


def get_insights(
    ad_id: Optional[str] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
) -> List[AdInsight]:
    """
    Query insights with optional filters.

    Args:
        ad_id: Filter to a specific ad.
        date_start: Inclusive start date (YYYY-MM-DD).
        date_end: Inclusive end date (YYYY-MM-DD).

    Returns:
        List of AdInsight objects ordered by date descending.
    """
    query = "SELECT * FROM ad_insights WHERE 1=1"
    params: List[Any] = []

    if ad_id is not None:
        query += " AND ad_id = ?"
        params.append(ad_id)
    if date_start is not None:
        query += " AND date >= ?"
        params.append(date_start)
    if date_end is not None:
        query += " AND date <= ?"
        params.append(date_end)

    query += " ORDER BY date DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [AdInsight.from_row(r) for r in rows]


def get_insights_summary(ad_id: str, days: int = 7) -> Optional[Dict[str, Any]]:
    """
    Return aggregated metrics for one ad over the last N days.

    Returns a dict with summed/averaged fields or None if no data exists.

    Keys: spend, impressions, reach, clicks, conversions, revenue,
          avg_ctr, avg_cpc, avg_cpm, avg_cpa, roas, hook_rate, hold_rate.
    """
    cutoff = _date_n_days_ago(days)

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                SUM(spend)            AS total_spend,
                SUM(impressions)      AS total_impressions,
                SUM(reach)            AS total_reach,
                SUM(clicks)           AS total_clicks,
                SUM(conversions)      AS total_conversions,
                SUM(revenue)          AS total_revenue,
                SUM(video_views_3s)   AS total_3s,
                SUM(video_views_15s)  AS total_15s,
                COUNT(*)              AS days_with_data
            FROM ad_insights
            WHERE ad_id = ? AND date >= ?
            """,
            (ad_id, cutoff),
        ).fetchone()

    if row is None or row["days_with_data"] == 0:
        return None

    total_spend = row["total_spend"] or 0.0
    total_imps = row["total_impressions"] or 0
    total_clicks = row["total_clicks"] or 0
    total_conv = row["total_conversions"] or 0
    total_rev = row["total_revenue"] or 0.0
    total_3s = row["total_3s"] or 0
    total_15s = row["total_15s"] or 0

    return {
        "ad_id": ad_id,
        "days": days,
        "days_with_data": row["days_with_data"],
        "spend": round(total_spend, 2),
        "impressions": total_imps,
        "reach": row["total_reach"] or 0,
        "clicks": total_clicks,
        "conversions": total_conv,
        "revenue": round(total_rev, 2),
        "avg_ctr": round(total_clicks / total_imps, 4) if total_imps else 0.0,
        "avg_cpc": round(total_spend / total_clicks, 2) if total_clicks else 0.0,
        "avg_cpm": round((total_spend / total_imps) * 1000, 2) if total_imps else 0.0,
        "avg_cpa": round(total_spend / total_conv, 2) if total_conv else 0.0,
        "roas": round(total_rev / total_spend, 2) if total_spend else 0.0,
        "hook_rate": round(total_3s / total_imps, 4) if total_imps else 0.0,
        "hold_rate": round(total_15s / total_3s, 4) if total_3s else 0.0,
    }


# ===================================================================
#  CREATIVE TAG CRUD
# ===================================================================


def save_creative_tag(tag: CreativeTag) -> None:
    """Insert or update a creative tag (upsert on creative_id + ad_id)."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO creative_tags
                (creative_id, ad_id, format, hook_type, angle,
                 has_text_overlay, has_testimonial, video_length_seconds,
                 body_text, headline, cta_type, source, tags, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(creative_id, ad_id) DO UPDATE SET
                format=excluded.format,
                hook_type=excluded.hook_type,
                angle=excluded.angle,
                has_text_overlay=excluded.has_text_overlay,
                has_testimonial=excluded.has_testimonial,
                video_length_seconds=excluded.video_length_seconds,
                body_text=excluded.body_text,
                headline=excluded.headline,
                cta_type=excluded.cta_type,
                source=excluded.source,
                tags=excluded.tags
            """,
            (
                tag.creative_id, tag.ad_id, tag.format, tag.hook_type,
                tag.angle, int(tag.has_text_overlay), int(tag.has_testimonial),
                tag.video_length_seconds, tag.body_text, tag.headline,
                tag.cta_type, tag.source, tag.tags, tag.created_at,
            ),
        )
    logger.debug("Saved creative tag %s / %s", tag.creative_id, tag.ad_id)


def get_creative_tags(
    ad_id: Optional[str] = None,
    format_filter: Optional[str] = None,
    hook_type: Optional[str] = None,
) -> List[CreativeTag]:
    """
    Fetch creative tags with optional filters.

    Args:
        ad_id: Filter to a specific ad.
        format_filter: Filter by creative format ("ugc", "static", etc.).
        hook_type: Filter by hook type ("question", "objection", etc.).
    """
    query = "SELECT * FROM creative_tags WHERE 1=1"
    params: List[Any] = []

    if ad_id is not None:
        query += " AND ad_id = ?"
        params.append(ad_id)
    if format_filter is not None:
        query += " AND format = ?"
        params.append(format_filter)
    if hook_type is not None:
        query += " AND hook_type = ?"
        params.append(hook_type)

    query += " ORDER BY created_at DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [CreativeTag.from_row(r) for r in rows]


# ===================================================================
#  RULE EXECUTION CRUD
# ===================================================================


def save_rule_execution(execution: RuleExecution) -> int:
    """
    Insert a rule execution record.

    Returns:
        The auto-generated row ID.
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO rule_executions
                (rule_name, rule_type, entity_id, entity_type,
                 action_taken, details, executed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                execution.rule_name, execution.rule_type, execution.entity_id,
                execution.entity_type, execution.action_taken,
                execution.details, execution.executed_at,
            ),
        )
        row_id = cur.lastrowid
    logger.info("Rule executed: %s on %s %s (id=%d)",
                execution.rule_name, execution.entity_type,
                execution.entity_id, row_id)
    return row_id


def get_rule_executions(
    days: int = 7,
    rule_type: Optional[str] = None,
    entity_id: Optional[str] = None,
) -> List[RuleExecution]:
    """
    Fetch rule execution history.

    Args:
        days: Look back N days from today.
        rule_type: Filter by type ("kill", "scale", "alert").
        entity_id: Filter by the entity that was acted on.
    """
    cutoff = _date_n_days_ago(days)
    query = "SELECT * FROM rule_executions WHERE executed_at >= ?"
    params: List[Any] = [cutoff]

    if rule_type is not None:
        query += " AND rule_type = ?"
        params.append(rule_type)
    if entity_id is not None:
        query += " AND entity_id = ?"
        params.append(entity_id)

    query += " ORDER BY executed_at DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [RuleExecution.from_row(r) for r in rows]


# ===================================================================
#  COMMUNITY ANGLE CRUD
# ===================================================================


def save_community_angle(angle: CommunityAngle) -> int:
    """
    Insert a new community angle.

    Returns:
        The auto-generated row ID.
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO community_angles
                (source_type, source_text, suggested_hook, suggested_angle,
                 hook_category, used_in_ad_id, performance_score,
                 created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                angle.source_type, angle.source_text, angle.suggested_hook,
                angle.suggested_angle, angle.hook_category,
                angle.used_in_ad_id, angle.performance_score,
                angle.created_at, angle.status,
            ),
        )
        row_id = cur.lastrowid
    logger.debug("Saved community angle id=%d", row_id)
    return row_id


def get_community_angles(
    status: Optional[str] = None,
    source_type: Optional[str] = None,
    limit: int = 100,
) -> List[CommunityAngle]:
    """
    Fetch community angles with optional filters.

    Args:
        status: Filter by status ("new", "used", "rejected").
        source_type: Filter by source type.
        limit: Max number of results.
    """
    query = "SELECT * FROM community_angles WHERE 1=1"
    params: List[Any] = []

    if status is not None:
        query += " AND status = ?"
        params.append(status)
    if source_type is not None:
        query += " AND source_type = ?"
        params.append(source_type)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [CommunityAngle.from_row(r) for r in rows]


def update_community_angle_status(
    angle_id: int,
    status: str,
    ad_id: Optional[str] = None,
) -> None:
    """
    Update the status of a community angle. Optionally link it to an ad.

    Args:
        angle_id: The row ID of the angle.
        status: New status ("new", "used", "rejected").
        ad_id: If the angle was used, the ad it was used in.
    """
    if status not in ("new", "used", "rejected"):
        raise ValueError(f"Invalid status: {status!r}. Must be 'new', 'used', or 'rejected'.")

    with get_connection() as conn:
        if ad_id is not None:
            conn.execute(
                "UPDATE community_angles SET status = ?, used_in_ad_id = ? WHERE id = ?",
                (status, ad_id, angle_id),
            )
        else:
            conn.execute(
                "UPDATE community_angles SET status = ? WHERE id = ?",
                (status, angle_id),
            )
    logger.debug("Updated community angle %d -> status=%s", angle_id, status)


# ===================================================================
#  COMPUTED METRICS
# ===================================================================


def get_hook_rate(ad_id: str, date: str) -> Optional[float]:
    """
    Calculate hook rate for a specific ad on a specific date.
    Hook rate = 3-second video views / impressions.

    Returns:
        Float between 0 and 1, or None if no data.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT impressions, video_views_3s FROM ad_insights WHERE ad_id = ? AND date = ?",
            (ad_id, date),
        ).fetchone()

    if row is None or row["impressions"] == 0:
        return None
    return round(row["video_views_3s"] / row["impressions"], 4)


def get_hold_rate(ad_id: str, date: str) -> Optional[float]:
    """
    Calculate hold rate for a specific ad on a specific date.
    Hold rate = 15-second video views / 3-second video views.

    Returns:
        Float between 0 and 1, or None if no data.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT video_views_3s, video_views_15s FROM ad_insights WHERE ad_id = ? AND date = ?",
            (ad_id, date),
        ).fetchone()

    if row is None or row["video_views_3s"] == 0:
        return None
    return round(row["video_views_15s"] / row["video_views_3s"], 4)


def get_best_performing_ads(
    metric: str,
    days: int = 7,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Return the top-performing ads ranked by a given metric over N days.

    Supported metrics: spend, impressions, clicks, conversions, revenue,
    roas, ctr, cpc, cpm, cpa, hook_rate, hold_rate.

    Returns:
        List of dicts with ad_id, ad name, and the aggregated metric value.
    """
    return _ranked_ads(metric, days, limit, ascending=False)


def get_worst_performing_ads(
    metric: str,
    days: int = 7,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Return the worst-performing ads ranked by a given metric over N days.
    Only includes ads that actually have spend (to avoid zero-spend noise).

    Supported metrics: same as get_best_performing_ads.
    """
    return _ranked_ads(metric, days, limit, ascending=True)


def _ranked_ads(
    metric: str,
    days: int,
    limit: int,
    ascending: bool,
) -> List[Dict[str, Any]]:
    """Internal helper that ranks ads by an aggregated metric."""
    cutoff = _date_n_days_ago(days)
    direction = "ASC" if ascending else "DESC"

    # Metrics that are computed from sums
    sum_metrics = {
        "spend", "impressions", "clicks", "conversions", "revenue",
        "reach", "video_views_3s", "video_views_15s",
    }
    # Metrics that require a ratio computation
    ratio_metrics = {
        "roas": "SUM(revenue) * 1.0 / NULLIF(SUM(spend), 0)",
        "ctr": "SUM(clicks) * 1.0 / NULLIF(SUM(impressions), 0)",
        "cpc": "SUM(spend) * 1.0 / NULLIF(SUM(clicks), 0)",
        "cpm": "(SUM(spend) * 1000.0) / NULLIF(SUM(impressions), 0)",
        "cpa": "SUM(spend) * 1.0 / NULLIF(SUM(conversions), 0)",
        "hook_rate": "SUM(video_views_3s) * 1.0 / NULLIF(SUM(impressions), 0)",
        "hold_rate": "SUM(video_views_15s) * 1.0 / NULLIF(SUM(video_views_3s), 0)",
    }

    if metric in sum_metrics:
        agg_expr = f"SUM({metric})"
    elif metric in ratio_metrics:
        agg_expr = ratio_metrics[metric]
    else:
        raise ValueError(
            f"Unknown metric: {metric!r}. "
            f"Supported: {sorted(sum_metrics | set(ratio_metrics.keys()))}"
        )

    query = f"""
        SELECT
            i.ad_id,
            a.name AS ad_name,
            a.campaign_id,
            ROUND({agg_expr}, 4) AS metric_value,
            SUM(i.spend) AS total_spend
        FROM ad_insights i
        JOIN ads a ON a.ad_id = i.ad_id
        WHERE i.date >= ?
        GROUP BY i.ad_id
        HAVING SUM(i.spend) > 0
        ORDER BY metric_value {direction}
        LIMIT ?
    """

    with get_connection() as conn:
        rows = conn.execute(query, (cutoff, limit)).fetchall()

    return [
        {
            "ad_id": row["ad_id"],
            "ad_name": row["ad_name"],
            "campaign_id": row["campaign_id"],
            "metric": metric,
            "value": row["metric_value"],
            "total_spend": round(row["total_spend"], 2),
        }
        for row in rows
    ]


def get_ad_trend(
    ad_id: str,
    metric: str,
    days: int = 14,
) -> List[Dict[str, Any]]:
    """
    Return daily values of a metric for one ad over N days.
    Useful for plotting trends and detecting fatigue.

    Args:
        ad_id: The ad to analyse.
        metric: Column name from ad_insights (e.g. "spend", "ctr", "roas").
        days: Number of days to look back.

    Returns:
        List of {"date": ..., "value": ...} dicts in chronological order.
    """
    # Computed metrics need special handling
    computed = {
        "hook_rate": "CAST(video_views_3s AS REAL) / NULLIF(impressions, 0)",
        "hold_rate": "CAST(video_views_15s AS REAL) / NULLIF(video_views_3s, 0)",
        "completion_rate": "CAST(video_views_p100 AS REAL) / NULLIF(video_views_3s, 0)",
    }

    # Validate the metric is a real column or known computed metric
    valid_columns = {
        "spend", "impressions", "reach", "frequency", "clicks", "ctr",
        "cpc", "cpm", "conversions", "cpa", "revenue", "roas",
        "video_views_3s", "video_views_15s", "video_views_p25",
        "video_views_p50", "video_views_p75", "video_views_p100",
    }

    if metric in computed:
        select_expr = f"ROUND({computed[metric]}, 4)"
    elif metric in valid_columns:
        select_expr = metric
    else:
        raise ValueError(
            f"Unknown metric: {metric!r}. "
            f"Supported: {sorted(valid_columns | set(computed.keys()))}"
        )

    cutoff = _date_n_days_ago(days)

    query = f"""
        SELECT date, {select_expr} AS value
        FROM ad_insights
        WHERE ad_id = ? AND date >= ?
        ORDER BY date ASC
    """

    with get_connection() as conn:
        rows = conn.execute(query, (ad_id, cutoff)).fetchall()

    return [{"date": row["date"], "value": row["value"]} for row in rows]


def get_account_summary(days: int = 7) -> Dict[str, Any]:
    """
    Account-wide aggregated metrics over the last N days.

    Returns a dict with total spend, impressions, clicks, conversions,
    revenue, ROAS, average CPA, unique active ads count, and more.
    """
    cutoff = _date_n_days_ago(days)

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(DISTINCT ad_id)   AS active_ads,
                SUM(spend)              AS total_spend,
                SUM(impressions)        AS total_impressions,
                SUM(reach)              AS total_reach,
                SUM(clicks)             AS total_clicks,
                SUM(conversions)        AS total_conversions,
                SUM(revenue)            AS total_revenue,
                SUM(video_views_3s)     AS total_3s,
                SUM(video_views_15s)    AS total_15s
            FROM ad_insights
            WHERE date >= ?
            """,
            (cutoff,),
        ).fetchone()

    if row is None or (row["total_spend"] or 0) == 0:
        return {
            "days": days,
            "active_ads": 0,
            "spend": 0.0,
            "impressions": 0,
            "reach": 0,
            "clicks": 0,
            "conversions": 0,
            "revenue": 0.0,
            "roas": 0.0,
            "avg_cpa": 0.0,
            "avg_ctr": 0.0,
            "avg_cpm": 0.0,
            "hook_rate": 0.0,
            "hold_rate": 0.0,
        }

    total_spend = row["total_spend"] or 0.0
    total_imps = row["total_impressions"] or 0
    total_clicks = row["total_clicks"] or 0
    total_conv = row["total_conversions"] or 0
    total_rev = row["total_revenue"] or 0.0
    total_3s = row["total_3s"] or 0
    total_15s = row["total_15s"] or 0

    return {
        "days": days,
        "active_ads": row["active_ads"],
        "spend": round(total_spend, 2),
        "impressions": total_imps,
        "reach": row["total_reach"] or 0,
        "clicks": total_clicks,
        "conversions": total_conv,
        "revenue": round(total_rev, 2),
        "roas": round(total_rev / total_spend, 2) if total_spend else 0.0,
        "avg_cpa": round(total_spend / total_conv, 2) if total_conv else 0.0,
        "avg_ctr": round(total_clicks / total_imps, 4) if total_imps else 0.0,
        "avg_cpm": round((total_spend / total_imps) * 1000, 2) if total_imps else 0.0,
        "hook_rate": round(total_3s / total_imps, 4) if total_imps else 0.0,
        "hold_rate": round(total_15s / total_3s, 4) if total_3s else 0.0,
    }
