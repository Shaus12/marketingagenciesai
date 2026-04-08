"""
Daily Morning Report — snapshot of yesterday's ad performance.

Generates a concise daily summary comparing actual performance against
targets and rolling averages, highlighting winners, losers, rule
triggers, and creative pipeline health.

Usage::

    from reports.daily_report import DailyReport
    from data import db

    report = DailyReport(db)
    data = report.generate()          # defaults to yesterday
    print(report.format_text())
    slack_payload = report.format_slack()
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config.settings import (
    CURRENCY,
    MONTHLY_BUDGET,
    SCALE_BUDGET_PCT,
    TARGET_CPA,
    TARGET_ROAS,
)
from config.rules import CREATIVE_THRESHOLDS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Currency / formatting helpers
# ---------------------------------------------------------------------------

_CURRENCY_SYMBOLS = {"EUR": "\u20ac", "USD": "$", "GBP": "\u00a3"}
_SYM = _CURRENCY_SYMBOLS.get(CURRENCY, CURRENCY + " ")


def _fmt_currency(value: float) -> str:
    """Format a monetary value with the configured currency symbol."""
    return f"{_SYM}{value:,.2f}"


def _fmt_pct(value: float, decimals: int = 1) -> str:
    """Format a percentage value."""
    return f"{value:+.{decimals}f}%"


def _arrow(delta: float) -> str:
    """Return an up/down arrow depending on sign."""
    if delta > 0:
        return "\u2191"
    if delta < 0:
        return "\u2193"
    return "\u2194"


def _pct_change(current: float, previous: float) -> float:
    """Calculate percentage change; returns 0.0 when previous is zero."""
    if previous == 0:
        return 0.0
    return round(((current - previous) / previous) * 100, 1)


def _safe_div(numerator: float, denominator: float) -> float:
    """Safe division returning 0.0 on zero denominator."""
    if denominator == 0:
        return 0.0
    return numerator / denominator


# ---------------------------------------------------------------------------
# DailyReport
# ---------------------------------------------------------------------------


class DailyReport:
    """
    Morning summary report covering one day of ad performance.

    Parameters
    ----------
    db : module
        The ``data.db`` module (or any object exposing the same query API).
    """

    def __init__(self, db: Any) -> None:
        self._db = db
        self._data: Dict[str, Any] = {}
        self._generated = False

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate(self, date: Optional[str] = None) -> Dict[str, Any]:
        """
        Build the daily report for *date* (YYYY-MM-DD).

        Defaults to yesterday (UTC).  After calling this method the report
        is stored internally and can be rendered via ``format_text()``,
        ``format_slack()``, or ``to_dict()``.

        Returns
        -------
        dict
            The raw report data.
        """
        if date is None:
            yesterday = datetime.now(tz=timezone.utc) - timedelta(days=1)
            date = yesterday.strftime("%Y-%m-%d")

        logger.info("Generating daily report for %s", date)

        # -- Day metrics (account-level for the single day) --
        day_insights = self._db.get_insights(date_start=date, date_end=date)
        day_agg = self._aggregate_insights(day_insights)

        # -- 7-day rolling average (the 7 days before *date*) --
        d = datetime.strptime(date, "%Y-%m-%d")
        avg_start = (d - timedelta(days=7)).strftime("%Y-%m-%d")
        avg_end = (d - timedelta(days=1)).strftime("%Y-%m-%d")
        avg_insights = self._db.get_insights(date_start=avg_start, date_end=avg_end)
        avg_agg = self._aggregate_insights(avg_insights, days=7)

        # -- Top / bottom ads by ROAS --
        top_ads = self._db.get_best_performing_ads("roas", days=1, limit=3)
        bottom_ads = self._db.get_worst_performing_ads("roas", days=1, limit=3)

        # Enrich top/bottom with extra daily metrics
        top_ads = self._enrich_ad_rows(top_ads, date)
        bottom_ads = self._enrich_ad_rows(bottom_ads, date)

        # -- Rules triggered today --
        rules_today = self._db.get_rule_executions(days=1)

        # -- Creative pipeline --
        pipeline = self._build_creative_pipeline()

        # -- Fatigue warnings --
        fatigue = self._detect_fatigue(date)

        # -- Assemble --
        self._data = {
            "date": date,
            "day": day_agg,
            "avg_7d": avg_agg,
            "vs_targets": self._compare_targets(day_agg),
            "vs_7d": self._compare_averages(day_agg, avg_agg),
            "top_ads": top_ads,
            "bottom_ads": bottom_ads,
            "rules_triggered": [r.to_dict() for r in rules_today],
            "actions_taken": self._summarise_actions(rules_today),
            "pipeline": pipeline,
            "fatigue_warnings": fatigue,
        }
        self._generated = True
        logger.info("Daily report generated for %s", date)
        return self._data

    # ------------------------------------------------------------------
    # Aggregation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate_insights(
        insights: List[Any], days: int = 1
    ) -> Dict[str, float]:
        """Aggregate a list of AdInsight objects into summary metrics."""
        if not insights:
            return {
                "spend": 0.0,
                "impressions": 0,
                "clicks": 0,
                "conversions": 0,
                "revenue": 0.0,
                "cpa": 0.0,
                "roas": 0.0,
                "ctr": 0.0,
                "cpm": 0.0,
                "hook_rate": 0.0,
                "hold_rate": 0.0,
                "frequency": 0.0,
                "active_ads": 0,
            }

        total_spend = sum(i.spend for i in insights)
        total_imps = sum(i.impressions for i in insights)
        total_clicks = sum(i.clicks for i in insights)
        total_conv = sum(i.conversions for i in insights)
        total_rev = sum(i.revenue for i in insights)
        total_3s = sum(i.video_views_3s for i in insights)
        total_15s = sum(i.video_views_15s for i in insights)
        unique_ads = len({i.ad_id for i in insights})

        # For averages over multi-day windows, divide by the number of days
        divisor = max(days, 1)

        return {
            "spend": round(total_spend / divisor, 2),
            "impressions": round(total_imps / divisor),
            "clicks": round(total_clicks / divisor),
            "conversions": round(total_conv / divisor),
            "revenue": round(total_rev / divisor, 2),
            "cpa": round(_safe_div(total_spend, total_conv), 2),
            "roas": round(_safe_div(total_rev, total_spend), 2),
            "ctr": round(_safe_div(total_clicks, total_imps) * 100, 2),
            "cpm": round(_safe_div(total_spend, total_imps) * 1000, 2),
            "hook_rate": round(_safe_div(total_3s, total_imps) * 100, 2),
            "hold_rate": round(_safe_div(total_15s, total_3s) * 100, 2),
            "frequency": round(
                sum(i.frequency for i in insights) / len(insights), 2
            ),
            "active_ads": unique_ads,
        }

    def _enrich_ad_rows(
        self, ad_rows: List[Dict[str, Any]], date: str
    ) -> List[Dict[str, Any]]:
        """Add per-ad daily metrics to ranked ad rows."""
        enriched: List[Dict[str, Any]] = []
        for row in ad_rows:
            ad_id = row["ad_id"]
            day_data = self._db.get_insights(
                ad_id=ad_id, date_start=date, date_end=date
            )
            if day_data:
                ins = day_data[0]
                row["spend"] = ins.spend
                row["conversions"] = ins.conversions
                row["cpa"] = ins.cpa
                row["roas"] = ins.roas
                row["ctr"] = ins.ctr
                row["impressions"] = ins.impressions
            else:
                row["spend"] = 0.0
                row["conversions"] = 0
                row["cpa"] = 0.0
                row["roas"] = 0.0
                row["ctr"] = 0.0
                row["impressions"] = 0
            enriched.append(row)
        return enriched

    # ------------------------------------------------------------------
    # Comparison helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compare_targets(day: Dict[str, float]) -> Dict[str, Any]:
        """Compare day metrics against business targets."""
        cpa = day["cpa"]
        roas = day["roas"]

        cpa_vs = _pct_change(cpa, TARGET_CPA)
        roas_vs = _pct_change(roas, TARGET_ROAS)

        return {
            "cpa": {
                "actual": cpa,
                "target": TARGET_CPA,
                "delta_pct": cpa_vs,
                "status": "good" if cpa <= TARGET_CPA else "bad",
                "arrow": _arrow(cpa_vs),
            },
            "roas": {
                "actual": roas,
                "target": TARGET_ROAS,
                "delta_pct": roas_vs,
                "status": "good" if roas >= TARGET_ROAS else "bad",
                "arrow": _arrow(roas_vs),
            },
        }

    @staticmethod
    def _compare_averages(
        day: Dict[str, float], avg: Dict[str, float]
    ) -> Dict[str, Any]:
        """Compare day metrics vs 7-day rolling averages."""
        comparisons: Dict[str, Any] = {}
        for key in ("spend", "cpa", "roas", "ctr"):
            curr = day.get(key, 0.0)
            prev = avg.get(key, 0.0)
            delta = _pct_change(curr, prev)
            comparisons[key] = {
                "today": curr,
                "avg_7d": prev,
                "delta_pct": delta,
                "arrow": _arrow(delta),
            }
        return comparisons

    # ------------------------------------------------------------------
    # Rules & actions
    # ------------------------------------------------------------------

    @staticmethod
    def _summarise_actions(rules: List[Any]) -> List[Dict[str, str]]:
        """Build a human-readable list of automated actions taken."""
        actions: List[Dict[str, str]] = []
        for r in rules:
            label = {
                "kill": "Paused",
                "scale": "Scaled",
                "alert": "Alerted",
            }.get(r.rule_type, r.rule_type.title())

            actions.append({
                "action": f"{label}: {r.entity_type} {r.entity_id}",
                "rule": r.rule_name,
                "details": r.details or r.action_taken,
            })
        return actions

    # ------------------------------------------------------------------
    # Creative pipeline
    # ------------------------------------------------------------------

    def _build_creative_pipeline(self) -> Dict[str, Any]:
        """Snapshot of creative pipeline health."""
        all_tags = self._db.get_creative_tags()
        all_ads = self._db.list_ads()
        campaigns = self._db.list_campaigns()

        # Map campaign_id -> type
        ctype = {c.campaign_id: c.campaign_type for c in campaigns}

        in_test = 0
        graduated = 0
        killed = 0

        for ad in all_ads:
            ct = ctype.get(ad.campaign_id, "test")
            if ad.status == "PAUSED":
                killed += 1
            elif ct == "test" and ad.status == "ACTIVE":
                in_test += 1
            elif ct == "scale" and ad.status == "ACTIVE":
                graduated += 1

        return {
            "total_creatives": len(all_tags),
            "in_test": in_test,
            "graduated": graduated,
            "killed": killed,
            "active_total": in_test + graduated,
        }

    # ------------------------------------------------------------------
    # Fatigue detection
    # ------------------------------------------------------------------

    def _detect_fatigue(self, date: str) -> List[Dict[str, Any]]:
        """Identify creatives showing fatigue signals on *date*."""
        warnings: List[Dict[str, Any]] = []
        insights = self._db.get_insights(date_start=date, date_end=date)

        for ins in insights:
            reasons: List[str] = []

            if ins.frequency > 4.0:
                reasons.append(
                    f"Frequency {ins.frequency:.1f} (threshold: 4.0)"
                )

            # Check hook-rate trend over last 5 days
            d = datetime.strptime(date, "%Y-%m-%d")
            trend_start = (d - timedelta(days=5)).strftime("%Y-%m-%d")
            trend = self._db.get_ad_trend(
                ins.ad_id, "hook_rate", days=5
            )
            if len(trend) >= 3:
                first_val = trend[0]["value"] or 0
                last_val = trend[-1]["value"] or 0
                if first_val > 0:
                    decline = _pct_change(last_val, first_val)
                    if decline < -10:
                        reasons.append(
                            f"Hook rate declined {decline:.1f}% over 5d"
                        )

            if reasons:
                ad = self._db.get_ad(ins.ad_id)
                warnings.append({
                    "ad_id": ins.ad_id,
                    "ad_name": ad.name if ad else ins.ad_id,
                    "reasons": reasons,
                })

        return warnings

    # ------------------------------------------------------------------
    # Output: dict
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return the raw report data as a dictionary."""
        if not self._generated:
            raise RuntimeError("Call generate() before to_dict().")
        return self._data

    # ------------------------------------------------------------------
    # Output: plain text
    # ------------------------------------------------------------------

    def format_text(self) -> str:
        """
        Render the report as clean plain text suitable for terminal or email.
        """
        if not self._generated:
            raise RuntimeError("Call generate() before format_text().")

        d = self._data
        day = d["day"]
        targets = d["vs_targets"]
        vs7d = d["vs_7d"]
        lines: List[str] = []

        # Header
        lines.append("=" * 62)
        lines.append("  DAILY ADS REPORT")
        lines.append(f"  Date: {d['date']}")
        lines.append("=" * 62)
        lines.append("")

        # Summary line
        lines.append(
            f"  Yesterday: {_fmt_currency(day['spend'])} spent | "
            f"{day['conversions']} conversions | "
            f"{_fmt_currency(day['cpa'])} CPA | "
            f"{day['roas']}x ROAS"
        )
        lines.append("")

        # vs Targets
        lines.append("--- VS TARGETS ---")
        cpa_t = targets["cpa"]
        roas_t = targets["roas"]
        cpa_status = "OK" if cpa_t["status"] == "good" else "HIGH"
        roas_status = "OK" if roas_t["status"] == "good" else "LOW"
        lines.append(
            f"  CPA:  {_fmt_currency(cpa_t['actual'])} vs "
            f"{_fmt_currency(cpa_t['target'])} target "
            f"({_fmt_pct(cpa_t['delta_pct'])} {cpa_t['arrow']}) [{cpa_status}]"
        )
        lines.append(
            f"  ROAS: {roas_t['actual']}x vs {roas_t['target']}x target "
            f"({_fmt_pct(roas_t['delta_pct'])} {roas_t['arrow']}) [{roas_status}]"
        )
        lines.append("")

        # vs 7-day average
        lines.append("--- VS 7-DAY AVERAGE ---")
        for key, label in [
            ("spend", "Spend"),
            ("cpa", "CPA"),
            ("roas", "ROAS"),
            ("ctr", "CTR"),
        ]:
            v = vs7d[key]
            today_val = (
                _fmt_currency(v["today"])
                if key == "spend" or key == "cpa"
                else f"{v['today']}"
            )
            avg_val = (
                _fmt_currency(v["avg_7d"])
                if key == "spend" or key == "cpa"
                else f"{v['avg_7d']}"
            )
            lines.append(
                f"  {label:6s}: {today_val} vs {avg_val} "
                f"({_fmt_pct(v['delta_pct'])} {v['arrow']})"
            )
        lines.append("")

        # Top 3 ads
        lines.append("--- TOP 3 ADS (by ROAS) ---")
        if not d["top_ads"]:
            lines.append("  (no data)")
        for i, ad in enumerate(d["top_ads"], 1):
            lines.append(
                f"  {i}. {ad.get('ad_name', ad['ad_id'])[:40]}"
            )
            lines.append(
                f"     ROAS {ad.get('roas', ad.get('value', 0))}x | "
                f"CPA {_fmt_currency(ad.get('cpa', 0))} | "
                f"Spend {_fmt_currency(ad.get('spend', ad.get('total_spend', 0)))} | "
                f"{ad.get('conversions', 0)} conv"
            )
        lines.append("")

        # Bottom 3 ads
        lines.append("--- BOTTOM 3 ADS (kill candidates) ---")
        if not d["bottom_ads"]:
            lines.append("  (no data)")
        for i, ad in enumerate(d["bottom_ads"], 1):
            lines.append(
                f"  {i}. {ad.get('ad_name', ad['ad_id'])[:40]}"
            )
            lines.append(
                f"     ROAS {ad.get('roas', ad.get('value', 0))}x | "
                f"CPA {_fmt_currency(ad.get('cpa', 0))} | "
                f"Spend {_fmt_currency(ad.get('spend', ad.get('total_spend', 0)))} | "
                f"{ad.get('conversions', 0)} conv"
            )
        lines.append("")

        # Rules triggered
        lines.append("--- RULES TRIGGERED ---")
        if not d["rules_triggered"]:
            lines.append("  (none)")
        for r in d["rules_triggered"]:
            severity = r.get("rule_type", "").upper()
            lines.append(
                f"  [{severity}] {r['rule_name']} -> "
                f"{r['entity_type']} {r['entity_id']}: {r['action_taken']}"
            )
        lines.append("")

        # Actions taken
        lines.append("--- ACTIONS TAKEN ---")
        if not d["actions_taken"]:
            lines.append("  (no automated actions)")
        for a in d["actions_taken"]:
            lines.append(f"  - {a['action']} ({a['rule']})")
        lines.append("")

        # Creative pipeline
        p = d["pipeline"]
        lines.append("--- CREATIVE PIPELINE ---")
        lines.append(f"  In test:    {p['in_test']}")
        lines.append(f"  Graduated:  {p['graduated']}")
        lines.append(f"  Killed:     {p['killed']}")
        lines.append(f"  Total:      {p['total_creatives']} creatives tracked")
        lines.append("")

        # Fatigue warnings
        lines.append("--- FATIGUE WARNINGS ---")
        if not d["fatigue_warnings"]:
            lines.append("  (no fatigue signals detected)")
        for fw in d["fatigue_warnings"]:
            lines.append(f"  {fw['ad_name'][:45]}:")
            for reason in fw["reasons"]:
                lines.append(f"    - {reason}")
        lines.append("")

        lines.append("=" * 62)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Output: Slack
    # ------------------------------------------------------------------

    def format_slack(self) -> Dict[str, Any]:
        """
        Render the report as a Slack Block Kit payload (mrkdwn).

        Returns a dict ready to POST to a Slack webhook.
        """
        if not self._generated:
            raise RuntimeError("Call generate() before format_slack().")

        d = self._data
        day = d["day"]
        targets = d["vs_targets"]
        vs7d = d["vs_7d"]

        blocks: List[Dict[str, Any]] = []

        # Header
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f":bar_chart: Daily Ads Report  --  {d['date']}",
                "emoji": True,
            },
        })

        # Summary
        cpa_emoji = ":white_check_mark:" if targets["cpa"]["status"] == "good" else ":red_circle:"
        roas_emoji = ":white_check_mark:" if targets["roas"]["status"] == "good" else ":red_circle:"

        summary = (
            f"*Yesterday:* {_fmt_currency(day['spend'])} spent | "
            f"{day['conversions']} conversions | "
            f"{_fmt_currency(day['cpa'])} CPA | "
            f"{day['roas']}x ROAS\n\n"
            f"{cpa_emoji} *CPA:* {_fmt_currency(targets['cpa']['actual'])} vs "
            f"{_fmt_currency(targets['cpa']['target'])} target "
            f"({_fmt_pct(targets['cpa']['delta_pct'])} {targets['cpa']['arrow']})\n"
            f"{roas_emoji} *ROAS:* {targets['roas']['actual']}x vs "
            f"{targets['roas']['target']}x target "
            f"({_fmt_pct(targets['roas']['delta_pct'])} {targets['roas']['arrow']})"
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": summary},
        })

        blocks.append({"type": "divider"})

        # 7-day trend
        trend_lines: List[str] = [":chart_with_upwards_trend: *vs 7-Day Average*"]
        for key, label in [
            ("spend", "Spend"),
            ("cpa", "CPA"),
            ("roas", "ROAS"),
            ("ctr", "CTR"),
        ]:
            v = vs7d[key]
            trend_lines.append(
                f"  {label}: {_fmt_pct(v['delta_pct'])} {v['arrow']}"
            )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(trend_lines)},
        })

        blocks.append({"type": "divider"})

        # Top ads
        if d["top_ads"]:
            top_lines = [":trophy: *Top 3 Ads*"]
            for i, ad in enumerate(d["top_ads"], 1):
                top_lines.append(
                    f"{i}. `{ad.get('ad_name', ad['ad_id'])[:35]}` -- "
                    f"ROAS {ad.get('roas', ad.get('value', 0))}x | "
                    f"CPA {_fmt_currency(ad.get('cpa', 0))}"
                )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(top_lines)},
            })

        # Bottom ads
        if d["bottom_ads"]:
            bot_lines = [":skull: *Bottom 3 Ads (kill candidates)*"]
            for i, ad in enumerate(d["bottom_ads"], 1):
                bot_lines.append(
                    f"{i}. `{ad.get('ad_name', ad['ad_id'])[:35]}` -- "
                    f"ROAS {ad.get('roas', ad.get('value', 0))}x | "
                    f"CPA {_fmt_currency(ad.get('cpa', 0))}"
                )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(bot_lines)},
            })

        blocks.append({"type": "divider"})

        # Rules & actions
        if d["rules_triggered"]:
            rule_lines = [":rotating_light: *Rules Triggered*"]
            for r in d["rules_triggered"]:
                rule_lines.append(
                    f"  [{r['rule_type'].upper()}] {r['rule_name']} -> "
                    f"{r['action_taken']}"
                )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(rule_lines)},
            })

        if d["actions_taken"]:
            act_lines = [":robot_face: *Actions Taken*"]
            for a in d["actions_taken"]:
                act_lines.append(f"  - {a['action']}")
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(act_lines)},
            })

        blocks.append({"type": "divider"})

        # Pipeline
        p = d["pipeline"]
        pipeline_text = (
            f":art: *Creative Pipeline*\n"
            f"  In test: {p['in_test']} | "
            f"Graduated: {p['graduated']} | "
            f"Killed: {p['killed']}"
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": pipeline_text},
        })

        # Fatigue
        if d["fatigue_warnings"]:
            fat_lines = [":warning: *Fatigue Warnings*"]
            for fw in d["fatigue_warnings"]:
                reasons_str = ", ".join(fw["reasons"])
                fat_lines.append(
                    f"  `{fw['ad_name'][:35]}`: {reasons_str}"
                )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(fat_lines)},
            })

        return {"blocks": blocks}
