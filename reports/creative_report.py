"""
Creative Performance Report — deep dive into creative asset performance.

Analyses creative scoreboard, format/hook/angle comparisons, fatigue
timelines, lifecycle analysis, and production recommendations over a
configurable time window.

Usage::

    from reports.creative_report import CreativeReport
    from data import db

    report = CreativeReport(db)
    data = report.generate(days=30)
    print(report.format_text())
    slack_payload = report.format_slack()
"""

import logging
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from config.settings import CURRENCY, TARGET_CPA, TARGET_ROAS
from config.rules import CREATIVE_THRESHOLDS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_CURRENCY_SYMBOLS = {"EUR": "\u20ac", "USD": "$", "GBP": "\u00a3"}
_SYM = _CURRENCY_SYMBOLS.get(CURRENCY, CURRENCY + " ")


def _fc(v: float) -> str:
    return f"{_SYM}{v:,.2f}"


def _fp(v: float, d: int = 1) -> str:
    return f"{v:+.{d}f}%"


def _safe_div(n: float, denom: float) -> float:
    return n / denom if denom else 0.0


def _grade(value: float, thresholds: Dict[str, float], higher_better: bool = True) -> str:
    """Return a letter-style grade based on threshold bands."""
    if higher_better:
        if value >= thresholds.get("great", float("inf")):
            return "A"
        if value >= thresholds.get("good", float("inf")):
            return "B"
        if value >= thresholds.get("okay", float("inf")):
            return "C"
        return "D"
    else:
        # Lower is better (e.g. CPA vs target)
        if value <= thresholds.get("great", 0):
            return "A"
        if value <= thresholds.get("good", 0):
            return "B"
        if value <= thresholds.get("okay", 0):
            return "C"
        return "D"


# ---------------------------------------------------------------------------
# CreativeReport
# ---------------------------------------------------------------------------


class CreativeReport:
    """
    Deep dive into creative asset performance over a configurable window.

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

    def generate(self, days: int = 30) -> Dict[str, Any]:
        """
        Build the creative performance report covering the last *days*.

        Returns
        -------
        dict
            The raw report data.
        """
        logger.info("Generating creative report for the last %d days", days)

        end_date = (
            datetime.now(tz=timezone.utc) - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        start_date = (
            datetime.now(tz=timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%d")

        # Pull all insights in the window
        all_insights = self._db.get_insights(
            date_start=start_date, date_end=end_date
        )
        all_tags = self._db.get_creative_tags()

        # Index tags by ad_id for fast lookup
        tag_by_ad: Dict[str, Any] = {}
        for t in all_tags:
            tag_by_ad[t.ad_id] = t

        # -- Scoreboard --
        scoreboard = self._build_scoreboard(all_insights, tag_by_ad, days)

        # -- Format comparison --
        format_cmp = self._compare_by_attribute(
            all_insights, tag_by_ad, "format"
        )

        # -- Hook type comparison --
        hook_cmp = self._compare_by_attribute(
            all_insights, tag_by_ad, "hook_type"
        )

        # -- Angle comparison --
        angle_cmp = self._compare_by_attribute(
            all_insights, tag_by_ad, "angle"
        )

        # -- Fatigue timeline --
        fatigue_timeline = self._fatigue_timeline(all_insights, tag_by_ad, days)

        # -- Lifecycle analysis --
        lifecycle = self._lifecycle_analysis(all_insights, tag_by_ad)

        # -- Production recommendations --
        prod_recs = self._production_recommendations(
            format_cmp, hook_cmp, angle_cmp, scoreboard
        )

        # -- Community vs non-community --
        source_cmp = self._compare_by_attribute(
            all_insights, tag_by_ad, "source"
        )

        # -- Top hooks --
        top_hooks = self._top_hooks(all_insights, tag_by_ad)

        self._data = {
            "period_days": days,
            "start_date": start_date,
            "end_date": end_date,
            "scoreboard": scoreboard,
            "format_comparison": format_cmp,
            "hook_type_comparison": hook_cmp,
            "angle_comparison": angle_cmp,
            "fatigue_timeline": fatigue_timeline,
            "lifecycle_analysis": lifecycle,
            "production_recommendations": prod_recs,
            "source_comparison": source_cmp,
            "top_hooks": top_hooks,
        }
        self._generated = True
        logger.info("Creative report generated (%d creatives scored)", len(scoreboard))
        return self._data

    # ------------------------------------------------------------------
    # Scoreboard
    # ------------------------------------------------------------------

    def _build_scoreboard(
        self,
        insights: List[Any],
        tag_by_ad: Dict[str, Any],
        days: int,
    ) -> List[Dict[str, Any]]:
        """Rank all creatives by a composite score."""
        # Aggregate per ad
        by_ad: Dict[str, List[Any]] = defaultdict(list)
        for ins in insights:
            by_ad[ins.ad_id].append(ins)

        entries: List[Dict[str, Any]] = []
        for ad_id, ins_list in by_ad.items():
            total_spend = sum(i.spend for i in ins_list)
            if total_spend == 0:
                continue

            total_rev = sum(i.revenue for i in ins_list)
            total_imp = sum(i.impressions for i in ins_list)
            total_cl = sum(i.clicks for i in ins_list)
            total_cv = sum(i.conversions for i in ins_list)
            total_3s = sum(i.video_views_3s for i in ins_list)
            total_15s = sum(i.video_views_15s for i in ins_list)

            roas = round(_safe_div(total_rev, total_spend), 2)
            cpa = round(_safe_div(total_spend, total_cv), 2)
            ctr = round(_safe_div(total_cl, total_imp) * 100, 2)
            hook_rate = round(_safe_div(total_3s, total_imp) * 100, 2)
            hold_rate = round(_safe_div(total_15s, total_3s) * 100, 2)

            # Composite score (weighted)
            score = self._composite_score(
                hook_rate, hold_rate, ctr, cpa, roas
            )

            tag = tag_by_ad.get(ad_id)
            ad_obj = self._db.get_ad(ad_id)
            entries.append({
                "ad_id": ad_id,
                "ad_name": ad_obj.name if ad_obj else ad_id,
                "format": tag.format if tag else "",
                "hook_type": tag.hook_type if tag else "",
                "angle": tag.angle if tag else "",
                "source": tag.source if tag else "",
                "spend": round(total_spend, 2),
                "revenue": round(total_rev, 2),
                "conversions": total_cv,
                "roas": roas,
                "cpa": cpa,
                "ctr": ctr,
                "hook_rate": hook_rate,
                "hold_rate": hold_rate,
                "composite_score": score,
                "days_active": len(ins_list),
                "grade_hook": _grade(
                    hook_rate, CREATIVE_THRESHOLDS["hook_rate"], True
                ),
                "grade_hold": _grade(
                    hold_rate, CREATIVE_THRESHOLDS["hold_rate"], True
                ),
                "grade_ctr": _grade(
                    ctr, CREATIVE_THRESHOLDS["ctr"], True
                ),
                "grade_cpa": _grade(
                    _safe_div(cpa, TARGET_CPA),
                    CREATIVE_THRESHOLDS["cpa_vs_target"],
                    False,
                ),
            })

        entries.sort(key=lambda x: x["composite_score"], reverse=True)
        return entries

    @staticmethod
    def _composite_score(
        hook_rate: float,
        hold_rate: float,
        ctr: float,
        cpa: float,
        roas: float,
    ) -> float:
        """
        Calculate a 0-100 composite score.

        Weights: ROAS 30%, CPA 25%, Hook 20%, Hold 15%, CTR 10%.
        Each sub-metric is normalised against its thresholds.
        """
        def _norm(val: float, poor: float, great: float) -> float:
            if great == poor:
                return 50.0
            clamped = max(poor, min(val, great))
            return ((clamped - poor) / (great - poor)) * 100

        def _norm_inv(val: float, great: float, poor: float) -> float:
            """Normalise where lower is better."""
            if poor == great:
                return 50.0
            clamped = max(great, min(val, poor))
            return ((poor - clamped) / (poor - great)) * 100

        th = CREATIVE_THRESHOLDS
        s_hook = _norm(hook_rate, th["hook_rate"]["poor"], th["hook_rate"]["great"])
        s_hold = _norm(hold_rate, th["hold_rate"]["poor"], th["hold_rate"]["great"])
        s_ctr = _norm(ctr, th["ctr"]["poor"], th["ctr"]["great"])
        s_cpa = _norm_inv(
            _safe_div(cpa, TARGET_CPA) if TARGET_CPA else 1.0,
            th["cpa_vs_target"]["great"],
            th["cpa_vs_target"]["poor"],
        )
        s_roas = _norm(
            _safe_div(roas, TARGET_ROAS) if TARGET_ROAS else 1.0,
            th["roas_vs_target"]["poor"],
            th["roas_vs_target"]["great"],
        )

        composite = (
            s_roas * 0.30
            + s_cpa * 0.25
            + s_hook * 0.20
            + s_hold * 0.15
            + s_ctr * 0.10
        )
        return round(composite, 1)

    # ------------------------------------------------------------------
    # Attribute comparison helper
    # ------------------------------------------------------------------

    def _compare_by_attribute(
        self,
        insights: List[Any],
        tag_by_ad: Dict[str, Any],
        attribute: str,
    ) -> List[Dict[str, Any]]:
        """Group insights by a creative tag attribute and aggregate."""
        groups: Dict[str, List[Any]] = defaultdict(list)
        for ins in insights:
            tag = tag_by_ad.get(ins.ad_id)
            value = getattr(tag, attribute, "") if tag else ""
            if not value:
                value = "(unknown)"
            groups[value].append(ins)

        results: List[Dict[str, Any]] = []
        for group_name, ins_list in groups.items():
            sp = sum(i.spend for i in ins_list)
            if sp == 0:
                continue
            rev = sum(i.revenue for i in ins_list)
            imp = sum(i.impressions for i in ins_list)
            cl = sum(i.clicks for i in ins_list)
            cv = sum(i.conversions for i in ins_list)
            v3 = sum(i.video_views_3s for i in ins_list)
            v15 = sum(i.video_views_15s for i in ins_list)

            results.append({
                "name": group_name,
                "ad_count": len({i.ad_id for i in ins_list}),
                "spend": round(sp, 2),
                "revenue": round(rev, 2),
                "conversions": cv,
                "roas": round(_safe_div(rev, sp), 2),
                "cpa": round(_safe_div(sp, cv), 2),
                "ctr": round(_safe_div(cl, imp) * 100, 2),
                "hook_rate": round(_safe_div(v3, imp) * 100, 2),
                "hold_rate": round(_safe_div(v15, v3) * 100, 2),
            })

        results.sort(key=lambda x: x["roas"], reverse=True)
        return results

    # ------------------------------------------------------------------
    # Fatigue timeline
    # ------------------------------------------------------------------

    def _fatigue_timeline(
        self,
        insights: List[Any],
        tag_by_ad: Dict[str, Any],
        days: int,
    ) -> List[Dict[str, Any]]:
        """
        For each creative, identify when performance started declining.

        Uses a simple rolling-3-day hook rate comparison to find the
        inflection point.
        """
        by_ad: Dict[str, List[Any]] = defaultdict(list)
        for ins in insights:
            by_ad[ins.ad_id].append(ins)

        timeline: List[Dict[str, Any]] = []
        for ad_id, ins_list in by_ad.items():
            if len(ins_list) < 5:
                continue

            # Sort by date ascending
            sorted_ins = sorted(ins_list, key=lambda x: x.date)
            hook_rates = [
                _safe_div(i.video_views_3s, i.impressions) * 100
                if i.impressions > 0 else 0.0
                for i in sorted_ins
            ]

            # Find first point where 3-day avg starts declining consistently
            fatigue_date: Optional[str] = None
            peak_rate = 0.0
            for idx in range(2, len(hook_rates)):
                window = hook_rates[idx - 2 : idx + 1]
                avg = sum(window) / len(window)
                if avg > peak_rate:
                    peak_rate = avg
                elif peak_rate > 0 and avg < peak_rate * 0.8:
                    fatigue_date = sorted_ins[idx].date
                    break

            if fatigue_date:
                ad_obj = self._db.get_ad(ad_id)
                tag = tag_by_ad.get(ad_id)
                timeline.append({
                    "ad_id": ad_id,
                    "ad_name": ad_obj.name if ad_obj else ad_id,
                    "format": tag.format if tag else "",
                    "fatigue_date": fatigue_date,
                    "peak_hook_rate": round(peak_rate, 2),
                    "days_before_fatigue": len([
                        i for i in sorted_ins if i.date < fatigue_date
                    ]),
                })

        timeline.sort(key=lambda x: x["fatigue_date"], reverse=True)
        return timeline

    # ------------------------------------------------------------------
    # Lifecycle analysis
    # ------------------------------------------------------------------

    def _lifecycle_analysis(
        self,
        insights: List[Any],
        tag_by_ad: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Calculate average creative lifespan before fatigue by format."""
        by_ad: Dict[str, List[Any]] = defaultdict(list)
        for ins in insights:
            by_ad[ins.ad_id].append(ins)

        lifespans_by_format: Dict[str, List[int]] = defaultdict(list)
        all_lifespans: List[int] = []

        for ad_id, ins_list in by_ad.items():
            if len(ins_list) < 3:
                continue
            sorted_ins = sorted(ins_list, key=lambda x: x.date)
            first = datetime.strptime(sorted_ins[0].date, "%Y-%m-%d")
            last = datetime.strptime(sorted_ins[-1].date, "%Y-%m-%d")
            lifespan = (last - first).days + 1

            tag = tag_by_ad.get(ad_id)
            fmt = tag.format if tag else "(unknown)"
            lifespans_by_format[fmt].append(lifespan)
            all_lifespans.append(lifespan)

        result: Dict[str, Any] = {
            "overall_avg_days": (
                round(statistics.mean(all_lifespans), 1)
                if all_lifespans else 0
            ),
            "overall_median_days": (
                round(statistics.median(all_lifespans), 1)
                if all_lifespans else 0
            ),
            "by_format": {},
        }

        for fmt, spans in lifespans_by_format.items():
            result["by_format"][fmt] = {
                "avg_days": round(statistics.mean(spans), 1) if spans else 0,
                "median_days": round(statistics.median(spans), 1) if spans else 0,
                "count": len(spans),
            }

        return result

    # ------------------------------------------------------------------
    # Production recommendations
    # ------------------------------------------------------------------

    @staticmethod
    def _production_recommendations(
        format_cmp: List[Dict],
        hook_cmp: List[Dict],
        angle_cmp: List[Dict],
        scoreboard: List[Dict],
    ) -> List[Dict[str, str]]:
        recs: List[Dict[str, str]] = []

        # Best format
        if format_cmp:
            best = format_cmp[0]
            worst = format_cmp[-1] if len(format_cmp) > 1 else None
            recs.append({
                "action": "produce_more",
                "detail": (
                    f"Produce more {best['name'].upper()} content "
                    f"(best ROAS at {best['roas']}x)"
                ),
            })
            if worst and worst["roas"] < 1.0:
                recs.append({
                    "action": "stop_producing",
                    "detail": (
                        f"Reduce {worst['name'].upper()} production "
                        f"(ROAS only {worst['roas']}x)"
                    ),
                })

        # Best hook type
        if hook_cmp:
            best_hook = hook_cmp[0]
            recs.append({
                "action": "hook_strategy",
                "detail": (
                    f"Prioritise '{best_hook['name']}' hooks "
                    f"({best_hook['hook_rate']:.0f}% hook rate, "
                    f"{best_hook['roas']}x ROAS)"
                ),
            })

        # Best angle
        if angle_cmp:
            top_angles = [a for a in angle_cmp if a["roas"] >= TARGET_ROAS][:3]
            if top_angles:
                names = ", ".join(a["name"][:25] for a in top_angles)
                recs.append({
                    "action": "angle_strategy",
                    "detail": f"Winning angles to iterate on: {names}",
                })

        # Top scoreboard entries -- create variations
        top_3 = scoreboard[:3] if scoreboard else []
        if top_3:
            names = ", ".join(e["ad_name"][:20] for e in top_3)
            recs.append({
                "action": "iterate",
                "detail": (
                    f"Create variations of top performers: {names}"
                ),
            })

        return recs

    # ------------------------------------------------------------------
    # Top hooks
    # ------------------------------------------------------------------

    def _top_hooks(
        self,
        insights: List[Any],
        tag_by_ad: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Return the best-performing individual hook lines by hook rate."""
        by_ad: Dict[str, List[Any]] = defaultdict(list)
        for ins in insights:
            by_ad[ins.ad_id].append(ins)

        entries: List[Dict[str, Any]] = []
        for ad_id, ins_list in by_ad.items():
            tag = tag_by_ad.get(ad_id)
            if not tag or not tag.headline:
                continue
            total_imp = sum(i.impressions for i in ins_list)
            total_3s = sum(i.video_views_3s for i in ins_list)
            if total_imp < 1000:
                continue  # too little data
            hook_rate = round(_safe_div(total_3s, total_imp) * 100, 2)
            entries.append({
                "hook_text": tag.headline[:80],
                "hook_type": tag.hook_type,
                "format": tag.format,
                "hook_rate": hook_rate,
                "impressions": total_imp,
                "ad_id": ad_id,
            })

        entries.sort(key=lambda x: x["hook_rate"], reverse=True)
        return entries[:15]

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
        """Render the creative report as plain text."""
        if not self._generated:
            raise RuntimeError("Call generate() before format_text().")

        d = self._data
        lines: List[str] = []

        lines.append("=" * 66)
        lines.append("  CREATIVE PERFORMANCE REPORT")
        lines.append(
            f"  Period: {d['start_date']} to {d['end_date']} "
            f"({d['period_days']} days)"
        )
        lines.append("=" * 66)
        lines.append("")

        # Scoreboard
        lines.append("--- CREATIVE SCOREBOARD ---")
        lines.append(
            f"  {'#':>3} {'Name':30s} {'Score':>6} {'ROAS':>6} "
            f"{'CPA':>10} {'Hook':>6} {'Hold':>6} {'Grade':>5}"
        )
        lines.append("  " + "-" * 75)
        for i, e in enumerate(d["scoreboard"][:15], 1):
            grade_str = (
                f"{e['grade_hook']}{e['grade_hold']}{e['grade_ctr']}{e['grade_cpa']}"
            )
            lines.append(
                f"  {i:3d} {e['ad_name'][:30]:30s} {e['composite_score']:6.1f} "
                f"{e['roas']:5.1f}x "
                f"{_fc(e['cpa']):>10s} "
                f"{e['hook_rate']:5.1f}% "
                f"{e['hold_rate']:5.1f}% "
                f"{grade_str:>5s}"
            )
        if not d["scoreboard"]:
            lines.append("  (no creative data)")
        lines.append("")

        # Format comparison
        lines.append("--- FORMAT COMPARISON ---")
        for f in d["format_comparison"]:
            lines.append(
                f"  {f['name'].upper():12s} | "
                f"{f['ad_count']:2d} ads | "
                f"ROAS {f['roas']}x | CPA {_fc(f['cpa'])} | "
                f"Hook {f['hook_rate']:.1f}% | "
                f"Spend {_fc(f['spend'])}"
            )
        if not d["format_comparison"]:
            lines.append("  (no data)")
        lines.append("")

        # Hook type comparison
        lines.append("--- HOOK TYPE COMPARISON ---")
        for h in d["hook_type_comparison"]:
            lines.append(
                f"  {h['name']:15s} | "
                f"Hook {h['hook_rate']:.1f}% | "
                f"ROAS {h['roas']}x | "
                f"CPA {_fc(h['cpa'])} | "
                f"{h['ad_count']} ads"
            )
        if not d["hook_type_comparison"]:
            lines.append("  (no data)")
        lines.append("")

        # Angle comparison
        lines.append("--- ANGLE COMPARISON ---")
        for a in d["angle_comparison"][:10]:
            lines.append(
                f"  {a['name'][:25]:25s} | "
                f"ROAS {a['roas']}x | CPA {_fc(a['cpa'])} | "
                f"{a['conversions']} conv"
            )
        if not d["angle_comparison"]:
            lines.append("  (no data)")
        lines.append("")

        # Fatigue timeline
        lines.append("--- FATIGUE TIMELINE ---")
        if not d["fatigue_timeline"]:
            lines.append("  (no fatigue detected)")
        for ft in d["fatigue_timeline"][:10]:
            lines.append(
                f"  {ft['ad_name'][:30]:30s} | "
                f"Fatigued: {ft['fatigue_date']} | "
                f"After {ft['days_before_fatigue']}d | "
                f"Peak hook: {ft['peak_hook_rate']:.1f}%"
            )
        lines.append("")

        # Lifecycle analysis
        lc = d["lifecycle_analysis"]
        lines.append("--- LIFECYCLE ANALYSIS ---")
        lines.append(
            f"  Overall avg lifespan: {lc['overall_avg_days']} days "
            f"(median: {lc['overall_median_days']})"
        )
        for fmt, stats in lc.get("by_format", {}).items():
            lines.append(
                f"  {fmt.upper():12s}: avg {stats['avg_days']}d "
                f"(median {stats['median_days']}d, n={stats['count']})"
            )
        lines.append("")

        # Production recommendations
        lines.append("--- PRODUCTION RECOMMENDATIONS ---")
        for r in d["production_recommendations"]:
            icon = {
                "produce_more": "+",
                "stop_producing": "-",
                "hook_strategy": "*",
                "angle_strategy": "*",
                "iterate": ">>",
            }.get(r["action"], "-")
            lines.append(f"  {icon} {r['detail']}")
        if not d["production_recommendations"]:
            lines.append("  (insufficient data)")
        lines.append("")

        # Community vs non-community
        lines.append("--- COMMUNITY vs NON-COMMUNITY ---")
        for s in d["source_comparison"]:
            lines.append(
                f"  {s['name']:15s} | "
                f"ROAS {s['roas']}x | CPA {_fc(s['cpa'])} | "
                f"{s['ad_count']} ads | Spend {_fc(s['spend'])}"
            )
        if not d["source_comparison"]:
            lines.append("  (no data)")
        lines.append("")

        # Top hooks
        lines.append("--- TOP HOOKS (by hook rate) ---")
        for i, h in enumerate(d["top_hooks"][:10], 1):
            lines.append(
                f"  {i:2d}. [{h['hook_type']:10s}] "
                f"{h['hook_rate']:5.1f}% -- \"{h['hook_text']}\""
            )
        if not d["top_hooks"]:
            lines.append("  (no hook data)")
        lines.append("")

        lines.append("=" * 66)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Output: Slack
    # ------------------------------------------------------------------

    def format_slack(self) -> Dict[str, Any]:
        """Render the creative report as Slack Block Kit payload."""
        if not self._generated:
            raise RuntimeError("Call generate() before format_slack().")

        d = self._data
        blocks: List[Dict[str, Any]] = []

        # Header
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": (
                    f":art: Creative Report  --  "
                    f"{d['start_date']} to {d['end_date']}"
                ),
                "emoji": True,
            },
        })

        # Scoreboard top 5
        if d["scoreboard"]:
            sb_lines = [":trophy: *Creative Scoreboard (Top 5)*"]
            for i, e in enumerate(d["scoreboard"][:5], 1):
                sb_lines.append(
                    f"{i}. `{e['ad_name'][:25]}` -- "
                    f"Score {e['composite_score']} | "
                    f"ROAS {e['roas']}x | "
                    f"Hook {e['hook_rate']:.0f}%"
                )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(sb_lines)},
            })

        blocks.append({"type": "divider"})

        # Format comparison
        if d["format_comparison"]:
            fmt_lines = [":film_frames: *Format Comparison*"]
            for f in d["format_comparison"]:
                fmt_lines.append(
                    f"  {f['name'].upper()}: ROAS {f['roas']}x | "
                    f"Hook {f['hook_rate']:.0f}% | {f['ad_count']} ads"
                )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(fmt_lines)},
            })

        # Hook comparison
        if d["hook_type_comparison"]:
            hook_lines = [":hook: *Hook Type Comparison*"]
            for h in d["hook_type_comparison"]:
                hook_lines.append(
                    f"  {h['name'].title()}: "
                    f"Hook {h['hook_rate']:.0f}% | ROAS {h['roas']}x"
                )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(hook_lines)},
            })

        blocks.append({"type": "divider"})

        # Lifecycle
        lc = d["lifecycle_analysis"]
        lc_text = (
            f":timer_clock: *Lifecycle*\n"
            f"  Avg lifespan: {lc['overall_avg_days']} days "
            f"(median: {lc['overall_median_days']})"
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": lc_text},
        })

        # Production recs
        if d["production_recommendations"]:
            rec_lines = [":factory: *Production Recommendations*"]
            for r in d["production_recommendations"]:
                rec_lines.append(f"  - {r['detail']}")
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(rec_lines)},
            })

        blocks.append({"type": "divider"})

        # Top hooks
        if d["top_hooks"]:
            top_lines = [":mega: *Top Hooks*"]
            for i, h in enumerate(d["top_hooks"][:5], 1):
                top_lines.append(
                    f"{i}. `{h['hook_text'][:50]}` -- "
                    f"{h['hook_rate']:.0f}% hook rate"
                )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(top_lines)},
            })

        return {"blocks": blocks}
