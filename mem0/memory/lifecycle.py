"""Memory lifecycle policy utilities.

Handles TTL computation, state classification, and policy resolution for
memories across SDK, REST API, CLI, and dashboard layers.

Field naming convention (consistent across all layers):
  - expires_at     : ISO 8601 UTC timestamp or None (permanent)
  - ttl_state      : "active" | "expiring_soon" | "expired" | "permanent"
  - ttl_source     : "default" | "category" | "user" | "agent" | "workspace" | "request"
                     (which policy scope produced the expires_at value)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Optional


class TtlState(str, Enum):
    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    PERMANENT = "permanent"


class TtlSource(str, Enum):
    DEFAULT = "default"
    CATEGORY = "category"
    USER = "user"
    AGENT = "agent"
    WORKSPACE = "workspace"
    REQUEST = "request"


EXPIRING_SOON_WINDOW_DAYS = 7


@dataclass
class LifecyclePolicy:
    """A retention policy that can be applied at different scopes.

    default_ttl_days=None means memories are permanent by default at this scope.
    """

    default_ttl_days: Optional[int] = None
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "default_ttl_days": self.default_ttl_days,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "LifecyclePolicy":
        if not data:
            return cls()
        return cls(
            default_ttl_days=data.get("default_ttl_days"),
            enabled=data.get("enabled", True),
        )


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    """Robust ISO datetime parser that accepts strings or datetime objects."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def compute_ttl_state(
    expires_at: Optional[Any],
    now: Optional[datetime] = None,
    expiring_soon_days: int = EXPIRING_SOON_WINDOW_DAYS,
) -> TtlState:
    """Classify a memory's TTL state from its expires_at value.

    Args:
        expires_at: ISO timestamp string or datetime (or None for permanent).
        now: Reference "now" datetime (defaults to current UTC time).
        expiring_soon_days: How many days before expiry counts as "expiring_soon".

    Returns:
        TtlState enum value.
    """
    if expires_at is None:
        return TtlState.PERMANENT
    parsed = _parse_iso_datetime(expires_at)
    if parsed is None:
        return TtlState.PERMANENT
    if now is None:
        now = _now_utc()
    if parsed <= now:
        return TtlState.EXPIRED
    if parsed <= now + timedelta(days=expiring_soon_days):
        return TtlState.EXPIRING_SOON
    return TtlState.ACTIVE


def compute_expires_at_from_ttl(
    ttl_days: int,
    now: Optional[datetime] = None,
) -> str:
    """Return an ISO UTC timestamp ttl_days from now."""
    if now is None:
        now = _now_utc()
    return (now + timedelta(days=ttl_days)).isoformat()


def resolve_expiration(
    *,
    request_expires: Optional[Any] = None,
    request_ttl_days: Optional[int] = None,
    category_policy: Optional[LifecyclePolicy] = None,
    categories: Optional[list] = None,
    category_policies: Optional[Dict[str, LifecyclePolicy]] = None,
    user_policy: Optional[LifecyclePolicy] = None,
    agent_policy: Optional[LifecyclePolicy] = None,
    workspace_policy: Optional[LifecyclePolicy] = None,
    default_policy: Optional[LifecyclePolicy] = None,
    now: Optional[datetime] = None,
) -> tuple[Optional[str], TtlSource]:
    """Resolve the effective expires_at and its source from policy hierarchy.

    Precedence (highest first):
      1. request_expires (explicit ISO date)           → ttl_source="request"
      2. request_ttl_days (explicit TTL days)          → ttl_source="request"
      3. best category policy (shortest TTL across
         matching categories from category_policies)    → ttl_source="category"
         + legacy single category_policy (used when
           category_policies / categories are not set)
      4. user_policy.default_ttl_days                   → ttl_source="user"
      5. agent_policy.default_ttl_days                  → ttl_source="agent"
      6. workspace_policy.default_ttl_days              → ttl_source="workspace"
      7. default_policy.default_ttl_days                → ttl_source="default"
      8. none of the above apply                        → expires_at=None, ttl_source="default"

    When multiple categories match and more than one has an enabled policy,
    the **shortest** TTL wins (most restrictive).

    A policy with enabled=False is skipped entirely.

    Returns:
        (expires_at_iso_or_none, ttl_source)
    """
    if now is None:
        now = _now_utc()

    if request_expires is not None:
        parsed = _parse_iso_datetime(request_expires)
        if parsed is not None:
            return parsed.isoformat(), TtlSource.REQUEST

    if request_ttl_days is not None and request_ttl_days > 0:
        return compute_expires_at_from_ttl(request_ttl_days, now), TtlSource.REQUEST

    # --- Category layer: shortest TTL across matching categories wins ---
    shortest_category_ttl: Optional[int] = None
    if categories and category_policies:
        for cat in categories:
            pol = category_policies.get(cat)
            if pol and pol.enabled and pol.default_ttl_days and pol.default_ttl_days > 0:
                if shortest_category_ttl is None or pol.default_ttl_days < shortest_category_ttl:
                    shortest_category_ttl = pol.default_ttl_days
    if shortest_category_ttl is not None:
        return compute_expires_at_from_ttl(shortest_category_ttl, now), TtlSource.CATEGORY

    # Legacy single category_policy for backwards compatibility
    if (
        category_policy
        and category_policy.enabled
        and category_policy.default_ttl_days
        and category_policy.default_ttl_days > 0
    ):
        return compute_expires_at_from_ttl(category_policy.default_ttl_days, now), TtlSource.CATEGORY

    for policy, source in (
        (user_policy, TtlSource.USER),
        (agent_policy, TtlSource.AGENT),
        (workspace_policy, TtlSource.WORKSPACE),
        (default_policy, TtlSource.DEFAULT),
    ):
        if policy and policy.enabled and policy.default_ttl_days and policy.default_ttl_days > 0:
            return compute_expires_at_from_ttl(policy.default_ttl_days, now), source

    return None, TtlSource.DEFAULT


def annotate_memory_result(
    item: Dict[str, Any],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Add expires_at / ttl_state / ttl_source to a memory dict payload (in place).

    - If payload already has ttl_state/ttl_source they are preserved.
    - ttl_state is always recomputed from expires_at to keep it honest.
    - expires_at is always normalised to ISO UTC string or None.
    """
    if now is None:
        now = _now_utc()

    raw_expires = item.get("expires_at")
    parsed = _parse_iso_datetime(raw_expires)
    item["expires_at"] = parsed.isoformat() if parsed else None

    item["ttl_state"] = compute_ttl_state(item["expires_at"], now=now).value

    if "ttl_source" not in item or not item["ttl_source"]:
        item["ttl_source"] = TtlSource.DEFAULT.value

    return item
