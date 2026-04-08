"""
Meta Ads Compliance Checker

Scans ad copy and images for potential policy violations BEFORE
submitting to Meta. Catches common disapproval triggers.

Based on Meta's Advertising Standards:
https://www.facebook.com/policies/ads/
"""

import re
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# VIOLATION PATTERNS
# ============================================================

# Income claims: specific dollar/euro amounts as promises
INCOME_CLAIM_PATTERNS = [
    r"(?:make|earn|profit|revenue|income)\s*\$[\d,]+",
    r"(?:make|earn|profit|revenue|income)\s*€[\d,]+",
    r"\$[\d,]+\s*(?:per|a|/)\s*(?:month|week|day|year|mo|wk)",
    r"€[\d,]+\s*(?:per|a|/)\s*(?:month|week|day|year|mo|wk)",
    r"[\d,]+\s*(?:per|a|/)\s*(?:month|week|day)\s*(?:recurring|passive|income)",
    r"(?:make|earn)\s*[\d,]+k",
    r"(?:quit|replace)\s*(?:your|my)\s*(?:job|9.to.5|salary)",
    r"get\s*rich",
    r"financial\s*freedom",
    r"passive\s*income",
]

# Misleading claims
MISLEADING_PATTERNS = [
    r"guaranteed\s*(?:results|income|money|revenue)",
    r"100%\s*(?:guaranteed|success|results)",
    r"no\s*risk",
    r"risk[\s-]*free",
    r"can'?t\s*(?:fail|lose)",
    r"zero\s*risk",
    r"overnight\s*(?:success|wealth|rich)",
    r"secret\s*(?:formula|method|system)",
]

# Before/after claims (Meta is strict on these)
BEFORE_AFTER_PATTERNS = [
    r"before\s*(?:and|&|\/)\s*after",
    r"transformation\s*(?:guaranteed|results)",
]

# Personal attributes (Meta prohibits implying user characteristics)
PERSONAL_ATTRIBUTE_PATTERNS = [
    r"are\s*you\s*(?:struggling|broke|poor|fat|ugly|lonely|sick)",
    r"(?:your|you)\s*(?:weight|debt|credit\s*score|addiction)",
    r"do\s*you\s*(?:suffer|struggle)\s*(?:from|with)",
]

# Sensational/clickbait (can cause disapproval)
SENSATIONAL_PATTERNS = [
    r"you\s*won'?t\s*believe",
    r"(?:doctors|banks|experts)\s*(?:hate|don'?t want)",
    r"one\s*weird\s*trick",
    r"(?:shocking|exposed|banned)",
]

# Prohibited content
PROHIBITED_PATTERNS = [
    r"(?:crypto|bitcoin|nft)\s*(?:trading|investment|profit)",
    r"gambling",
    r"(?:weight|fat)\s*loss\s*(?:pill|supplement|guaranteed)",
]


def check_text_compliance(text: str) -> List[Dict[str, Any]]:
    """Check ad text for potential Meta policy violations.

    Args:
        text: The ad copy to check (primary text, headline, or description).

    Returns:
        List of violation dicts: [{"type": "...", "severity": "...", "message": "...", "match": "..."}]
    """
    if not text:
        return []

    violations = []
    text_lower = text.lower()

    checks = [
        ("income_claim", "high", INCOME_CLAIM_PATTERNS,
         "Specific income claims can get your ad disapproved. Use vague language like 'recurring revenue' instead of exact amounts."),
        ("misleading", "high", MISLEADING_PATTERNS,
         "Misleading claims (guaranteed results, no risk) violate Meta's ad policy."),
        ("before_after", "medium", BEFORE_AFTER_PATTERNS,
         "Before/after claims are heavily scrutinized by Meta. Use testimonials instead."),
        ("personal_attributes", "high", PERSONAL_ATTRIBUTE_PATTERNS,
         "Meta prohibits ads that imply personal attributes. Reframe without 'you are/do you' language."),
        ("sensational", "medium", SENSATIONAL_PATTERNS,
         "Sensational/clickbait language can trigger disapproval or reduced reach."),
        ("prohibited", "critical", PROHIBITED_PATTERNS,
         "This content is prohibited on Meta. Remove immediately."),
    ]

    for violation_type, severity, patterns, advice in checks:
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                violations.append({
                    "type": violation_type,
                    "severity": severity,
                    "message": advice,
                    "match": match.group(),
                    "position": match.start(),
                })

    return violations


def check_image_text_compliance(image_text: str) -> List[Dict[str, Any]]:
    """Check text that will appear IN the image.

    Meta has relaxed the 20% text rule but still penalizes text-heavy images.
    For AI-generated ads, check the prompt for problematic text.
    """
    violations = []

    if not image_text:
        return violations

    # Check for income claims in image text (stricter than body copy)
    text_lower = image_text.lower()

    # Specific currency amounts in image are risky
    currency_matches = re.findall(r"[€$£]\s*[\d,]+(?:\.\d+)?(?:\s*(?:k|K|/mo|/month|recurring))?", image_text)
    for match in currency_matches:
        # Allow small amounts or prices, flag large income claims
        amount_str = re.search(r"[\d,]+", match)
        if amount_str:
            amount = float(amount_str.group().replace(",", ""))
            if amount >= 500:
                violations.append({
                    "type": "income_claim_in_image",
                    "severity": "high",
                    "message": f"Large currency amount '{match}' in image text may trigger income claim policy. Use vague terms or smaller examples.",
                    "match": match,
                })

    return violations


def check_full_ad(
    primary_text: str = "",
    headline: str = "",
    description: str = "",
    image_prompt: str = "",
) -> Dict[str, Any]:
    """Run full compliance check on an ad before submission.

    Returns:
        {
            "compliant": True/False,
            "violations": [...],
            "risk_level": "safe" / "caution" / "high_risk" / "will_be_rejected",
            "suggestions": [...]
        }
    """
    all_violations = []

    # Check all text components
    for text, label in [
        (primary_text, "primary_text"),
        (headline, "headline"),
        (description, "description"),
    ]:
        violations = check_text_compliance(text)
        for v in violations:
            v["source"] = label
        all_violations.extend(violations)

    # Check image text (from prompt)
    image_violations = check_image_text_compliance(image_prompt)
    for v in image_violations:
        v["source"] = "image_text"
    all_violations.extend(image_violations)

    # Determine risk level
    critical = [v for v in all_violations if v["severity"] == "critical"]
    high = [v for v in all_violations if v["severity"] == "high"]
    medium = [v for v in all_violations if v["severity"] == "medium"]

    if critical:
        risk_level = "will_be_rejected"
    elif high:
        risk_level = "high_risk"
    elif medium:
        risk_level = "caution"
    else:
        risk_level = "safe"

    # Generate suggestions
    suggestions = []
    for v in all_violations:
        suggestions.append(f"[{v['severity'].upper()}] {v['source']}: {v['message']} (matched: '{v['match']}')")

    if not all_violations:
        suggestions.append("✅ No policy violations detected. Ad looks compliant.")

    return {
        "compliant": len(all_violations) == 0,
        "violations": all_violations,
        "risk_level": risk_level,
        "violation_count": len(all_violations),
        "suggestions": suggestions,
    }


# ============================================================
# Safe copy alternatives
# ============================================================

SAFE_ALTERNATIVES = {
    "€500/month": "recurring revenue",
    "$500/month": "recurring revenue",
    "€1,500 recurring": "recurring client revenue",
    "make €": "build a business with",
    "earn €": "generate revenue",
    "make $": "build a business with",
    "earn $": "generate revenue",
    "passive income": "recurring revenue streams",
    "financial freedom": "business growth",
    "guaranteed results": "proven system",
    "get rich": "build a profitable business",
    "quit your job": "build your own business",
    "no risk": "low-commitment",
    "risk-free": "with a full refund guarantee",
}


def suggest_safe_copy(text: str) -> str:
    """Replace risky phrases with policy-safe alternatives."""
    result = text
    for risky, safe in SAFE_ALTERNATIVES.items():
        result = re.sub(re.escape(risky), safe, result, flags=re.IGNORECASE)
    return result
