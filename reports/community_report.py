"""
Community Intelligence Report — weekly community-sourced ad insights.

Combines community pulse data with ad performance data to surface
trending topics, language patterns, new ad angle suggestions, and
the track record of community-sourced creatives.

Usage::

    from reports.community_report import CommunityReport
    from data import db

    report = CommunityReport(db)
    data = report.generate(days=7)
    print(report.format_text())
    slack_payload = report.format_slack()
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config.settings import CURRENCY, TARGET_CPA, TARGET_ROAS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_CURRENCY_SYMBOLS = {"EUR": "\u20ac", "USD": "$", "GBP": "\u00a3"}
_SYM = _CURRENCY_SYMBOLS.get(CURRENCY, CURRENCY + " ")


def _fc(v: float) -> str:
    return f"{_SYM}{v:,.2f}"


def _safe_div(n: float, d: float) -> float:
    return n / d if d else 0.0


# ---------------------------------------------------------------------------
# CommunityReport
# ---------------------------------------------------------------------------


class CommunityReport:
    """
    Weekly community intelligence report combining community pulse
    data with ad performance metrics.

    Parameters
    ----------
    db : module
        The ``data.db`` module (or compatible query API).
    pulse : CommunityPulse, optional
        A pre-initialised ``CommunityPulse`` instance.  If *None*, the
        report will work with whatever community angle data is already
        stored in the database (via ``community_angles`` table).
    """

    def __init__(self, db: Any, pulse: Any = None) -> None:
        self._db = db
        self._pulse = pulse
        self._data: Dict[str, Any] = {}
        self._generated = False

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate(self, days: int = 7) -> Dict[str, Any]:
        """
        Build the community intelligence report for the last *days*.

        If a ``CommunityPulse`` instance was provided, it is used to
        generate a fresh pulse report.  Otherwise the report relies on
        previously-stored community angles in the database.

        Returns
        -------
        dict
            The raw report data.
        """
        logger.info("Generating community report for the last %d days", days)

        end_date = (
            datetime.now(tz=timezone.utc) - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        start_date = (
            datetime.now(tz=timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%d")

        # -- Pulse data (if available) --
        pulse_data: Optional[Dict[str, Any]] = None
        if self._pulse is not None:
            try:
                pulse_data = self._pulse.generate_pulse(days=days)
            except Exception:
                logger.warning(
                    "CommunityPulse.generate_pulse() failed; "
                    "falling back to DB data only.",
                    exc_info=True,
                )

        # -- Community angles from DB --
        all_angles = self._db.get_community_angles(limit=500)

        # Partition by recency
        recent_angles = [
            a for a in all_angles
            if a.created_at >= start_date
        ]
        older_angles = [
            a for a in all_angles
            if a.created_at < start_date
        ]

        # -- This week's pulse --
        community_pulse = self._build_pulse_summary(
            pulse_data, recent_angles
        )

        # -- Trending topics --
        trending = self._trending_topics(recent_angles, older_angles)

        # -- Language of the week --
        language = self._language_of_week(pulse_data)

        # -- Ad angle suggestions (new) --
        new_angles = self._new_angle_suggestions(pulse_data, recent_angles)

        # -- Angles used this week --
        used_this_week = [
            a for a in recent_angles if a.status == "used"
        ]
        angles_used = self._format_used_angles(used_this_week)

        # -- Angle performance --
        angle_performance = self._angle_performance(all_angles)

        # -- vs Last week --
        prev_start = (
            datetime.now(tz=timezone.utc) - timedelta(days=days * 2)
        ).strftime("%Y-%m-%d")
        prev_angles = [
            a for a in all_angles
            if prev_start <= a.created_at < start_date
        ]
        vs_last_week = self._compare_weeks(recent_angles, prev_angles)

        # -- Action items --
        action_items = self._build_action_items(
            community_pulse, new_angles, angle_performance, trending
        )

        self._data = {
            "period_days": days,
            "start_date": start_date,
            "end_date": end_date,
            "community_pulse": community_pulse,
            "trending_topics": trending,
            "language_of_week": language,
            "new_angle_suggestions": new_angles,
            "angles_used_this_week": angles_used,
            "angle_performance": angle_performance,
            "vs_last_week": vs_last_week,
            "action_items": action_items,
        }
        self._generated = True
        logger.info(
            "Community report generated: %d new angles, %d used",
            len(new_angles), len(angles_used),
        )
        return self._data

    # ------------------------------------------------------------------
    # Pulse summary
    # ------------------------------------------------------------------

    @staticmethod
    def _build_pulse_summary(
        pulse_data: Optional[Dict[str, Any]],
        recent_angles: List[Any],
    ) -> Dict[str, Any]:
        """Summarise this week's community pulse."""
        summary: Dict[str, Any] = {
            "top_questions": [],
            "top_objections": [],
            "success_stories": [],
            "total_new_angles": len(
                [a for a in recent_angles if a.status == "new"]
            ),
            "total_used_angles": len(
                [a for a in recent_angles if a.status == "used"]
            ),
        }

        if pulse_data:
            # Extract from pulse report
            questions = pulse_data.get("questions", {}).get("top", [])
            summary["top_questions"] = [
                {
                    "text": q.get("question", ""),
                    "upvotes": q.get("upvotes", 0),
                }
                for q in questions[:5]
            ]

            objections = pulse_data.get("objections", {}).get("top", [])
            summary["top_objections"] = [
                {
                    "text": o.get("text", o.get("complaint", "")),
                }
                for o in objections[:5]
            ]

            stories = pulse_data.get("proof", {}).get("stories", [])
            summary["success_stories"] = [
                {
                    "user": s.get("user", "anonymous"),
                    "result": s.get("result", ""),
                    "quote": s.get("quotable_line", ""),
                }
                for s in stories[:5]
            ]
        else:
            # Build from DB angles by source_type
            for a in recent_angles:
                if a.source_type == "question" and len(summary["top_questions"]) < 5:
                    summary["top_questions"].append({
                        "text": a.source_text[:200],
                        "upvotes": 0,
                    })
                elif a.source_type == "objection" and len(summary["top_objections"]) < 5:
                    summary["top_objections"].append({
                        "text": a.source_text[:200],
                    })
                elif a.source_type == "success_story" and len(summary["success_stories"]) < 5:
                    summary["success_stories"].append({
                        "user": "community",
                        "result": a.source_text[:200],
                        "quote": "",
                    })

        return summary

    # ------------------------------------------------------------------
    # Trending topics
    # ------------------------------------------------------------------

    @staticmethod
    def _trending_topics(
        recent: List[Any], older: List[Any]
    ) -> List[Dict[str, Any]]:
        """Identify topics gaining traction compared to the prior period."""
        def _count_categories(angles: List[Any]) -> Dict[str, int]:
            counts: Dict[str, int] = defaultdict(int)
            for a in angles:
                if a.hook_category:
                    counts[a.hook_category] += 1
                if a.source_type:
                    counts[a.source_type] += 1
            return counts

        recent_counts = _count_categories(recent)
        older_counts = _count_categories(older)

        trending: List[Dict[str, Any]] = []
        all_topics = set(recent_counts.keys()) | set(older_counts.keys())

        for topic in all_topics:
            curr = recent_counts.get(topic, 0)
            prev = older_counts.get(topic, 0)
            if curr > prev:
                change = curr - prev
                trending.append({
                    "topic": topic,
                    "this_week": curr,
                    "last_week": prev,
                    "change": change,
                    "direction": "up",
                })
            elif curr < prev:
                change = prev - curr
                trending.append({
                    "topic": topic,
                    "this_week": curr,
                    "last_week": prev,
                    "change": -change,
                    "direction": "down",
                })

        trending.sort(key=lambda x: abs(x["change"]), reverse=True)
        return trending[:10]

    # ------------------------------------------------------------------
    # Language of the week
    # ------------------------------------------------------------------

    @staticmethod
    def _language_of_week(
        pulse_data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Extract the top community phrases for ad copy."""
        if not pulse_data:
            return {
                "frequent_phrases": [],
                "pain_language": [],
                "aspiration_language": [],
            }

        lang = pulse_data.get("language", {})
        return {
            "frequent_phrases": [
                {"phrase": p["phrase"], "count": p["count"]}
                for p in lang.get("frequent_phrases", [])[:10]
            ],
            "pain_language": [
                p.get("phrase", "") for p in lang.get("pain_language", [])[:5]
            ],
            "aspiration_language": [
                p.get("phrase", "")
                for p in lang.get("aspiration_language", [])[:5]
            ],
        }

    # ------------------------------------------------------------------
    # New angle suggestions
    # ------------------------------------------------------------------

    @staticmethod
    def _new_angle_suggestions(
        pulse_data: Optional[Dict[str, Any]],
        recent_angles: List[Any],
    ) -> List[Dict[str, Any]]:
        """Return up to 10 new ad angle suggestions."""
        suggestions: List[Dict[str, Any]] = []

        # From pulse
        if pulse_data:
            for angle in pulse_data.get("angles", [])[:10]:
                suggestions.append({
                    "hook_category": angle.get("hook_category", ""),
                    "source": angle.get("source", "community"),
                    "draft_hook": angle.get("draft_hook", ""),
                    "value_target": angle.get("value_equation_target", ""),
                    "impact": angle.get("estimated_impact", "medium"),
                    "reasoning": angle.get("reasoning", ""),
                })

        # Supplement from DB if needed
        if len(suggestions) < 10:
            new_db_angles = [
                a for a in recent_angles if a.status == "new"
            ]
            for a in new_db_angles[: 10 - len(suggestions)]:
                suggestions.append({
                    "hook_category": a.hook_category,
                    "source": a.source_type,
                    "draft_hook": a.suggested_hook or a.source_text[:100],
                    "value_target": "",
                    "impact": "medium",
                    "reasoning": f"Sourced from community {a.source_type}",
                })

        return suggestions[:10]

    # ------------------------------------------------------------------
    # Used angles
    # ------------------------------------------------------------------

    @staticmethod
    def _format_used_angles(
        used: List[Any],
    ) -> List[Dict[str, Any]]:
        return [
            {
                "angle_id": a.id,
                "source_type": a.source_type,
                "hook": a.suggested_hook or a.source_text[:80],
                "ad_id": a.used_in_ad_id,
                "performance_score": a.performance_score,
            }
            for a in used
        ]

    # ------------------------------------------------------------------
    # Angle performance
    # ------------------------------------------------------------------

    def _angle_performance(
        self, all_angles: List[Any]
    ) -> Dict[str, Any]:
        """Measure how community-sourced ads perform vs others."""
        used = [a for a in all_angles if a.status == "used" and a.used_in_ad_id]

        if not used:
            return {
                "total_community_ads": 0,
                "avg_roas": 0.0,
                "avg_cpa": 0.0,
                "top_performers": [],
                "comparison_to_manual": None,
            }

        # Get performance for community-sourced ads
        community_metrics: List[Dict[str, Any]] = []
        for a in used:
            summary = self._db.get_insights_summary(a.used_in_ad_id, days=30)
            if summary and summary["spend"] > 0:
                community_metrics.append({
                    "angle_id": a.id,
                    "ad_id": a.used_in_ad_id,
                    "hook": a.suggested_hook[:60] if a.suggested_hook else "",
                    "source_type": a.source_type,
                    "spend": summary["spend"],
                    "conversions": summary["conversions"],
                    "roas": summary["roas"],
                    "cpa": summary["avg_cpa"],
                })

        if not community_metrics:
            return {
                "total_community_ads": len(used),
                "avg_roas": 0.0,
                "avg_cpa": 0.0,
                "top_performers": [],
                "comparison_to_manual": None,
            }

        total_spend = sum(m["spend"] for m in community_metrics)
        total_rev = sum(
            m["spend"] * m["roas"] for m in community_metrics
        )
        total_conv = sum(m["conversions"] for m in community_metrics)

        avg_roas = round(_safe_div(total_rev, total_spend), 2)
        avg_cpa = round(_safe_div(total_spend, total_conv), 2)

        # Sort by ROAS for top performers
        community_metrics.sort(key=lambda x: x["roas"], reverse=True)

        # Compare to non-community ads
        all_tags = self._db.get_creative_tags()
        manual_ad_ids = {
            t.ad_id for t in all_tags if t.source != "community"
        }
        community_ad_ids = {m["ad_id"] for m in community_metrics}

        manual_spend = 0.0
        manual_rev = 0.0
        manual_conv = 0
        for ad_id in manual_ad_ids:
            if ad_id in community_ad_ids:
                continue
            s = self._db.get_insights_summary(ad_id, days=30)
            if s and s["spend"] > 0:
                manual_spend += s["spend"]
                manual_rev += s["revenue"]
                manual_conv += s["conversions"]

        comparison: Optional[Dict[str, Any]] = None
        if manual_spend > 0:
            manual_roas = round(_safe_div(manual_rev, manual_spend), 2)
            manual_cpa = round(_safe_div(manual_spend, manual_conv), 2)
            comparison = {
                "community_roas": avg_roas,
                "manual_roas": manual_roas,
                "community_cpa": avg_cpa,
                "manual_cpa": manual_cpa,
                "roas_delta_pct": round(
                    _safe_div(avg_roas - manual_roas, manual_roas) * 100, 1
                ),
            }

        return {
            "total_community_ads": len(community_metrics),
            "avg_roas": avg_roas,
            "avg_cpa": avg_cpa,
            "top_performers": community_metrics[:5],
            "comparison_to_manual": comparison,
        }

    # ------------------------------------------------------------------
    # Week comparison
    # ------------------------------------------------------------------

    @staticmethod
    def _compare_weeks(
        recent: List[Any], previous: List[Any]
    ) -> Dict[str, Any]:
        def _source_counts(angles: List[Any]) -> Dict[str, int]:
            c: Dict[str, int] = defaultdict(int)
            for a in angles:
                c[a.source_type] += 1
            return c

        rc = _source_counts(recent)
        pc = _source_counts(previous)

        new_types = set(rc.keys()) - set(pc.keys())
        gone_types = set(pc.keys()) - set(rc.keys())

        return {
            "this_week_total": len(recent),
            "last_week_total": len(previous),
            "change": len(recent) - len(previous),
            "new_source_types": list(new_types),
            "gone_source_types": list(gone_types),
            "this_week_by_type": dict(rc),
            "last_week_by_type": dict(pc),
        }

    # ------------------------------------------------------------------
    # Action items
    # ------------------------------------------------------------------

    @staticmethod
    def _build_action_items(
        pulse: Dict[str, Any],
        new_angles: List[Dict[str, Any]],
        performance: Dict[str, Any],
        trending: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        """Generate specific action briefs from community intelligence."""
        items: List[Dict[str, str]] = []

        # High-impact angles to brief
        high_impact = [a for a in new_angles if a.get("impact") == "high"]
        if high_impact:
            for a in high_impact[:3]:
                items.append({
                    "priority": "high",
                    "action": (
                        f"Brief a {a['hook_category']} ad: "
                        f"\"{a['draft_hook'][:80]}\""
                    ),
                    "source": a.get("source", "community"),
                })

        # Objections to address
        objections = pulse.get("top_objections", [])
        if objections:
            obj_text = objections[0].get("text", "")[:60]
            items.append({
                "priority": "high",
                "action": (
                    f"Create objection-handling ad for: \"{obj_text}\""
                ),
                "source": "community_objection",
            })

        # Success stories to feature
        stories = pulse.get("success_stories", [])
        if stories:
            s = stories[0]
            items.append({
                "priority": "medium",
                "action": (
                    f"Feature success story from {s.get('user', 'member')}: "
                    f"\"{s.get('result', '')[:60]}\""
                ),
                "source": "community_proof",
            })

        # Trending topic to capitalise on
        up_trends = [t for t in trending if t.get("direction") == "up"]
        if up_trends:
            items.append({
                "priority": "medium",
                "action": (
                    f"Trending topic '{up_trends[0]['topic']}' "
                    f"({up_trends[0]['change']:+d} this week) -- "
                    "create content around it"
                ),
                "source": "trending",
            })

        # Iterate on best community performer
        top = performance.get("top_performers", [])
        if top:
            items.append({
                "priority": "medium",
                "action": (
                    f"Iterate on best community ad "
                    f"(ROAS {top[0]['roas']}x): create 3 variations"
                ),
                "source": "performance_data",
            })

        if not items:
            items.append({
                "priority": "low",
                "action": (
                    "No strong signals this week. "
                    "Continue monitoring community and testing."
                ),
                "source": "default",
            })

        return items

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
        """Render the community report as plain text."""
        if not self._generated:
            raise RuntimeError("Call generate() before format_text().")

        d = self._data
        pulse = d["community_pulse"]
        lines: List[str] = []

        lines.append("=" * 64)
        lines.append("  COMMUNITY INTELLIGENCE REPORT")
        lines.append(
            f"  Period: {d['start_date']} to {d['end_date']} "
            f"({d['period_days']} days)"
        )
        lines.append("=" * 64)
        lines.append("")

        # Community pulse
        lines.append("--- THIS WEEK'S COMMUNITY PULSE ---")
        lines.append(
            f"  New angles: {pulse['total_new_angles']} | "
            f"Used in ads: {pulse['total_used_angles']}"
        )
        lines.append("")

        if pulse["top_questions"]:
            lines.append("  Top Questions:")
            for i, q in enumerate(pulse["top_questions"], 1):
                upvotes = q.get("upvotes", 0)
                prefix = f"[{upvotes} votes] " if upvotes else ""
                lines.append(f"    {i}. {prefix}{q['text'][:80]}")
            lines.append("")

        if pulse["top_objections"]:
            lines.append("  Top Objections:")
            for i, o in enumerate(pulse["top_objections"], 1):
                lines.append(f"    {i}. \"{o['text'][:80]}\"")
            lines.append("")

        if pulse["success_stories"]:
            lines.append("  Success Stories:")
            for i, s in enumerate(pulse["success_stories"], 1):
                lines.append(
                    f"    {i}. @{s['user']}: {s['result'][:60]}"
                )
                if s.get("quote"):
                    lines.append(f"       \"{s['quote'][:60]}\"")
            lines.append("")

        # Trending topics
        lines.append("--- TRENDING TOPICS ---")
        if not d["trending_topics"]:
            lines.append("  (no significant trends)")
        for t in d["trending_topics"]:
            arrow = "\u2191" if t["direction"] == "up" else "\u2193"
            lines.append(
                f"  {arrow} {t['topic']:20s} | "
                f"This week: {t['this_week']} | "
                f"Last week: {t['last_week']} ({t['change']:+d})"
            )
        lines.append("")

        # Language of the week
        lang = d["language_of_week"]
        lines.append("--- LANGUAGE OF THE WEEK ---")
        if lang["frequent_phrases"]:
            lines.append("  Top phrases to use in copy:")
            for p in lang["frequent_phrases"][:5]:
                lines.append(f"    - \"{p['phrase']}\" ({p['count']}x)")
        if lang["pain_language"]:
            lines.append("  Pain language:")
            for p in lang["pain_language"][:3]:
                lines.append(f"    - \"{p}\"")
        if lang["aspiration_language"]:
            lines.append("  Aspiration language:")
            for p in lang["aspiration_language"][:3]:
                lines.append(f"    - \"{p}\"")
        if not any([
            lang["frequent_phrases"],
            lang["pain_language"],
            lang["aspiration_language"],
        ]):
            lines.append("  (no language data available)")
        lines.append("")

        # New angle suggestions
        lines.append("--- AD ANGLE SUGGESTIONS (NEW) ---")
        if not d["new_angle_suggestions"]:
            lines.append("  (no new suggestions)")
        for i, a in enumerate(d["new_angle_suggestions"], 1):
            impact_tag = a.get("impact", "?").upper()
            lines.append(
                f"  {i:2d}. [{a['hook_category'].upper():10s}] "
                f"[{impact_tag}] {a['draft_hook'][:60]}"
            )
            if a.get("reasoning"):
                lines.append(f"      Reason: {a['reasoning'][:70]}")
        lines.append("")

        # Angles used this week
        lines.append("--- ANGLES USED THIS WEEK ---")
        if not d["angles_used_this_week"]:
            lines.append("  (no community angles went live)")
        for a in d["angles_used_this_week"]:
            score_str = (
                f" (score: {a['performance_score']:.1f})"
                if a["performance_score"] > 0 else ""
            )
            lines.append(
                f"  - [{a['source_type']}] \"{a['hook'][:50]}\" "
                f"-> ad {a['ad_id'][:15]}{score_str}"
            )
        lines.append("")

        # Angle performance
        perf = d["angle_performance"]
        lines.append("--- ANGLE PERFORMANCE ---")
        lines.append(
            f"  Community ads tracked: {perf['total_community_ads']}"
        )
        if perf["total_community_ads"] > 0:
            lines.append(
                f"  Avg ROAS: {perf['avg_roas']}x | "
                f"Avg CPA: {_fc(perf['avg_cpa'])}"
            )

        cmp = perf.get("comparison_to_manual")
        if cmp:
            delta = cmp["roas_delta_pct"]
            verb = "outperforming" if delta > 0 else "underperforming"
            lines.append(
                f"  Community vs Manual: {verb} by "
                f"{abs(delta):.1f}% on ROAS "
                f"({cmp['community_roas']}x vs {cmp['manual_roas']}x)"
            )

        if perf["top_performers"]:
            lines.append("  Top community-sourced ads:")
            for i, tp in enumerate(perf["top_performers"][:3], 1):
                lines.append(
                    f"    {i}. ROAS {tp['roas']}x | "
                    f"CPA {_fc(tp['cpa'])} | "
                    f"\"{tp['hook'][:40]}\""
                )
        lines.append("")

        # vs Last week
        vs = d["vs_last_week"]
        lines.append("--- VS LAST WEEK ---")
        lines.append(
            f"  This week: {vs['this_week_total']} angles | "
            f"Last week: {vs['last_week_total']} angles | "
            f"Change: {vs['change']:+d}"
        )
        if vs["new_source_types"]:
            lines.append(
                f"  New source types: {', '.join(vs['new_source_types'])}"
            )
        if vs["gone_source_types"]:
            lines.append(
                f"  Gone source types: {', '.join(vs['gone_source_types'])}"
            )
        lines.append("")

        # Action items
        lines.append("--- ACTION ITEMS ---")
        for i, item in enumerate(d["action_items"], 1):
            prio = item["priority"].upper()
            lines.append(f"  {i}. [{prio}] {item['action']}")
        lines.append("")

        lines.append("=" * 64)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Output: Slack
    # ------------------------------------------------------------------

    def format_slack(self) -> Dict[str, Any]:
        """Render the community report as Slack Block Kit payload."""
        if not self._generated:
            raise RuntimeError("Call generate() before format_slack().")

        d = self._data
        pulse = d["community_pulse"]
        blocks: List[Dict[str, Any]] = []

        # Header
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": (
                    f":speech_balloon: Community Intelligence  --  "
                    f"{d['start_date']} to {d['end_date']}"
                ),
                "emoji": True,
            },
        })

        # Pulse summary
        pulse_lines = [
            f":bar_chart: *Community Pulse*",
            f"  New angles: {pulse['total_new_angles']} | "
            f"Used: {pulse['total_used_angles']}",
        ]
        if pulse["top_questions"]:
            pulse_lines.append("\n*Top Questions:*")
            for i, q in enumerate(pulse["top_questions"][:3], 1):
                pulse_lines.append(f"  {i}. {q['text'][:60]}")
        if pulse["top_objections"]:
            pulse_lines.append("\n*Top Objections:*")
            for i, o in enumerate(pulse["top_objections"][:3], 1):
                pulse_lines.append(f"  {i}. \"{o['text'][:60]}\"")
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(pulse_lines)},
        })

        blocks.append({"type": "divider"})

        # Trending
        if d["trending_topics"]:
            trend_lines = [":fire: *Trending Topics*"]
            for t in d["trending_topics"][:5]:
                arrow = "\u2191" if t["direction"] == "up" else "\u2193"
                trend_lines.append(
                    f"  {arrow} {t['topic']} ({t['change']:+d})"
                )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(trend_lines)},
            })

        # New angles
        if d["new_angle_suggestions"]:
            angle_lines = [":bulb: *New Ad Angle Suggestions*"]
            for i, a in enumerate(d["new_angle_suggestions"][:5], 1):
                angle_lines.append(
                    f"{i}. `[{a['hook_category'].upper()}]` "
                    f"{a['draft_hook'][:55]}"
                )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(angle_lines)},
            })

        blocks.append({"type": "divider"})

        # Performance
        perf = d["angle_performance"]
        if perf["total_community_ads"] > 0:
            perf_lines = [
                f":chart_with_upwards_trend: *Community Angle Performance*",
                f"  Tracked: {perf['total_community_ads']} ads | "
                f"Avg ROAS: {perf['avg_roas']}x | "
                f"Avg CPA: {_fc(perf['avg_cpa'])}",
            ]
            cmp = perf.get("comparison_to_manual")
            if cmp:
                delta = cmp["roas_delta_pct"]
                emoji = ":white_check_mark:" if delta > 0 else ":red_circle:"
                perf_lines.append(
                    f"  {emoji} Community vs Manual: "
                    f"{delta:+.1f}% ROAS"
                )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(perf_lines)},
            })

        blocks.append({"type": "divider"})

        # Action items
        act_lines = [":dart: *Action Items*"]
        for i, item in enumerate(d["action_items"], 1):
            prio_emoji = {
                "high": ":red_circle:",
                "medium": ":large_orange_circle:",
                "low": ":white_circle:",
            }.get(item["priority"], ":white_circle:")
            act_lines.append(f"  {prio_emoji} {item['action'][:70]}")
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(act_lines)},
        })

        return {"blocks": blocks}
