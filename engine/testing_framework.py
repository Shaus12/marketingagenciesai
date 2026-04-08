"""
Hormozi-style creative testing framework for Meta Ads Management System.

Manages systematic hook-first testing with volume targets, automatic
winner/loser detection, and a graduation pipeline from test -> iterate
-> scale campaigns.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config.settings import TARGET_CPA, TARGET_ROAS, CURRENCY
from config.hormozi import VOLUME_TARGETS, HOOK_CATEGORIES
from config.rules import LEARNING_PHASE_BUFFER_HOURS
from data import db
from data.models import AdData, AdSetData, CampaignData, CreativeTag, RuleExecution

logger = logging.getLogger(__name__)

# Minimum spend per ad before a test result is considered valid
_MIN_SPEND_FOR_RESULT = TARGET_CPA * 1.5
# Minimum conversions to declare a winner with confidence
_MIN_CONVERSIONS_FOR_WINNER = 5
# Default test duration in days
_DEFAULT_TEST_DURATION_DAYS = 7


class TestingFramework:
    """
    Manage the Hormozi hook-first creative testing system.

    Tests follow the structure:
    - Hook tests: 10 different hooks x 1 body creative
    - Angle tests: 6 angles x 5 hooks = 30 ads per batch
    - Each test tracks its hypothesis, variable, start date, min duration,
      and winner criteria.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_active_tests(self) -> List[Dict[str, Any]]:
        """
        List all currently running tests with their status and progress.

        Tests are identified as campaigns with campaign_type="test" and
        status="ACTIVE".

        Returns:
            List of test dicts with campaign_id, name, status, ads_count,
            days_running, spend, best_performer, and readiness assessment.
        """
        test_campaigns = db.list_campaigns(status="ACTIVE", campaign_type="test")
        results: List[Dict[str, Any]] = []

        for campaign in test_campaigns:
            ads = db.list_ads(campaign_id=campaign.campaign_id)
            active_ads = [a for a in ads if a.status == "ACTIVE"]

            # Calculate days running
            created = datetime.fromisoformat(
                campaign.created_at.replace("Z", "+00:00")
            )
            days_running = (datetime.now(tz=timezone.utc) - created).days

            # Aggregate performance
            total_spend = 0.0
            total_conversions = 0
            best_cpa = float("inf")
            best_ad_id = None
            ads_with_data = 0

            for ad in active_ads:
                summary = db.get_insights_summary(ad.ad_id, days=days_running or 7)
                if summary and summary["spend"] > 0:
                    ads_with_data += 1
                    total_spend += summary["spend"]
                    total_conversions += summary["conversions"]
                    if summary["avg_cpa"] > 0 and summary["avg_cpa"] < best_cpa:
                        best_cpa = summary["avg_cpa"]
                        best_ad_id = ad.ad_id

            # Readiness: do we have enough data to evaluate?
            has_enough_spend = total_spend >= _MIN_SPEND_FOR_RESULT * len(active_ads) * 0.5
            has_enough_time = days_running >= _DEFAULT_TEST_DURATION_DAYS
            is_ready = has_enough_spend and has_enough_time

            results.append({
                "campaign_id": campaign.campaign_id,
                "campaign_name": campaign.name,
                "status": campaign.status,
                "days_running": days_running,
                "total_ads": len(ads),
                "active_ads": len(active_ads),
                "ads_with_data": ads_with_data,
                "total_spend": round(total_spend, 2),
                "total_conversions": total_conversions,
                "best_ad_id": best_ad_id,
                "best_cpa": round(best_cpa, 2) if best_cpa < float("inf") else None,
                "is_ready_to_evaluate": is_ready,
                "currency": CURRENCY,
            })

        logger.info("Found %d active tests", len(results))
        return results

    def create_hook_test(
        self,
        body_creative_id: str,
        hooks: List[str],
        campaign_name: Optional[str] = None,
        daily_budget: float = 0.0,
        hypothesis: str = "",
    ) -> Dict[str, Any]:
        """
        Set up a hook test: multiple hooks paired with a single body creative.

        This implements Hormozi's principle of testing 10 hooks per body
        to find the best pattern interrupt.

        Args:
            body_creative_id: The base creative (body) to pair hooks with.
            hooks: List of hook text/descriptions to test.
            campaign_name: Optional name for the test campaign.
            daily_budget: Daily budget for the test campaign.
            hypothesis: What you expect to learn from this test.

        Returns:
            Dict with campaign_id, adset_id, ad_ids, and test metadata.
        """
        target_hooks = VOLUME_TARGETS.get("hooks_per_body", 10)
        if len(hooks) < 2:
            return {"error": "Need at least 2 hooks to run a test"}

        if not campaign_name:
            campaign_name = f"Hook Test - {datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M')}"

        if daily_budget <= 0:
            # Default: allocate enough to get each hook to min spend threshold
            daily_budget = round(
                (_MIN_SPEND_FOR_RESULT * len(hooks)) / _DEFAULT_TEST_DURATION_DAYS, 2
            )

        # Create campaign
        campaign_id = f"test_hook_{uuid.uuid4().hex[:8]}"
        campaign = CampaignData(
            campaign_id=campaign_id,
            name=campaign_name,
            status="ACTIVE",
            objective="CONVERSIONS",
            daily_budget=daily_budget,
            campaign_type="test",
        )
        db.save_campaign(campaign)

        # Create a single ad set
        adset_id = f"adset_{campaign_id}"
        adset = AdSetData(
            adset_id=adset_id,
            campaign_id=campaign_id,
            name=f"{campaign_name} - Ad Set",
            status="ACTIVE",
            daily_budget=daily_budget,
            optimization_goal="CONVERSIONS",
        )
        db.save_adset(adset)

        # Create one ad per hook
        ad_ids: List[str] = []
        for i, hook_text in enumerate(hooks):
            ad_id = f"ad_{campaign_id}_{i:02d}"
            ad = AdData(
                ad_id=ad_id,
                adset_id=adset_id,
                campaign_id=campaign_id,
                name=f"Hook {i + 1}: {hook_text[:50]}",
                status="ACTIVE",
                creative_id=body_creative_id,
            )
            db.save_ad(ad)

            # Tag the creative
            tag = CreativeTag(
                creative_id=body_creative_id,
                ad_id=ad_id,
                hook_type=self._classify_hook(hook_text),
                headline=hook_text,
                source="manual",
            )
            db.save_creative_tag(tag)
            ad_ids.append(ad_id)

        # Log the test creation
        test_metadata = {
            "test_type": "hook_test",
            "body_creative_id": body_creative_id,
            "hook_count": len(hooks),
            "hooks": hooks,
            "hypothesis": hypothesis,
            "min_duration_days": _DEFAULT_TEST_DURATION_DAYS,
            "winner_criteria": "lowest_cpa_with_min_conversions",
        }
        self._log_test_action(
            campaign_id, "test_created", json.dumps(test_metadata)
        )

        logger.info(
            "Created hook test '%s' with %d hooks (campaign: %s)",
            campaign_name, len(hooks), campaign_id,
        )

        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "adset_id": adset_id,
            "ad_ids": ad_ids,
            "hook_count": len(hooks),
            "daily_budget": daily_budget,
            "target_hooks": target_hooks,
            "hooks_provided": len(hooks),
            "hypothesis": hypothesis,
            "estimated_test_duration_days": _DEFAULT_TEST_DURATION_DAYS,
            "currency": CURRENCY,
        }

    def create_angle_test(
        self,
        angles: List[Dict[str, str]],
        hooks_per_angle: int = 5,
        campaign_name: Optional[str] = None,
        daily_budget: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Set up an angle batch: multiple angles, each with multiple hooks.

        Hormozi targets: 6 angles x 5 hooks = 30 ads per batch.

        Args:
            angles: List of dicts, each with "name", "creative_id", and
                    "hooks" (list of hook texts).
            hooks_per_angle: Number of hooks per angle (default 5).
            campaign_name: Optional name for the test campaign.
            daily_budget: Daily budget for the entire test.

        Returns:
            Dict with campaign_id, ad structure, and test metadata.
        """
        target_angles = VOLUME_TARGETS.get("angles_per_batch", 6)
        target_hooks = VOLUME_TARGETS.get("hooks_per_angle", 5)

        if len(angles) < 2:
            return {"error": "Need at least 2 angles to run an angle test"}

        if not campaign_name:
            campaign_name = f"Angle Test - {datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M')}"

        total_ads = sum(min(len(a.get("hooks", [])), hooks_per_angle) for a in angles)
        if daily_budget <= 0:
            daily_budget = round(
                (_MIN_SPEND_FOR_RESULT * total_ads) / _DEFAULT_TEST_DURATION_DAYS, 2
            )

        # Create campaign
        campaign_id = f"test_angle_{uuid.uuid4().hex[:8]}"
        campaign = CampaignData(
            campaign_id=campaign_id,
            name=campaign_name,
            status="ACTIVE",
            objective="CONVERSIONS",
            daily_budget=daily_budget,
            campaign_type="test",
        )
        db.save_campaign(campaign)

        # Create one ad set per angle
        angle_results: List[Dict[str, Any]] = []

        for angle_idx, angle_data in enumerate(angles):
            angle_name = angle_data.get("name", f"Angle {angle_idx + 1}")
            creative_id = angle_data.get("creative_id", "")
            hooks = angle_data.get("hooks", [])[:hooks_per_angle]

            adset_id = f"adset_{campaign_id}_a{angle_idx:02d}"
            adset = AdSetData(
                adset_id=adset_id,
                campaign_id=campaign_id,
                name=f"{angle_name}",
                status="ACTIVE",
                daily_budget=round(daily_budget / len(angles), 2),
                optimization_goal="CONVERSIONS",
            )
            db.save_adset(adset)

            ad_ids: List[str] = []
            for hook_idx, hook_text in enumerate(hooks):
                ad_id = f"ad_{campaign_id}_a{angle_idx:02d}_h{hook_idx:02d}"
                ad = AdData(
                    ad_id=ad_id,
                    adset_id=adset_id,
                    campaign_id=campaign_id,
                    name=f"{angle_name} | Hook {hook_idx + 1}",
                    status="ACTIVE",
                    creative_id=creative_id,
                )
                db.save_ad(ad)

                tag = CreativeTag(
                    creative_id=creative_id,
                    ad_id=ad_id,
                    angle=angle_name,
                    hook_type=self._classify_hook(hook_text),
                    headline=hook_text,
                    source="manual",
                )
                db.save_creative_tag(tag)
                ad_ids.append(ad_id)

            angle_results.append({
                "angle_name": angle_name,
                "adset_id": adset_id,
                "creative_id": creative_id,
                "ad_ids": ad_ids,
                "hook_count": len(hooks),
            })

        self._log_test_action(
            campaign_id,
            "angle_test_created",
            json.dumps({
                "angles": [a["angle_name"] for a in angle_results],
                "total_ads": total_ads,
                "hooks_per_angle": hooks_per_angle,
            }),
        )

        logger.info(
            "Created angle test '%s': %d angles, %d total ads",
            campaign_name, len(angles), total_ads,
        )

        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "angles": angle_results,
            "total_ads": total_ads,
            "daily_budget": daily_budget,
            "target_structure": {
                "target_angles": target_angles,
                "target_hooks_per_angle": target_hooks,
                "target_total": target_angles * target_hooks,
            },
            "estimated_test_duration_days": _DEFAULT_TEST_DURATION_DAYS,
            "currency": CURRENCY,
        }

    def evaluate_test(self, test_id: str) -> Dict[str, Any]:
        """
        Evaluate whether a test has enough data and determine the winner.

        Args:
            test_id: campaign_id of the test campaign.

        Returns:
            Dict with readiness status, winner (if determined), all ad
            results, and statistical comparison.
        """
        campaign = db.get_campaign(test_id)
        if campaign is None:
            return {"error": f"Test campaign '{test_id}' not found"}

        ads = db.list_ads(campaign_id=test_id)
        if not ads:
            return {"error": f"No ads found in test campaign '{test_id}'"}

        created = datetime.fromisoformat(campaign.created_at.replace("Z", "+00:00"))
        days_running = max(1, (datetime.now(tz=timezone.utc) - created).days)

        ad_results: List[Dict[str, Any]] = []
        for ad in ads:
            summary = db.get_insights_summary(ad.ad_id, days=days_running)
            if summary is None:
                summary = {
                    "spend": 0, "conversions": 0, "avg_cpa": 0,
                    "roas": 0, "avg_ctr": 0, "hook_rate": 0, "hold_rate": 0,
                }

            tags = db.get_creative_tags(ad_id=ad.ad_id)
            tag = tags[0] if tags else None

            ad_results.append({
                "ad_id": ad.ad_id,
                "ad_name": ad.name,
                "status": ad.status,
                "hook_type": tag.hook_type if tag else "",
                "hook_text": tag.headline if tag else "",
                "angle": tag.angle if tag else "",
                "spend": summary["spend"],
                "conversions": summary["conversions"],
                "cpa": summary["avg_cpa"],
                "roas": summary["roas"],
                "ctr": round(summary["avg_ctr"] * 100, 2),
                "hook_rate": round(summary["hook_rate"] * 100, 2),
                "hold_rate": round(summary["hold_rate"] * 100, 2),
                "has_enough_spend": summary["spend"] >= _MIN_SPEND_FOR_RESULT,
                "has_enough_conversions": summary["conversions"] >= _MIN_CONVERSIONS_FOR_WINNER,
            })

        # Sort by CPA (lowest first), but only consider ads with conversions
        converting_ads = [r for r in ad_results if r["conversions"] > 0]
        converting_ads.sort(key=lambda x: x["cpa"])

        # Determine readiness
        ads_with_data = [r for r in ad_results if r["has_enough_spend"]]
        is_ready = (
            len(ads_with_data) >= len(ad_results) * 0.5
            and days_running >= _DEFAULT_TEST_DURATION_DAYS
        )

        # Determine winner
        winner = None
        if converting_ads:
            best = converting_ads[0]
            if best["has_enough_conversions"] and best["cpa"] <= TARGET_CPA * 1.5:
                winner = {
                    "ad_id": best["ad_id"],
                    "ad_name": best["ad_name"],
                    "cpa": best["cpa"],
                    "roas": best["roas"],
                    "conversions": best["conversions"],
                    "hook_text": best["hook_text"],
                    "confidence": (
                        "high" if best["conversions"] >= _MIN_CONVERSIONS_FOR_WINNER * 2
                        else "medium" if best["has_enough_conversions"]
                        else "low"
                    ),
                }

        return {
            "test_id": test_id,
            "campaign_name": campaign.name,
            "days_running": days_running,
            "total_ads": len(ads),
            "ads_with_data": len(ads_with_data),
            "is_ready_to_evaluate": is_ready,
            "winner": winner,
            "all_results": ad_results,
            "converting_ads_count": len(converting_ads),
            "recommendation": self._test_recommendation(is_ready, winner, days_running),
        }

    def graduate_winner(self, ad_id: str) -> Dict[str, Any]:
        """
        Move a winning creative from a test campaign into an iterate or
        scale campaign.

        Args:
            ad_id: The winning ad to graduate.

        Returns:
            Dict with the new campaign_id, ad_id, and graduation details.
        """
        ad = db.get_ad(ad_id)
        if ad is None:
            return {"error": f"Ad '{ad_id}' not found"}

        source_campaign = db.get_campaign(ad.campaign_id)
        if source_campaign is None or source_campaign.campaign_type != "test":
            return {
                "error": f"Ad '{ad_id}' is not in a test campaign",
                "current_campaign_type": source_campaign.campaign_type if source_campaign else None,
            }

        # Find or create an iterate campaign to receive the winner
        iterate_campaigns = db.list_campaigns(status="ACTIVE", campaign_type="iterate")
        if iterate_campaigns:
            target_campaign = iterate_campaigns[0]
        else:
            target_campaign_id = f"iterate_{uuid.uuid4().hex[:8]}"
            target_campaign = CampaignData(
                campaign_id=target_campaign_id,
                name=f"Iterate - Winners {datetime.now(tz=timezone.utc).strftime('%Y%m')}",
                status="ACTIVE",
                objective="CONVERSIONS",
                campaign_type="iterate",
            )
            db.save_campaign(target_campaign)

        # Create new ad set in the target campaign
        new_adset_id = f"adset_grad_{uuid.uuid4().hex[:8]}"
        new_adset = AdSetData(
            adset_id=new_adset_id,
            campaign_id=target_campaign.campaign_id,
            name=f"Graduated: {ad.name}",
            status="ACTIVE",
            optimization_goal="CONVERSIONS",
        )
        db.save_adset(new_adset)

        # Clone the ad into the new campaign
        new_ad_id = f"ad_grad_{uuid.uuid4().hex[:8]}"
        new_ad = AdData(
            ad_id=new_ad_id,
            adset_id=new_adset_id,
            campaign_id=target_campaign.campaign_id,
            name=f"[Graduated] {ad.name}",
            status="ACTIVE",
            creative_id=ad.creative_id,
        )
        db.save_ad(new_ad)

        # Copy creative tags
        source_tags = db.get_creative_tags(ad_id=ad_id)
        for tag in source_tags:
            new_tag = CreativeTag(
                creative_id=tag.creative_id,
                ad_id=new_ad_id,
                format=tag.format,
                hook_type=tag.hook_type,
                angle=tag.angle,
                has_text_overlay=tag.has_text_overlay,
                has_testimonial=tag.has_testimonial,
                video_length_seconds=tag.video_length_seconds,
                body_text=tag.body_text,
                headline=tag.headline,
                cta_type=tag.cta_type,
                source="graduated",
            )
            db.save_creative_tag(new_tag)

        # Log the graduation
        self._log_test_action(
            ad.campaign_id,
            "winner_graduated",
            json.dumps({
                "source_ad_id": ad_id,
                "new_ad_id": new_ad_id,
                "target_campaign_id": target_campaign.campaign_id,
            }),
        )

        logger.info(
            "Graduated ad %s from test to iterate campaign %s (new ad: %s)",
            ad_id, target_campaign.campaign_id, new_ad_id,
        )

        return {
            "graduated": True,
            "source_ad_id": ad_id,
            "source_campaign_id": ad.campaign_id,
            "new_ad_id": new_ad_id,
            "new_adset_id": new_adset_id,
            "target_campaign_id": target_campaign.campaign_id,
            "target_campaign_name": target_campaign.name,
            "target_campaign_type": target_campaign.campaign_type,
        }

    def kill_losers(self, test_id: str) -> Dict[str, Any]:
        """
        Pause underperforming ads in a test campaign.

        Keeps the best performer active and pauses ads that have spent
        enough budget without meeting performance thresholds.

        Args:
            test_id: campaign_id of the test to evaluate.

        Returns:
            Dict with killed ad_ids, kept ad_ids, and reasoning.
        """
        evaluation = self.evaluate_test(test_id)
        if "error" in evaluation:
            return evaluation

        all_results = evaluation.get("all_results", [])
        winner = evaluation.get("winner")

        killed: List[Dict[str, Any]] = []
        kept: List[str] = []

        for result in all_results:
            ad_id = result["ad_id"]

            # Never kill the winner
            if winner and ad_id == winner["ad_id"]:
                kept.append(ad_id)
                continue

            # Kill if: spent enough but no conversions, or CPA > 2x target
            should_kill = False
            reason = ""

            if result["has_enough_spend"] and result["conversions"] == 0:
                should_kill = True
                reason = f"Spent {result['spend']:.2f} {CURRENCY} with 0 conversions"
            elif result["has_enough_spend"] and result["cpa"] > TARGET_CPA * 2:
                should_kill = True
                reason = f"CPA of {result['cpa']:.2f} exceeds 2x target ({TARGET_CPA * 2:.2f})"

            if should_kill:
                ad = db.get_ad(ad_id)
                if ad:
                    ad.status = "PAUSED"
                    ad.updated_at = datetime.now(tz=timezone.utc).isoformat()
                    db.save_ad(ad)
                killed.append({
                    "ad_id": ad_id,
                    "ad_name": result["ad_name"],
                    "reason": reason,
                    "spend": result["spend"],
                    "conversions": result["conversions"],
                    "cpa": result["cpa"],
                })
            else:
                kept.append(ad_id)

        self._log_test_action(
            test_id,
            "losers_killed",
            json.dumps({"killed_count": len(killed), "kept_count": len(kept)}),
        )

        logger.info(
            "Test %s: killed %d losers, kept %d ads", test_id, len(killed), len(kept),
        )

        return {
            "test_id": test_id,
            "killed": killed,
            "kept": kept,
            "killed_count": len(killed),
            "kept_count": len(kept),
        }

    def get_test_results(self, test_id: str) -> Dict[str, Any]:
        """
        Return structured results for a completed or in-progress test
        with statistical comparison between ads.

        Args:
            test_id: campaign_id of the test.

        Returns:
            Full evaluation results plus ranking and performance spread.
        """
        evaluation = self.evaluate_test(test_id)
        if "error" in evaluation:
            return evaluation

        all_results = evaluation.get("all_results", [])

        # Add ranking
        converting = [r for r in all_results if r["conversions"] > 0]
        converting.sort(key=lambda x: x["cpa"])
        for i, result in enumerate(converting):
            result["rank"] = i + 1

        # Performance spread
        if converting:
            cpas = [r["cpa"] for r in converting]
            best_cpa = min(cpas)
            worst_cpa = max(cpas)
            avg_cpa = sum(cpas) / len(cpas)
            spread = {
                "best_cpa": round(best_cpa, 2),
                "worst_cpa": round(worst_cpa, 2),
                "avg_cpa": round(avg_cpa, 2),
                "cpa_range": round(worst_cpa - best_cpa, 2),
                "best_vs_worst_pct": (
                    round(((worst_cpa - best_cpa) / best_cpa) * 100, 1)
                    if best_cpa > 0 else 0
                ),
            }
        else:
            spread = {"note": "No converting ads yet"}

        evaluation["ranked_results"] = converting
        evaluation["performance_spread"] = spread

        return evaluation

    def suggest_next_test(self) -> Dict[str, Any]:
        """
        Based on past test results and winning patterns, suggest what
        to test next.

        Analyzes which hook categories and angles have been tested,
        which have performed well, and which are untested.

        Returns:
            Dict with suggested test type, suggested hooks/angles,
            reasoning, and which categories are under-explored.
        """
        # Gather all tested hooks and angles
        all_tags = db.get_creative_tags()
        tested_hooks: Dict[str, int] = {}
        tested_angles: Dict[str, int] = {}
        hook_performance: Dict[str, List[float]] = {}

        for tag in all_tags:
            if tag.hook_type:
                tested_hooks[tag.hook_type] = tested_hooks.get(tag.hook_type, 0) + 1
                # Get performance for this hook type
                summary = db.get_insights_summary(tag.ad_id, days=30)
                if summary and summary["avg_cpa"] > 0:
                    if tag.hook_type not in hook_performance:
                        hook_performance[tag.hook_type] = []
                    hook_performance[tag.hook_type].append(summary["avg_cpa"])
            if tag.angle:
                tested_angles[tag.angle] = tested_angles.get(tag.angle, 0) + 1

        # Find untested hook categories
        all_categories = set(HOOK_CATEGORIES.keys())
        tested_categories = set(tested_hooks.keys())
        untested_categories = all_categories - tested_categories

        # Find best performing hook category
        best_category = None
        best_avg_cpa = float("inf")
        for cat, cpas in hook_performance.items():
            avg = sum(cpas) / len(cpas)
            if avg < best_avg_cpa:
                best_avg_cpa = avg
                best_category = cat

        # Build suggestion
        suggestions: List[str] = []
        suggested_hooks: List[Dict[str, Any]] = []

        if untested_categories:
            for cat in list(untested_categories)[:3]:
                cat_info = HOOK_CATEGORIES.get(cat, {})
                suggestions.append(
                    f"Test '{cat}' hooks -- this category is unexplored. "
                    f"Template: {cat_info.get('template', 'N/A')}"
                )
                suggested_hooks.append({
                    "category": cat,
                    "template": cat_info.get("template", ""),
                    "examples": cat_info.get("examples", []),
                    "reason": "untested",
                })

        if best_category:
            cat_info = HOOK_CATEGORIES.get(best_category, {})
            suggestions.append(
                f"Create more '{best_category}' hooks -- this category has the "
                f"best avg CPA ({best_avg_cpa:.2f} {CURRENCY}). "
                f"Try new variations of: {cat_info.get('template', '')}"
            )
            suggested_hooks.append({
                "category": best_category,
                "template": cat_info.get("template", ""),
                "examples": cat_info.get("examples", []),
                "reason": f"top_performer (avg CPA: {best_avg_cpa:.2f})",
            })

        # Check community angles
        new_angles = db.get_community_angles(status="new", limit=5)
        if new_angles:
            suggestions.append(
                f"{len(new_angles)} unused community angles available. "
                f"Consider building tests around: "
                f"{', '.join(a.suggested_angle or a.source_text[:40] for a in new_angles[:3])}"
            )

        return {
            "tested_hook_categories": tested_hooks,
            "untested_hook_categories": list(untested_categories),
            "tested_angle_count": len(tested_angles),
            "best_performing_category": best_category,
            "best_category_avg_cpa": round(best_avg_cpa, 2) if best_avg_cpa < float("inf") else None,
            "suggestions": suggestions,
            "suggested_hooks": suggested_hooks,
            "community_angles_available": len(new_angles) if new_angles else 0,
            "volume_targets": VOLUME_TARGETS,
        }

    def get_testing_calendar(self, weeks: int = 4) -> List[Dict[str, Any]]:
        """
        Generate a planned testing calendar for the next N weeks.

        Uses volume targets to schedule hook tests and angle tests,
        incorporating community angles and past performance data.

        Args:
            weeks: Number of weeks to plan.

        Returns:
            List of week plans, each with planned tests and targets.
        """
        suggestion = self.suggest_next_test()
        suggested_hooks = suggestion.get("suggested_hooks", [])
        min_ads_per_week = VOLUME_TARGETS.get("min_ads_per_week", 5)
        community_per_week = VOLUME_TARGETS.get("community_ads_per_week", 3)
        hooks_per_body = VOLUME_TARGETS.get("hooks_per_body", 10)

        calendar: List[Dict[str, Any]] = []
        now = datetime.now(tz=timezone.utc)

        for week_num in range(weeks):
            week_start = now + timedelta(weeks=week_num)
            week_end = week_start + timedelta(days=6)

            planned_tests: List[Dict[str, Any]] = []

            # Week 1: focus on top suggestion or untested categories
            if week_num == 0 and suggested_hooks:
                hook = suggested_hooks[0]
                planned_tests.append({
                    "test_type": "hook_test",
                    "description": f"Test {hooks_per_body} hooks with '{hook['category']}' style",
                    "hook_category": hook["category"],
                    "target_ad_count": hooks_per_body,
                    "reason": hook.get("reason", "suggested"),
                })

            # Alternating weeks: hook test vs angle test
            if week_num % 2 == 0:
                planned_tests.append({
                    "test_type": "hook_test",
                    "description": f"Hook variation test (target: {min_ads_per_week} new ads)",
                    "target_ad_count": min_ads_per_week,
                    "reason": "volume_target",
                })
            else:
                planned_tests.append({
                    "test_type": "angle_test",
                    "description": "New angle batch test (multiple angles x hooks)",
                    "target_ad_count": min_ads_per_week,
                    "reason": "volume_target",
                })

            # Community-sourced tests
            if suggestion.get("community_angles_available", 0) > 0:
                planned_tests.append({
                    "test_type": "community_sourced",
                    "description": f"Ads from community insights (target: {community_per_week})",
                    "target_ad_count": community_per_week,
                    "reason": "community_intelligence",
                })

            calendar.append({
                "week_number": week_num + 1,
                "week_start": week_start.strftime("%Y-%m-%d"),
                "week_end": week_end.strftime("%Y-%m-%d"),
                "planned_tests": planned_tests,
                "total_target_ads": sum(t["target_ad_count"] for t in planned_tests),
            })

        logger.info("Generated %d-week testing calendar", weeks)
        return calendar

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_hook(hook_text: str) -> str:
        """
        Attempt to classify a hook into one of the HOOK_CATEGORIES based
        on simple keyword matching. Returns the best guess category.
        """
        text_lower = hook_text.lower()

        if "?" in hook_text or text_lower.startswith(("are you", "do you", "what if", "want to")):
            return "question"
        if any(w in text_lower for w in ["but", "actually", "truth", "myth", "wrong"]):
            return "objection"
        if any(w in text_lower for w in ["%", "stat", "number", "data", "analyzed"]):
            return "shock_stat"
        if any(w in text_lower for w in ["attention", "hey", "if you're a", "this is for"]):
            return "callout"
        if any(w in text_lower for w in ["went from", "achieved", "from", "to", "result"]):
            return "proof"
        if any(w in text_lower for w in ["stop", "wrong", "worst", "never", "instead"]):
            return "contrarian"
        if any(w in text_lower for w in ["secret", "hidden", "nobody", "discovered"]):
            return "curiosity"
        if any(w in text_lower for w in ["I went", "I was", "transformation", "changed"]):
            return "transformation"

        return "general"

    @staticmethod
    def _test_recommendation(
        is_ready: bool, winner: Optional[Dict], days_running: int
    ) -> str:
        """Generate a human-readable recommendation for a test."""
        if not is_ready and days_running < _DEFAULT_TEST_DURATION_DAYS:
            remaining = _DEFAULT_TEST_DURATION_DAYS - days_running
            return (
                f"Test needs {remaining} more day(s) of data. "
                f"Do not make decisions yet -- let the data mature."
            )
        if not is_ready:
            return (
                "Test has been running long enough but not all ads have "
                "sufficient spend. Consider increasing test budget or "
                "killing obvious losers to concentrate spend."
            )
        if winner:
            confidence = winner.get("confidence", "medium")
            return (
                f"Winner found: '{winner['ad_name']}' with CPA of "
                f"{winner['cpa']:.2f} ({confidence} confidence). "
                f"Consider graduating this creative to iterate/scale."
            )
        return (
            "No clear winner yet. Consider extending the test, "
            "adjusting the creative approach, or testing new hooks."
        )

    @staticmethod
    def _log_test_action(campaign_id: str, action: str, details: str) -> None:
        """Log a test-related action to rule executions for audit trail."""
        execution = RuleExecution(
            rule_name=f"testing_framework:{action}",
            rule_type="test",
            entity_id=campaign_id,
            entity_type="campaign",
            action_taken=action,
            details=details,
        )
        try:
            db.save_rule_execution(execution)
        except Exception as exc:
            logger.error("Failed to log test action: %s", exc)
