"""
Weekly Strategic Report — deeper analysis of the past 7 days.

Covers week-over-week trends, campaign breakdown, budget allocation
health, creative winners/losers, pattern insights, test results,
frequency checks, and concrete next-week recommendations.

Usage::

    from reports.weekly_report import WeeklyReport
    from data import db

    report = WeeklyReport(db)
    data = report.generate()                 # week ending yesterday
    print(report.format_text())
    slack_payload = report.format_slack()
"""

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config.settings import (
    CURRENCY,
    ITERATE_BUDGET_PCT,
    MONTHLY_BUDGET,
    SCALE_BUDGET_PCT,
    TARGET_CPA,
    TARGET_ROAS,
    TEST_BUDGET_PCT,
)
from config.rules import CREATIVE_THRESHOLDS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_CURRENCY_SYMBOLS = {"EUR": "\u20ac", "USD": "$", "GBP": "\u00a3"}
_SYM = _CURRENCY_SYMBOLS.get(CURRENCY, CURRENCY + " ")


def _fc(value: float) -> str:
    return f"{_SYM}{value:,.2f}"


def _fp(value: float, decimals: int = 1) -> str:
    return f"{value:+.{decimals}f}%"


def _arrow(delta: float) -> str:
    if delta > 0:
        return "\u2191"
    if delta < 0:
        return "\u2193"
    return "\u2194"


def _pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return round(((current - previous) / previous) * 100, 1)


def _safe_div(n: float, d: float) -> float:
    return n / d if d else 0.0


# ---------------------------------------------------------------------------
# WeeklyReport
# ---------------------------------------------------------------------------


class WeeklyReport:
    """
    Weekly strategic analysis report.

    Parameters
    ----------
    db : module
        The ``data.db`` module (or compatible query API).
    """

    def __init__(self, db: Any) -> None:
        self._db = db
        self._data: Dict[str, Any] = {}
        self._generated = False

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate(self, week_end_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Build the weekly report.

        Parameters
        ----------
        week_end_date : str, optional
            End date of the reporting week (YYYY-MM-DD).  Defaults to
            yesterday (UTC).

        Returns
        -------
        dict
            The raw report data.
        """
        if week_end_date is None:
            week_end_date = (
                datetime.now(tz=timezone.utc) - timedelta(days=1)
            ).strftime("%Y-%m-%d")

        end_dt = datetime.strptime(week_end_date, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=6)
        week_start = start_dt.strftime("%Y-%m-%d")

        # Previous week
        prev_end_dt = start_dt - timedelta(days=1)
        prev_start_dt = prev_end_dt - timedelta(days=6)
        prev_start = prev_start_dt.strftime("%Y-%m-%d")
        prev_end = prev_end_dt.strftime("%Y-%m-%d")

        logger.info(
            "Generating weekly report: %s to %s", week_start, week_end_date
        )

        # -- This week insights --
        this_week = self._db.get_insights(
            date_start=week_start, date_end=week_end_date
        )
        tw_agg = self._aggregate(this_week)

        # -- Last week insights --
        last_week = self._db.get_insights(
            date_start=prev_start, date_end=prev_end
        )
        lw_agg = self._aggregate(last_week)

        # -- WoW trends --
        wow = self._wow_trends(tw_agg, lw_agg)

        # -- Campaign breakdown --
        campaigns = self._db.list_campaigns()
        campaign_breakdown = self._campaign_breakdown(
            campaigns, week_start, week_end_date
        )

        # -- Budget allocation --
        budget_check = self._budget_allocation_check(
            campaign_breakdown, tw_agg["spend"]
        )

        # -- Creative winners & losers --
        winners = self._db.get_best_performing_ads("roas", days=7, limit=5)
        losers = self._db.get_worst_performing_ads("roas", days=7, limit=5)

        # Enrich winners/losers with creative tag info
        winners = self._enrich_with_tags(winners)
        losers = self._enrich_with_tags(losers)

        # -- Pattern insights --
        patterns = self._detect_patterns(this_week, week_start, week_end_date)

        # -- Test results --
        tests = self._summarise_tests(campaigns, week_start, week_end_date)

        # -- Recommendations --
        recommendations = self._build_recommendations(
            tw_agg, wow, budget_check, patterns, losers
        )

        # -- Frequency check --
        freq_warnings = self._frequency_check(this_week)

        self._data = {
            "week_start": week_start,
            "week_end": week_end_date,
            "summary": tw_agg,
            "prev_week_summary": lw_agg,
            "wow_trends": wow,
            "campaign_breakdown": campaign_breakdown,
            "budget_allocation": budget_check,
            "creative_winners": winners,
            "creative_losers": losers,
            "pattern_insights": patterns,
            "test_results": tests,
            "recommendations": recommendations,
            "frequency_warnings": freq_warnings,
        }
        self._generated = True
        logger.info("Weekly report generated")
        return self._data

    # ------------------------------------------------------------------
    # Internal aggregation
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate(insights: List[Any]) -> Dict[str, float]:
        if not insights:
            return {
                "spend": 0.0, "revenue": 0.0, "impressions": 0,
                "clicks": 0, "conversions": 0, "cpa": 0.0, "roas": 0.0,
                "ctr": 0.0, "cpm": 0.0, "hook_rate": 0.0, "hold_rate": 0.0,
                "frequency": 0.0, "active_ads": 0,
            }
        s = sum(i.spend for i in insights)
        imp = sum(i.impressions for i in insights)
        cl = sum(i.clicks for i in insights)
        cv = sum(i.conversions for i in insights)
        rev = sum(i.revenue for i in insights)
        v3 = sum(i.video_views_3s for i in insights)
        v15 = sum(i.video_views_15s for i in insights)
        return {
            "spend": round(s, 2),
            "revenue": round(rev, 2),
            "impressions": imp,
            "clicks": cl,
            "conversions": cv,
            "cpa": round(_safe_div(s, cv), 2),
            "roas": round(_safe_div(rev, s), 2),
            "ctr": round(_safe_div(cl, imp) * 100, 2),
            "cpm": round(_safe_div(s, imp) * 1000, 2),
            "hook_rate": round(_safe_div(v3, imp) * 100, 2),
            "hold_rate": round(_safe_div(v15, v3) * 100, 2),
            "frequency": round(
                sum(i.frequency for i in insights) / len(insights), 2
            ),
            "active_ads": len({i.ad_id for i in insights}),
        }

    @staticmethod
    def _wow_trends(tw: Dict, lw: Dict) -> Dict[str, Any]:
        trends: Dict[str, Any] = {}
        for key in ("spend", "revenue", "cpa", "roas", "ctr", "conversions"):
            curr = tw.get(key, 0)
            prev = lw.get(key, 0)
            delta = _pct_change(float(curr), float(prev))
            trends[key] = {
                "this_week": curr,
                "last_week": prev,
                "delta_pct": delta,
                "arrow": _arrow(delta),
            }
        return trends

    # ------------------------------------------------------------------
    # Campaign breakdown
    # ------------------------------------------------------------------

    def _campaign_breakdown(
        self,
        campaigns: List[Any],
        start: str,
        end: str,
    ) -> List[Dict[str, Any]]:
        breakdown: List[Dict[str, Any]] = []
        for c in campaigns:
            insights = self._db.get_insights(
                date_start=start, date_end=end
            )
            # Filter to ads belonging to this campaign
            camp_insights = [
                i for i in insights
                if self._ad_belongs_to_campaign(i.ad_id, c.campaign_id)
            ]
            if not camp_insights:
                continue
            agg = self._aggregate(camp_insights)
            breakdown.append({
                "campaign_id": c.campaign_id,
                "campaign_name": c.name,
                "campaign_type": c.campaign_type,
                "status": c.status,
                **agg,
            })
        # Sort by spend descending
        breakdown.sort(key=lambda x: x["spend"], reverse=True)
        return breakdown

    def _ad_belongs_to_campaign(self, ad_id: str, campaign_id: str) -> bool:
        """Check whether an ad belongs to a given campaign."""
        ad = self._db.get_ad(ad_id)
        if ad is None:
            return False
        return ad.campaign_id == campaign_id

    # ------------------------------------------------------------------
    # Budget allocation
    # ------------------------------------------------------------------

    @staticmethod
    def _budget_allocation_check(
        breakdown: List[Dict[str, Any]], total_spend: float
    ) -> Dict[str, Any]:
        if total_spend == 0:
            return {
                "scale": {"target_pct": 70, "actual_pct": 0, "delta": 0},
                "iterate": {"target_pct": 20, "actual_pct": 0, "delta": 0},
                "test": {"target_pct": 10, "actual_pct": 0, "delta": 0},
                "rebalance_needed": False,
                "suggestions": [],
            }

        spend_by_type: Dict[str, float] = defaultdict(float)
        for c in breakdown:
            spend_by_type[c["campaign_type"]] += c["spend"]

        target_map = {
            "scale": SCALE_BUDGET_PCT * 100,
            "iterate": ITERATE_BUDGET_PCT * 100,
            "test": TEST_BUDGET_PCT * 100,
        }

        result: Dict[str, Any] = {}
        suggestions: List[str] = []
        rebalance = False

        for ctype, target_pct in target_map.items():
            actual = spend_by_type.get(ctype, 0.0)
            actual_pct = round((actual / total_spend) * 100, 1)
            delta = round(actual_pct - target_pct, 1)
            result[ctype] = {
                "target_pct": target_pct,
                "actual_pct": actual_pct,
                "actual_spend": round(actual, 2),
                "delta": delta,
            }
            if abs(delta) > 10:
                rebalance = True
                direction = "over" if delta > 0 else "under"
                suggestions.append(
                    f"{ctype.title()} campaigns are {direction}-allocated "
                    f"by {abs(delta):.1f}pp ({actual_pct:.1f}% vs {target_pct:.0f}% target)"
                )

        # Include retarget if it has spend
        retarget_spend = spend_by_type.get("retarget", 0.0)
        if retarget_spend > 0:
            result["retarget"] = {
                "actual_pct": round((retarget_spend / total_spend) * 100, 1),
                "actual_spend": round(retarget_spend, 2),
            }

        result["rebalance_needed"] = rebalance
        result["suggestions"] = suggestions
        return result

    # ------------------------------------------------------------------
    # Creative enrichment
    # ------------------------------------------------------------------

    def _enrich_with_tags(
        self, ad_rows: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        for row in ad_rows:
            tags = self._db.get_creative_tags(ad_id=row["ad_id"])
            if tags:
                t = tags[0]
                row["format"] = t.format
                row["hook_type"] = t.hook_type
                row["angle"] = t.angle
                row["source"] = t.source
            else:
                row["format"] = ""
                row["hook_type"] = ""
                row["angle"] = ""
                row["source"] = ""
        return ad_rows

    # ------------------------------------------------------------------
    # Pattern detection
    # ------------------------------------------------------------------

    def _detect_patterns(
        self, insights: List[Any], start: str, end: str
    ) -> List[Dict[str, str]]:
        """Detect performance patterns by creative attributes."""
        patterns: List[Dict[str, str]] = []

        # Build per-format and per-hook aggregates
        by_format: Dict[str, List[Any]] = defaultdict(list)
        by_hook: Dict[str, List[Any]] = defaultdict(list)
        by_source: Dict[str, List[Any]] = defaultdict(list)

        for ins in insights:
            tags = self._db.get_creative_tags(ad_id=ins.ad_id)
            if not tags:
                continue
            t = tags[0]
            if t.format:
                by_format[t.format].append(ins)
            if t.hook_type:
                by_hook[t.hook_type].append(ins)
            if t.source:
                by_source[t.source].append(ins)

        # Format comparison
        format_roas: Dict[str, float] = {}
        for fmt, ins_list in by_format.items():
            total_rev = sum(i.revenue for i in ins_list)
            total_spend = sum(i.spend for i in ins_list)
            format_roas[fmt] = round(_safe_div(total_rev, total_spend), 2)

        if len(format_roas) >= 2:
            sorted_fmts = sorted(
                format_roas.items(), key=lambda x: x[1], reverse=True
            )
            best_fmt, best_roas = sorted_fmts[0]
            worst_fmt, worst_roas = sorted_fmts[-1]
            if worst_roas > 0:
                ratio = round(best_roas / worst_roas, 1)
                patterns.append({
                    "type": "format_comparison",
                    "insight": (
                        f"{best_fmt.upper()} outperformed {worst_fmt.upper()} "
                        f"by {ratio}x this week "
                        f"(ROAS {best_roas}x vs {worst_roas}x)"
                    ),
                })

        # Hook type comparison
        hook_rates: Dict[str, float] = {}
        for hook, ins_list in by_hook.items():
            total_3s = sum(i.video_views_3s for i in ins_list)
            total_imp = sum(i.impressions for i in ins_list)
            hook_rates[hook] = round(_safe_div(total_3s, total_imp) * 100, 1)

        if len(hook_rates) >= 2:
            best_hook = max(hook_rates, key=hook_rates.get)  # type: ignore[arg-type]
            patterns.append({
                "type": "hook_comparison",
                "insight": (
                    f"{best_hook.title()} hooks averaged "
                    f"{hook_rates[best_hook]:.0f}% hook rate"
                ),
            })

        # Community vs non-community
        comm = by_source.get("community", [])
        manual = by_source.get("manual", [])
        if comm and manual:
            comm_roas = round(
                _safe_div(
                    sum(i.revenue for i in comm),
                    sum(i.spend for i in comm),
                ),
                2,
            )
            manual_roas = round(
                _safe_div(
                    sum(i.revenue for i in manual),
                    sum(i.spend for i in manual),
                ),
                2,
            )
            if manual_roas > 0:
                ratio = round(comm_roas / manual_roas, 1)
                verb = "outperformed" if ratio > 1 else "underperformed vs"
                patterns.append({
                    "type": "source_comparison",
                    "insight": (
                        f"Community-sourced ads {verb} manual "
                        f"({comm_roas}x vs {manual_roas}x ROAS)"
                    ),
                })

        return patterns

    # ------------------------------------------------------------------
    # Test results
    # ------------------------------------------------------------------

    def _summarise_tests(
        self,
        campaigns: List[Any],
        start: str,
        end: str,
    ) -> List[Dict[str, Any]]:
        test_campaigns = [c for c in campaigns if c.campaign_type == "test"]
        results: List[Dict[str, Any]] = []

        for c in test_campaigns:
            ads = self._db.list_ads(campaign_id=c.campaign_id)
            for ad in ads:
                summary = self._db.get_insights_summary(ad.ad_id, days=7)
                if summary is None or summary["spend"] == 0:
                    continue
                status = "winner" if summary["roas"] >= TARGET_ROAS else "testing"
                if summary["conversions"] >= 10 and summary["roas"] >= TARGET_ROAS:
                    status = "graduate"
                elif (
                    summary["spend"] > TARGET_CPA * 2
                    and summary["conversions"] == 0
                ):
                    status = "killed"

                results.append({
                    "ad_id": ad.ad_id,
                    "ad_name": ad.name,
                    "campaign": c.name,
                    "spend": summary["spend"],
                    "conversions": summary["conversions"],
                    "cpa": summary["avg_cpa"],
                    "roas": summary["roas"],
                    "status": status,
                })

        results.sort(key=lambda x: x["roas"], reverse=True)
        return results

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    @staticmethod
    def _build_recommendations(
        tw: Dict,
        wow: Dict,
        budget: Dict,
        patterns: List,
        losers: List,
    ) -> List[str]:
        recs: List[str] = []

        # CPA rising
        cpa_trend = wow.get("cpa", {}).get("delta_pct", 0)
        if cpa_trend > 15:
            recs.append(
                f"CPA rose {cpa_trend:.0f}% WoW -- review audience overlap "
                "and creative freshness."
            )

        # Budget rebalance
        if budget.get("rebalance_needed"):
            for s in budget.get("suggestions", []):
                recs.append(f"Budget: {s}")

        # Pattern-based
        for p in patterns:
            if p["type"] == "format_comparison":
                recs.append(
                    f"Double down on top format: {p['insight']}"
                )

        # Kill losers
        if losers:
            low_roas = [l for l in losers if l.get("value", 0) < 1.0]
            if low_roas:
                names = ", ".join(
                    l.get("ad_name", l["ad_id"])[:25] for l in low_roas[:3]
                )
                recs.append(
                    f"Consider killing low-ROAS ads: {names}"
                )

        # Conversions declining
        conv_trend = wow.get("conversions", {}).get("delta_pct", 0)
        if conv_trend < -20:
            recs.append(
                f"Conversions dropped {abs(conv_trend):.0f}% WoW -- "
                "check landing page and offer."
            )

        if not recs:
            recs.append("Performance is stable. Keep testing new creatives.")

        return recs

    # ------------------------------------------------------------------
    # Frequency check
    # ------------------------------------------------------------------

    @staticmethod
    def _frequency_check(insights: List[Any]) -> List[Dict[str, Any]]:
        """Flag ad sets approaching fatigue-level frequency."""
        # Group by ad_id, take max frequency
        by_ad: Dict[str, float] = {}
        for i in insights:
            by_ad[i.ad_id] = max(by_ad.get(i.ad_id, 0), i.frequency)

        warnings: List[Dict[str, Any]] = []
        for ad_id, freq in sorted(
            by_ad.items(), key=lambda x: x[1], reverse=True
        ):
            if freq >= 3.0:
                level = "critical" if freq >= 5.0 else "warning"
                warnings.append({
                    "ad_id": ad_id,
                    "frequency": freq,
                    "level": level,
                })
        return warnings[:10]

    # ------------------------------------------------------------------
    # Output: dict
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        if not self._generated:
            raise RuntimeError("Call generate() before to_dict().")
        return self._data

    # ------------------------------------------------------------------
    # Output: plain text
    # ------------------------------------------------------------------

    def format_text(self) -> str:
        """Render the weekly report as plain text."""
        if not self._generated:
            raise RuntimeError("Call generate() before format_text().")

        d = self._data
        tw = d["summary"]
        wow = d["wow_trends"]
        lines: List[str] = []

        lines.append("=" * 64)
        lines.append("  WEEKLY ADS REPORT")
        lines.append(f"  {d['week_start']} to {d['week_end']}")
        lines.append("=" * 64)
        lines.append("")

        # Week summary
        lines.append("--- WEEK SUMMARY ---")
        lines.append(
            f"  Spend:       {_fc(tw['spend'])}\n"
            f"  Revenue:     {_fc(tw['revenue'])}\n"
            f"  ROAS:        {tw['roas']}x\n"
            f"  CPA:         {_fc(tw['cpa'])}\n"
            f"  Conversions: {tw['conversions']}\n"
            f"  Active ads:  {tw['active_ads']}"
        )
        lines.append("")

        # WoW trends
        lines.append("--- WEEK-OVER-WEEK TRENDS ---")
        for key, label in [
            ("spend", "Spend"),
            ("revenue", "Revenue"),
            ("cpa", "CPA"),
            ("roas", "ROAS"),
            ("ctr", "CTR"),
            ("conversions", "Conversions"),
        ]:
            v = wow.get(key, {})
            lines.append(
                f"  {label:13s} {_fp(v.get('delta_pct', 0)):>8s} {v.get('arrow', '')}"
            )
        lines.append("")

        # Campaign breakdown
        lines.append("--- CAMPAIGN BREAKDOWN ---")
        for c in d["campaign_breakdown"]:
            tag = c["campaign_type"].upper()
            lines.append(
                f"  [{tag:8s}] {c['campaign_name'][:30]:30s} | "
                f"Spend {_fc(c['spend']):>10s} | "
                f"ROAS {c['roas']}x | "
                f"CPA {_fc(c['cpa'])}"
            )
        if not d["campaign_breakdown"]:
            lines.append("  (no campaign data)")
        lines.append("")

        # Budget allocation
        ba = d["budget_allocation"]
        lines.append("--- BUDGET ALLOCATION (70/20/10 target) ---")
        for ctype in ("scale", "iterate", "test"):
            info = ba.get(ctype, {})
            actual = info.get("actual_pct", 0)
            target = info.get("target_pct", 0)
            delta = info.get("delta", 0)
            bar_len = int(actual / 2)
            bar = "\u2588" * bar_len + "\u2591" * (50 - bar_len)
            lines.append(
                f"  {ctype.title():8s}: {actual:5.1f}% / {target:.0f}% "
                f"({_fp(delta)}) {bar}"
            )
        if ba.get("rebalance_needed"):
            lines.append("  ** REBALANCE RECOMMENDED **")
            for s in ba.get("suggestions", []):
                lines.append(f"    - {s}")
        lines.append("")

        # Creative winners
        lines.append("--- CREATIVE WINNERS OF THE WEEK ---")
        for i, w in enumerate(d["creative_winners"], 1):
            fmt = w.get("format", "?").upper()
            hook = w.get("hook_type", "?")
            lines.append(
                f"  {i}. {w.get('ad_name', w['ad_id'])[:35]}"
            )
            lines.append(
                f"     ROAS {w.get('value', 0)}x | "
                f"Spend {_fc(w.get('total_spend', 0))} | "
                f"Format: {fmt} | Hook: {hook}"
            )
        if not d["creative_winners"]:
            lines.append("  (no data)")
        lines.append("")

        # Creative losers
        lines.append("--- CREATIVE LOSERS ---")
        for i, l in enumerate(d["creative_losers"], 1):
            lines.append(
                f"  {i}. {l.get('ad_name', l['ad_id'])[:35]}"
            )
            lines.append(
                f"     ROAS {l.get('value', 0)}x | "
                f"Spend {_fc(l.get('total_spend', 0))} | "
                f"Format: {l.get('format', '?').upper()}"
            )
        if not d["creative_losers"]:
            lines.append("  (no data)")
        lines.append("")

        # Pattern insights
        lines.append("--- PATTERN INSIGHTS ---")
        if not d["pattern_insights"]:
            lines.append("  (insufficient data for patterns)")
        for p in d["pattern_insights"]:
            lines.append(f"  - {p['insight']}")
        lines.append("")

        # Test results
        lines.append("--- TEST RESULTS ---")
        if not d["test_results"]:
            lines.append("  (no active tests)")
        for t in d["test_results"]:
            status_icon = {
                "graduate": "[GRADUATE]",
                "winner": "[WINNER]",
                "testing": "[TESTING]",
                "killed": "[KILLED]",
            }.get(t["status"], f"[{t['status'].upper()}]")
            lines.append(
                f"  {status_icon:12s} {t['ad_name'][:30]:30s} | "
                f"ROAS {t['roas']}x | CPA {_fc(t['cpa'])} | "
                f"{t['conversions']} conv"
            )
        lines.append("")

        # Frequency warnings
        lines.append("--- FREQUENCY CHECK ---")
        if not d["frequency_warnings"]:
            lines.append("  All frequencies within healthy range.")
        for fw in d["frequency_warnings"]:
            icon = "!!" if fw["level"] == "critical" else "!"
            lines.append(
                f"  {icon} ad {fw['ad_id'][:25]} -- "
                f"frequency {fw['frequency']:.1f}"
            )
        lines.append("")

        # Recommendations
        lines.append("--- RECOMMENDATIONS FOR NEXT WEEK ---")
        for i, r in enumerate(d["recommendations"], 1):
            lines.append(f"  {i}. {r}")
        lines.append("")

        lines.append("=" * 64)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Output: Slack
    # ------------------------------------------------------------------

    def format_slack(self) -> Dict[str, Any]:
        """Render the weekly report as Slack Block Kit payload."""
        if not self._generated:
            raise RuntimeError("Call generate() before format_slack().")

        d = self._data
        tw = d["summary"]
        wow = d["wow_trends"]
        blocks: List[Dict[str, Any]] = []

        # Header
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": (
                    f":calendar: Weekly Ads Report  --  "
                    f"{d['week_start']} to {d['week_end']}"
                ),
                "emoji": True,
            },
        })

        # Summary
        summary = (
            f"*Week Summary*\n"
            f"Spend: {_fc(tw['spend'])} | Revenue: {_fc(tw['revenue'])} | "
            f"ROAS: {tw['roas']}x | CPA: {_fc(tw['cpa'])} | "
            f"{tw['conversions']} conversions"
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": summary},
        })

        blocks.append({"type": "divider"})

        # WoW trends
        trend_lines = [":chart_with_upwards_trend: *Week-over-Week*"]
        for key, label in [
            ("spend", "Spend"),
            ("revenue", "Revenue"),
            ("cpa", "CPA"),
            ("roas", "ROAS"),
            ("conversions", "Conv"),
        ]:
            v = wow.get(key, {})
            trend_lines.append(
                f"  {label}: {_fp(v.get('delta_pct', 0))} {v.get('arrow', '')}"
            )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(trend_lines)},
        })

        blocks.append({"type": "divider"})

        # Campaign breakdown
        if d["campaign_breakdown"]:
            camp_lines = [":clipboard: *Campaign Breakdown*"]
            for c in d["campaign_breakdown"]:
                camp_lines.append(
                    f"  `[{c['campaign_type'].upper()}]` {c['campaign_name'][:25]} -- "
                    f"ROAS {c['roas']}x | CPA {_fc(c['cpa'])}"
                )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(camp_lines)},
            })

        # Budget allocation
        ba = d["budget_allocation"]
        ba_lines = [":moneybag: *Budget Allocation (70/20/10)*"]
        for ctype in ("scale", "iterate", "test"):
            info = ba.get(ctype, {})
            ba_lines.append(
                f"  {ctype.title()}: {info.get('actual_pct', 0):.1f}% "
                f"(target {info.get('target_pct', 0):.0f}%)"
            )
        if ba.get("rebalance_needed"):
            ba_lines.append("  :warning: *Rebalance recommended*")
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(ba_lines)},
        })

        blocks.append({"type": "divider"})

        # Winners
        if d["creative_winners"]:
            win_lines = [":trophy: *Creative Winners*"]
            for i, w in enumerate(d["creative_winners"][:5], 1):
                win_lines.append(
                    f"{i}. `{w.get('ad_name', w['ad_id'])[:30]}` -- "
                    f"ROAS {w.get('value', 0)}x | {w.get('format', '').upper()}"
                )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(win_lines)},
            })

        # Pattern insights
        if d["pattern_insights"]:
            pat_lines = [":bulb: *Pattern Insights*"]
            for p in d["pattern_insights"]:
                pat_lines.append(f"  - {p['insight']}")
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(pat_lines)},
            })

        blocks.append({"type": "divider"})

        # Recommendations
        rec_lines = [":dart: *Recommendations*"]
        for i, r in enumerate(d["recommendations"], 1):
            rec_lines.append(f"  {i}. {r}")
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(rec_lines)},
        })

        return {"blocks": blocks}
