"""
Hook generator for Meta Ads creative module.

Generates hook variations using Hormozi's hook categories. Works template-based
by default and optionally uses the Anthropic API for higher-quality output.
"""

import logging
import random
import re
from typing import Any, Dict, List, Optional

from config.hormozi import COPY_RULES, HOOK_CATEGORIES, VOLUME_TARGETS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_VARIABLE_RE = re.compile(r"\{(\w+)\}")


def _extract_variables(template: str) -> List[str]:
    """Return placeholder names found in a template string."""
    return _VARIABLE_RE.findall(template)


def _safe_fill(template: str, variables: Dict[str, str]) -> str:
    """Fill template placeholders with provided variables, leaving unknowns."""
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{key}}}", value)
    return result


def _pick_random_template(category: str) -> str:
    """Pick a random template (main or example) from a hook category."""
    cat = HOOK_CATEGORIES.get(category)
    if cat is None:
        return ""
    pool = [cat["template"]] + cat.get("examples", [])
    return random.choice(pool)


# ---------------------------------------------------------------------------
# HookGenerator
# ---------------------------------------------------------------------------


class HookGenerator:
    """
    Generate hook variations using Hormozi's hook categories.

    By default all generation is template-based. Pass ``use_ai=True`` to key
    methods to get Claude-powered output instead.
    """

    def __init__(self) -> None:
        self._categories = list(HOOK_CATEGORIES.keys())
        self._power_words: List[str] = COPY_RULES.get("power_words", [])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_hooks(
        self,
        topic: str,
        count: int = 10,
        *,
        use_ai: bool = False,
    ) -> List[Dict[str, Any]]:
        """Generate *count* hook variations for a given topic.

        Args:
            topic: The subject or pain point to write hooks about.
            count: Number of hooks to generate (default matches
                   ``VOLUME_TARGETS["hooks_per_body"]``).
            use_ai: When True, use the Anthropic API for generation.

        Returns:
            List of dicts with keys ``hook``, ``category``, ``source``.
        """
        if use_ai:
            return self._generate_hooks_ai(topic, count)

        hooks: List[Dict[str, Any]] = []
        cats = self._categories.copy()

        for i in range(count):
            category = cats[i % len(cats)]
            template = _pick_random_template(category)
            variables = self._infer_variables(template, topic)
            hook_text = _safe_fill(template, variables)
            hooks.append({
                "hook": hook_text,
                "category": category,
                "source": "template",
            })
        return hooks

    def generate_hooks_from_question(
        self,
        question_text: str,
        count: int = 10,
        *,
        use_ai: bool = False,
    ) -> List[Dict[str, Any]]:
        """Turn a community question into hook variations.

        The question is used as raw material. Hooks lean toward
        the *question*, *curiosity*, and *contrarian* categories.
        """
        if use_ai:
            return self._generate_hooks_ai(
                f"community question: {question_text}", count
            )

        preferred = ["question", "curiosity", "contrarian"]
        return self._generate_from_source(
            question_text, preferred, count, "community"
        )

    def generate_hooks_from_objection(
        self,
        objection_text: str,
        count: int = 10,
        *,
        use_ai: bool = False,
    ) -> List[Dict[str, Any]]:
        """Turn a community objection into hook variations.

        Hooks lean toward *objection*, *contrarian*, and *shock_stat*
        categories.
        """
        if use_ai:
            return self._generate_hooks_ai(
                f"common objection: {objection_text}", count
            )

        preferred = ["objection", "contrarian", "shock_stat"]
        return self._generate_from_source(
            objection_text, preferred, count, "community"
        )

    def generate_hooks_from_success(
        self,
        success_story: str,
        count: int = 10,
        *,
        use_ai: bool = False,
    ) -> List[Dict[str, Any]]:
        """Turn a success story into hook variations.

        Hooks lean toward *proof*, *transformation*, and *callout*
        categories.
        """
        if use_ai:
            return self._generate_hooks_ai(
                f"success story: {success_story}", count
            )

        preferred = ["proof", "transformation", "callout"]
        return self._generate_from_source(
            success_story, preferred, count, "community"
        )

    def generate_hooks_for_body(
        self,
        body_text: str,
        count: int = 10,
        *,
        use_ai: bool = False,
    ) -> List[Dict[str, Any]]:
        """Create hooks that lead naturally into a specific ad body.

        Extracts the core topic from the body and generates hooks
        across all categories that would serve as a natural opener.
        """
        if use_ai:
            return self._generate_hooks_ai(
                f"Write hooks that lead into this ad body:\n\n{body_text}",
                count,
            )

        topic = self._extract_topic_from_body(body_text)
        return self.generate_hooks(topic, count)

    def categorize_hook(self, hook_text: str) -> str:
        """Classify a hook into one of the HOOK_CATEGORIES.

        Uses simple keyword heuristics. Returns the best-matching
        category name.
        """
        text = hook_text.lower().strip()

        # Ordered checks — first match wins
        if text.endswith("?") or text.startswith(("are you", "do you", "want to", "what if")):
            return "question"
        if any(w in text for w in ("wrong", "myth", "lie", "stop believing", "truth")):
            return "objection"
        if any(w in text for w in ("%", "stat", "analyzed", "data", "number")):
            return "shock_stat"
        if any(w in text for w in ("hey ", "attention", "if you're a", "this is for")):
            return "callout"
        if any(w in text for w in ("went from", "achieved", "result", "before", "after")):
            return "proof"
        if any(w in text for w in ("stop doing", "instead", "worst advice", "actually hurting")):
            return "contrarian"
        if any(w in text for w in ("went from", "ago i was", "took me from", "transformation")):
            return "transformation"
        # Default fallback
        return "curiosity"

    def get_hook_templates(self, category: str) -> List[str]:
        """Return all available templates for a specific hook category.

        Args:
            category: One of the HOOK_CATEGORIES keys.

        Returns:
            List of template strings. Empty list if category unknown.
        """
        cat = HOOK_CATEGORIES.get(category)
        if cat is None:
            logger.warning("Unknown hook category: %s", category)
            return []
        return [cat["template"]] + cat.get("examples", [])

    def fill_template(self, template: str, variables: Dict[str, str]) -> str:
        """Fill a hook template with specific variables.

        Args:
            template: A string with ``{placeholder}`` markers.
            variables: Mapping of placeholder name to replacement text.

        Returns:
            The filled template string.
        """
        return _safe_fill(template, variables)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_from_source(
        self,
        source_text: str,
        preferred_categories: List[str],
        count: int,
        source_label: str,
    ) -> List[Dict[str, Any]]:
        """Generate hooks biased toward preferred categories."""
        hooks: List[Dict[str, Any]] = []
        # Build a weighted category pool — preferred categories appear 2x
        pool = preferred_categories * 2 + self._categories
        random.shuffle(pool)

        seen: set = set()
        attempts = 0
        while len(hooks) < count and attempts < count * 4:
            attempts += 1
            category = pool[attempts % len(pool)]
            template = _pick_random_template(category)
            variables = self._infer_variables(template, source_text)
            hook_text = _safe_fill(template, variables)
            if hook_text in seen:
                continue
            seen.add(hook_text)
            hooks.append({
                "hook": hook_text,
                "category": category,
                "source": source_label,
            })
        return hooks

    def _infer_variables(self, template: str, source: str) -> Dict[str, str]:
        """Build a best-effort variable mapping from a source string.

        For template-based mode we map generic placeholder names to
        sensible slices of the source text.
        """
        placeholders = _extract_variables(template)
        if not placeholders:
            return {}

        words = source.strip().split()
        short = " ".join(words[:6]) if len(words) > 6 else source.strip()
        very_short = " ".join(words[:3]) if len(words) > 3 else source.strip()

        mapping: Dict[str, str] = {}
        for ph in placeholders:
            ph_lower = ph.lower()
            if ph_lower in ("pain_point", "problem", "thing", "topic", "niche", "outcome"):
                mapping[ph] = short
            elif ph_lower in ("objection", "myth", "bad_advice", "common_advice"):
                mapping[ph] = short
            elif ph_lower in ("persona", "specific_persona", "audience"):
                mapping[ph] = very_short
            elif ph_lower in ("name",):
                mapping[ph] = "someone just like you"
            elif ph_lower in ("before", "before_state"):
                mapping[ph] = "struggling"
            elif ph_lower in ("after", "after_state", "result", "achieved_thing"):
                mapping[ph] = short
            elif ph_lower in ("timeframe",):
                mapping[ph] = "30 days"
            elif ph_lower in ("percentage",):
                mapping[ph] = str(random.choice([73, 82, 91, 87, 94]))
            elif ph_lower in ("number",):
                mapping[ph] = str(random.choice([100, 500, 1000, 2500]))
            elif ph_lower in ("surprising_fact",):
                mapping[ph] = short
            elif ph_lower in ("doing_thing_wrong",):
                mapping[ph] = short
            elif ph_lower in ("specific_behavior",):
                mapping[ph] = short
            elif ph_lower in ("authority",):
                mapping[ph] = "the gurus"
            elif ph_lower in ("popular_thing",):
                mapping[ph] = short
            elif ph_lower in ("things",):
                mapping[ph] = "cases"
            else:
                mapping[ph] = short
        return mapping

    def _extract_topic_from_body(self, body_text: str) -> str:
        """Pull the core topic from an ad body for hook generation."""
        sentences = re.split(r"[.!?]+", body_text)
        # Use the first meaningful sentence as the topic
        for s in sentences:
            stripped = s.strip()
            if len(stripped) > 10:
                return stripped
        return body_text[:80].strip()

    # ------------------------------------------------------------------
    # AI-powered generation (optional)
    # ------------------------------------------------------------------

    def _generate_hooks_ai(
        self, prompt_context: str, count: int
    ) -> List[Dict[str, Any]]:
        """Use the Anthropic API to generate high-quality hooks."""
        try:
            import anthropic
            from config.settings import ANTHROPIC_API_KEY
        except ImportError:
            logger.warning("anthropic package not installed — falling back to templates")
            return self.generate_hooks(prompt_context, count)

        if not ANTHROPIC_API_KEY:
            logger.warning("ANTHROPIC_API_KEY not set — falling back to templates")
            return self.generate_hooks(prompt_context, count)

        categories_desc = "\n".join(
            f"- {name}: {data['template']}"
            for name, data in HOOK_CATEGORIES.items()
        )

        system_prompt = (
            "You are an expert direct-response copywriter trained on Alex Hormozi's "
            "ad frameworks. You write at a 3rd grade reading level. Short sentences. "
            "Conversational. No jargon. Every hook must stop the scroll."
        )
        user_prompt = (
            f"Generate exactly {count} ad hooks for the following context:\n\n"
            f"{prompt_context}\n\n"
            f"Use these hook categories:\n{categories_desc}\n\n"
            f"Rules:\n"
            f"- Max {COPY_RULES['max_words_per_sentence']} words per sentence\n"
            f"- Forbidden words: {', '.join(COPY_RULES['forbidden_words'])}\n"
            f"- Use power words when natural: {', '.join(COPY_RULES['power_words'])}\n\n"
            f"Return ONLY a JSON array of objects with keys: hook, category, source.\n"
            f"Set source to \"ai_generated\" for all."
        )

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            import json
            block = response.content[0]
            text = block.text if hasattr(block, "text") else str(block)
            # Extract JSON array from response
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                hooks = json.loads(text[start:end])
                return hooks
            logger.warning("Could not parse AI hook response — falling back to templates")
        except Exception:
            logger.exception("AI hook generation failed — falling back to templates")

        return self.generate_hooks(prompt_context, count)
