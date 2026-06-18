"""Quick functional smoke tests for lifecycle policy features."""

from __future__ import annotations

import datetime

from mem0.configs.base import LifecyclePoliciesConfig
from mem0.memory.lifecycle import (
    LifecyclePolicy,
    TtlSource,
    TtlState,
    annotate_memory_result,
    compute_ttl_state,
    resolve_expiration,
)


def test_ttl_state_enum_values():
    assert TtlState.ACTIVE.value == "active"
    assert TtlState.EXPIRING_SOON.value == "expiring_soon"
    assert TtlState.EXPIRED.value == "expired"
    assert TtlState.PERMANENT.value == "permanent"


def test_ttl_source_enum_values():
    assert TtlSource.DEFAULT.value == "default"
    assert TtlSource.CATEGORY.value == "category"
    assert TtlSource.USER.value == "user"
    assert TtlSource.AGENT.value == "agent"
    assert TtlSource.WORKSPACE.value == "workspace"
    assert TtlSource.REQUEST.value == "request"


def test_compute_ttl_state_basic():
    now = datetime.datetime(2025, 6, 15, tzinfo=datetime.timezone.utc)
    assert compute_ttl_state(None, now=now) == TtlState.PERMANENT
    assert compute_ttl_state("2020-01-01T00:00:00Z", now=now) == TtlState.EXPIRED
    # 3 days out = expiring soon
    assert compute_ttl_state("2025-06-18T00:00:00Z", now=now) == TtlState.EXPIRING_SOON
    # 30 days out = active
    assert compute_ttl_state("2025-07-15T00:00:00Z", now=now) == TtlState.ACTIVE


def test_resolve_expiration_precedence_chain():
    now = datetime.datetime(2025, 6, 15, tzinfo=datetime.timezone.utc)
    default_p = LifecyclePolicy(default_ttl_days=90, enabled=True)
    workspace_p = LifecyclePolicy(default_ttl_days=60, enabled=True)
    agent_p = LifecyclePolicy(default_ttl_days=45, enabled=True)
    user_p = LifecyclePolicy(default_ttl_days=30, enabled=True)
    category_p = LifecyclePolicy(default_ttl_days=14, enabled=True)

    # 1. default only → 90d
    exp, src = resolve_expiration(default_policy=default_p, now=now)
    assert src == TtlSource.DEFAULT
    # Should be roughly 2025-09-13 = 90 days from 2025-06-15
    target = (now + datetime.timedelta(days=90)).isoformat()
    assert exp == target

    # 2. workspace beats default → 60d
    exp, src = resolve_expiration(
        workspace_policy=workspace_p, default_policy=default_p, now=now
    )
    assert src == TtlSource.WORKSPACE

    # 3. agent beats workspace → 45d
    exp, src = resolve_expiration(
        agent_policy=agent_p,
        workspace_policy=workspace_p,
        default_policy=default_p,
        now=now,
    )
    assert src == TtlSource.AGENT

    # 4. user beats agent → 30d
    exp, src = resolve_expiration(
        user_policy=user_p,
        agent_policy=agent_p,
        workspace_policy=workspace_p,
        default_policy=default_p,
        now=now,
    )
    assert src == TtlSource.USER

    # 5. category beats user → 14d
    exp, src = resolve_expiration(
        category_policy=category_p,
        user_policy=user_p,
        agent_policy=agent_p,
        workspace_policy=workspace_p,
        default_policy=default_p,
        now=now,
    )
    assert src == TtlSource.CATEGORY

    # 6. explicit ttl_days beats everything
    exp, src = resolve_expiration(
        request_ttl_days=5,
        category_policy=category_p,
        user_policy=user_p,
        default_policy=default_p,
        now=now,
    )
    assert src == TtlSource.REQUEST
    target_5 = (now + datetime.timedelta(days=5)).isoformat()
    assert exp == target_5

    # 7. explicit expires beats ttl_days
    explicit = (now + datetime.timedelta(days=2)).isoformat()
    exp, src = resolve_expiration(
        request_expires=explicit,
        request_ttl_days=5,
        category_policy=category_p,
        default_policy=default_p,
        now=now,
    )
    assert src == TtlSource.REQUEST
    assert exp == explicit


def test_resolve_expiration_disabled_policy_skipped():
    now = datetime.datetime(2025, 6, 15, tzinfo=datetime.timezone.utc)
    disabled_workspace = LifecyclePolicy(default_ttl_days=60, enabled=False)
    default_p = LifecyclePolicy(default_ttl_days=90, enabled=True)
    exp, src = resolve_expiration(
        workspace_policy=disabled_workspace, default_policy=default_p, now=now
    )
    # Workspace disabled → falls through to default
    assert src == TtlSource.DEFAULT


def test_resolve_expiration_no_policy_permanent():
    exp, src = resolve_expiration()
    assert exp is None
    assert src == TtlSource.DEFAULT


def test_annotate_memory_result_round_trip():
    now = datetime.datetime(2025, 6, 15, tzinfo=datetime.timezone.utc)

    # permanent
    item = annotate_memory_result({"id": "1", "memory": "hello"}, now=now)
    assert item["ttl_state"] == "permanent"
    assert item["expires_at"] is None

    # active 30 days
    future = (now + datetime.timedelta(days=30)).isoformat()
    item = annotate_memory_result(
        {"id": "2", "memory": "hi", "expires_at": future, "ttl_source": "user"},
        now=now,
    )
    assert item["ttl_state"] == "active"
    assert item["ttl_source"] == "user"

    # expired
    item = annotate_memory_result(
        {"id": "3", "memory": "old", "expires_at": "2020-01-01T00:00:00Z"},
        now=now,
    )
    assert item["ttl_state"] == "expired"


def test_lifecycle_config_extra_scopes():
    """User/agent/category maps are present and empty by default."""
    cfg = LifecyclePoliciesConfig()
    assert cfg.users == {}
    assert cfg.agents == {}
    assert cfg.categories == {}

    cfg2 = LifecyclePoliciesConfig(
        users={"alice": {"default_ttl_days": 30, "enabled": True}},
        categories={"sensitive": {"default_ttl_days": 7, "enabled": True}},
    )
    assert cfg2.users["alice"].default_ttl_days == 30
    assert cfg2.categories["sensitive"].default_ttl_days == 7


def test_lifecycle_policy_from_dict_to_dict():
    p = LifecyclePolicy(default_ttl_days=15, enabled=True)
    d = p.to_dict()
    p2 = LifecyclePolicy.from_dict(d)
    assert p2.default_ttl_days == 15
    assert p2.enabled is True

    p3 = LifecyclePolicy.from_dict(None)
    assert p3.default_ttl_days is None
    assert p3.enabled is True


def test_resolve_expiration_multi_category_shortest_wins():
    """When a memory has multiple categories, the shortest TTL wins."""
    now = datetime.datetime(2025, 6, 15, tzinfo=datetime.timezone.utc)
    cat_policies = {
        "work": LifecyclePolicy(default_ttl_days=90, enabled=True),
        "sensitive": LifecyclePolicy(default_ttl_days=7, enabled=True),
        "personal": LifecyclePolicy(default_ttl_days=30, enabled=True),
    }
    exp, src = resolve_expiration(
        categories=["work", "personal"],
        category_policies=cat_policies,
        now=now,
    )
    assert src == TtlSource.CATEGORY
    # shortest is personal = 30 days (work=90, personal=30)
    expected = now + datetime.timedelta(days=30)
    assert exp == expected.isoformat()

    # Add sensitive → shortest becomes 7 days
    exp2, src2 = resolve_expiration(
        categories=["work", "sensitive", "personal"],
        category_policies=cat_policies,
        now=now,
    )
    assert src2 == TtlSource.CATEGORY
    expected2 = now + datetime.timedelta(days=7)
    assert exp2 == expected2.isoformat()


def test_resolve_expiration_multi_category_some_disabled():
    """Disabled category policies are skipped; we still pick the shortest enabled one."""
    now = datetime.datetime(2025, 6, 15, tzinfo=datetime.timezone.utc)
    cat_policies = {
        "work": LifecyclePolicy(default_ttl_days=90, enabled=False),
        "personal": LifecyclePolicy(default_ttl_days=30, enabled=True),
    }
    exp, src = resolve_expiration(
        categories=["work", "personal"],
        category_policies=cat_policies,
        default_policy=LifecyclePolicy(default_ttl_days=365, enabled=True),
        now=now,
    )
    assert src == TtlSource.CATEGORY
    expected = now + datetime.timedelta(days=30)
    assert exp == expected.isoformat()


def test_resolve_expiration_no_matching_category_falls_through():
    now = datetime.datetime(2025, 6, 15, tzinfo=datetime.timezone.utc)
    cat_policies = {"other": LifecyclePolicy(default_ttl_days=7, enabled=True)}
    exp, src = resolve_expiration(
        categories=["random"],
        category_policies=cat_policies,
        default_policy=LifecyclePolicy(default_ttl_days=365, enabled=True),
        now=now,
    )
    assert src == TtlSource.DEFAULT
    expected = now + datetime.timedelta(days=365)
    assert exp == expected.isoformat()


def test_annotate_memory_result_preserves_categories():
    """categories list passes through annotate_memory_result unchanged."""
    item = {
        "id": "1",
        "memory": "test",
        "categories": ["work", "personal"],
        "expires_at": "2025-12-31T00:00:00+00:00",
    }
    result = annotate_memory_result(item)
    assert result["categories"] == ["work", "personal"]
    assert result["ttl_state"] == "active"


if __name__ == "__main__":
    import sys

    test_ttl_state_enum_values()
    test_ttl_source_enum_values()
    test_compute_ttl_state_basic()
    test_resolve_expiration_precedence_chain()
    test_resolve_expiration_disabled_policy_skipped()
    test_resolve_expiration_no_policy_permanent()
    test_annotate_memory_result_round_trip()
    test_lifecycle_config_extra_scopes()
    test_lifecycle_policy_from_dict_to_dict()
    print("All lifecycle policy tests passed.")
    sys.exit(0)
