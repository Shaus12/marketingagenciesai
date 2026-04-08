"""
Hormozi Value Equation scorer for Meta Ads Management System.

Scores ad copy and creatives against the four pillars of the
Value Equation:

  Value = (Dream Outcome x Perceived Likelihood) / (Time Delay x Effort)

Each pillar is scored 0-25, giving a total of 0-100.  Keyword/phrase
detection powers the scoring, and results are correlated against actual
ad performance to validate the framework over time.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from config.hormozi import VALUE_EQUATION
from config.settings import TARGET_CPA, TARGET_ROAS, CURRENCY
from data import db

logger = logging.getLogger(__name__)


# ======================================================================
# Keyword / phrase libraries for each pillar
# ======================================================================

_DREAM_OUTCOME_SIGNALS = {
    "specific_result_mentioned": [
        r"\d+[xX%]", r"\$\d+", r"\d+\s*(clients|customers|sales|leads|users)",
        r"(revenue|income|profit|sales)\s+(of|to|by|over)\s+\d+",
        r"(doubled|tripled|quadrupled|10x|100x)",
        r"(hit|reach|achieve|get|earn)\s+\d+",
    ],
    "emotional_outcome": [
        r"(freedom|free time|quit.*(job|9.to.5))",
        r"(confidence|confident|fearless|unstoppable)",
        r"(stress.free|worry.free|peace of mind|relief)",
        r"(dream|life.changing|transform|changed my life)",
        r"(escape|break free|finally|never again)",
    ],
    "measurable_goal": [
        r"\d+\s*(per|a|every)\s*(day|week|month|year)",
        r"(in just|within|under)\s+\d+\s*(days|weeks|months|hours|minutes)",
        r"\d+\s*(figure|digit)",
        r"(first|next)\s+\d+\s*(clients|customers|sales)",
    ],
}

_LIKELIHOOD_SIGNALS = {
    "has_testimonial": [
        r"(testimonial|review|said|told me|wrote)",
        r"(client|customer|student|member)\s+(said|shared|told)",
        r"(here'?s what|see what)\s+\w+\s+(said|thinks|achieved)",
    ],
    "has_specific_proof": [
        r"(proven|proof|evidence|data|study|research|results)",
        r"(case study|case.study|real results)",
        r"(screenshot|receipt|dashboard|analytics|stats)",
        r"(backed|supported|verified|documented)",
    ],
    "has_before_after": [
        r"(before|after|used to|now I|went from|transformation)",
        r"(from\s+\w+\s+to\s+\w+)",
        r"(was\s+\w+\s*,?\s*now\s+\w+)",
    ],
    "has_social_proof_count": [
        r"\d+\s*(clients|customers|students|users|members|people|businesses)",
        r"(thousands|hundreds|millions)\s+of\s+(people|clients|users)",
        r"(over|more than|helped)\s+\d+",
        r"(best.?selling|#1|number one|top.rated)",
    ],
}

_TIME_DELAY_SIGNALS = {
    "specific_timeframe": [
        r"(in\s+)?(just\s+)?\d+\s*(days|hours|minutes|weeks|months)",
        r"(by|within|under|in less than)\s+\d+",
        r"(overnight|today|tonight|this week|right now)",
    ],
    "fast_result_claim": [
        r"(fast|quick|rapid|instant|immediate|lightning)",
        r"(shortcut|hack|trick|cheat code|fast.?track)",
        r"(skip.*(line|queue|wait|years))",
        r"(accelerate|speed up|compress)",
    ],
    "immediate_value": [
        r"(right away|right now|immediately|instantly|today)",
        r"(get started|start seeing|begin|launch)\s*(today|now|immediately)",
        r"(no waiting|zero wait|skip the)",
    ],
}

_EFFORT_SIGNALS = {
    "easy_steps": [
        r"(easy|simple|straightforward|no.brainer|effortless)",
        r"(\d+\s*(simple|easy)?\s*(steps?|things?))",
        r"(just\s+(do|follow|click|watch|copy))",
        r"(step.by.step|plug.and.play|fill.in.the.blank|copy.paste|template)",
    ],
    "no_prior_knowledge": [
        r"(no experience|beginner|newbie|complete beginner|zero knowledge)",
        r"(even if you.*(never|don't|aren't))",
        r"(anyone can|works for everyone|no matter)",
    ],
    "done_for_you": [
        r"(done.for.you|DFY|we do it|we handle|we take care)",
        r"(hands.?off|set.?and.?forget|autopilot|automated)",
        r"(team|assistant|expert|specialist)\s+(does|handles|manages)",
    ],
    "minimal_time_commitment": [
        r"(\d+\s*min(utes)?|half.?hour|\d+\s*hours?\s*(per|a)\s*(day|week))",
        r"(spare time|part.?time|side hustle|without quitting)",
        r"(low.?commitment|minimal effort|little time)",
    ],
}


class ValueEquationScorer:
    """
    Score ads against Hormozi's Value Equation using keyword and phrase
    detection across the four pillars.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score_ad(self, ad_id: str) -> Dict[str, Any]:
        """
        Analyze an ad's copy and creative metadata against the four
        Value Equation pillars.

        Each pillar scores 0-25; total ranges 0-100.

        Args:
            ad_id: The ad to score.

        Returns:
            Dict with pillar scores, total, per-signal detail, and the
            underlying text that was analyzed.
        """
        ad = db.get_ad(ad_id)
        if ad is None:
            return {"error": f"Ad '{ad_id}' not found"}

        # Gather all text associated with this ad
        tags = db.get_creative_tags(ad_id=ad_id)
        text_parts: List[str] = [ad.name]
        for tag in tags:
            if tag.body_text:
                text_parts.append(tag.body_text)
            if tag.headline:
                text_parts.append(tag.headline)

        full_text = " ".join(text_parts)

        result = self.score_ad_copy(full_text)
        result["ad_id"] = ad_id
        result["ad_name"] = ad.name

        # Add creative metadata signals
        for tag in tags:
            if tag.has_testimonial:
                result["pillar_details"]["perceived_likelihood"]["bonus_signals"].append(
                    "Creative is tagged with testimonial"
                )
                result["pillars"]["perceived_likelihood"] = min(
                    25, result["pillars"]["perceived_likelihood"] + 3
                )
            if tag.has_text_overlay:
                result["pillar_details"]["dream_outcome"]["bonus_signals"].append(
                    "Creative has text overlay (reinforces message)"
                )
                result["pillars"]["dream_outcome"] = min(
                    25, result["pillars"]["dream_outcome"] + 1
                )

        # Recalculate total after bonuses
        result["total"] = sum(result["pillars"].values())
        result["rating"] = self._rating_label(result["total"])

        return result

    def score_ad_copy(self, text: str) -> Dict[str, Any]:
        """
        Score just the text content against the Value Equation.

        Args:
            text: The ad copy / headline / body text to evaluate.

        Returns:
            Dict with pillar scores, signal matches, and total.
        """
        if not text or not text.strip():
            return self._empty_score(text)

        text_lower = text.lower()

        # Score each pillar
        dream_score, dream_details = self._score_pillar(
            text_lower, _DREAM_OUTCOME_SIGNALS, "dream_outcome"
        )
        likelihood_score, likelihood_details = self._score_pillar(
            text_lower, _LIKELIHOOD_SIGNALS, "perceived_likelihood"
        )
        time_score, time_details = self._score_pillar(
            text_lower, _TIME_DELAY_SIGNALS, "time_delay"
        )
        effort_score, effort_details = self._score_pillar(
            text_lower, _EFFORT_SIGNALS, "effort_sacrifice"
        )

        total = dream_score + likelihood_score + time_score + effort_score

        return {
            "text_analyzed": text[:500],
            "pillars": {
                "dream_outcome": dream_score,
                "perceived_likelihood": likelihood_score,
                "time_delay": time_score,
                "effort": effort_score,
            },
            "total": total,
            "rating": self._rating_label(total),
            "pillar_details": {
                "dream_outcome": dream_details,
                "perceived_likelihood": likelihood_details,
                "time_delay": time_details,
                "effort": effort_details,
            },
        }

    def get_improvement_suggestions(self, ad_id: str) -> Dict[str, Any]:
        """
        Provide specific, actionable suggestions to improve the Value
        Equation score for an ad.

        Identifies the weakest pillar(s) and gives concrete recommendations.

        Args:
            ad_id: The ad to analyze.

        Returns:
            Dict with current score, weakest pillars, and specific
            suggestions for each weak area.
        """
        score = self.score_ad(ad_id)
        if "error" in score:
            return score

        pillars = score["pillars"]
        suggestions: List[Dict[str, Any]] = []

        # Analyze each pillar and suggest improvements for weak ones
        pillar_configs = {
            "dream_outcome": {
                "max": 25,
                "tips": [
                    "Add a specific, measurable result (e.g., '10 new clients in 30 days')",
                    "Include an emotional outcome (freedom, confidence, peace of mind)",
                    "Use concrete numbers rather than vague promises",
                    "Paint a picture of their life AFTER the transformation",
                ],
            },
            "perceived_likelihood": {
                "max": 25,
                "tips": [
                    "Add a testimonial or customer quote with specific results",
                    "Include social proof numbers (e.g., 'helped 500+ businesses')",
                    "Show a before/after comparison or case study reference",
                    "Add proof elements: screenshots, data, real results",
                ],
            },
            "time_delay": {
                "max": 25,
                "tips": [
                    "Specify a timeframe (e.g., 'in just 14 days')",
                    "Emphasize speed: 'fast results', 'get started today'",
                    "Offer an immediate first win or quick start action",
                    "Reduce perceived wait with phased milestones",
                ],
            },
            "effort": {
                "max": 25,
                "tips": [
                    "Emphasize simplicity: 'just 3 simple steps'",
                    "Use 'done-for-you' or 'plug-and-play' language",
                    "Address the 'I don't have time' objection",
                    "Make it clear no prior experience is needed",
                ],
            },
        }

        for pillar_name, config in pillar_configs.items():
            pillar_score = pillars.get(pillar_name, 0)
            threshold = config["max"] * 0.5  # Below 50% is weak

            if pillar_score < threshold:
                gap = config["max"] - pillar_score
                matched = score["pillar_details"].get(pillar_name, {}).get(
                    "matched_signals", []
                )

                suggestions.append({
                    "pillar": pillar_name,
                    "current_score": pillar_score,
                    "max_score": config["max"],
                    "gap": round(gap, 1),
                    "priority": "high" if pillar_score < config["max"] * 0.25 else "medium",
                    "existing_signals": matched,
                    "suggestions": config["tips"],
                    "description": VALUE_EQUATION.get(pillar_name, {}).get("description", ""),
                })

        # Sort by gap (biggest improvement opportunity first)
        suggestions.sort(key=lambda x: x["gap"], reverse=True)

        potential_gain = sum(s["gap"] for s in suggestions)

        return {
            "ad_id": ad_id,
            "ad_name": score.get("ad_name", ""),
            "current_total": score["total"],
            "current_rating": score["rating"],
            "potential_total": min(100, score["total"] + potential_gain),
            "improvement_areas": suggestions,
            "top_priority": suggestions[0]["pillar"] if suggestions else "none",
            "summary": self._improvement_summary(score["total"], suggestions),
        }

    def compare_scores(self, ad_ids: List[str]) -> Dict[str, Any]:
        """
        Compare multiple ads' Value Equation scores side by side.

        Args:
            ad_ids: List of ad IDs to compare.

        Returns:
            Dict with all scores, a ranking, and per-pillar comparison.
        """
        scores: List[Dict[str, Any]] = []

        for ad_id in ad_ids:
            score = self.score_ad(ad_id)
            if "error" not in score:
                scores.append(score)

        if not scores:
            return {"error": "No valid scores found for the provided ad IDs"}

        # Rank by total score
        scores.sort(key=lambda x: x["total"], reverse=True)
        for i, score in enumerate(scores):
            score["rank"] = i + 1

        # Per-pillar bests
        pillar_names = ["dream_outcome", "perceived_likelihood", "time_delay", "effort"]
        pillar_bests: Dict[str, Dict[str, Any]] = {}
        for pillar in pillar_names:
            best_score = max(scores, key=lambda x: x["pillars"].get(pillar, 0))
            pillar_bests[pillar] = {
                "best_ad_id": best_score.get("ad_id", ""),
                "best_ad_name": best_score.get("ad_name", ""),
                "best_score": best_score["pillars"].get(pillar, 0),
            }

        return {
            "scores": scores,
            "ranking": [
                {
                    "rank": s["rank"],
                    "ad_id": s.get("ad_id", ""),
                    "ad_name": s.get("ad_name", ""),
                    "total": s["total"],
                    "rating": s["rating"],
                }
                for s in scores
            ],
            "pillar_bests": pillar_bests,
            "ads_compared": len(scores),
        }

    def get_best_by_value_equation(self, top_n: int = 10) -> List[Dict[str, Any]]:
        """
        Score all active ads and return the top N by Value Equation score.

        Args:
            top_n: Number of top-scoring ads to return.

        Returns:
            Sorted list of score dicts (highest total first).
        """
        active_ads = db.list_ads(status="ACTIVE")
        scores: List[Dict[str, Any]] = []

        for ad in active_ads:
            score = self.score_ad(ad.ad_id)
            if "error" not in score:
                scores.append(score)

        scores.sort(key=lambda x: x["total"], reverse=True)
        top_scores = scores[:top_n]

        logger.info(
            "Value Equation ranking: top %d of %d active ads scored",
            len(top_scores), len(scores),
        )
        return top_scores

    def correlate_with_performance(self, days: int = 30) -> Dict[str, Any]:
        """
        Correlate Value Equation scores with actual ad performance to
        validate whether higher VE scores produce better results.

        Args:
            days: Lookback window for performance data.

        Returns:
            Dict with correlation analysis: high-VE vs low-VE performance
            averages, insights, and validation status.
        """
        active_ads = db.list_ads(status="ACTIVE")
        data_points: List[Dict[str, Any]] = []

        for ad in active_ads:
            ve_score = self.score_ad(ad.ad_id)
            summary = db.get_insights_summary(ad.ad_id, days=days)

            if "error" in ve_score or summary is None or summary["spend"] == 0:
                continue

            data_points.append({
                "ad_id": ad.ad_id,
                "ve_total": ve_score["total"],
                "cpa": summary["avg_cpa"],
                "roas": summary["roas"],
                "ctr": summary["avg_ctr"] * 100,
                "hook_rate": summary["hook_rate"] * 100,
                "spend": summary["spend"],
                "conversions": summary["conversions"],
            })

        if len(data_points) < 4:
            return {
                "status": "insufficient_data",
                "data_points": len(data_points),
                "message": "Need at least 4 ads with both VE scores and performance data.",
            }

        # Split into high-VE and low-VE groups
        data_points.sort(key=lambda x: x["ve_total"], reverse=True)
        midpoint = len(data_points) // 2
        high_ve = data_points[:midpoint]
        low_ve = data_points[midpoint:]

        def _avg(items: List[Dict], key: str) -> float:
            vals = [item[key] for item in items if item[key] > 0]
            return round(sum(vals) / len(vals), 2) if vals else 0.0

        high_ve_metrics = {
            "avg_ve_score": _avg(high_ve, "ve_total"),
            "avg_cpa": _avg(high_ve, "cpa"),
            "avg_roas": _avg(high_ve, "roas"),
            "avg_ctr": _avg(high_ve, "ctr"),
            "avg_hook_rate": _avg(high_ve, "hook_rate"),
            "sample_size": len(high_ve),
        }

        low_ve_metrics = {
            "avg_ve_score": _avg(low_ve, "ve_total"),
            "avg_cpa": _avg(low_ve, "cpa"),
            "avg_roas": _avg(low_ve, "roas"),
            "avg_ctr": _avg(low_ve, "ctr"),
            "avg_hook_rate": _avg(low_ve, "hook_rate"),
            "sample_size": len(low_ve),
        }

        # Determine if high VE => better performance
        insights: List[str] = []
        is_validated = True

        if high_ve_metrics["avg_cpa"] > 0 and low_ve_metrics["avg_cpa"] > 0:
            cpa_diff = (
                (low_ve_metrics["avg_cpa"] - high_ve_metrics["avg_cpa"])
                / low_ve_metrics["avg_cpa"] * 100
            )
            if cpa_diff > 0:
                insights.append(
                    f"High VE ads have {cpa_diff:.0f}% lower CPA "
                    f"({high_ve_metrics['avg_cpa']:.2f} vs {low_ve_metrics['avg_cpa']:.2f})"
                )
            else:
                insights.append(
                    f"Low VE ads actually have better CPA -- framework may not "
                    f"apply well to this account's audience"
                )
                is_validated = False

        if high_ve_metrics["avg_roas"] > 0 and low_ve_metrics["avg_roas"] > 0:
            roas_ratio = high_ve_metrics["avg_roas"] / low_ve_metrics["avg_roas"]
            if roas_ratio > 1:
                insights.append(
                    f"High VE ads have {roas_ratio:.1f}x better ROAS"
                )
            else:
                insights.append("ROAS does not correlate positively with VE score")
                is_validated = False

        return {
            "status": "validated" if is_validated else "inconclusive",
            "data_points": len(data_points),
            "high_ve_group": high_ve_metrics,
            "low_ve_group": low_ve_metrics,
            "insights": insights,
            "is_framework_validated": is_validated,
            "recommendation": (
                "The Value Equation framework correlates with better performance. "
                "Continue optimizing ads for higher VE scores."
                if is_validated
                else "The VE framework shows mixed results for this account. "
                "Consider adjusting pillar weights or reviewing audience fit."
            ),
        }

    # ------------------------------------------------------------------
    # Internal scoring
    # ------------------------------------------------------------------

    def _score_pillar(
        self,
        text: str,
        signal_library: Dict[str, List[str]],
        pillar_name: str,
    ) -> tuple:
        """
        Score a single pillar by checking how many signal patterns match.

        Each signal category that has at least one match contributes to
        the score. Max score per pillar is 25.

        Returns:
            Tuple of (score: float, details: dict).
        """
        max_score = 25.0
        categories = list(signal_library.keys())
        points_per_category = max_score / len(categories) if categories else 0

        matched_signals: List[str] = []
        matched_categories = 0

        for category, patterns in signal_library.items():
            category_matched = False
            for pattern in patterns:
                try:
                    if re.search(pattern, text, re.IGNORECASE):
                        match = re.search(pattern, text, re.IGNORECASE)
                        matched_signals.append(
                            f"{category}: '{match.group()[:60]}'"
                        )
                        category_matched = True
                        break  # One match per category is enough
                except re.error:
                    continue

            if category_matched:
                matched_categories += 1

        score = round(matched_categories * points_per_category, 1)

        # Bonus for multiple matches in same category (up to pillar max)
        total_matches = len(matched_signals)
        if total_matches > matched_categories:
            bonus = min(3, (total_matches - matched_categories) * 0.5)
            score = min(max_score, score + bonus)

        details = {
            "matched_signals": matched_signals,
            "matched_categories": matched_categories,
            "total_categories": len(categories),
            "coverage_pct": round(
                (matched_categories / len(categories) * 100) if categories else 0, 1
            ),
            "bonus_signals": [],  # populated by score_ad for tag-based bonuses
        }

        return score, details

    @staticmethod
    def _rating_label(total: float) -> str:
        """Map total VE score to a human-readable rating."""
        if total >= 80:
            return "Excellent"
        if total >= 60:
            return "Good"
        if total >= 40:
            return "Average"
        if total >= 20:
            return "Weak"
        return "Very Weak"

    @staticmethod
    def _empty_score(text: str) -> Dict[str, Any]:
        """Return a zeroed-out score for empty or missing text."""
        return {
            "text_analyzed": text or "",
            "pillars": {
                "dream_outcome": 0,
                "perceived_likelihood": 0,
                "time_delay": 0,
                "effort": 0,
            },
            "total": 0,
            "rating": "No Data",
            "pillar_details": {
                "dream_outcome": {"matched_signals": [], "matched_categories": 0, "total_categories": 3, "coverage_pct": 0, "bonus_signals": []},
                "perceived_likelihood": {"matched_signals": [], "matched_categories": 0, "total_categories": 4, "coverage_pct": 0, "bonus_signals": []},
                "time_delay": {"matched_signals": [], "matched_categories": 0, "total_categories": 3, "coverage_pct": 0, "bonus_signals": []},
                "effort": {"matched_signals": [], "matched_categories": 0, "total_categories": 4, "coverage_pct": 0, "bonus_signals": []},
            },
        }

    @staticmethod
    def _improvement_summary(current_total: float, suggestions: List[Dict]) -> str:
        """Build a one-line summary of the improvement opportunity."""
        if not suggestions:
            return "Ad scores well across all Value Equation pillars."
        top = suggestions[0]
        return (
            f"Biggest opportunity: improve '{top['pillar']}' "
            f"(currently {top['current_score']}/{top['max_score']}). "
            f"{top['suggestions'][0]}"
        )
