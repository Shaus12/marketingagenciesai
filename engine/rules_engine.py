"""
Automated rules engine for Meta Ads Management System.

Evaluates kill, scale, and alert rules against current ad data,
logs every decision, and optionally executes actions (pause ads,
change budgets) with a dry-run safety default.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config.settings import TARGET_CPA, TARGET_ROAS
from config.rules import (
    KILL_RULES,
    SCALE_RULES,
    ALERT_RULES,
    LEARNING_PHASE_BUFFER_HOURS,
    MAX_BUDGET_INCREASE_PCT,
    MIN_HOURS_BETWEEN_CHANGES,
)
from data import db
from data.models import RuleExecution

logger = logging.getLogger(__name__)


class RulesEngine:
    """
    Evaluate kill / scale / alert rules against live ad data, log every
    decision to the database, and optionally execute actions.
    """

    def __init__(self) -> None:
        self._cooldown_cache: Dict[str, datetime] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_all(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Run every kill, scale, and alert rule against all active ads.

        Returns:
            Dict with keys "kills", "scales", "alerts" -- each a list of
            action dicts describing what should happen and why.
        """
        logger.info("Starting full rules evaluation")
        kills = self.evaluate_kills()
        scales = self.evaluate_scales()
        alerts = self.evaluate_alerts()

        logger.info(
            "Rules evaluation complete: %d kills, %d scales, %d alerts",
            len(kills), len(scales), len(alerts),
        )
        return {"kills": kills, "scales": scales, "alerts": alerts}

    def evaluate_kills(self) -> List[Dict[str, Any]]:
        """
        Evaluate all kill rules against active ads.

        Returns:
            List of dicts, each describing an ad to pause and why.
        """
        enriched_ads = self._get_enriched_active_ads()
        results: List[Dict[str, Any]] = []

        for ad_data in enriched_ads:
            for rule in KILL_RULES:
                try:
                    if rule["condition"](ad_data):
                        result = {
                            "rule_name": rule["name"],
                            "rule_description": rule["description"],
                            "action": rule["action"],
                            "severity": rule.get("severity", "critical"),
                            "ad_id": ad_data["ad_id"],
                            "ad_name": ad_data.get("ad_name", ""),
                            "campaign_id": ad_data.get("campaign_id", ""),
                            "metrics": {
                                "spend": ad_data.get("spend", 0),
                                "conversions": ad_data.get("conversions", 0),
                                "cpa": ad_data.get("cpa", 0),
                                "roas": ad_data.get("roas", 0),
                                "ctr": ad_data.get("ctr", 0),
                            },
                        }
                        results.append(result)
                        self._log_execution(
                            rule_name=rule["name"],
                            rule_type="kill",
                            entity_id=ad_data["ad_id"],
                            entity_type="ad",
                            action_taken=rule["action"],
                            details=json.dumps(result["metrics"]),
                        )
                        logger.info(
                            "Kill rule '%s' triggered for ad %s: %s",
                            rule["name"], ad_data["ad_id"], rule["description"],
                        )
                        # One kill per ad is enough; stop checking further rules
                        break
                except (KeyError, TypeError, ZeroDivisionError) as exc:
                    logger.warning(
                        "Kill rule '%s' error on ad %s: %s",
                        rule["name"], ad_data.get("ad_id", "?"), exc,
                    )
        return results

    def evaluate_scales(self) -> List[Dict[str, Any]]:
        """
        Evaluate all scale rules against active ads.

        Returns:
            List of dicts, each describing a budget change suggestion.
        """
        enriched_ads = self._get_enriched_active_ads()
        results: List[Dict[str, Any]] = []

        for ad_data in enriched_ads:
            for rule in SCALE_RULES:
                try:
                    if rule["condition"](ad_data):
                        cooldown_hours = rule.get("cooldown_hours", MIN_HOURS_BETWEEN_CHANGES)
                        if self._check_cooldown(ad_data["ad_id"], "scale", cooldown_hours):
                            logger.debug(
                                "Scale rule '%s' on ad %s skipped -- cooldown active",
                                rule["name"], ad_data["ad_id"],
                            )
                            continue

                        suggested_increase = self._calculate_budget_change(
                            ad_data, rule["action"],
                        )
                        result = {
                            "rule_name": rule["name"],
                            "rule_description": rule["description"],
                            "action": rule["action"],
                            "ad_id": ad_data["ad_id"],
                            "ad_name": ad_data.get("ad_name", ""),
                            "campaign_id": ad_data.get("campaign_id", ""),
                            "current_daily_budget": ad_data.get("daily_budget", 0),
                            "suggested_daily_budget": suggested_increase,
                            "metrics": {
                                "roas": ad_data.get("roas", 0),
                                "cpa": ad_data.get("cpa", 0),
                                "conversions_7d": ad_data.get("conversions_7d", 0),
                                "consecutive_days_above_target": ad_data.get(
                                    "consecutive_days_above_target", 0
                                ),
                            },
                        }
                        results.append(result)
                        self._log_execution(
                            rule_name=rule["name"],
                            rule_type="scale",
                            entity_id=ad_data["ad_id"],
                            entity_type="ad",
                            action_taken=rule["action"],
                            details=json.dumps(result["metrics"]),
                        )
                        logger.info(
                            "Scale rule '%s' triggered for ad %s",
                            rule["name"], ad_data["ad_id"],
                        )
                except (KeyError, TypeError, ZeroDivisionError) as exc:
                    logger.warning(
                        "Scale rule '%s' error on ad %s: %s",
                        rule["name"], ad_data.get("ad_id", "?"), exc,
                    )
        return results

    def evaluate_alerts(self) -> List[Dict[str, Any]]:
        """
        Evaluate all alert rules against active ads.

        Returns:
            List of notification dicts to be sent via Slack/email.
        """
        enriched_ads = self._get_enriched_active_ads()
        results: List[Dict[str, Any]] = []

        for ad_data in enriched_ads:
            for rule in ALERT_RULES:
                try:
                    if rule["condition"](ad_data):
                        result = {
                            "rule_name": rule["name"],
                            "rule_description": rule["description"],
                            "severity": rule.get("severity", "info"),
                            "ad_id": ad_data["ad_id"],
                            "ad_name": ad_data.get("ad_name", ""),
                            "campaign_id": ad_data.get("campaign_id", ""),
                            "metrics": {
                                "frequency": ad_data.get("frequency", 0),
                                "cpa": ad_data.get("cpa", 0),
                                "roas": ad_data.get("roas", 0),
                                "hook_rate": ad_data.get("hook_rate", 0),
                            },
                        }
                        results.append(result)
                        self._log_execution(
                            rule_name=rule["name"],
                            rule_type="alert",
                            entity_id=ad_data["ad_id"],
                            entity_type="ad",
                            action_taken="alert",
                            details=json.dumps(result["metrics"]),
                        )
                except (KeyError, TypeError, ZeroDivisionError) as exc:
                    logger.warning(
                        "Alert rule '%s' error on ad %s: %s",
                        rule["name"], ad_data.get("ad_id", "?"), exc,
                    )
        return results

    def execute_kills(self, dry_run: bool = True) -> List[Dict[str, Any]]:
        """
        Evaluate kill rules and optionally pause the matched ads.

        Args:
            dry_run: If True (default), only report what would be paused.
                     If False, actually update ad status to PAUSED in the DB.

        Returns:
            List of action dicts, each with a "executed" boolean field.
        """
        kills = self.evaluate_kills()

        for kill in kills:
            if dry_run:
                kill["executed"] = False
                kill["mode"] = "dry_run"
                logger.info(
                    "[DRY RUN] Would pause ad %s (rule: %s)",
                    kill["ad_id"], kill["rule_name"],
                )
            else:
                ad = db.get_ad(kill["ad_id"])
                if ad is not None:
                    ad.status = "PAUSED"
                    ad.updated_at = datetime.now(tz=timezone.utc).isoformat()
                    db.save_ad(ad)
                    kill["executed"] = True
                    kill["mode"] = "live"
                    logger.info(
                        "Paused ad %s (rule: %s)", kill["ad_id"], kill["rule_name"],
                    )
                else:
                    kill["executed"] = False
                    kill["mode"] = "error"
                    logger.error("Ad %s not found in DB -- cannot pause", kill["ad_id"])

        return kills

    def execute_scales(self, dry_run: bool = True) -> List[Dict[str, Any]]:
        """
        Evaluate scale rules and optionally apply budget changes.

        Args:
            dry_run: If True (default), only report what would change.
                     If False, actually update budgets in the DB.

        Returns:
            List of action dicts, each with a "executed" boolean field.
        """
        scales = self.evaluate_scales()

        for scale in scales:
            if dry_run:
                scale["executed"] = False
                scale["mode"] = "dry_run"
                logger.info(
                    "[DRY RUN] Would change budget for ad %s to %.2f (rule: %s)",
                    scale["ad_id"],
                    scale.get("suggested_daily_budget", 0),
                    scale["rule_name"],
                )
            else:
                ad = db.get_ad(scale["ad_id"])
                if ad is None:
                    scale["executed"] = False
                    scale["mode"] = "error"
                    continue

                # Apply budget change at the adset level
                adset = db.get_adset(ad.adset_id)
                if adset is not None and scale.get("suggested_daily_budget"):
                    adset.daily_budget = scale["suggested_daily_budget"]
                    adset.updated_at = datetime.now(tz=timezone.utc).isoformat()
                    db.save_adset(adset)
                    scale["executed"] = True
                    scale["mode"] = "live"
                    logger.info(
                        "Updated budget for adset %s to %.2f (rule: %s)",
                        adset.adset_id,
                        scale["suggested_daily_budget"],
                        scale["rule_name"],
                    )
                else:
                    scale["executed"] = False
                    scale["mode"] = "error"

        return scales

    # ------------------------------------------------------------------
    # Data enrichment
    # ------------------------------------------------------------------

    def _get_enriched_active_ads(self) -> List[Dict[str, Any]]:
        """Fetch all active ads and enrich them with computed fields."""
        active_ads = db.list_ads(status="ACTIVE")
        enriched: List[Dict[str, Any]] = []

        # Pre-compute account-level best CPA for scale campaign ads
        best_scale_cpa = self._get_best_scale_cpa()

        # Pre-compute account-level CPA week-over-week change
        account_cpa_wow = self._get_account_cpa_wow_pct()

        for ad in active_ads:
            summary = db.get_insights_summary(ad.ad_id, days=7)
            if summary is None:
                continue

            campaign = db.get_campaign(ad.campaign_id)
            adset = db.get_adset(ad.adset_id)

            ad_data: Dict[str, Any] = {
                "ad_id": ad.ad_id,
                "ad_name": ad.name,
                "adset_id": ad.adset_id,
                "campaign_id": ad.campaign_id,
                "campaign_type": campaign.campaign_type if campaign else "test",
                "daily_budget": adset.daily_budget if adset else 0.0,
                "spend": summary["spend"],
                "impressions": summary["impressions"],
                "clicks": summary["clicks"],
                "conversions": summary["conversions"],
                "conversions_7d": summary["conversions"],
                "revenue": summary["revenue"],
                "ctr": summary["avg_ctr"] * 100,  # as percentage
                "cpc": summary["avg_cpc"],
                "cpm": summary["avg_cpm"],
                "cpa": summary["avg_cpa"],
                "roas": summary["roas"],
                "frequency": self._get_latest_frequency(ad.ad_id),
                "hook_rate": summary["hook_rate"] * 100,  # as percentage
                "hold_rate": summary["hold_rate"] * 100,  # as percentage
                "best_scale_cpa": best_scale_cpa,
                "account_cpa_wow_pct": account_cpa_wow,
            }

            # Enrich with computed fields needed by rules
            ad_data = self._enrich_ad_data(ad_data)
            enriched.append(ad_data)

        logger.debug("Enriched %d active ads for rule evaluation", len(enriched))
        return enriched

    def _enrich_ad_data(self, ad_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add computed fields required by the rule conditions:
        - ctr_vs_7d_avg_pct: percentage change of today's CTR vs 7-day avg
        - days_above_target_cpa: consecutive recent days with CPA > 2x target
        - consecutive_days_above_target: consecutive days ROAS > target * 1.2
        - is_learning_phase_complete: whether the ad has exited learning phase
        - just_exited_learning: whether the ad just left learning in the last 24h
        - hook_rate_5d_trend_pct: hook rate change over the last 5 days
        - spend_vs_daily_budget_pct: how much spend exceeds daily budget
        - cpa_vs_best_pct: how CPA compares to the current best performer
        """
        ad_id = ad_data["ad_id"]

        # --- CTR vs 7-day average ---
        ctr_trend = db.get_ad_trend(ad_id, "ctr", days=7)
        if len(ctr_trend) >= 2:
            values = [d["value"] for d in ctr_trend if d["value"] is not None]
            if values:
                avg_ctr = sum(values) / len(values)
                latest_ctr = values[-1]
                if avg_ctr > 0:
                    ad_data["ctr_vs_7d_avg_pct"] = round(
                        ((latest_ctr - avg_ctr) / avg_ctr) * 100, 2
                    )
                else:
                    ad_data["ctr_vs_7d_avg_pct"] = 0.0
            else:
                ad_data["ctr_vs_7d_avg_pct"] = 0.0
        else:
            ad_data["ctr_vs_7d_avg_pct"] = 0.0

        # --- Days with CPA above 2x target (consecutive, most recent) ---
        cpa_trend = db.get_ad_trend(ad_id, "cpa", days=14)
        consecutive_above = 0
        for point in reversed(cpa_trend):
            val = point.get("value")
            if val is not None and val > TARGET_CPA * 2:
                consecutive_above += 1
            else:
                break
        ad_data["days_above_target_cpa"] = consecutive_above

        # --- Consecutive days ROAS above target * 1.2 (for scale rule) ---
        roas_trend = db.get_ad_trend(ad_id, "roas", days=14)
        consecutive_above_roas = 0
        for point in reversed(roas_trend):
            val = point.get("value")
            if val is not None and val > TARGET_ROAS * 1.2:
                consecutive_above_roas += 1
            else:
                break
        ad_data["consecutive_days_above_target"] = consecutive_above_roas

        # --- Learning phase detection ---
        ad_obj = db.get_ad(ad_id)
        if ad_obj:
            created = datetime.fromisoformat(ad_obj.created_at.replace("Z", "+00:00"))
            now = datetime.now(tz=timezone.utc)
            hours_since_creation = (now - created).total_seconds() / 3600
            ad_data["is_learning_phase_complete"] = (
                hours_since_creation > LEARNING_PHASE_BUFFER_HOURS
            )
            # Just exited = was in learning 24h ago, now out
            ad_data["just_exited_learning"] = (
                LEARNING_PHASE_BUFFER_HOURS
                < hours_since_creation
                <= LEARNING_PHASE_BUFFER_HOURS + 24
            )
        else:
            ad_data["is_learning_phase_complete"] = True
            ad_data["just_exited_learning"] = False

        # --- Hook rate 5-day trend ---
        hook_trend = db.get_ad_trend(ad_id, "hook_rate", days=5)
        if len(hook_trend) >= 2:
            hook_values = [d["value"] for d in hook_trend if d["value"] is not None]
            if len(hook_values) >= 2 and hook_values[0] > 0:
                ad_data["hook_rate_5d_trend_pct"] = round(
                    ((hook_values[-1] - hook_values[0]) / hook_values[0]) * 100, 2
                )
            else:
                ad_data["hook_rate_5d_trend_pct"] = 0.0
        else:
            ad_data["hook_rate_5d_trend_pct"] = 0.0

        # --- Spend vs daily budget ---
        daily_budget = ad_data.get("daily_budget", 0)
        if daily_budget > 0:
            # Use the most recent day's spend
            recent = db.get_insights(ad_id=ad_id)
            if recent:
                latest_spend = recent[0].spend
                ad_data["spend_vs_daily_budget_pct"] = round(
                    ((latest_spend - daily_budget) / daily_budget) * 100, 2
                )
            else:
                ad_data["spend_vs_daily_budget_pct"] = 0.0
        else:
            ad_data["spend_vs_daily_budget_pct"] = 0.0

        # --- CPA vs best performer ---
        best_cpa = ad_data.get("best_scale_cpa", TARGET_CPA)
        if best_cpa > 0 and ad_data.get("cpa", 0) > 0:
            ad_data["cpa_vs_best_pct"] = round(
                ((ad_data["cpa"] - best_cpa) / best_cpa) * 100, 2
            )
        else:
            ad_data["cpa_vs_best_pct"] = 0.0

        return ad_data

    # ------------------------------------------------------------------
    # Cooldown management
    # ------------------------------------------------------------------

    def _check_cooldown(
        self, entity_id: str, action: str, cooldown_hours: int
    ) -> bool:
        """
        Check whether an action is still in cooldown for an entity.

        Looks at the rule_executions table for the most recent matching
        execution and returns True if the cooldown period has not elapsed.
        """
        if cooldown_hours <= 0:
            return False

        cache_key = f"{entity_id}:{action}"
        if cache_key in self._cooldown_cache:
            last_exec = self._cooldown_cache[cache_key]
            if datetime.now(tz=timezone.utc) - last_exec < timedelta(hours=cooldown_hours):
                return True

        # Check the database
        recent_executions = db.get_rule_executions(
            days=max(1, cooldown_hours // 24 + 1),
            rule_type=action,
            entity_id=entity_id,
        )

        if recent_executions:
            last_time_str = recent_executions[0].executed_at
            try:
                last_time = datetime.fromisoformat(
                    last_time_str.replace("Z", "+00:00")
                )
            except ValueError:
                return False

            self._cooldown_cache[cache_key] = last_time
            if datetime.now(tz=timezone.utc) - last_time < timedelta(hours=cooldown_hours):
                return True

        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log_execution(
        self,
        rule_name: str,
        rule_type: str,
        entity_id: str,
        entity_type: str,
        action_taken: str,
        details: str = "",
    ) -> None:
        """Persist a rule execution record to the database."""
        execution = RuleExecution(
            rule_name=rule_name,
            rule_type=rule_type,
            entity_id=entity_id,
            entity_type=entity_type,
            action_taken=action_taken,
            details=details,
        )
        try:
            db.save_rule_execution(execution)
        except Exception as exc:
            logger.error("Failed to save rule execution: %s", exc)

    def _get_best_scale_cpa(self) -> float:
        """
        Return the best (lowest) CPA among active ads in 'scale' campaigns.
        Falls back to TARGET_CPA if no scale campaigns have data.
        """
        scale_campaigns = db.list_campaigns(status="ACTIVE", campaign_type="scale")
        best_cpa = TARGET_CPA

        for campaign in scale_campaigns:
            ads = db.list_ads(campaign_id=campaign.campaign_id, status="ACTIVE")
            for ad in ads:
                summary = db.get_insights_summary(ad.ad_id, days=7)
                if summary and summary["avg_cpa"] > 0:
                    best_cpa = min(best_cpa, summary["avg_cpa"])

        return best_cpa

    def _get_account_cpa_wow_pct(self) -> float:
        """
        Calculate account-level CPA change week-over-week.

        Returns percentage change (positive = CPA increasing = bad).
        """
        this_week = db.get_account_summary(days=7)
        last_week_summary = db.get_account_summary(days=14)

        this_cpa = this_week.get("avg_cpa", 0)

        # Derive last week's CPA by subtracting this week from the 14-day window
        total_14d_spend = last_week_summary.get("spend", 0)
        total_14d_conv = last_week_summary.get("conversions", 0)
        this_week_spend = this_week.get("spend", 0)
        this_week_conv = this_week.get("conversions", 0)

        last_week_spend = total_14d_spend - this_week_spend
        last_week_conv = total_14d_conv - this_week_conv

        if last_week_conv > 0:
            last_cpa = last_week_spend / last_week_conv
        else:
            return 0.0

        if last_cpa > 0:
            return round(((this_cpa - last_cpa) / last_cpa) * 100, 2)
        return 0.0

    def _get_latest_frequency(self, ad_id: str) -> float:
        """Return the most recent frequency value for an ad."""
        recent = db.get_insights(ad_id=ad_id)
        if recent:
            return recent[0].frequency
        return 0.0

    def _calculate_budget_change(
        self, ad_data: Dict[str, Any], action: str
    ) -> float:
        """
        Calculate the new daily budget for a scale action.

        Respects MAX_BUDGET_INCREASE_PCT from rules config.
        """
        current_budget = ad_data.get("daily_budget", 0)

        if action == "increase_budget_20pct":
            increase_pct = min(20, MAX_BUDGET_INCREASE_PCT) / 100
            return round(current_budget * (1 + increase_pct), 2)
        elif action == "graduate_to_scale":
            # When graduating from test, suggest a sensible starting budget
            # based on current spend with a 50% bump
            return round(current_budget * 1.5, 2) if current_budget > 0 else 0.0
        else:
            # Default: 20% increase capped by config
            increase_pct = MAX_BUDGET_INCREASE_PCT / 100
            return round(current_budget * (1 + increase_pct), 2)
