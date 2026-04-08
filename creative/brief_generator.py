"""
Brief generator for Meta Ads creative module.

Auto-generates creative briefs combining performance data, community
intelligence, and Hormozi frameworks. Works template-based by default
and optionally uses the Anthropic API for richer output.
"""

import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config.hormozi import (
    AD_STRUCTURE,
    COPY_RULES,
    HOOK_CATEGORIES,
    VALUE_EQUATION,
    VOLUME_TARGETS,
)
from data import db
from data.models import CommunityAngle

from creative.angle_miner import AngleMiner
from creative.copy_generator import CopyGenerator
from creative.hook_generator import HookGenerator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(tz=timezone.utc).isoformat()


def _brief_id() -> str:
    """Generate a unique brief identifier."""
    return f"brief_{uuid.uuid4().hex[:12]}"


_FORMAT_OPTIONS = [
    {"format": "ugc", "description": "User-generated content style. Raw, authentic, phone-recorded."},
    {"format": "talking_head", "description": "Person speaking directly to camera. Personal and direct."},
    {"format": "static_image", "description": "Single image with text overlay. Fast to produce."},
    {"format": "carousel", "description": "Multi-image swipe. Good for step-by-step or before/after."},
    {"format": "b-roll_voiceover", "description": "Footage with voiceover narration. Polished but still real."},
    {"format": "screenshot_proof", "description": "Screenshot or screen recording showing real results."},
]


# ---------------------------------------------------------------------------
# BriefGenerator
# ---------------------------------------------------------------------------


class BriefGenerator:
    """
    Auto-generate creative briefs combining performance data, community
    intelligence, and Hormozi frameworks.

    Each brief follows the Proof-Promise-Plan ad structure, includes
    value-equation targeting, community source attribution, format
    recommendations, and 10 hook variations to record.
    """

    def __init__(self) -> None:
        self._hook_gen = HookGenerator()
        self._copy_gen = CopyGenerator()
        self._angle_miner = AngleMiner()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_brief(
        self,
        performance_data: Optional[Dict[str, Any]] = None,
        community_pulse: Optional[Dict[str, Any]] = None,
        *,
        use_ai: bool = False,
    ) -> Dict[str, Any]:
        """Create a full Hormozi-style creative brief.

        Args:
            performance_data: Optional dict with top-performing ad metrics
                (e.g. from ``db.get_insights_summary``). Used to inform
                the brief with what's already working.
            community_pulse: Optional community pulse report dict with
                keys like ``top_questions``, ``top_objections``,
                ``success_stories``, ``trending_topics``.
            use_ai: Use the Anthropic API for richer brief generation.

        Returns:
            A brief dict with keys: ``id``, ``created_at``, ``source``,
            ``status``, ``value_equation``, ``community_source``,
            ``ad_structure``, ``format_recommendation``, ``text_guidelines``,
            ``hooks``, ``reference_ads``, ``angle``, ``body_draft``,
            ``headline_draft``, ``cta_draft``.
        """
        if use_ai:
            return self._generate_brief_ai(performance_data, community_pulse)

        # Derive angle from community data or fallback
        angle_text, community_source = self._pick_angle(community_pulse)

        # Value equation targeting
        value_eq = self._build_value_equation(angle_text)

        # Ad structure with section-level guidance
        ad_struct = self._build_ad_structure(angle_text)

        # Format recommendation
        fmt = self._recommend_format(performance_data)

        # Generate hooks
        hooks = self._hook_gen.generate_hooks(
            angle_text,
            count=VOLUME_TARGETS.get("hooks_per_body", 10),
        )

        # Draft copy pieces
        body_draft = self._copy_gen.generate_body_text(angle_text, max_words=50)
        headline_draft = self._copy_gen.generate_headline(angle_text)
        cta_draft = self._copy_gen.generate_cta_text()

        # Reference ads (top performers)
        reference_ads = self._get_reference_ads(performance_data)

        brief: Dict[str, Any] = {
            "id": _brief_id(),
            "created_at": _now_iso(),
            "source": "community" if community_pulse else "performance",
            "status": "draft",
            "angle": angle_text,
            "value_equation": value_eq,
            "community_source": community_source,
            "ad_structure": ad_struct,
            "format_recommendation": fmt,
            "text_guidelines": {
                "reading_level": COPY_RULES["reading_level"],
                "max_words_per_sentence": COPY_RULES["max_words_per_sentence"],
                "tone": COPY_RULES["tone"],
                "forbidden_words": COPY_RULES["forbidden_words"],
                "power_words": COPY_RULES["power_words"],
                "cta_rules": COPY_RULES["cta_rules"],
            },
            "hooks": hooks,
            "reference_ads": reference_ads,
            "body_draft": body_draft,
            "headline_draft": headline_draft,
            "cta_draft": cta_draft,
        }

        logger.info("Generated brief %s (angle: %s)", brief["id"], angle_text[:50])
        return brief

    def generate_batch(
        self,
        count: int = 5,
        community_pulse: Optional[Dict[str, Any]] = None,
        *,
        use_ai: bool = False,
    ) -> List[Dict[str, Any]]:
        """Generate multiple briefs at once.

        Args:
            count: Number of briefs to generate.
            community_pulse: Optional community pulse for sourcing angles.
            use_ai: Use the Anthropic API for richer output.

        Returns:
            List of brief dicts.
        """
        briefs: List[Dict[str, Any]] = []
        for _ in range(count):
            brief = self.generate_brief(
                community_pulse=community_pulse, use_ai=use_ai
            )
            briefs.append(brief)
        logger.info("Generated batch of %d briefs", len(briefs))
        return briefs

    def brief_from_winner(
        self,
        ad_id: str,
        *,
        use_ai: bool = False,
    ) -> Dict[str, Any]:
        """Create a variation brief based on a winning ad.

        Pulls the winning ad's creative tags and performance data,
        then generates a new brief that iterates on what worked.

        Args:
            ad_id: The ID of the winning ad.
            use_ai: Use the Anthropic API for richer output.

        Returns:
            A brief dict with the winner as the reference ad.
        """
        # Get the winning ad's metadata
        tags = db.get_creative_tags(ad_id=ad_id)
        summary = db.get_insights_summary(ad_id, days=14)

        performance_data: Dict[str, Any] = {}
        if summary:
            performance_data = summary

        # Build angle from the winning ad's creative
        angle_text = "Variation of winning ad"
        if tags:
            tag = tags[0]
            if tag.angle:
                angle_text = tag.angle
            elif tag.body_text:
                angle_text = tag.body_text[:80]

        # Generate the brief with performance context
        brief = self.generate_brief(
            performance_data=performance_data, use_ai=use_ai
        )
        brief["source"] = "winner_variation"
        brief["angle"] = f"[ITERATE] {angle_text}"
        brief["reference_ads"] = [{
            "ad_id": ad_id,
            "metrics": performance_data,
            "note": "This is the winning ad to iterate on.",
        }]

        # Regenerate hooks specifically for this angle
        brief["hooks"] = self._hook_gen.generate_hooks(
            angle_text,
            count=VOLUME_TARGETS.get("hooks_per_body", 10),
        )

        logger.info(
            "Generated winner-variation brief %s from ad %s", brief["id"], ad_id
        )
        return brief

    def brief_from_community_angle(
        self,
        angle: CommunityAngle,
        *,
        use_ai: bool = False,
    ) -> Dict[str, Any]:
        """Create a brief from a CommunityAngle dataclass.

        Args:
            angle: A CommunityAngle instance (from DB or angle_miner).
            use_ai: Use the Anthropic API for richer output.

        Returns:
            A brief dict sourced from the community angle.
        """
        # Build a mini pulse from the single angle
        angle_text = angle.suggested_angle or angle.source_text

        brief = self.generate_brief(use_ai=use_ai)
        brief["source"] = "community_angle"
        brief["angle"] = angle_text
        brief["community_source"] = {
            "type": angle.source_type,
            "text": angle.source_text,
            "hook_category": angle.hook_category,
            "suggested_hook": angle.suggested_hook,
            "angle_id": angle.id,
        }

        # Generate hooks using source-type-aware methods
        if angle.source_type == "question":
            brief["hooks"] = self._hook_gen.generate_hooks_from_question(
                angle.source_text,
                count=VOLUME_TARGETS.get("hooks_per_body", 10),
            )
        elif angle.source_type == "objection":
            brief["hooks"] = self._hook_gen.generate_hooks_from_objection(
                angle.source_text,
                count=VOLUME_TARGETS.get("hooks_per_body", 10),
            )
        elif angle.source_type == "success_story":
            brief["hooks"] = self._hook_gen.generate_hooks_from_success(
                angle.source_text,
                count=VOLUME_TARGETS.get("hooks_per_body", 10),
            )
        else:
            brief["hooks"] = self._hook_gen.generate_hooks(
                angle.source_text,
                count=VOLUME_TARGETS.get("hooks_per_body", 10),
            )

        # Regenerate body draft for this angle
        brief["body_draft"] = self._copy_gen.generate_body_text(
            angle_text, max_words=50
        )
        brief["headline_draft"] = self._copy_gen.generate_headline(angle_text)

        logger.info(
            "Generated community-angle brief %s from angle %s",
            brief["id"],
            angle.id or "unsaved",
        )
        return brief

    def format_brief(self, brief_dict: Dict[str, Any]) -> str:
        """Render a brief dict as clean formatted text for human reading.

        Args:
            brief_dict: A brief dict as returned by ``generate_brief()``.

        Returns:
            Multi-line formatted string.
        """
        lines: List[str] = []
        lines.append("=" * 60)
        lines.append(f"CREATIVE BRIEF: {brief_dict.get('id', 'unknown')}")
        lines.append(f"Created: {brief_dict.get('created_at', '')}")
        lines.append(f"Source: {brief_dict.get('source', '')}")
        lines.append(f"Status: {brief_dict.get('status', '')}")
        lines.append("=" * 60)

        # Angle
        lines.append("")
        lines.append("ANGLE")
        lines.append("-" * 40)
        lines.append(brief_dict.get("angle", ""))

        # Value Equation
        ve = brief_dict.get("value_equation", {})
        if ve:
            lines.append("")
            lines.append("VALUE EQUATION TARGETING")
            lines.append("-" * 40)
            for key, val in ve.items():
                lines.append(f"  {key}: {val}")

        # Community Source
        cs = brief_dict.get("community_source", {})
        if cs and cs.get("text"):
            lines.append("")
            lines.append("COMMUNITY SOURCE")
            lines.append("-" * 40)
            lines.append(f"  Type: {cs.get('type', '')}")
            lines.append(f"  Text: {cs.get('text', '')}")
            if cs.get("hook_category"):
                lines.append(f"  Hook Category: {cs.get('hook_category', '')}")

        # Ad Structure
        ad_struct = brief_dict.get("ad_structure", {})
        if ad_struct:
            lines.append("")
            lines.append("AD STRUCTURE")
            lines.append("-" * 40)
            for section, details in ad_struct.items():
                if isinstance(details, dict):
                    timing = details.get("timing", "")
                    purpose = details.get("purpose", "")
                    guidance = details.get("guidance", "")
                    lines.append(f"  [{timing}] {section.upper()}")
                    lines.append(f"    Purpose: {purpose}")
                    if guidance:
                        lines.append(f"    Guidance: {guidance}")
                else:
                    lines.append(f"  {section}: {details}")

        # Format Recommendation
        fmt = brief_dict.get("format_recommendation", {})
        if fmt:
            lines.append("")
            lines.append("FORMAT RECOMMENDATION")
            lines.append("-" * 40)
            lines.append(f"  Format: {fmt.get('format', '')}")
            lines.append(f"  Why: {fmt.get('description', '')}")

        # Text Guidelines
        tg = brief_dict.get("text_guidelines", {})
        if tg:
            lines.append("")
            lines.append("TEXT GUIDELINES")
            lines.append("-" * 40)
            lines.append(f"  Reading Level: {tg.get('reading_level', '')}")
            lines.append(f"  Max Words/Sentence: {tg.get('max_words_per_sentence', '')}")
            lines.append(f"  Tone: {tg.get('tone', '')}")
            fw = tg.get("forbidden_words", [])
            if fw:
                lines.append(f"  Forbidden: {', '.join(fw)}")

        # Hooks
        hooks = brief_dict.get("hooks", [])
        if hooks:
            lines.append("")
            lines.append(f"HOOKS TO RECORD ({len(hooks)} variations)")
            lines.append("-" * 40)
            for i, h in enumerate(hooks, 1):
                hook_text = h.get("hook", "") if isinstance(h, dict) else str(h)
                category = h.get("category", "") if isinstance(h, dict) else ""
                lines.append(f"  {i:2d}. [{category}] {hook_text}")

        # Draft Copy
        lines.append("")
        lines.append("DRAFT COPY")
        lines.append("-" * 40)
        lines.append(f"  Headline: {brief_dict.get('headline_draft', '')}")
        lines.append(f"  Body: {brief_dict.get('body_draft', '')}")
        lines.append(f"  CTA: {brief_dict.get('cta_draft', '')}")

        # Reference Ads
        refs = brief_dict.get("reference_ads", [])
        if refs:
            lines.append("")
            lines.append("REFERENCE ADS (top performers to model)")
            lines.append("-" * 40)
            for ref in refs:
                ad_id = ref.get("ad_id", "unknown")
                note = ref.get("note", "")
                metrics = ref.get("metrics", {})
                lines.append(f"  Ad {ad_id}")
                if note:
                    lines.append(f"    Note: {note}")
                if metrics:
                    roas = metrics.get("roas", 0)
                    ctr = metrics.get("avg_ctr", 0)
                    hr = metrics.get("hook_rate", 0)
                    lines.append(f"    ROAS: {roas}  CTR: {ctr}  Hook Rate: {hr}")

        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _pick_angle(
        self, community_pulse: Optional[Dict[str, Any]]
    ) -> tuple:
        """Pick an angle from community data or generate a generic one.

        Returns:
            Tuple of (angle_text, community_source_dict).
        """
        community_source: Dict[str, Any] = {}

        if community_pulse:
            angles = self._angle_miner.mine_angles_from_pulse(community_pulse)
            if angles:
                top = angles[0]
                return (
                    top.get("suggested_angle", top.get("source_text", "")),
                    {
                        "type": top.get("source_type", ""),
                        "text": top.get("source_text", ""),
                        "hook_category": top.get("hook_category", ""),
                    },
                )

        # Try unused angles from DB
        unused = self._angle_miner.get_unused_angles(count=1)
        if unused:
            angle = unused[0]
            return (
                angle.suggested_angle or angle.source_text,
                {
                    "type": angle.source_type,
                    "text": angle.source_text,
                    "hook_category": angle.hook_category,
                    "angle_id": angle.id,
                },
            )

        # Fallback: generic angle
        generic_angles = [
            "Show the transformation. Before and after.",
            "Address the #1 objection directly.",
            "Lead with a bold, specific result.",
            "Tell a real customer story.",
            "Flip conventional wisdom on its head.",
        ]
        return random.choice(generic_angles), community_source

    def _build_value_equation(self, angle_text: str) -> Dict[str, str]:
        """Build value equation targeting for the brief."""
        return {
            "dream_outcome": f"Clearly state the result: relate to '{angle_text[:40]}'",
            "perceived_likelihood": "Include specific proof — testimonial, number, or screenshot",
            "time_delay": "Mention a realistic timeframe for results",
            "effort_sacrifice": "Emphasize how simple the next step is",
        }

    def _build_ad_structure(self, angle_text: str) -> Dict[str, Dict[str, str]]:
        """Build section-level ad structure guidance."""
        structure: Dict[str, Dict[str, str]] = {}
        for section, data in AD_STRUCTURE.items():
            start, end = data["duration_seconds"]
            structure[section] = {
                "timing": f"{start}-{end}s",
                "purpose": data["purpose"],
                "guidance": data["rules"][0] if data["rules"] else "",
            }
        return structure

    def _recommend_format(
        self, performance_data: Optional[Dict[str, Any]]
    ) -> Dict[str, str]:
        """Recommend an ad format based on performance data or random."""
        if performance_data and performance_data.get("hook_rate", 0) > 0.25:
            # Good hook rate suggests video works well — try UGC
            return _FORMAT_OPTIONS[0]
        if performance_data and performance_data.get("avg_ctr", 0) > 0.02:
            # High CTR suggests direct approach works
            return _FORMAT_OPTIONS[1]
        # Default: pick randomly
        return random.choice(_FORMAT_OPTIONS)

    def _get_reference_ads(
        self, performance_data: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Get top-performing ads as reference material."""
        refs: List[Dict[str, Any]] = []

        if performance_data and performance_data.get("ad_id"):
            refs.append({
                "ad_id": performance_data["ad_id"],
                "metrics": performance_data,
                "note": "Current top performer. Study what works.",
            })

        # Try to pull additional winners from the DB
        try:
            active_ads = db.list_campaigns(status="ACTIVE", campaign_type="scale")
            for camp in active_ads[:2]:
                # Look for ads in scaling campaigns — they're proven
                adsets = db.list_adsets(campaign_id=camp.campaign_id, status="ACTIVE")
                for adset in adsets[:1]:
                    from data.models import AdData
                    with db.get_connection() as conn:
                        rows = conn.execute(
                            "SELECT * FROM ads WHERE adset_id = ? AND status = 'ACTIVE' LIMIT 1",
                            (adset.adset_id,),
                        ).fetchall()
                    for row in rows:
                        ad = AdData.from_row(row)
                        summary = db.get_insights_summary(ad.ad_id, days=7)
                        if summary and summary.get("roas", 0) > 1.0:
                            refs.append({
                                "ad_id": ad.ad_id,
                                "metrics": summary,
                                "note": "Active winner in scale campaign.",
                            })
        except Exception:
            logger.debug("Could not fetch reference ads from DB", exc_info=True)

        return refs

    # ------------------------------------------------------------------
    # AI-powered brief generation (optional)
    # ------------------------------------------------------------------

    def _generate_brief_ai(
        self,
        performance_data: Optional[Dict[str, Any]],
        community_pulse: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Use Claude to generate a richer creative brief."""
        try:
            import anthropic
            from config.settings import ANTHROPIC_API_KEY
        except ImportError:
            logger.warning("anthropic package not installed — falling back to templates")
            return self.generate_brief(performance_data, community_pulse)

        if not ANTHROPIC_API_KEY:
            logger.warning("ANTHROPIC_API_KEY not set — falling back to templates")
            return self.generate_brief(performance_data, community_pulse)

        import json

        # Build context
        ve_desc = "\n".join(
            f"- {k}: {v['description']}" for k, v in VALUE_EQUATION.items()
        )
        struct_desc = "\n".join(
            f"- {s}: {d['purpose']} ({d['duration_seconds'][0]}-{d['duration_seconds'][1]}s)"
            for s, d in AD_STRUCTURE.items()
        )
        cats_desc = ", ".join(HOOK_CATEGORIES.keys())

        context_parts = [
            f"Value Equation:\n{ve_desc}",
            f"\nAd Structure:\n{struct_desc}",
            f"\nHook Categories: {cats_desc}",
        ]
        if performance_data:
            context_parts.append(
                f"\nPerformance Data:\n{json.dumps(performance_data, indent=2, default=str)}"
            )
        if community_pulse:
            context_parts.append(
                f"\nCommunity Pulse:\n{json.dumps(community_pulse, indent=2, default=str)}"
            )

        system_prompt = (
            "You are an expert Meta Ads creative director trained on Alex Hormozi's "
            "frameworks. You create detailed creative briefs that combine performance "
            "data with community intelligence. Write at a 3rd grade reading level.\n\n"
            f"Copy rules: {json.dumps(COPY_RULES, default=str)}"
        )

        user_prompt = (
            "Generate a complete creative brief with these sections:\n"
            "1. angle - the core message\n"
            "2. value_equation - targeting for each of the 4 levers\n"
            "3. community_source - which community insight inspired this\n"
            "4. ad_structure - guidance per section (hook, promise, proof, bridge, cta)\n"
            "5. format_recommendation - format and description\n"
            "6. hooks - exactly 10 hook variations as objects {hook, category, source}\n"
            "7. body_draft - primary text draft\n"
            "8. headline_draft - headline draft\n"
            "9. cta_draft - call to action draft\n\n"
            f"Context:\n{''.join(context_parts)}\n\n"
            "Return ONLY a JSON object with the keys above."
        )

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=3000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            block = response.content[0]
            text = block.text if hasattr(block, "text") else str(block)
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                brief = json.loads(text[start:end])
                # Ensure required metadata
                brief.setdefault("id", _brief_id())
                brief.setdefault("created_at", _now_iso())
                brief.setdefault("source", "ai_generated")
                brief.setdefault("status", "draft")
                brief.setdefault("text_guidelines", {
                    "reading_level": COPY_RULES["reading_level"],
                    "max_words_per_sentence": COPY_RULES["max_words_per_sentence"],
                    "tone": COPY_RULES["tone"],
                    "forbidden_words": COPY_RULES["forbidden_words"],
                    "power_words": COPY_RULES["power_words"],
                    "cta_rules": COPY_RULES["cta_rules"],
                })
                brief.setdefault("reference_ads", self._get_reference_ads(performance_data))
                logger.info("Generated AI brief %s", brief["id"])
                return brief
            logger.warning("Could not parse AI brief response")
        except Exception:
            logger.exception("AI brief generation failed — falling back to templates")

        return self.generate_brief(performance_data, community_pulse)
