"""Contract-driven payload builder for Platform API requests.

All field names, defaults, error messages, filter merge order, and PENDING
dedup rules are derived from the shared payload_contract.json so Python and
Node CLIs produce identical request payloads with consistent behaviour.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from importlib.resources import files
from typing import Any

from mem0_cli.branding import print_error

_CONTRACT_PATH = files("mem0_cli.contract").joinpath("payload_contract.json")
_CONTRACT: dict[str, Any] = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))


def _validation() -> dict[str, Any]:
    return _CONTRACT["validation"]


def _field_mapping() -> dict[str, str]:
    return _CONTRACT["fieldMapping"]


def _filter_building() -> dict[str, Any]:
    return _CONTRACT["filterBuilding"]


def _pending_dedup() -> dict[str, Any]:
    return _CONTRACT["pendingDedup"]


def _agent_pick_fields() -> dict[str, Any]:
    return _CONTRACT["agentPickFields"]


def _resolve_api_name(field_def: dict[str, Any]) -> str:
    from_name = field_def.get("from", field_def.get("api"))
    if field_def.get("mapped") and from_name in _field_mapping():
        return _field_mapping()[from_name]
    return field_def["api"]


@dataclass
class ValidationError(Exception):
    """Raised when parameter validation fails."""

    message: str


def normalize_categories(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    v = _validation()["categories"]
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValidationError(v["arrayError"])
        return [str(c).strip() for c in parsed if c]
    except json.JSONDecodeError:
        return [c.strip() for c in raw.split(",") if c.strip()]


def validate_expires(raw: str | None) -> str | None:
    if not raw:
        return None
    v = _validation()["expires"]
    if not re.match(v["pattern"], raw):
        raise ValidationError(v["formatError"])
    if date.fromisoformat(raw) <= date.today():
        raise ValidationError(v["futureError"])
    return raw


def parse_filter_json(raw: str | None) -> dict | None:
    if not raw:
        return None
    v = _validation()["filters"]
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValidationError(v["objectError"])
        return parsed
    except json.JSONDecodeError as e:
        raise ValidationError(v["jsonError"].replace("{error}", str(e))) from None


def build_filters(
    *,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    extra_filters: dict | None = None,
) -> dict | None:
    fb = _filter_building()

    if extra_filters:
        for key in fb["passthroughKeys"]:
            if key in extra_filters:
                return extra_filters

    entity_order: list[str] = fb["entityOrder"]
    entity_values = {
        "user_id": user_id,
        "agent_id": agent_id,
        "app_id": app_id,
        "run_id": run_id,
    }

    and_conditions: list[dict[str, Any]] = []
    for field_name in entity_order:
        val = entity_values.get(field_name)
        if val:
            and_conditions.append({field_name: val})

    if extra_filters:
        for k, v in extra_filters.items():
            and_conditions.append({k: v})

    if len(and_conditions) == 1:
        return and_conditions[0]
    elif and_conditions:
        return {fb["combineOperator"]: and_conditions}
    return None


def build_add_payload(
    *,
    content: str | None = None,
    messages: list[dict] | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    metadata: dict | None = None,
    immutable: bool = False,
    infer: bool = True,
    expires: str | None = None,
    categories: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    source = _CONTRACT["source"]
    role = _CONTRACT["addMessageRole"]

    local_vars = {
        "messages": messages,
        "user_id": user_id,
        "agent_id": agent_id,
        "app_id": app_id,
        "run_id": run_id,
        "metadata": metadata,
        "immutable": immutable,
        "infer": infer,
        "expires": expires,
        "categories": categories,
    }

    for field_def in _CONTRACT["addFields"]:
        api_name = _resolve_api_name(field_def)
        from_name = field_def.get("from", "")

        if "literal" in field_def:
            payload[api_name] = field_def["literal"]
            continue

        if field_def.get("type") == "messages_or_content":
            if messages:
                payload[api_name] = messages
            elif content:
                payload[api_name] = [{"role": role, "content": content}]
            continue

        value = local_vars.get(from_name)

        if value is None:
            continue

        rule = field_def.get("rule")
        if rule == "includeWhenTrue" and not value:
            continue
        if rule == "includeWhenFalse" and value:
            continue

        payload[api_name] = value

    if "source" not in payload:
        payload["source"] = source

    return payload


def build_search_payload(
    query: str,
    *,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    top_k: int | None = None,
    threshold: float | None = None,
    rerank: bool = False,
    keyword: bool = False,
    filters: dict | None = None,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    defaults = _CONTRACT["defaults"]
    source = _CONTRACT["source"]

    payload: dict[str, Any] = {
        "query": query,
        "top_k": top_k if top_k is not None else defaults["top_k"],
        "threshold": threshold if threshold is not None else defaults["threshold"],
    }

    api_filters = build_filters(
        user_id=user_id,
        agent_id=agent_id,
        app_id=app_id,
        run_id=run_id,
        extra_filters=filters,
    )
    if api_filters:
        payload["filters"] = api_filters

    local_vars = {
        "rerank": rerank,
        "keyword": keyword,
        "fields": fields,
    }

    for field_def in _CONTRACT["searchFields"]:
        api_name = _resolve_api_name(field_def)
        from_name = field_def.get("from", "")

        if "literal" in field_def:
            payload[api_name] = field_def["literal"]
            continue

        if api_name in payload or from_name in ("query", "top_k", "threshold", "filters"):
            continue

        value = local_vars.get(from_name)
        if value is None:
            continue

        rule = field_def.get("rule")
        if rule == "includeWhenTrue" and not value:
            continue
        if rule == "includeWhenFalse" and value:
            continue

        payload[api_name] = value

    if "source" not in payload:
        payload["source"] = source

    return payload


def build_list_payload(
    *,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    category: str | None = None,
    after: str | None = None,
    before: str | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    payload: dict[str, Any] = {}
    params: dict[str, str] = {}

    list_extra = _filter_building().get("listExtra", {})
    extra: dict[str, Any] = {}

    if category and "category" in list_extra:
        spec = list_extra["category"]
        extra[spec["field"]] = {spec["op"]: category}

    created_at_parts: dict[str, str] = {}
    if after and "after" in list_extra:
        spec = list_extra["after"]
        created_at_parts[spec["op"]] = after
    if before and "before" in list_extra:
        spec = list_extra["before"]
        created_at_parts[spec["op"]] = before
    if created_at_parts and "after" in list_extra:
        spec = list_extra["after"]
        extra[spec["field"]] = created_at_parts

    api_filters = build_filters(
        user_id=user_id,
        agent_id=agent_id,
        app_id=app_id,
        run_id=run_id,
        extra_filters=extra if extra else None,
    )
    if api_filters:
        payload["filters"] = api_filters
    payload["source"] = _CONTRACT["source"]

    return payload, params


def handle_validation_error(err: ValidationError, err_console: Any) -> None:
    print_error(err_console, err.message)
    raise SystemExit(1) from None
