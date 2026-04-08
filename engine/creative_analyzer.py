"""
Creative performance analyzer for Meta Ads Management System.

Scores, ranks, and analyzes ad creatives using performance metrics and
creative tags. Detects fatigue and identifies winning patterns across
formats, hook types, and angles.
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from config.settings import TARGET_CPA, TARGET_ROAS
from config.rules import CREATIVE_THRESHOLDS
from data import db

logger = logging.getLogger(__name__)


class CreativeAnalyzer:
    """Score and analyze creative performance for decision-making."""

    # Weight each metric in the composite score (must sum to 1.0)
    _SCORE_WEIGHTS = {
        "hook_rate": 0.20,
        "hold_rate": 0.15,
        "ctr": 0.20,
        "cpa_vs_target": 0.25,
        "roas_vs_target": 0.20,
    }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score_creative(self, ad_id: str, days: int = 7) -> Dict[str, Any]:
        """
        Compute a composite score (0-100) for a single ad creative.

        The score is a weighted blend of sub-scores for hook_rate,
        hold_rate, CTR, CPA-vs-target, and ROAS-vs-target -- each
        mapped through the thresholds defined in rules.CREATIVE_THRESHOLDS.

        Args:
            ad_id: The ad to score.
            days: Number of days of data to consider.

        Returns:
            Dict with ad_id, composite_score (0-100), sub_scores dict,
            rating label, and the underlying metrics.
        """
        summary = db.get_insights_summary(ad_id, days=days)
        if summary is None:
            logger.warning("No insights data for ad %s", ad_id)
            return self._empty_score(ad_id)

        ad = db.get_ad(ad_id)
        ad_name = ad.name if ad else ""

        metrics = {
            "hook_rate": summary["hook_rate"] * 100,  # percentage
            "hold_rate": summary["hold_rate"] * 100,
            "ctr": summary["avg_ctr"] * 100,
            "cpa": summary["avg_cpa"],
            "roas": summary["roas"],
        }

        sub_scores: Dict[str, float] = {}

        # Hook rate sub-score (0-100)
        sub_scores["hook_rate"] = self._threshold_score(
            metrics["hook_rate"], CREATIVE_THRESHOLDS["hook_rate"], higher_is_better=True
        )

        # Hold rate sub-score
        sub_scores["hold_rate"] = self._threshold_score(
            metrics["hold_rate"], CREATIVE_THRESHOLDS["hold_rate"], higher_is_better=True
        )

        # CTR sub-score
        sub_scores["ctr"] = self._threshold_score(
            metrics["ctr"], CREATIVE_THRESHOLDS["ctr"], higher_is_better=True
        )

        # CPA vs target sub-score (lower CPA = better)
        cpa_ratio = metrics["cpa"] / TARGET_CPA if TARGET_CPA > 0 else 2.0
        sub_scores["cpa_vs_target"] = self._threshold_score(
            cpa_ratio, CREATIVE_THRESHOLDS["cpa_vs_target"], higher_is_better=False
        )

        # ROAS vs target sub-score
        roas_ratio = metrics["roas"] / TARGET_ROAS if TARGET_ROAS > 0 else 0.0
        sub_scores["roas_vs_target"] = self._threshold_score(
            roas_ratio, CREATIVE_THRESHOLDS["roas_vs_target"], higher_is_better=True
        )

        # Weighted composite
        composite = sum(
            sub_scores[k] * self._SCORE_WEIGHTS[k] for k in self._SCORE_WEIGHTS
        )
        composite = round(min(100, max(0, composite)), 1)

        return {
            "ad_id": ad_id,
            "ad_name": ad_name,
            "composite_score": composite,
            "rating": self._rating_label(composite),
            "sub_scores": sub_scores,
            "metrics": metrics,
            "days": days,
        }

    def analyze_all_creatives(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Score every active creative and return them sorted best-to-worst.

        Args:
            days: Lookback window for metrics.

        Returns:
            Sorted list of score dicts (highest composite_score first).
        """
        active_ads = db.list_ads(status="ACTIVE")
        results: List[Dict[str, Any]] = []

        for ad in active_ads:
            score = self.score_creative(ad.ad_id, days=days)
            if score["composite_score"] > 0 or score["metrics"].get("cpa", 0) > 0:
                results.append(score)

        results.sort(key=lambda x: x["composite_score"], reverse=True)
        logger.info("Analyzed %d active creatives over %d days", len(results), days)
        return results

    def get_winners(self, days: int = 7, top_n: int = 5) -> List[Dict[str, Any]]:
        """Return the top N creatives by composite score."""
        all_scored = self.analyze_all_creatives(days=days)
        return all_scored[:top_n]

    def get_losers(self, days: int = 7, bottom_n: int = 5) -> List[Dict[str, Any]]:
        """Return the bottom N creatives by composite score."""
        all_scored = self.analyze_all_creatives(days=days)
        return all_scored[-bottom_n:] if len(all_scored) >= bottom_n else all_scored

    def detect_fatigue(self, ad_id: str) -> Dict[str, Any]:
        """
        Detect whether a creative is fatiguing based on declining hook
        rate and rising frequency over the past 7 days.

        Returns:
            Dict with fatigue assessment: is_fatiguing, hook_rate_trend_pct,
            frequency_trend, days_analyzed, and a recommendation.
        """
        hook_trend = db.get_ad_trend(ad_id, "hook_rate", days=7)
        freq_trend = db.get_ad_trend(ad_id, "frequency", days=7)

        hook_values = [d["value"] for d in hook_trend if d["value"] is not None]
        freq_values = [d["value"] for d in freq_trend if d["value"] is not None]

        ad = db.get_ad(ad_id)
        ad_name = ad.name if ad else ""

        result: Dict[str, Any] = {
            "ad_id": ad_id,
            "ad_name": ad_name,
            "is_fatiguing": False,
            "hook_rate_trend_pct": 0.0,
            "frequency_current": freq_values[-1] if freq_values else 0.0,
            "frequency_trend": 0.0,
            "days_analyzed": len(hook_values),
            "recommendation": "Insufficient data",
        }

        if len(hook_values) < 3:
            return result

        # Hook rate trend: compare first half average to second half average
        midpoint = len(hook_values) // 2
        first_half_avg = sum(hook_values[:midpoint]) / midpoint if midpoint > 0 else 0
        second_half_avg = (
            sum(hook_values[midpoint:]) / len(hook_values[midpoint:])
            if len(hook_values[midpoint:]) > 0
            else 0
        )

        if first_half_avg > 0:
            hook_change_pct = ((second_half_avg - first_half_avg) / first_half_avg) * 100
        else:
            hook_change_pct = 0.0

        result["hook_rate_trend_pct"] = round(hook_change_pct, 2)

        # Frequency trend
        if len(freq_values) >= 2:
            result["frequency_trend"] = round(freq_values[-1] - freq_values[0], 2)

        # Fatigue heuristic: hook rate dropping AND frequency rising
        is_hook_declining = hook_change_pct < -10
        is_freq_high = result["frequency_current"] > 3.0
        is_freq_rising = result["frequency_trend"] > 0.5

        if is_hook_declining and (is_freq_high or is_freq_rising):
            result["is_fatiguing"] = True
            result["recommendation"] = (
                "Creative is fatiguing. Hook rate declining "
                f"({hook_change_pct:+.1f}%) while frequency is "
                f"{result['frequency_current']:.1f}. Consider pausing or "
                "refreshing with a new hook variation."
            )
        elif is_hook_declining:
            result["is_fatiguing"] = False
            result["recommendation"] = (
                "Hook rate is declining but frequency is still acceptable. "
                "Monitor closely over the next 2-3 days."
            )
        elif is_freq_high:
            result["is_fatiguing"] = False
            result["recommendation"] = (
                f"Frequency is high ({result['frequency_current']:.1f}) but "
                "hook rate is holding. Audience may be saturating -- "
                "consider expanding targeting."
            )
        else:
            result["recommendation"] = "Creative performance looks healthy."

        return result

    def detect_fatigue_all(self) -> List[Dict[str, Any]]:
        """
        Run fatigue detection on all active ads.

        Returns:
            List of fatigue results, fatiguing ads listed first.
        """
        active_ads = db.list_ads(status="ACTIVE")
        results: List[Dict[str, Any]] = []

        for ad in active_ads:
            fatigue = self.detect_fatigue(ad.ad_id)
            results.append(fatigue)

        # Sort: fatiguing first, then by hook_rate_trend_pct ascending
        results.sort(
            key=lambda x: (not x["is_fatiguing"], x["hook_rate_trend_pct"])
        )
        fatiguing_count = sum(1 for r in results if r["is_fatiguing"])
        logger.info(
            "Fatigue detection: %d/%d ads showing fatigue",
            fatiguing_count, len(results),
        )
        return results

    def get_patterns(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Correlate creative tags (format, hook_type, angle, etc.) with
        performance metrics to surface winning patterns.

        Example output entries:
            "UGC format averages 2.3x better hook rate"
            "Question hooks average 15% lower CPA"

        Args:
            days: Lookback window.

        Returns:
            List of pattern dicts with dimension, value, metric,
            avg_value, comparison text, and sample_size.
        """
        all_tags = db.get_creative_tags()
        if not all_tags:
            logger.info("No creative tags found -- cannot detect patterns")
            return []

        # Gather performance per tag dimension
        dimensions = ["format", "hook_type", "angle"]
        performance_by_dim: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
            dim: defaultdict(list) for dim in dimensions
        }

        for tag in all_tags:
            summary = db.get_insights_summary(tag.ad_id, days=days)
            if summary is None:
                continue

            entry = {
                "ad_id": tag.ad_id,
                "hook_rate": summary["hook_rate"] * 100,
                "hold_rate": summary["hold_rate"] * 100,
                "ctr": summary["avg_ctr"] * 100,
                "cpa": summary["avg_cpa"],
                "roas": summary["roas"],
                "spend": summary["spend"],
            }

            for dim in dimensions:
                value = getattr(tag, dim, "")
                if value:
                    performance_by_dim[dim][value].append(entry)

        # Compute averages and build pattern insights
        patterns: List[Dict[str, Any]] = []
        metrics_to_analyze = ["hook_rate", "ctr", "cpa", "roas"]

        for dim in dimensions:
            for metric in metrics_to_analyze:
                # Compute global average
                all_values: List[float] = []
                group_avgs: Dict[str, float] = {}

                for group_name, entries in performance_by_dim[dim].items():
                    vals = [e[metric] for e in entries if e[metric] > 0]
                    if not vals:
                        continue
                    group_avg = sum(vals) / len(vals)
                    group_avgs[group_name] = group_avg
                    all_values.extend(vals)

                if not all_values or not group_avgs:
                    continue

                global_avg = sum(all_values) / len(all_values)
                if global_avg == 0:
                    continue

                # Find notable deviations (>15% from global average)
                for group_name, group_avg in group_avgs.items():
                    sample_size = len(performance_by_dim[dim][group_name])
                    if sample_size < 2:
                        continue

                    diff_pct = ((group_avg - global_avg) / global_avg) * 100

                    if abs(diff_pct) < 15:
                        continue

                    # Build human-readable insight
                    higher_is_better = metric != "cpa"
                    is_good = (diff_pct > 0) == higher_is_better

                    if metric == "cpa":
                        comparison = (
                            f"{group_name} {dim} averages {abs(diff_pct):.0f}% "
                            f"{'lower' if diff_pct < 0 else 'higher'} CPA"
                        )
                    else:
                        ratio = group_avg / global_avg if global_avg > 0 else 0
                        comparison = (
                            f"{group_name} {dim} averages "
                            f"{ratio:.1f}x {'better' if is_good else 'worse'} "
                            f"{metric.replace('_', ' ')}"
                        )

                    patterns.append({
                        "dimension": dim,
                        "value": group_name,
                        "metric": metric,
                        "group_avg": round(group_avg, 2),
                        "global_avg": round(global_avg, 2),
                        "diff_pct": round(diff_pct, 1),
                        "is_positive": is_good,
                        "comparison": comparison,
                        "sample_size": sample_size,
                    })

        # Sort by absolute impact, most significant first
        patterns.sort(key=lambda x: abs(x["diff_pct"]), reverse=True)
        logger.info("Found %d creative patterns over %d days", len(patterns), days)
        return patterns

    def compare_to_best(self, ad_id: str, days: int = 7) -> Dict[str, Any]:
        """
        Compare an ad's performance to the current best performer.

        Returns:
            Dict with the ad's score, the best ad's score, and a
            per-metric comparison.
        """
        ad_score = self.score_creative(ad_id, days=days)
        winners = self.get_winners(days=days, top_n=1)

        if not winners:
            return {
                "ad_id": ad_id,
                "ad_score": ad_score,
                "best_ad": None,
                "comparison": "No other active ads to compare against.",
            }

        best = winners[0]

        # Avoid comparing an ad to itself
        if best["ad_id"] == ad_id:
            all_scored = self.analyze_all_creatives(days=days)
            others = [s for s in all_scored if s["ad_id"] != ad_id]
            best = others[0] if others else best

        metric_comparison: Dict[str, Dict[str, Any]] = {}
        for metric_name in ad_score["metrics"]:
            ad_val = ad_score["metrics"][metric_name]
            best_val = best["metrics"].get(metric_name, 0)
            if best_val != 0:
                diff_pct = ((ad_val - best_val) / best_val) * 100
            else:
                diff_pct = 0.0

            metric_comparison[metric_name] = {
                "ad_value": round(ad_val, 2),
                "best_value": round(best_val, 2),
                "diff_pct": round(diff_pct, 1),
            }

        return {
            "ad_id": ad_id,
            "ad_score": ad_score["composite_score"],
            "ad_rating": ad_score["rating"],
            "best_ad_id": best["ad_id"],
            "best_ad_name": best.get("ad_name", ""),
            "best_score": best["composite_score"],
            "best_rating": best["rating"],
            "score_gap": round(best["composite_score"] - ad_score["composite_score"], 1),
            "metric_comparison": metric_comparison,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _threshold_score(
        value: float,
        thresholds: Dict[str, float],
        higher_is_better: bool = True,
    ) -> float:
        """
        Map a metric value to a 0-100 score using the tier thresholds.

        Thresholds dict has keys: poor, okay, good, great.
        Returns a score interpolated between tiers.
        """
        tiers = ["poor", "okay", "good", "great"]
        tier_scores = [15, 40, 65, 90]

        tier_values = [thresholds[t] for t in tiers]

        if not higher_is_better:
            # For inverse metrics (like CPA ratio), lower value = better
            # The thresholds are already ordered great < good < okay < poor
            tier_values = list(reversed(tier_values))

        # Clamp to range
        if higher_is_better:
            if value <= tier_values[0]:
                return 5.0
            if value >= tier_values[-1]:
                return 95.0
        else:
            if value >= tier_values[0]:
                return 5.0
            if value <= tier_values[-1]:
                return 95.0

        # Interpolate between tiers
        for i in range(len(tier_values) - 1):
            low_val = tier_values[i]
            high_val = tier_values[i + 1]
            low_score = tier_scores[i]
            high_score = tier_scores[i + 1]

            if higher_is_better:
                if low_val <= value <= high_val:
                    ratio = (value - low_val) / (high_val - low_val) if high_val != low_val else 0
                    return low_score + ratio * (high_score - low_score)
            else:
                if high_val <= value <= low_val:
                    ratio = (low_val - value) / (low_val - high_val) if low_val != high_val else 0
                    return low_score + ratio * (high_score - low_score)

        return 50.0  # fallback

    @staticmethod
    def _rating_label(score: float) -> str:
        """Map a composite score to a human-readable rating."""
        if score >= 80:
            return "Excellent"
        if score >= 65:
            return "Good"
        if score >= 45:
            return "Average"
        if score >= 25:
            return "Below Average"
        return "Poor"

    @staticmethod
    def _empty_score(ad_id: str) -> Dict[str, Any]:
        """Return a zeroed-out score dict when no data is available."""
        return {
            "ad_id": ad_id,
            "ad_name": "",
            "composite_score": 0.0,
            "rating": "No Data",
            "sub_scores": {k: 0.0 for k in CreativeAnalyzer._SCORE_WEIGHTS},
            "metrics": {
                "hook_rate": 0.0,
                "hold_rate": 0.0,
                "ctr": 0.0,
                "cpa": 0.0,
                "roas": 0.0,
            },
            "days": 0,
        }
