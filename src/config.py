"""Campaign configuration loader and validator."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class CampaignConfig:
    """Parsed, validated campaign configuration."""

    id: str
    name: str
    owner_email: str
    discovery: dict[str, Any]
    qualification: dict[str, Any]
    contacts: dict[str, Any]
    outreach: dict[str, Any]
    follow_up: dict[str, Any]
    monitoring: dict[str, Any]
    tracking: dict[str, Any]
    approval: dict[str, Any]

    # Derived convenience properties
    @property
    def spreadsheet_name(self) -> str:
        return self.tracking.get("spreadsheet_name", f"{self.name} Outreach")

    @property
    def sheet_tab_name(self) -> str:
        return self.tracking.get("sheet_tab_name", "Prospects")

    @property
    def approval_mode(self) -> str:
        return self.approval.get("mode", "sheet")

    @property
    def emails_per_day(self) -> int:
        return self.outreach.get("rate_limit", {}).get("emails_per_day", 30)

    @property
    def min_gap_seconds(self) -> int:
        return self.outreach.get("rate_limit", {}).get("min_gap_seconds", 120)

    @property
    def follow_up_wait_days(self) -> int:
        return self.follow_up.get("wait_days", 7)

    @property
    def max_follow_ups(self) -> int:
        return self.follow_up.get("max_follow_ups", 1)

    @property
    def sender_name(self) -> str:
        return self.outreach.get("sender_name", "")

    @property
    def sender_title(self) -> str:
        return self.outreach.get("sender_title", "")

    @property
    def sender_gmail(self) -> str:
        return self.outreach.get("sender_gmail", self.owner_email)

    @property
    def guest_name(self) -> str:
        return self.outreach.get("guest_name", "")

    @property
    def guest_title(self) -> str:
        return self.outreach.get("guest_title", "")

    @property
    def qualification_model(self) -> str:
        return self.qualification.get("model", "claude-opus-4-6")

    @property
    def composition_model(self) -> str:
        return self.outreach.get("personalization", {}).get("model", "claude-opus-4-6")

    @property
    def classification_model(self) -> str:
        return self.monitoring.get("classification_model", "claude-opus-4-6")

    @property
    def min_qualification_score(self) -> int:
        return self.qualification.get("min_score", 70)

    @property
    def use_hunter(self) -> bool:
        return self.contacts.get("use_hunter", False)

    @property
    def hunter_confidence_min(self) -> int:
        return self.contacts.get("hunter_confidence_min", 70)

    @property
    def notify_on_positive(self) -> bool:
        return self.tracking.get("notify_on_positive", True)

    @property
    def notify_email(self) -> str:
        return self.tracking.get("notify_email", self.owner_email)

    @property
    def template_dir(self) -> str:
        return self.outreach.get("template_dir", f"templates/{self.id}")

    @property
    def initial_template(self) -> str:
        return self.outreach.get("initial_template", "initial_outreach.j2")

    @property
    def template_map(self) -> dict[str, str]:
        return self.outreach.get("template_map", {})

    def get_template_for_category(self, category: Optional[str]) -> str:
        """Return the Jinja2 template filename for this prospect's category.
        Falls back to initial_template if category is missing or not in the map."""
        if category and category in self.template_map:
            return self.template_map[category]
        return self.initial_template

    @property
    def follow_up_template(self) -> str:
        return self.outreach.get("follow_up_template", "follow_up.j2")

    @property
    def personalization_enabled(self) -> bool:
        return self.outreach.get("personalization", {}).get("enabled", True)


_REQUIRED_FIELDS = [
    ("campaign.id", ["campaign", "id"]),
    ("campaign.name", ["campaign", "name"]),
    ("campaign.owner_email", ["campaign", "owner_email"]),
]


def load_campaign(campaign_id: str, campaigns_dir: str = "campaigns") -> CampaignConfig:
    """Load and validate a campaign YAML file by campaign ID."""
    path = Path(campaigns_dir) / f"{campaign_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Campaign config not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    is_valid, errors = _validate_raw(raw)
    if not is_valid:
        raise ValueError(f"Invalid campaign config {path}:\n" + "\n".join(f"  - {e}" for e in errors))

    c = raw.get("campaign", {})
    return CampaignConfig(
        id=c["id"],
        name=c["name"],
        owner_email=c["owner_email"],
        discovery=raw.get("discovery", {}),
        qualification=raw.get("qualification", {}),
        contacts=raw.get("contacts", {}),
        outreach=raw.get("outreach", {}),
        follow_up=raw.get("follow_up", {}),
        monitoring=raw.get("monitoring", {}),
        tracking=raw.get("tracking", {}),
        approval=raw.get("approval", {}),
    )


def list_campaigns(campaigns_dir: str = "campaigns") -> list[str]:
    """Return list of available campaign IDs."""
    p = Path(campaigns_dir)
    if not p.exists():
        return []
    return [f.stem for f in sorted(p.glob("*.yaml"))]


def validate_campaign_yaml(path: str) -> tuple[bool, list[str]]:
    """Validate a campaign YAML file. Returns (is_valid, errors)."""
    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
    except Exception as e:
        return False, [f"YAML parse error: {e}"]
    return _validate_raw(raw)


def _validate_raw(raw: dict) -> tuple[bool, list[str]]:
    errors = []
    if not isinstance(raw, dict):
        return False, ["Root must be a YAML mapping"]

    for field_name, keys in _REQUIRED_FIELDS:
        obj = raw
        for k in keys:
            if not isinstance(obj, dict) or k not in obj:
                errors.append(f"Missing required field: {field_name}")
                break
            obj = obj[k]

    return len(errors) == 0, errors
