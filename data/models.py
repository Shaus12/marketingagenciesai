"""
Data models for the Meta Ads Management System.

Dataclass-based models representing campaigns, ad sets, ads, insights,
creative tags, rule executions, and community-sourced angles.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------

@dataclass
class CampaignData:
    """A Meta Ads campaign with its configuration and budget info."""

    campaign_id: str
    name: str
    status: str = "ACTIVE"
    objective: str = ""
    daily_budget: float = 0.0
    lifetime_budget: float = 0.0
    campaign_type: str = "test"  # "scale", "iterate", "test", "retarget"
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now_iso()
        if not self.updated_at:
            self.updated_at = _now_iso()
        self.daily_budget = float(self.daily_budget)
        self.lifetime_budget = float(self.lifetime_budget)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CampaignData":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_row(cls, row: Any) -> "CampaignData":
        """Build from a sqlite3.Row or tuple with column order matching the table."""
        if hasattr(row, "keys"):
            return cls.from_dict(dict(row))
        keys = list(cls.__dataclass_fields__.keys())
        return cls(**dict(zip(keys, row)))


# ---------------------------------------------------------------------------
# Ad Set
# ---------------------------------------------------------------------------

@dataclass
class AdSetData:
    """An ad set within a campaign."""

    adset_id: str
    campaign_id: str
    name: str
    status: str = "ACTIVE"
    daily_budget: float = 0.0
    optimization_goal: str = ""
    targeting_summary: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now_iso()
        if not self.updated_at:
            self.updated_at = _now_iso()
        self.daily_budget = float(self.daily_budget)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AdSetData":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_row(cls, row: Any) -> "AdSetData":
        if hasattr(row, "keys"):
            return cls.from_dict(dict(row))
        keys = list(cls.__dataclass_fields__.keys())
        return cls(**dict(zip(keys, row)))


# ---------------------------------------------------------------------------
# Ad
# ---------------------------------------------------------------------------

@dataclass
class AdData:
    """An individual ad."""

    ad_id: str
    adset_id: str
    campaign_id: str
    name: str
    status: str = "ACTIVE"
    creative_id: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now_iso()
        if not self.updated_at:
            self.updated_at = _now_iso()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AdData":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_row(cls, row: Any) -> "AdData":
        if hasattr(row, "keys"):
            return cls.from_dict(dict(row))
        keys = list(cls.__dataclass_fields__.keys())
        return cls(**dict(zip(keys, row)))


# ---------------------------------------------------------------------------
# Ad Insight (daily metrics snapshot)
# ---------------------------------------------------------------------------

@dataclass
class AdInsight:
    """Daily performance metrics for a single ad."""

    ad_id: str
    date: str
    spend: float = 0.0
    impressions: int = 0
    reach: int = 0
    frequency: float = 0.0
    clicks: int = 0
    ctr: float = 0.0
    cpc: float = 0.0
    cpm: float = 0.0
    conversions: int = 0
    cpa: float = 0.0
    revenue: float = 0.0
    roas: float = 0.0
    video_views_3s: int = 0    # for hook rate
    video_views_15s: int = 0   # for hold rate
    video_views_p25: int = 0
    video_views_p50: int = 0
    video_views_p75: int = 0
    video_views_p100: int = 0

    def __post_init__(self) -> None:
        self.spend = float(self.spend)
        self.frequency = float(self.frequency)
        self.ctr = float(self.ctr)
        self.cpc = float(self.cpc)
        self.cpm = float(self.cpm)
        self.cpa = float(self.cpa)
        self.revenue = float(self.revenue)
        self.roas = float(self.roas)
        self.impressions = int(self.impressions)
        self.reach = int(self.reach)
        self.clicks = int(self.clicks)
        self.conversions = int(self.conversions)
        self.video_views_3s = int(self.video_views_3s)
        self.video_views_15s = int(self.video_views_15s)
        self.video_views_p25 = int(self.video_views_p25)
        self.video_views_p50 = int(self.video_views_p50)
        self.video_views_p75 = int(self.video_views_p75)
        self.video_views_p100 = int(self.video_views_p100)

    @property
    def hook_rate(self) -> float:
        """Hook rate = 3-second views / impressions."""
        if self.impressions == 0:
            return 0.0
        return self.video_views_3s / self.impressions

    @property
    def hold_rate(self) -> float:
        """Hold rate = 15-second views / 3-second views."""
        if self.video_views_3s == 0:
            return 0.0
        return self.video_views_15s / self.video_views_3s

    @property
    def completion_rate(self) -> float:
        """Completion rate = 100% views / 3-second views."""
        if self.video_views_3s == 0:
            return 0.0
        return self.video_views_p100 / self.video_views_3s

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["hook_rate"] = self.hook_rate
        d["hold_rate"] = self.hold_rate
        d["completion_rate"] = self.completion_rate
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AdInsight":
        # Filter out computed properties that aren't constructor args
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)

    @classmethod
    def from_row(cls, row: Any) -> "AdInsight":
        if hasattr(row, "keys"):
            return cls.from_dict(dict(row))
        keys = list(cls.__dataclass_fields__.keys())
        return cls(**dict(zip(keys, row)))


# ---------------------------------------------------------------------------
# Creative Tag (metadata about ad creatives)
# ---------------------------------------------------------------------------

@dataclass
class CreativeTag:
    """Structured metadata and tags for an ad creative."""

    creative_id: str
    ad_id: str
    format: str = ""             # "ugc", "polished", "static", "carousel"
    hook_type: str = ""          # "question", "objection", "shock", "callout", "proof"
    angle: str = ""              # descriptive angle name
    has_text_overlay: bool = False
    has_testimonial: bool = False
    video_length_seconds: int = 0
    body_text: str = ""
    headline: str = ""
    cta_type: str = ""
    source: str = "manual"       # "community", "manual", "ai_generated"
    tags: str = "[]"             # JSON string of additional tags
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now_iso()
        self.has_text_overlay = bool(self.has_text_overlay)
        self.has_testimonial = bool(self.has_testimonial)
        self.video_length_seconds = int(self.video_length_seconds)
        # Ensure tags is valid JSON
        if isinstance(self.tags, list):
            self.tags = json.dumps(self.tags)

    @property
    def tags_list(self) -> List[str]:
        """Return tags as a Python list."""
        try:
            return json.loads(self.tags)
        except (json.JSONDecodeError, TypeError):
            return []

    def add_tag(self, tag: str) -> None:
        """Append a tag to the tags list."""
        current = self.tags_list
        if tag not in current:
            current.append(tag)
            self.tags = json.dumps(current)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CreativeTag":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_row(cls, row: Any) -> "CreativeTag":
        if hasattr(row, "keys"):
            return cls.from_dict(dict(row))
        keys = list(cls.__dataclass_fields__.keys())
        return cls(**dict(zip(keys, row)))


# ---------------------------------------------------------------------------
# Rule Execution (audit log for rules engine)
# ---------------------------------------------------------------------------

@dataclass
class RuleExecution:
    """Record of an automated rule execution (kill, scale, alert)."""

    rule_name: str
    rule_type: str              # "kill", "scale", "alert"
    entity_id: str              # ad_id, adset_id, or campaign_id
    entity_type: str            # "ad", "adset", "campaign"
    action_taken: str
    details: str = ""
    executed_at: str = ""
    id: Optional[int] = None    # auto-increment in DB

    def __post_init__(self) -> None:
        if not self.executed_at:
            self.executed_at = _now_iso()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuleExecution":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_row(cls, row: Any) -> "RuleExecution":
        if hasattr(row, "keys"):
            return cls.from_dict(dict(row))
        # Row order: id, rule_name, rule_type, entity_id, entity_type,
        #            action_taken, details, executed_at
        keys = ["id", "rule_name", "rule_type", "entity_id", "entity_type",
                "action_taken", "details", "executed_at"]
        return cls(**dict(zip(keys, row)))


# ---------------------------------------------------------------------------
# Community Angle (sourced from community intelligence)
# ---------------------------------------------------------------------------

@dataclass
class CommunityAngle:
    """An ad angle or hook sourced from community content."""

    source_type: str             # "question", "objection", "success_story", "trending"
    source_text: str             # original community text
    suggested_hook: str = ""
    suggested_angle: str = ""
    hook_category: str = ""      # from hormozi.HOOK_CATEGORIES
    used_in_ad_id: str = ""      # if used, which ad
    performance_score: float = 0.0
    created_at: str = ""
    status: str = "new"          # "new", "used", "rejected"
    id: Optional[int] = None     # auto-increment in DB

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now_iso()
        self.performance_score = float(self.performance_score)
        if self.status not in ("new", "used", "rejected"):
            self.status = "new"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CommunityAngle":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_row(cls, row: Any) -> "CommunityAngle":
        if hasattr(row, "keys"):
            return cls.from_dict(dict(row))
        # Row order: id, source_type, source_text, suggested_hook, suggested_angle,
        #            hook_category, used_in_ad_id, performance_score, created_at, status
        keys = ["id", "source_type", "source_text", "suggested_hook", "suggested_angle",
                "hook_category", "used_in_ad_id", "performance_score", "created_at", "status"]
        return cls(**dict(zip(keys, row)))
