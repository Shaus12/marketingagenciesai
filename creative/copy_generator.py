"""
Copy generator for Meta Ads creative module.

Generates ad copy following Hormozi's Proof-Promise-Plan structure.
Works template-based by default and optionally uses the Anthropic API
for higher-quality output.
"""

import logging
import random
import re
from typing import Any, Dict, List, Optional

from config.hormozi import AD_STRUCTURE, COPY_RULES, HOOK_CATEGORIES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_HEADLINE_TEMPLATES = {
    "benefit": [
        "Get {outcome} without {pain}",
        "The simple way to {outcome}",
        "{outcome} in {timeframe} or less",
        "Finally. {outcome} made simple.",
        "How to {outcome} (step by step)",
    ],
    "curiosity": [
        "The hidden reason you're not getting {outcome}",
        "Why {common_approach} is holding you back",
        "What nobody tells you about {topic}",
        "This one thing changed everything",
        "The {topic} secret that works every time",
    ],
    "proof": [
        "How we helped {persona} get {outcome}",
        "{number}+ people already got {outcome}",
        "Real results. Real people. Real {outcome}.",
        "See how {persona} went from {before} to {after}",
        "Proof that {claim} actually works",
    ],
    "urgency": [
        "Last chance to get {outcome}",
        "This won't be available forever",
        "Spots are filling up fast",
        "Don't miss this",
        "Act now. Get {outcome} today.",
    ],
}

_BODY_TEMPLATES = [
    "Here's the thing. Most people {common_mistake}. "
    "That's why they stay stuck. "
    "But there's a better way. {solution}. "
    "It takes {timeframe}. And it works.",

    "You've tried {old_way}. It didn't work. "
    "Not because you're bad at it. "
    "Because the approach is broken. "
    "{solution} fixes that. Simple as that.",

    "What if you could {dream_outcome}? "
    "No {sacrifice}. No {pain}. "
    "Just {simple_steps}. "
    "That's exactly what {solution} gives you.",

    "Stop wasting time on {wrong_approach}. "
    "Here's what actually works: {solution}. "
    "It's simple. It's fast. And it gets results.",

    "I used to {before_state}. "
    "Then I found {solution}. "
    "Now I {after_state}. "
    "And you can too.",
]

_CTA_TEMPLATES = {
    "link_click": [
        "Click the link below to get started.",
        "Tap the link. See for yourself.",
        "Click below. It takes 30 seconds.",
        "Hit the link. Start today.",
        "Click the link to learn more.",
    ],
    "lead_form": [
        "Drop your email below. We'll send it over.",
        "Fill out the form. It takes 10 seconds.",
        "Sign up now. It's free.",
        "Enter your info. Get instant access.",
        "Leave your details. We'll do the rest.",
    ],
    "message": [
        "Send us a message. We'll reply in minutes.",
        "DM us the word 'START'. We'll take it from there.",
        "Drop a comment. We'll reach out.",
        "Message us now. No strings.",
        "Hit the message button. Ask us anything.",
    ],
    "purchase": [
        "Buy now. Risk-free guarantee.",
        "Order today. Get it this week.",
        "Grab yours before it's gone.",
        "Add to cart. Thank yourself later.",
        "Get yours now. Limited stock.",
    ],
}

# Words that inflate reading level
_COMPLEX_WORD_MAP = {
    "utilize": "use",
    "leverage": "use",
    "optimize": "improve",
    "implement": "start",
    "facilitate": "help",
    "demonstrate": "show",
    "approximately": "about",
    "consequently": "so",
    "nevertheless": "but",
    "furthermore": "also",
    "regarding": "about",
    "sufficient": "enough",
    "numerous": "many",
    "purchase": "buy",
    "commence": "start",
    "terminate": "end",
    "additional": "more",
    "assistance": "help",
    "individuals": "people",
    "subsequent": "next",
    "prior to": "before",
    "in order to": "to",
    "at this point in time": "now",
    "due to the fact that": "because",
}


# ---------------------------------------------------------------------------
# CopyGenerator
# ---------------------------------------------------------------------------


class CopyGenerator:
    """
    Generate ad copy following Hormozi's Proof-Promise-Plan structure.

    All generation is template-based by default. Pass ``use_ai=True``
    to key methods to use Claude for higher-quality output.
    """

    def __init__(self) -> None:
        self._forbidden: List[str] = COPY_RULES.get("forbidden_words", [])
        self._power_words: List[str] = COPY_RULES.get("power_words", [])
        self._max_sentence_words: int = COPY_RULES.get("max_words_per_sentence", 12)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_ad_copy(
        self,
        angle: str,
        hook: Optional[str] = None,
        proof: Optional[str] = None,
        cta: Optional[str] = None,
        *,
        use_ai: bool = False,
    ) -> Dict[str, str]:
        """Generate full ad copy following AD_STRUCTURE.

        Args:
            angle: The core message or angle for the ad.
            hook: Optional pre-written hook. Generated if omitted.
            proof: Optional proof / testimonial text.
            cta: Optional call-to-action text.
            use_ai: Use the Anthropic API for generation.

        Returns:
            Dict with keys matching AD_STRUCTURE sections:
            ``hook``, ``promise``, ``proof``, ``bridge``, ``cta``, and
            ``full_copy`` (concatenated version).
        """
        if use_ai:
            return self._generate_ad_copy_ai(angle, hook, proof, cta)

        hook_text = hook or self._generate_hook_from_angle(angle)
        promise_text = self._generate_promise(angle)
        proof_text = proof or self._generate_proof_placeholder(angle)
        bridge_text = self._generate_bridge(angle)
        cta_text = cta or random.choice(_CTA_TEMPLATES["link_click"])

        parts = {
            "hook": hook_text,
            "promise": promise_text,
            "proof": proof_text,
            "bridge": bridge_text,
            "cta": cta_text,
        }
        # Apply copy rules to every section
        parts = {k: self.apply_copy_rules(v) for k, v in parts.items()}
        parts["full_copy"] = "\n\n".join([
            parts["hook"],
            parts["promise"],
            parts["proof"],
            parts["bridge"],
            parts["cta"],
        ])
        return parts

    def generate_headline(
        self,
        angle: str,
        style: str = "benefit",
        *,
        use_ai: bool = False,
    ) -> str:
        """Generate a short headline.

        Args:
            angle: The core message or value proposition.
            style: One of ``benefit``, ``curiosity``, ``proof``, ``urgency``.
            use_ai: Use the Anthropic API for generation.

        Returns:
            A single headline string.
        """
        if use_ai:
            return self._generate_headline_ai(angle, style)

        templates = _HEADLINE_TEMPLATES.get(style, _HEADLINE_TEMPLATES["benefit"])
        template = random.choice(templates)
        variables = self._headline_variables(angle)
        headline = self._fill(template, variables)
        return self.apply_copy_rules(headline)

    def generate_body_text(
        self,
        angle: str,
        proof: Optional[str] = None,
        max_words: int = 50,
        *,
        use_ai: bool = False,
    ) -> str:
        """Generate primary text / body copy.

        Args:
            angle: The core angle or value proposition.
            proof: Optional proof point to weave in.
            max_words: Soft word limit for the output.
            use_ai: Use the Anthropic API for generation.

        Returns:
            Body text string.
        """
        if use_ai:
            return self._generate_body_ai(angle, proof, max_words)

        template = random.choice(_BODY_TEMPLATES)
        variables = self._body_variables(angle, proof)
        body = self._fill(template, variables)
        body = self.apply_copy_rules(body)

        # Trim to approximate word limit
        words = body.split()
        if len(words) > max_words:
            # Cut at the last sentence boundary within limit
            trimmed = " ".join(words[:max_words])
            last_period = trimmed.rfind(".")
            if last_period > 0:
                body = trimmed[: last_period + 1]
            else:
                body = trimmed + "."
        return body

    def generate_cta_text(self, offer_type: str = "link_click") -> str:
        """Generate a call-to-action line.

        Args:
            offer_type: One of ``link_click``, ``lead_form``, ``message``,
                        ``purchase``.

        Returns:
            CTA string.
        """
        templates = _CTA_TEMPLATES.get(offer_type, _CTA_TEMPLATES["link_click"])
        return random.choice(templates)

    def apply_copy_rules(self, text: str) -> str:
        """Enforce COPY_RULES on a piece of text.

        - Replaces forbidden words with simpler synonyms.
        - Breaks long sentences.
        - Strips jargon.

        Returns:
            Cleaned text.
        """
        result = text
        # Replace forbidden words
        for word in self._forbidden:
            pattern = re.compile(re.escape(word), re.IGNORECASE)
            replacement = _COMPLEX_WORD_MAP.get(word.lower(), "")
            if replacement:
                result = pattern.sub(replacement, result)
            else:
                result = pattern.sub("", result)

        # Replace other complex words
        for complex_word, simple in _COMPLEX_WORD_MAP.items():
            pattern = re.compile(re.escape(complex_word), re.IGNORECASE)
            result = pattern.sub(simple, result)

        # Break overly long sentences
        result = self._enforce_sentence_length(result)

        # Clean up whitespace
        result = re.sub(r" {2,}", " ", result).strip()
        return result

    def simplify_text(self, text: str) -> str:
        """Rewrite text toward a 3rd grade reading level.

        Applies word simplification and sentence splitting.
        Does not use AI.
        """
        simplified = text
        # Apply complex word replacements
        for complex_word, simple in _COMPLEX_WORD_MAP.items():
            pattern = re.compile(re.escape(complex_word), re.IGNORECASE)
            simplified = pattern.sub(simple, simplified)

        # Break long sentences
        simplified = self._enforce_sentence_length(simplified)

        # Remove parentheticals
        simplified = re.sub(r"\([^)]*\)", "", simplified)

        # Clean up
        simplified = re.sub(r" {2,}", " ", simplified).strip()
        return simplified

    def generate_variations(
        self,
        base_copy: str,
        count: int = 3,
        *,
        use_ai: bool = False,
    ) -> List[str]:
        """Create variations of existing ad copy.

        Args:
            base_copy: The original copy to create variations of.
            count: Number of variations to generate.
            use_ai: Use the Anthropic API for generation.

        Returns:
            List of variation strings.
        """
        if use_ai:
            return self._generate_variations_ai(base_copy, count)

        variations: List[str] = []
        sentences = re.split(r"(?<=[.!?])\s+", base_copy.strip())

        for i in range(count):
            variant_sentences = sentences.copy()

            if i % 3 == 0 and len(variant_sentences) > 1:
                # Swap two sentences
                idx_a = random.randint(0, len(variant_sentences) - 1)
                idx_b = random.randint(0, len(variant_sentences) - 1)
                variant_sentences[idx_a], variant_sentences[idx_b] = (
                    variant_sentences[idx_b],
                    variant_sentences[idx_a],
                )
            elif i % 3 == 1 and len(variant_sentences) > 2:
                # Drop a middle sentence for brevity
                mid = len(variant_sentences) // 2
                variant_sentences.pop(mid)
            else:
                # Inject a power word into the first sentence
                if variant_sentences:
                    pw = random.choice(self._power_words)
                    first = variant_sentences[0]
                    variant_sentences[0] = f"{pw.capitalize()}. {first}"

            variation = " ".join(variant_sentences)
            variation = self.apply_copy_rules(variation)
            variations.append(variation)

        return variations

    def score_copy(self, text: str) -> Dict[str, Any]:
        """Score copy against COPY_RULES.

        Returns:
            Dict with ``score`` (0-100), ``deductions`` list, and
            ``suggestions`` list.
        """
        score = 100
        deductions: List[str] = []
        suggestions: List[str] = []

        # Check forbidden words
        text_lower = text.lower()
        for word in self._forbidden:
            if word.lower() in text_lower:
                score -= 10
                deductions.append(f"Contains forbidden word: '{word}' (-10)")

        # Check sentence length
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        long_count = 0
        for sentence in sentences:
            word_count = len(sentence.split())
            if word_count > self._max_sentence_words:
                long_count += 1
        if long_count > 0:
            penalty = min(long_count * 5, 25)
            score -= penalty
            deductions.append(
                f"{long_count} sentence(s) over {self._max_sentence_words} "
                f"words (-{penalty})"
            )
            suggestions.append("Break long sentences into shorter ones.")

        # Check for power words
        power_count = sum(
            1 for w in self._power_words if w.lower() in text_lower
        )
        if power_count == 0:
            score -= 5
            deductions.append("No power words found (-5)")
            suggestions.append(
                f"Add power words: {', '.join(self._power_words[:5])}"
            )

        # Check for passive voice indicators
        passive_indicators = [" is being ", " was being ", " has been ", " had been "]
        for indicator in passive_indicators:
            if indicator in text_lower:
                score -= 5
                deductions.append(f"Passive voice detected: '{indicator.strip()}' (-5)")
                suggestions.append("Use active voice. Be direct.")
                break

        # Check for complex words
        complex_count = 0
        for complex_word in _COMPLEX_WORD_MAP:
            if complex_word.lower() in text_lower:
                complex_count += 1
        if complex_count > 0:
            penalty = min(complex_count * 3, 15)
            score -= penalty
            deductions.append(
                f"{complex_count} complex word(s) found (-{penalty})"
            )
            suggestions.append("Simplify your language. Write like you talk.")

        # Check total length (ads should be punchy)
        word_count = len(text.split())
        if word_count > 150:
            score -= 10
            deductions.append(f"Too long ({word_count} words) (-10)")
            suggestions.append("Cut it down. Shorter is better.")

        # Check for clear CTA
        cta_signals = ["click", "tap", "sign up", "get", "start", "buy", "order", "join"]
        has_cta = any(signal in text_lower for signal in cta_signals)
        if not has_cta:
            score -= 5
            deductions.append("No clear CTA detected (-5)")
            suggestions.append("End with a clear call to action.")

        score = max(0, score)

        return {
            "score": score,
            "deductions": deductions,
            "suggestions": suggestions,
            "word_count": word_count,
            "sentence_count": len(sentences),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fill(self, template: str, variables: Dict[str, str]) -> str:
        """Fill placeholders in a template string."""
        result = template
        for key, val in variables.items():
            result = result.replace(f"{{{key}}}", val)
        return result

    def _generate_hook_from_angle(self, angle: str) -> str:
        """Create a hook from an angle using a random category template."""
        category = random.choice(list(HOOK_CATEGORIES.keys()))
        cat = HOOK_CATEGORIES[category]
        templates = [cat["template"]] + cat.get("examples", [])
        template = random.choice(templates)
        variables = self._headline_variables(angle)
        return self._fill(template, variables)

    def _generate_promise(self, angle: str) -> str:
        """Generate the promise section of an ad."""
        words = angle.strip().split()
        short = " ".join(words[:8]) if len(words) > 8 else angle.strip()
        templates = [
            f"Here's what you get: {short}.",
            f"Imagine this: {short}. In less time than you think.",
            f"You can {short}. For real. Here's how.",
            f"What if {short} was actually simple? It is.",
        ]
        return random.choice(templates)

    def _generate_proof_placeholder(self, angle: str) -> str:
        """Generate placeholder proof text."""
        templates = [
            "We've seen it work hundreds of times. Real people. Real results.",
            "Don't take our word for it. Look at what happened when people tried this.",
            "The proof is in the results. And the results speak for themselves.",
            "People told us it wouldn't work. Then they tried it. Now they tell everyone.",
        ]
        return random.choice(templates)

    def _generate_bridge(self, angle: str) -> str:
        """Generate the bridge section connecting problem to solution."""
        templates = [
            "Here's how it works. Step 1: Start. Step 2: Follow the plan. Step 3: See results.",
            "It's simpler than you think. One step at a time. We show you exactly what to do.",
            "No guesswork. No confusion. Just a clear path from where you are to where you want to be.",
            "Three steps. That's it. We walk you through each one.",
        ]
        return random.choice(templates)

    def _headline_variables(self, angle: str) -> Dict[str, str]:
        """Build variable mapping for headline templates."""
        words = angle.strip().split()
        short = " ".join(words[:5]) if len(words) > 5 else angle.strip()
        very_short = " ".join(words[:3]) if len(words) > 3 else angle.strip()
        return {
            "outcome": short,
            "pain": "the hard way",
            "topic": short,
            "common_approach": "what everyone else does",
            "persona": very_short,
            "number": str(random.choice([100, 500, 1000, 2500])),
            "before": "struggling",
            "after": short,
            "claim": short,
            "timeframe": "30 days",
        }

    def _body_variables(
        self, angle: str, proof: Optional[str] = None
    ) -> Dict[str, str]:
        """Build variable mapping for body templates."""
        words = angle.strip().split()
        short = " ".join(words[:6]) if len(words) > 6 else angle.strip()
        return {
            "common_mistake": "try to figure it out alone",
            "solution": short,
            "timeframe": "a few weeks",
            "old_way": "everything else",
            "dream_outcome": short,
            "sacrifice": "burnout",
            "pain": "confusion",
            "simple_steps": "a clear plan and simple steps",
            "wrong_approach": "things that don't work",
            "before_state": "stuck",
            "after_state": short,
        }

    def _enforce_sentence_length(self, text: str) -> str:
        """Break sentences that exceed the max word count."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        result_sentences: List[str] = []

        for sentence in sentences:
            words = sentence.split()
            if len(words) <= self._max_sentence_words:
                result_sentences.append(sentence)
                continue
            # Break at natural points
            chunks: List[str] = []
            current: List[str] = []
            for word in words:
                current.append(word)
                if len(current) >= self._max_sentence_words:
                    chunk = " ".join(current)
                    if not chunk.endswith((".", "!", "?")):
                        chunk += "."
                    chunks.append(chunk)
                    current = []
            if current:
                chunk = " ".join(current)
                if not chunk.endswith((".", "!", "?")):
                    chunk += "."
                chunks.append(chunk)
            result_sentences.extend(chunks)

        return " ".join(result_sentences)

    # ------------------------------------------------------------------
    # AI-powered generation (optional)
    # ------------------------------------------------------------------

    def _get_ai_client(self):
        """Return an Anthropic client or None if unavailable."""
        try:
            import anthropic
            from config.settings import ANTHROPIC_API_KEY
        except ImportError:
            logger.warning("anthropic package not installed")
            return None
        if not ANTHROPIC_API_KEY:
            logger.warning("ANTHROPIC_API_KEY not set")
            return None
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def _ai_system_prompt(self) -> str:
        """Standard system prompt for copy generation."""
        return (
            "You are an expert direct-response copywriter trained on Alex Hormozi's "
            "frameworks. You write at a 3rd grade reading level. Short sentences. "
            "Conversational. Direct. Confident. No jargon. No fluff.\n\n"
            f"Rules:\n"
            f"- Max {self._max_sentence_words} words per sentence\n"
            f"- Forbidden words: {', '.join(self._forbidden)}\n"
            f"- Use power words when natural: {', '.join(self._power_words)}\n"
            f"- Tone: {COPY_RULES['tone']}"
        )

    def _generate_ad_copy_ai(
        self,
        angle: str,
        hook: Optional[str],
        proof: Optional[str],
        cta: Optional[str],
    ) -> Dict[str, str]:
        """Use Claude to generate full ad copy."""
        client = self._get_ai_client()
        if client is None:
            return self.generate_ad_copy(angle, hook, proof, cta)

        structure_desc = "\n".join(
            f"- {section}: {data['purpose']} ({data['duration_seconds'][0]}-{data['duration_seconds'][1]}s)"
            for section, data in AD_STRUCTURE.items()
        )
        user_prompt = (
            f"Write a complete ad following this structure:\n{structure_desc}\n\n"
            f"Angle: {angle}\n"
        )
        if hook:
            user_prompt += f"Hook (use this): {hook}\n"
        if proof:
            user_prompt += f"Proof (use this): {proof}\n"
        if cta:
            user_prompt += f"CTA (use this): {cta}\n"

        user_prompt += (
            "\nReturn ONLY a JSON object with keys: hook, promise, proof, bridge, cta, full_copy."
        )

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                system=self._ai_system_prompt(),
                messages=[{"role": "user", "content": user_prompt}],
            )
            import json
            block = response.content[0]
            text = block.text if hasattr(block, "text") else str(block)
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except Exception:
            logger.exception("AI ad copy generation failed — falling back to templates")

        return self.generate_ad_copy(angle, hook, proof, cta)

    def _generate_headline_ai(self, angle: str, style: str) -> str:
        """Use Claude to generate a headline."""
        client = self._get_ai_client()
        if client is None:
            return self.generate_headline(angle, style)

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=128,
                system=self._ai_system_prompt(),
                messages=[{
                    "role": "user",
                    "content": (
                        f"Write one short ad headline for: {angle}\n"
                        f"Style: {style}\n"
                        f"Max 10 words. Return ONLY the headline text."
                    ),
                }],
            )
            return (response.content[0].text if hasattr(response.content[0], "text") else str(response.content[0])).strip().strip('"')
        except Exception:
            logger.exception("AI headline generation failed")

        return self.generate_headline(angle, style)

    def _generate_body_ai(
        self, angle: str, proof: Optional[str], max_words: int
    ) -> str:
        """Use Claude to generate body text."""
        client = self._get_ai_client()
        if client is None:
            return self.generate_body_text(angle, proof, max_words)

        extra = f"\nProof to include: {proof}" if proof else ""
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=512,
                system=self._ai_system_prompt(),
                messages=[{
                    "role": "user",
                    "content": (
                        f"Write ad body copy for: {angle}{extra}\n"
                        f"Max {max_words} words. Return ONLY the body text."
                    ),
                }],
            )
            return (response.content[0].text if hasattr(response.content[0], "text") else str(response.content[0])).strip()
        except Exception:
            logger.exception("AI body generation failed")

        return self.generate_body_text(angle, proof, max_words)

    def _generate_variations_ai(self, base_copy: str, count: int) -> List[str]:
        """Use Claude to create copy variations."""
        client = self._get_ai_client()
        if client is None:
            return self.generate_variations(base_copy, count)

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                system=self._ai_system_prompt(),
                messages=[{
                    "role": "user",
                    "content": (
                        f"Create {count} variations of this ad copy:\n\n{base_copy}\n\n"
                        f"Keep the same message. Change the wording and structure.\n"
                        f"Return ONLY a JSON array of strings."
                    ),
                }],
            )
            import json
            text = (response.content[0].text if hasattr(response.content[0], "text") else str(response.content[0]))
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except Exception:
            logger.exception("AI variations generation failed")

        return self.generate_variations(base_copy, count)
