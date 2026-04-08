"""
Budget allocation and optimization for Meta Ads Management System.

Implements the Hormozi 70/20/10 budget split (Scale / Iterate / Test)
and provides marginal ROAS analysis, rebalancing suggestions, and
efficiency rankings.
"""

import logging
from typing import Any, Dict, List, Optional

from config.settings import (
    MONTHLY_BUDGET,
    SCALE_BUDGET_PCT,
    ITERATE_BUDGET_PCT,
    TEST_BUDGET_PCT,
    TARGET_CPA,
    TARGET_ROAS,
    CURRENCY,
)
from config.rules import MAX_BUDGET_INCREASE_PCT
from data import db

logger = logging.getLogger(__name__)

# Tolerance before a rebalance suggestion is generated (percentage points)
_REBALANCE_THRESHOLD_PCT = 5.0


class BudgetOptimizer:
    """
    Analyze current budget allocation, compare against the Hormozi
    70/20/10 target, and produce actionable rebalancing suggestions.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_current_allocation(self, days: int = 7) -> Dict[str, Any]:
        """
        Calculate how spend is currently distributed across campaign types
        (scale, iterate, test, retarget, other).

        Args:
            days: Lookback window for spend data.

        Returns:
            Dict mapping campaign_type to spend amount, percentage,
            and campaign count, plus totals.
        """
        campaigns = db.list_campaigns(status="ACTIVE")
        allocation: Dict[str, Dict[str, Any]] = {}

        total_spend = 0.0

        for campaign in campaigns:
            ctype = campaign.campaign_type or "other"
            if ctype not in allocation:
                allocation[ctype] = {"spend": 0.0, "campaign_count": 0, "campaign_ids": []}

            ads = db.list_ads(campaign_id=campaign.campaign_id, status="ACTIVE")
            campaign_spend = 0.0
            for ad in ads:
                summary = db.get_insights_summary(ad.ad_id, days=days)
                if summary:
                    campaign_spend += summary["spend"]

            allocation[ctype]["spend"] += campaign_spend
            allocation[ctype]["campaign_count"] += 1
            allocation[ctype]["campaign_ids"].append(campaign.campaign_id)
            total_spend += campaign_spend

        # Compute percentages
        for ctype in allocation:
            spend = allocation[ctype]["spend"]
            allocation[ctype]["spend"] = round(spend, 2)
            allocation[ctype]["pct"] = (
                round((spend / total_spend) * 100, 1) if total_spend > 0 else 0.0
            )

        result = {
            "total_spend": round(total_spend, 2),
            "days": days,
            "currency": CURRENCY,
            "by_type": allocation,
        }

        logger.info(
            "Current allocation: total=%.2f %s over %d days",
            total_spend, CURRENCY, days,
        )
        return result

    def get_target_allocation(self) -> Dict[str, Any]:
        """
        Return the target budget split based on Hormozi 70/20/10 settings.

        Returns:
            Dict with monthly amounts and percentages for each tier.
        """
        return {
            "monthly_budget": MONTHLY_BUDGET,
            "currency": CURRENCY,
            "tiers": {
                "scale": {
                    "pct": SCALE_BUDGET_PCT * 100,
                    "monthly_amount": round(MONTHLY_BUDGET * SCALE_BUDGET_PCT, 2),
                    "daily_amount": round(
                        (MONTHLY_BUDGET * SCALE_BUDGET_PCT) / 30, 2
                    ),
                    "description": "Proven winners with consistent ROAS",
                },
                "iterate": {
                    "pct": ITERATE_BUDGET_PCT * 100,
                    "monthly_amount": round(MONTHLY_BUDGET * ITERATE_BUDGET_PCT, 2),
                    "daily_amount": round(
                        (MONTHLY_BUDGET * ITERATE_BUDGET_PCT) / 30, 2
                    ),
                    "description": "Adjacent variations of winners",
                },
                "test": {
                    "pct": TEST_BUDGET_PCT * 100,
                    "monthly_amount": round(MONTHLY_BUDGET * TEST_BUDGET_PCT, 2),
                    "daily_amount": round(
                        (MONTHLY_BUDGET * TEST_BUDGET_PCT) / 30, 2
                    ),
                    "description": "New concepts and hook tests",
                },
            },
        }

    def get_rebalance_suggestions(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Compare current allocation to target and suggest specific budget
        changes for each campaign type that is off-target.

        Only generates suggestions when the deviation exceeds the internal
        threshold (5 percentage points by default).

        Args:
            days: Lookback window for current spend data.

        Returns:
            List of suggestion dicts, each with campaign_type, current_pct,
            target_pct, deviation, direction, and suggested_action.
        """
        current = self.get_current_allocation(days=days)
        target = self.get_target_allocation()
        suggestions: List[Dict[str, Any]] = []

        total_spend = current["total_spend"]
        if total_spend == 0:
            logger.info("No spend data -- cannot suggest rebalancing")
            return [{
                "campaign_type": "all",
                "suggestion": "No spend data available. Start running campaigns first.",
                "priority": "info",
            }]

        target_pcts = {
            "scale": SCALE_BUDGET_PCT * 100,
            "iterate": ITERATE_BUDGET_PCT * 100,
            "test": TEST_BUDGET_PCT * 100,
        }

        for ctype, target_pct in target_pcts.items():
            current_data = current["by_type"].get(ctype, {"spend": 0, "pct": 0})
            current_pct = current_data.get("pct", 0)
            deviation = current_pct - target_pct

            if abs(deviation) < _REBALANCE_THRESHOLD_PCT:
                continue

            target_daily = target["tiers"][ctype]["daily_amount"]
            current_daily = current_data["spend"] / days if days > 0 else 0

            if deviation > 0:
                direction = "over-allocated"
                priority = "warning" if ctype == "test" else "info"
                suggested_action = (
                    f"Reduce {ctype} daily budget by approximately "
                    f"{abs(current_daily - target_daily):.2f} {CURRENCY} "
                    f"(from ~{current_daily:.2f} to ~{target_daily:.2f}/day)"
                )
            else:
                direction = "under-allocated"
                priority = "warning" if ctype == "scale" else "info"
                suggested_action = (
                    f"Increase {ctype} daily budget by approximately "
                    f"{abs(target_daily - current_daily):.2f} {CURRENCY} "
                    f"(from ~{current_daily:.2f} to ~{target_daily:.2f}/day)"
                )

            suggestions.append({
                "campaign_type": ctype,
                "current_pct": round(current_pct, 1),
                "target_pct": target_pct,
                "deviation_pct": round(deviation, 1),
                "direction": direction,
                "current_daily_spend": round(current_daily, 2),
                "target_daily_spend": target_daily,
                "suggested_action": suggested_action,
                "priority": priority,
            })

        suggestions.sort(key=lambda x: abs(x.get("deviation_pct", 0)), reverse=True)
        logger.info("Generated %d rebalance suggestions", len(suggestions))
        return suggestions

    def calculate_marginal_roas(
        self, campaign_id: str, days: int = 7
    ) -> Dict[str, Any]:
        """
        Estimate the marginal ROAS for a campaign -- what an extra unit
        of budget is likely to return based on recent efficiency trends.

        Uses the relationship between daily spend and daily revenue to
        estimate diminishing returns.

        Args:
            campaign_id: The campaign to analyze.
            days: Lookback window.

        Returns:
            Dict with campaign_id, current_roas, estimated_marginal_roas,
            efficiency_trend, and a recommendation.
        """
        campaign = db.get_campaign(campaign_id)
        if campaign is None:
            return {
                "campaign_id": campaign_id,
                "error": "Campaign not found",
            }

        ads = db.list_ads(campaign_id=campaign_id, status="ACTIVE")
        total_spend = 0.0
        total_revenue = 0.0

        # Collect daily spend/revenue pairs for trend analysis
        daily_pairs: List[Dict[str, float]] = []
        seen_dates: Dict[str, Dict[str, float]] = {}

        for ad in ads:
            insights = db.get_insights(ad_id=ad.ad_id)
            for insight in insights[:days]:
                d = insight.date
                if d not in seen_dates:
                    seen_dates[d] = {"spend": 0.0, "revenue": 0.0}
                seen_dates[d]["spend"] += insight.spend
                seen_dates[d]["revenue"] += insight.revenue
                total_spend += insight.spend
                total_revenue += insight.revenue

        for date_str in sorted(seen_dates.keys()):
            daily_pairs.append(seen_dates[date_str])

        current_roas = round(total_revenue / total_spend, 2) if total_spend > 0 else 0.0

        # Estimate marginal ROAS: compare ROAS at higher spend days vs lower
        if len(daily_pairs) < 3:
            return {
                "campaign_id": campaign_id,
                "campaign_name": campaign.name,
                "current_roas": current_roas,
                "estimated_marginal_roas": current_roas,
                "efficiency_trend": "insufficient_data",
                "recommendation": (
                    "Not enough daily data points to estimate marginal ROAS. "
                    "Need at least 3 days of data."
                ),
            }

        # Sort by spend ascending, compare low-spend days ROAS vs high-spend days
        daily_pairs_sorted = sorted(daily_pairs, key=lambda x: x["spend"])
        midpoint = len(daily_pairs_sorted) // 2

        low_spend_days = daily_pairs_sorted[:midpoint]
        high_spend_days = daily_pairs_sorted[midpoint:]

        low_spend_total = sum(d["spend"] for d in low_spend_days)
        low_rev_total = sum(d["revenue"] for d in low_spend_days)
        high_spend_total = sum(d["spend"] for d in high_spend_days)
        high_rev_total = sum(d["revenue"] for d in high_spend_days)

        low_roas = low_rev_total / low_spend_total if low_spend_total > 0 else 0
        high_roas = high_rev_total / high_spend_total if high_spend_total > 0 else 0

        # Marginal ROAS is estimated from the high-spend segment
        marginal_roas = round(high_roas, 2)

        if low_roas > 0 and high_roas < low_roas * 0.8:
            trend = "diminishing_returns"
            recommendation = (
                f"ROAS drops from {low_roas:.2f} at lower spend to {high_roas:.2f} "
                f"at higher spend. Diminishing returns detected -- adding budget "
                f"here will be less efficient."
            )
        elif high_roas > low_roas * 1.1:
            trend = "improving_efficiency"
            recommendation = (
                f"ROAS improves from {low_roas:.2f} to {high_roas:.2f} at higher "
                f"spend. This campaign scales well -- consider increasing budget."
            )
        else:
            trend = "stable"
            recommendation = (
                f"ROAS is stable around {current_roas:.2f} across spend levels. "
                f"Moderate budget increases should maintain efficiency."
            )

        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign.name,
            "current_roas": current_roas,
            "estimated_marginal_roas": marginal_roas,
            "low_spend_roas": round(low_roas, 2),
            "high_spend_roas": round(high_roas, 2),
            "efficiency_trend": trend,
            "recommendation": recommendation,
            "data_points": len(daily_pairs),
        }

    def suggest_budget_moves(
        self, amount: float, days: int = 7
    ) -> List[Dict[str, Any]]:
        """
        Given extra budget to allocate, suggest where to put it and why.

        Uses efficiency ranking and marginal ROAS to determine the best
        placement for additional spend.

        Args:
            amount: Additional daily budget to allocate (in account currency).
            days: Lookback window for performance data.

        Returns:
            List of suggestions, each with campaign_id, suggested_amount,
            expected_impact, and reasoning.
        """
        if amount <= 0:
            return [{
                "error": "Amount must be positive",
                "amount_provided": amount,
            }]

        ranking = self.get_efficiency_ranking(days=days)
        if not ranking:
            return [{
                "suggestion": "No campaigns with performance data available.",
                "amount": amount,
            }]

        # Distribute budget weighted by efficiency score
        total_score = sum(r["efficiency_score"] for r in ranking if r["efficiency_score"] > 0)
        suggestions: List[Dict[str, Any]] = []
        remaining = amount

        for entry in ranking:
            if entry["efficiency_score"] <= 0:
                continue
            if remaining <= 0:
                break

            # Weight allocation by efficiency, cap at MAX_BUDGET_INCREASE_PCT
            weight = entry["efficiency_score"] / total_score if total_score > 0 else 0
            suggested = round(amount * weight, 2)

            # Cap increase at MAX_BUDGET_INCREASE_PCT of current budget
            current_daily = entry.get("daily_spend", 0)
            if current_daily > 0:
                max_increase = current_daily * (MAX_BUDGET_INCREASE_PCT / 100)
                suggested = min(suggested, max_increase)

            suggested = min(suggested, remaining)
            remaining -= suggested

            if suggested < 1.0:
                continue

            # Project impact
            roas = entry.get("roas", 0)
            projected_revenue = round(suggested * roas, 2) if roas > 0 else 0

            suggestions.append({
                "campaign_id": entry["campaign_id"],
                "campaign_name": entry["campaign_name"],
                "campaign_type": entry["campaign_type"],
                "suggested_daily_increase": suggested,
                "current_daily_spend": current_daily,
                "new_daily_spend": round(current_daily + suggested, 2),
                "projected_daily_revenue": projected_revenue,
                "current_roas": roas,
                "efficiency_score": entry["efficiency_score"],
                "reasoning": (
                    f"ROAS of {roas:.2f} with CPA of "
                    f"{entry.get('cpa', 0):.2f} {CURRENCY}. "
                    f"Adding {suggested:.2f} {CURRENCY}/day should generate "
                    f"~{projected_revenue:.2f} {CURRENCY} in revenue."
                ),
            })

        # If there's unallocated budget, note it
        if remaining > 1.0:
            suggestions.append({
                "campaign_id": None,
                "suggestion": (
                    f"{remaining:.2f} {CURRENCY} could not be allocated without "
                    f"exceeding {MAX_BUDGET_INCREASE_PCT}% increase limits. "
                    f"Consider launching new test campaigns."
                ),
                "unallocated_amount": round(remaining, 2),
            })

        logger.info(
            "Budget move suggestions: %.2f %s across %d campaigns",
            amount, CURRENCY, len([s for s in suggestions if s.get("campaign_id")]),
        )
        return suggestions

    def get_efficiency_ranking(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Rank all active campaigns by cost-efficiency.

        The efficiency score combines ROAS, CPA-vs-target, and volume
        into a single comparable metric.

        Args:
            days: Lookback window.

        Returns:
            Sorted list of campaign dicts (most efficient first).
        """
        campaigns = db.list_campaigns(status="ACTIVE")
        rankings: List[Dict[str, Any]] = []

        for campaign in campaigns:
            ads = db.list_ads(campaign_id=campaign.campaign_id, status="ACTIVE")
            total_spend = 0.0
            total_revenue = 0.0
            total_conversions = 0
            total_clicks = 0
            total_impressions = 0

            for ad in ads:
                summary = db.get_insights_summary(ad.ad_id, days=days)
                if summary:
                    total_spend += summary["spend"]
                    total_revenue += summary["revenue"]
                    total_conversions += summary["conversions"]
                    total_clicks += summary["clicks"]
                    total_impressions += summary["impressions"]

            if total_spend == 0:
                continue

            roas = total_revenue / total_spend if total_spend > 0 else 0
            cpa = total_spend / total_conversions if total_conversions > 0 else 0
            ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
            daily_spend = total_spend / days if days > 0 else 0

            # Composite efficiency score (0-100)
            roas_score = min(50, (roas / TARGET_ROAS) * 25) if TARGET_ROAS > 0 else 0
            cpa_score = min(30, (TARGET_CPA / cpa) * 15) if cpa > 0 else 0
            volume_score = min(20, total_conversions / 2)  # 40+ conversions = max score

            efficiency_score = round(roas_score + cpa_score + volume_score, 1)

            rankings.append({
                "campaign_id": campaign.campaign_id,
                "campaign_name": campaign.name,
                "campaign_type": campaign.campaign_type,
                "spend": round(total_spend, 2),
                "daily_spend": round(daily_spend, 2),
                "revenue": round(total_revenue, 2),
                "conversions": total_conversions,
                "roas": round(roas, 2),
                "cpa": round(cpa, 2),
                "ctr": round(ctr, 2),
                "efficiency_score": efficiency_score,
                "active_ads": len(ads),
            })

        rankings.sort(key=lambda x: x["efficiency_score"], reverse=True)
        logger.info("Efficiency ranking: %d campaigns evaluated", len(rankings))
        return rankings
