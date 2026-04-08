"""
Angle miner for Meta Ads creative module.

Turns community data (questions, objections, success stories, trending topics)
into actionable ad angles. Each angle maps to a CommunityAngle dataclass
for database persistence and later performance tracking.
"""

import logging
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config.hormozi import COPY_RULES, HOOK_CATEGORIES, VALUE_EQUATION
from data import db
from data.models import CommunityAngle

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(tz=timezone.utc).isoformat()


def _pick_hook_category(source_type: str) -> str:
    """Pick the most natural hook category for a given source type."""
    mapping = {
        "question": ["question", "curiosity", "contrarian"],
        "objection": ["objection", "contrarian", "shock_stat"],
        "success_story": ["proof", "transformation", "callout"],
        "trending": ["curiosity", "shock_stat", "callout"],
    }
    options = mapping.get(source_type, list(HOOK_CATEGORIES.keys()))
    return random.choice(options)


def _generate_hook_for_text(text: str, category: str) -> str:
    """Generate a suggested hook from source text and a hook category."""
    cat_data = HOOK_CATEGORIES.get(category)
    if cat_data is None:
        return text[:80]

    template = cat_data["template"]
    words = text.strip().split()
    short = " ".join(words[:6]) if len(words) > 6 else text.strip()
    very_short = " ".join(words[:3]) if len(words) > 3 else text.strip()

    # Best-effort placeholder fill
    result = template
    replacements = {
        "pain_point": short,
        "objection": short,
        "myth": short,
        "percentage": str(random.choice([73, 82, 87, 91, 94])),
        "audience": very_short,
        "topic": short,
        "specific_persona": very_short,
        "name": "someone just like you",
        "before": "struggling",
        "after": short,
        "timeframe": "30 days",
        "common_advice": short,
        "niche": very_short,
        "bad_advice": short,
        "popular_thing": short,
        "outcome": short,
        "authority": "the gurus",
        "number": str(random.choice([100, 500, 1000])),
        "things": "cases",
        "surprising_fact": short,
        "doing_thing_wrong": short,
        "persona": very_short,
        "specific_behavior": short,
        "result": short,
        "achieved_thing": short,
        "before_state": "stuck",
        "after_state": short,
        "thing": short,
        "problem": short,
    }
    for key, val in replacements.items():
        result = result.replace(f"{{{key}}}", val)
    return result


def _generate_angle_text(source_text: str, source_type: str) -> str:
    """Generate a suggested angle description from source material."""
    templates = {
        "question": [
            f"Address the question: {source_text[:60]}",
            f"Answer this directly and show proof: {source_text[:60]}",
            f"Flip this question into a bold claim: {source_text[:60]}",
        ],
        "objection": [
            f"Break down this objection with proof: {source_text[:60]}",
            f"Agree then redirect: {source_text[:60]}",
            f"Show results that destroy this myth: {source_text[:60]}",
        ],
        "success_story": [
            f"Feature this transformation as social proof: {source_text[:60]}",
            f"Use this story as the hook and proof: {source_text[:60]}",
            f"Build a before/after ad around: {source_text[:60]}",
        ],
        "trending": [
            f"Ride this trend with a hot take: {source_text[:60]}",
            f"Use trending discussion as pattern interrupt: {source_text[:60]}",
            f"Connect this topic to our offer: {source_text[:60]}",
        ],
    }
    options = templates.get(source_type, templates["question"])
    return random.choice(options)


def _score_angle(
    source_text: str,
    source_type: str,
    *,
    engagement: float = 0.0,
    recency_days: int = 7,
) -> float:
    """Estimate an angle's potential on a 0-100 scale.

    Factors: emotional weight, novelty (proxy: shorter text is usually
    more focused), relevance to value equation, and source type weighting.
    """
    score = 50.0  # baseline

    # Source type bonus
    type_bonus = {
        "success_story": 15,
        "objection": 12,
        "question": 10,
        "trending": 8,
    }
    score += type_bonus.get(source_type, 5)

    # Emotional words boost
    emotional_words = [
        "struggle", "frustrated", "amazing", "changed", "finally",
        "never", "always", "hate", "love", "scared", "excited",
        "impossible", "broke", "dream", "fail", "worst", "best",
    ]
    text_lower = source_text.lower()
    emotion_count = sum(1 for w in emotional_words if w in text_lower)
    score += min(emotion_count * 3, 15)

    # Power words boost
    power_words = COPY_RULES.get("power_words", [])
    power_count = sum(1 for w in power_words if w.lower() in text_lower)
    score += min(power_count * 2, 10)

    # Specificity bonus (numbers in source text)
    import re
    numbers = re.findall(r"\d+", source_text)
    if numbers:
        score += 5

    # Engagement proxy
    if engagement > 0:
        score += min(engagement * 2, 10)

    # Recency bonus (more recent = better)
    if recency_days <= 3:
        score += 5
    elif recency_days <= 7:
        score += 3

    return min(100.0, max(0.0, round(score, 1)))


# ---------------------------------------------------------------------------
# AngleMiner
# ---------------------------------------------------------------------------


class AngleMiner:
    """
    Turn community data into actionable ad angles.

    All mining is deterministic / template-based by default.
    Pass ``use_ai=True`` to key methods for Claude-powered angle
    extraction.
    """

    # ------------------------------------------------------------------
    # Core mining methods
    # ------------------------------------------------------------------

    def mine_angles_from_pulse(
        self,
        community_pulse: Dict[str, Any],
        *,
        use_ai: bool = False,
    ) -> List[Dict[str, Any]]:
        """Extract ad angles from a community pulse report.

        A *community_pulse* typically has keys like ``top_questions``,
        ``top_objections``, ``success_stories``, ``trending_topics``.

        Args:
            community_pulse: The pulse report dict.
            use_ai: Use the Anthropic API for extraction.

        Returns:
            List of angle dicts with keys: ``source_type``,
            ``source_text``, ``suggested_hook``, ``suggested_angle``,
            ``hook_category``, ``score``.
        """
        if use_ai:
            return self._mine_angles_ai(community_pulse)

        angles: List[Dict[str, Any]] = []

        questions = community_pulse.get("top_questions", [])
        angles.extend(self.mine_angles_from_questions(questions))

        objections = community_pulse.get("top_objections", [])
        angles.extend(self.mine_angles_from_objections(objections))

        stories = community_pulse.get("success_stories", [])
        angles.extend(self.mine_angles_from_success_stories(stories))

        trending = community_pulse.get("trending_topics", [])
        angles.extend(self.mine_angles_from_trending(trending))

        return self.rank_angles(angles)

    def mine_angles_from_questions(
        self, questions: List[str]
    ) -> List[Dict[str, Any]]:
        """Convert community questions into ad angles.

        Args:
            questions: List of question strings from the community.

        Returns:
            List of angle dicts.
        """
        angles: List[Dict[str, Any]] = []
        for q in questions:
            if not q or not q.strip():
                continue
            category = _pick_hook_category("question")
            angles.append({
                "source_type": "question",
                "source_text": q.strip(),
                "suggested_hook": _generate_hook_for_text(q, category),
                "suggested_angle": _generate_angle_text(q, "question"),
                "hook_category": category,
                "score": _score_angle(q, "question"),
            })
        return angles

    def mine_angles_from_objections(
        self, objections: List[str]
    ) -> List[Dict[str, Any]]:
        """Convert community objections into ad angles.

        Args:
            objections: List of objection strings from the community.

        Returns:
            List of angle dicts.
        """
        angles: List[Dict[str, Any]] = []
        for obj in objections:
            if not obj or not obj.strip():
                continue
            category = _pick_hook_category("objection")
            angles.append({
                "source_type": "objection",
                "source_text": obj.strip(),
                "suggested_hook": _generate_hook_for_text(obj, category),
                "suggested_angle": _generate_angle_text(obj, "objection"),
                "hook_category": category,
                "score": _score_angle(obj, "objection"),
            })
        return angles

    def mine_angles_from_success_stories(
        self, stories: List[str]
    ) -> List[Dict[str, Any]]:
        """Convert success stories into ad angles.

        Args:
            stories: List of success story strings.

        Returns:
            List of angle dicts.
        """
        angles: List[Dict[str, Any]] = []
        for story in stories:
            if not story or not story.strip():
                continue
            category = _pick_hook_category("success_story")
            angles.append({
                "source_type": "success_story",
                "source_text": story.strip(),
                "suggested_hook": _generate_hook_for_text(story, category),
                "suggested_angle": _generate_angle_text(story, "success_story"),
                "hook_category": category,
                "score": _score_angle(story, "success_story"),
            })
        return angles

    def mine_angles_from_trending(
        self, trending_topics: List[str]
    ) -> List[Dict[str, Any]]:
        """Convert trending community discussions into ad angles.

        Args:
            trending_topics: List of trending topic strings.

        Returns:
            List of angle dicts.
        """
        angles: List[Dict[str, Any]] = []
        for topic in trending_topics:
            if not topic or not topic.strip():
                continue
            category = _pick_hook_category("trending")
            angles.append({
                "source_type": "trending",
                "source_text": topic.strip(),
                "suggested_hook": _generate_hook_for_text(topic, category),
                "suggested_angle": _generate_angle_text(topic, "trending"),
                "hook_category": category,
                "score": _score_angle(topic, "trending"),
            })
        return angles

    # ------------------------------------------------------------------
    # Ranking and conversion
    # ------------------------------------------------------------------

    def rank_angles(
        self, angles: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Rank angles by estimated potential (score descending).

        Args:
            angles: List of angle dicts (must contain a ``score`` key).

        Returns:
            The same list, sorted by score descending.
        """
        return sorted(angles, key=lambda a: a.get("score", 0), reverse=True)

    def angle_to_community_angle(
        self, angle: Dict[str, Any]
    ) -> CommunityAngle:
        """Convert an angle dict to a CommunityAngle dataclass for DB storage.

        Args:
            angle: Dict with keys ``source_type``, ``source_text``,
                   ``suggested_hook``, ``suggested_angle``, ``hook_category``.

        Returns:
            A CommunityAngle instance ready for ``db.save_community_angle()``.
        """
        return CommunityAngle(
            source_type=angle.get("source_type", ""),
            source_text=angle.get("source_text", ""),
            suggested_hook=angle.get("suggested_hook", ""),
            suggested_angle=angle.get("suggested_angle", ""),
            hook_category=angle.get("hook_category", ""),
            status="new",
        )

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    def get_unused_angles(self, count: int = 10) -> List[CommunityAngle]:
        """Pull angles from DB that haven't been used in ads yet.

        Args:
            count: Maximum number of angles to return.

        Returns:
            List of CommunityAngle instances with status ``new``.
        """
        return db.get_community_angles(status="new", limit=count)

    def mark_angle_used(self, angle_id: int, ad_id: str) -> None:
        """Mark an angle as used when it goes into an ad.

        Args:
            angle_id: Database row ID of the community angle.
            ad_id: The ad that this angle was used in.
        """
        db.update_community_angle_status(angle_id, "used", ad_id=ad_id)
        logger.info("Marked angle %d as used in ad %s", angle_id, ad_id)

    def get_angle_performance(self) -> List[Dict[str, Any]]:
        """Show which community-sourced angles performed best.

        Joins community_angles (status = 'used') with their ad insights
        to build a performance ranking.

        Returns:
            List of dicts with angle metadata and aggregated ad metrics,
            sorted by ROAS descending.
        """
        used_angles = db.get_community_angles(status="used", limit=500)
        results: List[Dict[str, Any]] = []

        for angle in used_angles:
            if not angle.used_in_ad_id:
                continue
            summary = db.get_insights_summary(angle.used_in_ad_id, days=30)
            if summary is None:
                continue

            results.append({
                "angle_id": angle.id,
                "source_type": angle.source_type,
                "source_text": angle.source_text[:80],
                "suggested_hook": angle.suggested_hook[:80],
                "hook_category": angle.hook_category,
                "ad_id": angle.used_in_ad_id,
                "spend": summary.get("spend", 0),
                "conversions": summary.get("conversions", 0),
                "roas": summary.get("roas", 0),
                "cpa": summary.get("avg_cpa", 0),
                "hook_rate": summary.get("hook_rate", 0),
                "ctr": summary.get("avg_ctr", 0),
            })

        results.sort(key=lambda r: r.get("roas", 0), reverse=True)
        return results

    # ------------------------------------------------------------------
    # AI-powered mining (optional)
    # ------------------------------------------------------------------

    def _mine_angles_ai(
        self, community_pulse: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Use Claude to extract high-quality angles from a pulse report."""
        try:
            import anthropic
            from config.settings import ANTHROPIC_API_KEY
        except ImportError:
            logger.warning("anthropic package not installed — falling back to templates")
            return self.mine_angles_from_pulse(community_pulse)

        if not ANTHROPIC_API_KEY:
            logger.warning("ANTHROPIC_API_KEY not set — falling back to templates")
            return self.mine_angles_from_pulse(community_pulse)

        categories_desc = ", ".join(HOOK_CATEGORIES.keys())
        value_eq_desc = "\n".join(
            f"- {k}: {v['description']}" for k, v in VALUE_EQUATION.items()
        )

        system_prompt = (
            "You are an expert direct-response ad strategist trained on Alex Hormozi's "
            "frameworks. Your job is to turn community data into ad angles.\n\n"
            f"Hook categories: {categories_desc}\n\n"
            f"Value equation:\n{value_eq_desc}"
        )

        import json
        pulse_text = json.dumps(community_pulse, indent=2, default=str)

        user_prompt = (
            f"Analyze this community pulse report and extract ad angles:\n\n"
            f"{pulse_text}\n\n"
            f"For each angle, provide:\n"
            f"- source_type: question, objection, success_story, or trending\n"
            f"- source_text: the original community text\n"
            f"- suggested_hook: a scroll-stopping hook\n"
            f"- suggested_angle: how to position the ad\n"
            f"- hook_category: one of {categories_desc}\n"
            f"- score: estimated potential 0-100\n\n"
            f"Return ONLY a JSON array of objects."
        )

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            block = response.content[0]
            text = block.text if hasattr(block, "text") else str(block)
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                angles = json.loads(text[start:end])
                return self.rank_angles(angles)
            logger.warning("Could not parse AI angle response")
        except Exception:
            logger.exception("AI angle mining failed — falling back to templates")

        return self.mine_angles_from_pulse(community_pulse)
