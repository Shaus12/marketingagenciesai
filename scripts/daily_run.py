"""
Scheduled daily execution for the Meta Ads Management System.

Performs the full daily routine: data pull, rules evaluation, report
generation, and notification dispatch.  Can run as a one-shot via cron
or as a persistent process using the ``schedule`` library.

Usage::

    # One-shot (e.g. from cron)
    python -m scripts.daily_run

    # Persistent daemon
    python -m scripts.daily_run --schedule

    # Preview without side-effects
    python -m scripts.daily_run --dry-run
"""

import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import click
from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()


# ======================================================================
# Helpers
# ======================================================================


def _today() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def _yesterday() -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def _is_community_pulse_day() -> bool:
    """Return True if today matches the configured community pulse day."""
    from config.settings import COMMUNITY_PULSE_DAY
    return datetime.now(tz=timezone.utc).weekday() == COMMUNITY_PULSE_DAY


# ======================================================================
# Individual steps
# ======================================================================


def _step_pull_data(dry_run: bool = False) -> Dict[str, Any]:
    """Step 1: Pull yesterday's ad insights from the Meta API.

    Returns:
        Dict with ``ok`` (bool), ``rows`` (int), and optional ``error``.
    """
    logger.info("Step 1: Pulling data from Meta API...")

    if dry_run:
        logger.info("[DRY RUN] Would pull insights for %s", _yesterday())
        return {"ok": True, "rows": 0, "dry_run": True}

    try:
        from api.insights_fetcher import fetch_ad_insights
        from data.db import save_insights, init_db
        from data.models import AdInsight

        init_db()

        start = _yesterday()
        end = _yesterday()

        raw_rows = fetch_ad_insights(start, end)

        insights = []
        for row in raw_rows:
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

        logger.info("Pulled and saved %d insight rows", len(insights))
        return {"ok": True, "rows": len(insights)}

    except Exception as exc:
        logger.exception("Data pull failed")
        return {"ok": False, "rows": 0, "error": str(exc)}


def _step_run_rules(dry_run: bool = False) -> Dict[str, Any]:
    """Step 2: Evaluate kill / scale / alert rules.

    Returns:
        Dict with ``ok``, ``kills``, ``scales``, ``alerts`` counts
        and detail lists.
    """
    logger.info("Step 2: Running rules engine...")

    try:
        from config.rules import KILL_RULES, SCALE_RULES, ALERT_RULES
        from data.db import list_ads, get_insights_summary, save_rule_execution
        from data.models import RuleExecution
        from notifications.slack import get_notifier as get_slack

        slack = get_slack()
        active_ads = list_ads(status="ACTIVE")

        kills: List[Dict[str, Any]] = []
        scales: List[Dict[str, Any]] = []
        alerts: List[Dict[str, Any]] = []

        for ad in active_ads:
            summary = get_insights_summary(ad.ad_id, days=7)
            if not summary:
                continue

            ad_data: Dict[str, Any] = {
                "ad_id": ad.ad_id,
                "ad_name": ad.name,
                "spend": summary["spend"],
                "conversions": summary["conversions"],
                "cpa": summary["avg_cpa"],
                "roas": summary["roas"],
                "ctr": summary["avg_ctr"],
                "frequency": 0,
                "hook_rate": summary["hook_rate"],
                "hold_rate": summary["hold_rate"],
                "impressions": summary["impressions"],
                "is_learning_phase_complete": True,
                "ctr_vs_7d_avg_pct": 0,
                "days_above_target_cpa": 0,
                "consecutive_days_above_target": 0,
                "conversions_7d": summary["conversions"],
                "campaign_type": "test",
                "best_scale_cpa": 999,
            }

            # Kill rules
            for rule in KILL_RULES:
                try:
                    if rule["condition"](ad_data):
                        entry = {
                            "ad_name": ad.name,
                            "ad_id": ad.ad_id,
                            "rule": rule["name"],
                            "reason": rule["description"],
                            "severity": rule.get("severity", "critical"),
                            "metrics": summary,
                        }
                        kills.append(entry)

                        if not dry_run:
                            save_rule_execution(RuleExecution(
                                rule_name=rule["name"],
                                rule_type="kill",
                                entity_id=ad.ad_id,
                                entity_type="ad",
                                action_taken=rule.get("action", "pause"),
                                details=rule["description"],
                            ))
                            slack.send_kill_notification(
                                ad.name, ad.ad_id, rule["description"], summary
                            )
                except Exception:
                    logger.exception("Error evaluating kill rule %s on ad %s",
                                     rule["name"], ad.ad_id)

            # Scale rules
            for rule in SCALE_RULES:
                try:
                    if rule["condition"](ad_data):
                        entry = {
                            "ad_name": ad.name,
                            "ad_id": ad.ad_id,
                            "rule": rule["name"],
                            "reason": rule["description"],
                        }
                        scales.append(entry)

                        if not dry_run:
                            save_rule_execution(RuleExecution(
                                rule_name=rule["name"],
                                rule_type="scale",
                                entity_id=ad.ad_id,
                                entity_type="ad",
                                action_taken=rule.get("action", "increase_budget_20pct"),
                                details=rule["description"],
                            ))
                except Exception:
                    logger.exception("Error evaluating scale rule %s on ad %s",
                                     rule["name"], ad.ad_id)

            # Alert rules
            for rule in ALERT_RULES:
                try:
                    if rule["condition"](ad_data):
                        entry = {
                            "ad_name": ad.name,
                            "ad_id": ad.ad_id,
                            "rule": rule["name"],
                            "reason": rule["description"],
                            "severity": rule.get("severity", "info"),
                        }
                        alerts.append(entry)

                        if not dry_run:
                            save_rule_execution(RuleExecution(
                                rule_name=rule["name"],
                                rule_type="alert",
                                entity_id=ad.ad_id,
                                entity_type="ad",
                                action_taken="alert",
                                details=rule["description"],
                            ))
                            slack.send_alert(
                                rule["name"], rule["description"],
                                severity=rule.get("severity", "info"),
                            )
                except Exception:
                    logger.exception("Error evaluating alert rule %s on ad %s",
                                     rule["name"], ad.ad_id)

        logger.info(
            "Rules complete: %d kills, %d scales, %d alerts",
            len(kills), len(scales), len(alerts),
        )
        return {
            "ok": True,
            "kills": len(kills),
            "scales": len(scales),
            "alerts": len(alerts),
            "kill_details": kills,
            "scale_details": scales,
            "alert_details": alerts,
        }

    except Exception as exc:
        logger.exception("Rules engine failed")
        return {"ok": False, "error": str(exc), "kills": 0, "scales": 0, "alerts": 0}


def _step_generate_report(dry_run: bool = False) -> Dict[str, Any]:
    """Step 3: Generate the daily report text.

    Returns:
        Dict with ``ok`` and ``report_text``.
    """
    logger.info("Step 3: Generating daily report...")

    try:
        from data.db import get_account_summary, get_best_performing_ads, get_worst_performing_ads
        from config.settings import TARGET_CPA, TARGET_ROAS, CURRENCY

        summary = get_account_summary(days=1)
        best = get_best_performing_ads("roas", days=1, limit=5)
        worst = get_worst_performing_ads("cpa", days=1, limit=5)

        lines = [
            f"Daily Performance Report ({_yesterday()})",
            "=" * 50,
            f"Spend:       {CURRENCY} {summary['spend']:,.2f}",
            f"Revenue:     {CURRENCY} {summary['revenue']:,.2f}",
            f"ROAS:        {summary['roas']:.2f}x  (target: {TARGET_ROAS:.1f}x)",
            f"CPA:         {CURRENCY} {summary['avg_cpa']:,.2f}  (target: {CURRENCY} {TARGET_CPA:.2f})",
            f"Conversions: {summary['conversions']}",
            f"Active Ads:  {summary['active_ads']}",
            f"CTR:         {summary['avg_ctr']:.2%}",
            f"Hook Rate:   {summary['hook_rate']:.2%}",
            f"Hold Rate:   {summary['hold_rate']:.2%}",
            "",
        ]

        if best:
            lines.append("Top 5 by ROAS:")
            for ad in best:
                val = f"{ad['value']:.2f}x" if ad["value"] else "n/a"
                lines.append(f"  - {ad['ad_name'][:40]}  ROAS={val}  Spend={CURRENCY} {ad['total_spend']:,.2f}")
            lines.append("")

        if worst:
            lines.append("Bottom 5 by CPA:")
            for ad in worst:
                val = f"{CURRENCY} {ad['value']:,.2f}" if ad["value"] else "n/a"
                lines.append(f"  - {ad['ad_name'][:40]}  CPA={val}  Spend={CURRENCY} {ad['total_spend']:,.2f}")

        report_text = "\n".join(lines)
        logger.info("Report generated (%d lines)", len(lines))
        return {"ok": True, "report_text": report_text}

    except Exception as exc:
        logger.exception("Report generation failed")
        return {"ok": False, "report_text": "", "error": str(exc)}


def _step_send_notifications(
    report_text: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Step 4: Send the report via Slack and email.

    Returns:
        Dict with ``ok``, ``slack_sent``, ``email_sent``.
    """
    logger.info("Step 4: Sending notifications...")

    if dry_run:
        logger.info("[DRY RUN] Would send report via Slack and email")
        return {"ok": True, "slack_sent": False, "email_sent": False, "dry_run": True}

    slack_sent = False
    email_sent = False

    # Slack
    try:
        from notifications.slack import get_notifier as get_slack
        slack = get_slack()
        slack_sent = slack.send_report(report_text, title="Daily Ad Report")
    except Exception as exc:
        logger.error("Slack notification failed: %s", exc)

    # Email
    try:
        from notifications.email import get_notifier as get_email
        email = get_email()
        email_sent = email.send_report(report_text, report_type="daily")
    except Exception as exc:
        logger.error("Email notification failed: %s", exc)

    return {"ok": True, "slack_sent": slack_sent, "email_sent": email_sent}


def _step_community_pulse(dry_run: bool = False) -> Dict[str, Any]:
    """Step 5 (conditional): Run community pulse if today is the configured day.

    Returns:
        Dict with ``ok``, ``skipped``, and optionally ``report``.
    """
    if not _is_community_pulse_day():
        logger.info("Step 5: Skipping community pulse (not scheduled today)")
        return {"ok": True, "skipped": True}

    logger.info("Step 5: Generating community pulse...")

    if dry_run:
        logger.info("[DRY RUN] Would generate community pulse")
        return {"ok": True, "skipped": False, "dry_run": True}

    try:
        from community.community_pulse import CommunityPulse
        from notifications.slack import get_notifier as get_slack

        pulse = CommunityPulse()
        report_data = pulse.generate_pulse(days=7)
        formatted = report_data.get("formatted", "")

        if formatted:
            slack = get_slack()
            slack.send_report(formatted, title="Community Pulse")

        logger.info("Community pulse generated and sent")
        return {"ok": True, "skipped": False, "report": formatted}

    except ConnectionError:
        logger.warning("Supabase not configured; skipping community pulse")
        return {"ok": True, "skipped": True, "reason": "supabase_not_configured"}
    except Exception as exc:
        logger.exception("Community pulse failed")
        return {"ok": False, "skipped": False, "error": str(exc)}


# ======================================================================
# Orchestrator
# ======================================================================


def run_daily(dry_run: bool = False) -> Dict[str, Any]:
    """Execute the full daily routine.

    Steps:
        1. Pull yesterday's insights from Meta API
        2. Evaluate kill / scale / alert rules
        3. Generate the daily report
        4. Send notifications (Slack + email)
        5. Community pulse (if scheduled)
        6. Log completion

    Args:
        dry_run: If True, preview the run without executing actions.

    Returns:
        Summary dict with the results of each step.
    """
    mode = "DRY RUN" if dry_run else "LIVE"
    logger.info("=== Daily run started (%s) ===", mode)
    start_time = time.time()

    results: Dict[str, Any] = {"mode": mode, "started_at": _today()}
    errors: List[str] = []

    # Step 1: Pull data
    try:
        results["pull"] = _step_pull_data(dry_run=dry_run)
    except Exception as exc:
        results["pull"] = {"ok": False, "error": str(exc)}
        errors.append(f"Pull: {exc}")

    # Step 2: Run rules
    try:
        results["rules"] = _step_run_rules(dry_run=dry_run)
    except Exception as exc:
        results["rules"] = {"ok": False, "error": str(exc)}
        errors.append(f"Rules: {exc}")

    # Step 3: Generate report
    try:
        report_result = _step_generate_report(dry_run=dry_run)
        results["report"] = {"ok": report_result["ok"]}
    except Exception as exc:
        report_result = {"ok": False, "report_text": "", "error": str(exc)}
        results["report"] = {"ok": False, "error": str(exc)}
        errors.append(f"Report: {exc}")

    # Step 4: Send notifications
    try:
        results["notifications"] = _step_send_notifications(
            report_result.get("report_text", ""),
            dry_run=dry_run,
        )
    except Exception as exc:
        results["notifications"] = {"ok": False, "error": str(exc)}
        errors.append(f"Notifications: {exc}")

    # Step 5: Community pulse
    try:
        results["community"] = _step_community_pulse(dry_run=dry_run)
    except Exception as exc:
        results["community"] = {"ok": False, "error": str(exc)}
        errors.append(f"Community: {exc}")

    # Step 6: Summary
    elapsed = time.time() - start_time
    results["elapsed_seconds"] = round(elapsed, 1)
    results["errors"] = errors
    results["success"] = len(errors) == 0

    if errors:
        logger.warning(
            "Daily run completed with %d error(s) in %.1fs: %s",
            len(errors), elapsed, "; ".join(errors),
        )
        # Try to notify about errors
        if not dry_run:
            try:
                from notifications.slack import get_notifier as get_slack
                slack = get_slack()
                slack.send_alert(
                    "daily_run_errors",
                    f"Daily run completed with {len(errors)} error(s):\n" + "\n".join(f"- {e}" for e in errors),
                    severity="warning",
                )
            except Exception:
                pass
    else:
        logger.info("Daily run completed successfully in %.1fs", elapsed)

    return results


# ======================================================================
# CLI entry point
# ======================================================================


@click.command()
@click.option("--dry-run", is_flag=True, default=False, help="Preview without executing actions.")
@click.option(
    "--schedule", "run_scheduled", is_flag=True, default=False,
    help="Run as a persistent scheduled daemon.",
)
def main(dry_run: bool, run_scheduled: bool) -> None:
    """Run the daily Meta Ads routine (one-shot or scheduled)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if run_scheduled:
        try:
            import schedule
        except ImportError:
            console.print("[red]The 'schedule' library is required for daemon mode.[/red]")
            console.print("Install it with: pip install schedule")
            sys.exit(1)

        from config.settings import DATA_PULL_HOUR, REPORT_HOUR

        logger.info(
            "Starting scheduled daemon: data pull at %02d:00, report at %02d:00",
            DATA_PULL_HOUR, REPORT_HOUR,
        )

        schedule.every().day.at(f"{DATA_PULL_HOUR:02d}:00").do(run_daily, dry_run=dry_run)
        schedule.every().day.at(f"{REPORT_HOUR:02d}:00").do(run_daily, dry_run=dry_run)

        console.print(
            f"[green]Daemon running.[/green] "
            f"Data pull at {DATA_PULL_HOUR:02d}:00, report at {REPORT_HOUR:02d}:00. "
            f"Press Ctrl+C to stop."
        )

        try:
            while True:
                schedule.run_pending()
                time.sleep(60)
        except KeyboardInterrupt:
            logger.info("Daemon stopped by user")
            console.print("\n[dim]Stopped.[/dim]")
    else:
        # One-shot run
        results = run_daily(dry_run=dry_run)

        if results.get("success"):
            console.print(f"[green]Daily run completed in {results['elapsed_seconds']}s[/green]")
        else:
            console.print(
                f"[yellow]Daily run completed with {len(results.get('errors', []))} error(s) "
                f"in {results['elapsed_seconds']}s[/yellow]"
            )
            for err in results.get("errors", []):
                console.print(f"  [red]- {err}[/red]")
            sys.exit(1)


if __name__ == "__main__":
    main()
