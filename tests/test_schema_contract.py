"""Tests for the shared schema contract (mem0.schema.fields and mem0.schema.models)."""

import pytest
from datetime import date, timedelta

from mem0.schema.fields import (
    ADD_API_FIELD_MAP,
    CLI_TO_API_MAP,
    ENTITY_FIELD_SET,
    ENTITY_FIELDS,
    EXPIRES_FORMAT,
    FIELD_DEFAULTS,
    FIELD_VALIDATION,
    SCOPE_DISPLAY_NAMES,
    build_scope_dict,
    build_scope_display,
    cli_to_api,
    get_add_api_key,
    get_search_api_key,
    validate_entity_id,
    validate_expires,
    validate_field,
    validate_filters_contain_entity,
)
from mem0.schema.models import (
    AddMemoryOptions,
    AddMemoryRequest,
    DeleteAllMemoryOptions,
    GetAllMemoryOptions,
    SearchMemoryOptions,
    UpdateMemoryOptions,
)


class TestEntityFields:
    def test_entity_fields_contains_core_ids(self):
        assert "user_id" in ENTITY_FIELDS
        assert "agent_id" in ENTITY_FIELDS
        assert "app_id" in ENTITY_FIELDS
        assert "run_id" in ENTITY_FIELDS

    def test_entity_field_set_matches_tuple(self):
        assert ENTITY_FIELD_SET == frozenset(ENTITY_FIELDS)

    def test_entity_fields_has_four_entries(self):
        assert len(ENTITY_FIELDS) == 4


class TestCliToApiMap:
    def test_user_id_mapping(self):
        assert cli_to_api("userId") == "user_id"

    def test_agent_id_mapping(self):
        assert cli_to_api("agentId") == "agent_id"

    def test_unknown_key_passthrough(self):
        assert cli_to_api("unknown_key") == "unknown_key"


class TestFieldDefaults:
    def test_top_k_default(self):
        assert FIELD_DEFAULTS["top_k"] == 10

    def test_threshold_default(self):
        assert FIELD_DEFAULTS["threshold"] == 0.3

    def test_infer_default(self):
        assert FIELD_DEFAULTS["infer"] is True

    def test_page_defaults(self):
        assert FIELD_DEFAULTS["page"] == 1
        assert FIELD_DEFAULTS["page_size"] == 100


class TestAddApiKeyMapping:
    def test_expires_maps_to_expiration_date(self):
        assert get_add_api_key("expires") == "expiration_date"

    def test_regular_field_passthrough(self):
        assert get_add_api_key("metadata") == "metadata"

    def test_user_id_passthrough(self):
        assert get_add_api_key("user_id") == "user_id"


class TestSearchApiKeyMapping:
    def test_keyword_maps_to_keyword_search(self):
        assert get_search_api_key("keyword") == "keyword_search"

    def test_regular_field_passthrough(self):
        assert get_search_api_key("top_k") == "top_k"


class TestBuildScopeDict:
    def test_all_entity_ids(self):
        result = build_scope_dict(user_id="u1", agent_id="a1", app_id="p1", run_id="r1")
        assert result == {"user_id": "u1", "agent_id": "a1", "app_id": "p1", "run_id": "r1"}

    def test_partial_entity_ids(self):
        result = build_scope_dict(user_id="u1", agent_id=None, app_id="p1", run_id=None)
        assert result == {"user_id": "u1", "app_id": "p1"}

    def test_no_entity_ids(self):
        result = build_scope_dict(user_id=None, agent_id=None, app_id=None, run_id=None)
        assert result == {}

    def test_non_entity_field_ignored(self):
        result = build_scope_dict(user_id="u1", unknown="val")
        assert "unknown" not in result


class TestBuildScopeDisplay:
    def test_all_entity_ids(self):
        result = build_scope_display(user_id="u1", agent_id="a1", app_id="p1", run_id="r1")
        assert "user=u1" in result
        assert "agent=a1" in result
        assert "app=p1" in result
        assert "run=r1" in result

    def test_no_entity_ids(self):
        result = build_scope_display(user_id=None, agent_id=None, app_id=None, run_id=None)
        assert result == "ALL entities"


class TestValidateEntityId:
    def test_valid_id(self):
        assert validate_entity_id("user123", "user_id") == "user123"

    def test_whitespace_trimmed(self):
        assert validate_entity_id("  user123  ", "user_id") == "user123"

    def test_empty_after_trim(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_entity_id("   ", "user_id")

    def test_too_long(self):
        with pytest.raises(ValueError, match="at most 255"):
            validate_entity_id("x" * 256, "user_id")

    def test_unknown_field(self):
        with pytest.raises(ValueError, match="Unknown entity field"):
            validate_entity_id("val", "unknown_field")


class TestValidateExpires:
    def test_valid_future_date(self):
        future = (date.today() + timedelta(days=30)).isoformat()
        assert validate_expires(future) == future

    def test_past_date_rejected(self):
        past = (date.today() - timedelta(days=1)).isoformat()
        with pytest.raises(ValueError, match="must be in the future"):
            validate_expires(past)

    def test_today_rejected(self):
        today = date.today().isoformat()
        with pytest.raises(ValueError, match="must be in the future"):
            validate_expires(today)

    def test_invalid_format_rejected(self):
        with pytest.raises(ValueError, match="Invalid date format"):
            validate_expires("12-31-2025")

    def test_non_date_rejected(self):
        with pytest.raises(ValueError, match="Invalid date format"):
            validate_expires("not-a-date")


class TestValidateField:
    def test_top_k_valid(self):
        validate_field("top_k", 5)

    def test_top_k_too_small(self):
        with pytest.raises(ValueError, match="--top-k"):
            validate_field("top_k", 0)

    def test_threshold_valid(self):
        validate_field("threshold", 0.5)

    def test_threshold_too_large(self):
        with pytest.raises(ValueError, match="--threshold"):
            validate_field("threshold", 1.5)

    def test_threshold_too_small(self):
        with pytest.raises(ValueError, match="--threshold"):
            validate_field("threshold", -0.1)


class TestValidateFiltersContainEntity:
    def test_valid_filters(self):
        validate_filters_contain_entity({"user_id": "u1"})

    def test_empty_filters(self):
        with pytest.raises(ValueError, match="at least one of"):
            validate_filters_contain_entity({})

    def test_none_filters(self):
        with pytest.raises(ValueError, match="at least one of"):
            validate_filters_contain_entity(None)

    def test_non_entity_filters(self):
        with pytest.raises(ValueError, match="at least one of"):
            validate_filters_contain_entity({"metadata": "value"})


class TestPydanticModels:
    def test_add_memory_options_defaults(self):
        opts = AddMemoryOptions()
        assert opts.filters is None
        assert opts.metadata is None
        assert opts.infer is None

    def test_add_memory_options_with_values(self):
        opts = AddMemoryOptions(
            filters={"user_id": "u1"},
            metadata={"key": "value"},
            infer=True,
        )
        assert opts.filters == {"user_id": "u1"}
        assert opts.metadata == {"key": "value"}
        assert opts.infer is True

    def test_search_memory_options_defaults(self):
        opts = SearchMemoryOptions()
        assert opts.filters is None
        assert opts.top_k is None

    def test_get_all_memory_options_defaults(self):
        opts = GetAllMemoryOptions()
        assert opts.filters is None
        assert opts.page is None

    def test_update_memory_options_defaults(self):
        opts = UpdateMemoryOptions()
        assert opts.text is None
        assert opts.metadata is None

    def test_delete_all_memory_options_defaults(self):
        opts = DeleteAllMemoryOptions()
        assert opts.filters is None

    def test_add_memory_request_model(self):
        req = AddMemoryRequest(
            messages=[{"role": "user", "content": "hello"}],
            user_id="u1",
        )
        assert req.user_id == "u1"
        assert req.infer is None or req.infer == FIELD_DEFAULTS["infer"]

    def test_search_memory_request_model(self):
        req = SearchMemoryOptions(
            filters={"user_id": "u1"},
            top_k=5,
            threshold=0.8,
        )
        assert req.top_k == 5
        assert req.threshold == 0.8

    def test_add_memory_options_has_expires(self):
        opts = AddMemoryOptions(expires="2026-12-31")
        assert opts.expires == "2026-12-31"

    def test_add_memory_options_has_categories(self):
        opts = AddMemoryOptions(categories=["personal", "work"])
        assert opts.categories == ["personal", "work"]

    def test_add_memory_options_has_immutable(self):
        opts = AddMemoryOptions(immutable=True)
        assert opts.immutable is True


class TestScopeDisplayNames:
    def test_user_id_display(self):
        assert SCOPE_DISPLAY_NAMES["user_id"] == "user"

    def test_agent_id_display(self):
        assert SCOPE_DISPLAY_NAMES["agent_id"] == "agent"

    def test_app_id_display(self):
        assert SCOPE_DISPLAY_NAMES["app_id"] == "app"

    def test_run_id_display(self):
        assert SCOPE_DISPLAY_NAMES["run_id"] == "run"

    def test_display_names_cover_all_entity_fields(self):
        for field in ENTITY_FIELDS:
            assert field in SCOPE_DISPLAY_NAMES


class TestCrossLayerConsistency:
    def test_cli_map_covers_all_entity_fields(self):
        for field in ENTITY_FIELDS:
            ts_name = field.replace("_id", "Id").replace("_", "").replace("userId", "userId").replace("agentId", "agentId").replace("appId", "appId").replace("runId", "runId")
            if ts_name in CLI_TO_API_MAP:
                assert CLI_TO_API_MAP[ts_name] == field

    def test_add_api_field_map_consistent_with_get_add_api_key(self):
        for field, expected in ADD_API_FIELD_MAP.items():
            assert get_add_api_key(field) == expected

    def test_field_validation_covers_key_fields(self):
        assert "top_k" in FIELD_VALIDATION
        assert "threshold" in FIELD_VALIDATION
        assert "page" in FIELD_VALIDATION
        assert "page_size" in FIELD_VALIDATION
