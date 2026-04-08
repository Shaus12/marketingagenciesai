"""
Historical data backfill for the Meta Ads Management System.

Pulls campaign, ad set, and ad-level insights for the last N days
from the Meta Marketing API and saves them to the local SQLite database.

Usage::

    python -m scripts.backfill
    python -m scripts.backfill --days 30
"""

import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import click
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

logger = logging.getLogger(__name__)
console = Console()

# Maximum days per API request to avoid Meta timeouts
_CHUNK_DAYS = 30


# ======================================================================
# Core backfill logic
# ======================================================================


def run_backfill(days: int = 90) -> Dict[str, Any]:
    """Pull historical data for the last *days* days and save to the database.

    Splits the date range into 30-day chunks to respect Meta API limits.
    Shows a progress bar during the operation.

    Args:
        days: Number of historical days to pull (default 90).

    Returns:
        Summary dict with row counts per level (campaigns, adsets, ads).
    """
    from api.insights_fetcher import (
        fetch_ad_insights,
        fetch_campaign_insights,
        fetch_adset_insights,
    )
    from data.db import init_db, save_campaign, save_adset, save_ad, save_insights
    from data.models import AdInsight, CampaignData, AdSetData, AdData

    # Ensure the database schema exists
    init_db()

    today = datetime.now(tz=timezone.utc).date()
    start_date = today - timedelta(days=days)

    # Build the list of chunks
    chunks: List[tuple[str, str]] = []
    chunk_start = start_date
    while chunk_start < today:
        chunk_end = min(chunk_start + timedelta(days=_CHUNK_DAYS - 1), today - timedelta(days=1))
        chunks.append((chunk_start.isoformat(), chunk_end.isoformat()))
        chunk_start = chunk_end + timedelta(days=1)

    total_campaigns = 0
    total_adsets = 0
    total_ads = 0
    errors: List[str] = []

    start_time = time.time()

    console.print(
        f"\n[bold]Backfilling {days} days of data "
        f"({start_date.isoformat()} to {today.isoformat()}) "
        f"in {len(chunks)} chunk(s)...[/bold]\n"
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        main_task = progress.add_task("Backfill progress", total=len(chunks) * 3)

        for chunk_idx, (ds, de) in enumerate(chunks, 1):
            chunk_label = f"Chunk {chunk_idx}/{len(chunks)} ({ds} to {de})"

            # --- Campaign insights ---
            progress.update(main_task, description=f"{chunk_label}: campaigns...")
            try:
                camp_rows = fetch_campaign_insights(ds, de)
                # Save campaign metadata
                seen_campaigns = set()
                for row in camp_rows:
                    cid = row.get("campaign_id", "")
                    if cid and cid not in seen_campaigns:
                        seen_campaigns.add(cid)
                        save_campaign(CampaignData(
                            campaign_id=cid,
                            name=row.get("campaign_name", ""),
                            status="ACTIVE",
                        ))
                total_campaigns += len(camp_rows)
            except Exception as exc:
                msg = f"Campaign fetch failed for {ds}-{de}: {exc}"
                logger.error(msg)
                errors.append(msg)
            progress.advance(main_task)

            # --- Ad set insights ---
            progress.update(main_task, description=f"{chunk_label}: ad sets...")
            try:
                adset_rows = fetch_adset_insights(ds, de)
                seen_adsets = set()
                for row in adset_rows:
                    asid = row.get("adset_id", "")
                    if asid and asid not in seen_adsets:
                        seen_adsets.add(asid)
                        save_adset(AdSetData(
                            adset_id=asid,
                            campaign_id=row.get("campaign_id", ""),
                            name=row.get("adset_name", ""),
                            status="ACTIVE",
                        ))
                total_adsets += len(adset_rows)
            except Exception as exc:
                msg = f"Ad set fetch failed for {ds}-{de}: {exc}"
                logger.error(msg)
                errors.append(msg)
            progress.advance(main_task)

            # --- Ad-level insights ---
            progress.update(main_task, description=f"{chunk_label}: ads...")
            try:
                ad_rows = fetch_ad_insights(ds, de)

                # Save ad metadata
                seen_ads = set()
                for row in ad_rows:
                    aid = row.get("ad_id", "")
                    if aid and aid not in seen_ads:
                        seen_ads.add(aid)
                        save_ad(AdData(
                            ad_id=aid,
                            adset_id=row.get("adset_id", ""),
                            campaign_id=row.get("campaign_id", ""),
                            name=row.get("ad_name", ""),
                            status="ACTIVE",
                        ))

                # Convert to AdInsight and save
                insights = []
                for row in ad_rows:
                    insights.append(AdInsight(
                        ad_id=row.get("ad_id", ""),
                        date=row.get("date_start", ""),
                        spend=row.get("spend", 0),
                        impressions=int(row.get("impressions", 0)),
                        reach=int(row.get("reach", 0)),
                        frequency=row.get("frequency", 0),
                        clicks=int(row.get("clicks", 0)),
                        ctr=row.get("ctr", 0),
                        cpc=row.get("cpc", 0),
                        cpm=row.get("cpm", 0),
                        conversions=int(row.get("conversions", 0)),
                        cpa=row.get("cpa", 0),
                        revenue=row.get("purchase_value", 0),
                        roas=row.get("roas", 0),
                        video_views_3s=int(row.get("video_plays", 0)),
                        video_views_15s=0,
                        video_views_p25=int(row.get("video_p25", 0)),
                        video_views_p50=int(row.get("video_p50", 0)),
                        video_views_p75=int(row.get("video_p75", 0)),
                        video_views_p100=int(row.get("video_p100", 0)),
                    ))

                if insights:
                    save_insights(insights)

                total_ads += len(ad_rows)
            except Exception as exc:
                msg = f"Ad fetch failed for {ds}-{de}: {exc}"
                logger.error(msg)
                errors.append(msg)
            progress.advance(main_task)

    elapsed = time.time() - start_time

    # Print summary
    console.print()
    summary = {
        "days": days,
        "chunks": len(chunks),
        "campaign_rows": total_campaigns,
        "adset_rows": total_adsets,
        "ad_rows": total_ads,
        "errors": len(errors),
        "elapsed_seconds": round(elapsed, 1),
    }

    if errors:
        console.print(f"[yellow]Backfill completed with {len(errors)} error(s) in {elapsed:.1f}s[/yellow]")
        for err in errors:
            console.print(f"  [red]- {err}[/red]")
    else:
        console.print(f"[green]Backfill completed in {elapsed:.1f}s[/green]")

    console.print(f"  Campaign insight rows: {total_campaigns:,}")
    console.print(f"  Ad set insight rows:   {total_adsets:,}")
    console.print(f"  Ad insight rows:       {total_ads:,}")
    console.print(f"  Total rows:            {total_campaigns + total_adsets + total_ads:,}")

    return summary


# ======================================================================
# CLI entry point
# ======================================================================


@click.command()
@click.option("--days", default=90, help="Number of historical days to pull (default 90).")
def main(days: int) -> None:
    """Backfill historical Meta Ads data into the local database."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        summary = run_backfill(days=days)
        if summary.get("errors", 0) > 0:
            sys.exit(1)
    except Exception as exc:
        console.print(f"[red]Backfill failed:[/red] {exc}")
        logger.exception("Backfill failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
