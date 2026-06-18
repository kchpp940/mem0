import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from memory_utils import (
    EntityResponseItem,
    EntityResponseModel,
    MemoryResponseItem,
    MemoryResponseModel,
    VALID_ENTITY_TYPES,
    format_memory_response,
    format_vector_store_row,
    is_entity_response_item,
    is_memory_response_item,
    list_vector_store_memories,
    normalize_response,
)


def _typed_dict_keys(td_cls) -> set[str]:
    ann = getattr(td_cls, "__annotations__", {})
    return set(ann.keys())


def _pydantic_model_keys(model_cls) -> set[str]:
    return set(model_cls.model_fields.keys())


def _parse_ts_interface_fields(ts_content: str, interface_name: str) -> set[str]:
    pattern = rf"export\s+interface\s+{interface_name}\s*\{{([^}}]*)\}}"
    match = re.search(pattern, ts_content)
    if not match:
        return set()
    body = match.group(1)
    fields = set()
    for line in body.strip().split("\n"):
        line = line.strip().rstrip(";").rstrip(",")
        if not line or line.startswith("//") or line.startswith("/*"):
            continue
        parts = line.split(":")
        if len(parts) >= 2:
            name = parts[0].strip().rstrip("?")
            if name.isidentifier():
                fields.add(name)
    return fields


_TS_API_PATH = os.path.join(
    os.path.dirname(__file__), "..", "server", "dashboard", "src", "types", "api.ts"
)


class TestMemorySchemaParity:
    def test_typed_dict_matches_pydantic_model(self):
        td_keys = _typed_dict_keys(MemoryResponseItem)
        pydantic_keys = _pydantic_model_keys(MemoryResponseModel)
        assert td_keys == pydantic_keys, (
            f"MemoryResponseItem TypedDict keys != MemoryResponseModel Pydantic fields.\n"
            f"  In TypedDict only: {td_keys - pydantic_keys}\n"
            f"  In Pydantic only: {pydantic_keys - td_keys}"
        )

    def test_typed_dict_matches_ts_interface(self):
        if not os.path.exists(_TS_API_PATH):
            return
        ts_content = open(_TS_API_PATH).read()
        ts_fields = _parse_ts_interface_fields(ts_content, "Memory")
        td_keys = _typed_dict_keys(MemoryResponseItem)
        assert td_keys == ts_fields, (
            f"MemoryResponseItem TypedDict keys != TS Memory interface fields.\n"
            f"  In TypedDict only: {td_keys - ts_fields}\n"
            f"  In TS only: {ts_fields - td_keys}"
        )

    def test_pydantic_model_validates_output(self):
        item = format_memory_response(
            {"id": "x", "memory": "test", "user_id": "u1", "actor_id": "alice"},
            score=0.9,
        )
        validated = MemoryResponseModel.model_validate(item)
        assert validated.id == "x"
        assert validated.memory == "test"
        assert validated.user_id == "u1"
        assert validated.actor_id == "alice"
        assert validated.score == 0.9

    def test_pydantic_model_validates_vector_store_row(self):
        class FakeRow:
            id = "r1"
            payload = {"data": "hi", "user_id": "u1"}

        item = format_vector_store_row(FakeRow())
        validated = MemoryResponseModel.model_validate(item)
        assert validated.id == "r1"
        assert validated.memory == "hi"
        assert validated.user_id == "u1"

    def test_internal_fields_not_in_model(self):
        model_fields = _pydantic_model_keys(MemoryResponseModel)
        for field in ("text_lemmatized", "attributed_to", "data"):
            assert field not in model_fields, f"Internal field '{field}' should not be in MemoryResponseModel"


class TestEntitySchemaParity:
    def test_typed_dict_matches_pydantic_model(self):
        td_keys = _typed_dict_keys(EntityResponseItem)
        pydantic_keys = _pydantic_model_keys(EntityResponseModel)
        assert td_keys == pydantic_keys, (
            f"EntityResponseItem TypedDict keys != EntityResponseModel Pydantic fields.\n"
            f"  In TypedDict only: {td_keys - pydantic_keys}\n"
            f"  In Pydantic only: {pydantic_keys - td_keys}"
        )

    def test_typed_dict_matches_ts_interface(self):
        if not os.path.exists(_TS_API_PATH):
            return
        ts_content = open(_TS_API_PATH).read()
        ts_fields = _parse_ts_interface_fields(ts_content, "Entity")
        td_keys = _typed_dict_keys(EntityResponseItem)
        assert td_keys == ts_fields, (
            f"EntityResponseItem TypedDict keys != TS Entity interface fields.\n"
            f"  In TypedDict only: {td_keys - ts_fields}\n"
            f"  In TS only: {ts_fields - td_keys}"
        )

    def test_entity_type_values_match_ts(self):
        if not os.path.exists(_TS_API_PATH):
            return
        ts_content = open(_TS_API_PATH).read()
        pattern = r'export\s+type\s+EntityType\s*=\s*([^;]+);'
        match = re.search(pattern, ts_content)
        if not match:
            return
        ts_values = {v.strip().strip('"').strip("'") for v in match.group(1).split("|")}
        assert ts_values == VALID_ENTITY_TYPES, (
            f"EntityType values mismatch.\n  Backend: {VALID_ENTITY_TYPES}\n  TS: {ts_values}"
        )

    def test_entities_router_model_extends_shared_model(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server", "routers"))
        try:
            from entities import Entity
            base_fields = _pydantic_model_keys(EntityResponseModel)
            entity_fields = _pydantic_model_keys(Entity)
            assert base_fields.issubset(entity_fields), (
                f"Entity model should extend EntityResponseModel.\n"
                f"  Missing base fields: {base_fields - entity_fields}"
            )
        except ImportError:
            pass


class TestEndpointResponseShapeCompatibility:
    def test_post_memories_preserves_list_shape(self):
        add_result = [{"id": "m1", "memory": "a", "event": "ADD", "actor_id": "alice"}]
        result = normalize_response(add_result)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["event"] == "ADD"
        assert result[0]["actor_id"] == "alice"
        MemoryResponseModel.model_validate(result[0])

    def test_post_memories_preserves_dict_shape(self):
        add_result = {"results": [{"id": "m1", "memory": "a", "event": "ADD"}]}
        result = normalize_response(add_result)
        assert isinstance(result, dict)
        assert set(result.keys()) == {"results"}
        MemoryResponseModel.model_validate(result["results"][0])

    def test_get_memories_no_filter_shape(self):
        class FakeRow:
            id = "r1"
            payload = {"data": "hi", "user_id": "u1", "text_lemmatized": "x"}

        class FakeVS:
            def list(self, top_k):
                return [[FakeRow()]]

        memories = list_vector_store_memories(FakeVS(), limit=100)
        outer = {"results": memories}
        assert isinstance(outer, dict)
        assert set(outer.keys()) == {"results"}
        assert "text_lemmatized" not in outer["results"][0]
        MemoryResponseModel.model_validate(outer["results"][0])

    def test_get_memories_with_filter_preserves_list_shape(self):
        get_all_list = [{"id": "m1", "memory": "a", "user_id": "u1"}]
        result = normalize_response(get_all_list)
        assert isinstance(result, list)
        MemoryResponseModel.model_validate(result[0])

    def test_get_memories_with_filter_preserves_dict_shape(self):
        get_all_dict = {"results": [{"id": "m1", "memory": "a", "user_id": "u1"}]}
        result = normalize_response(get_all_dict)
        assert isinstance(result, dict) and "results" in result
        MemoryResponseModel.model_validate(result["results"][0])

    def test_get_memory_by_id_shape(self):
        get_result = {"id": "m1", "memory": "hi", "actor_id": "bob", "metadata": {"custom": "y"}}
        result = normalize_response(get_result)
        assert isinstance(result, dict)
        MemoryResponseModel.model_validate(result)

    def test_post_search_shape(self):
        search_result = {
            "results": [
                {"id": "m1", "memory": "a", "score": 0.9, "metadata": {"category": "sports"}},
                {"id": "m2", "memory": "b", "score": 0.8, "actor_id": "alice"},
            ]
        }
        result = normalize_response(search_result)
        assert isinstance(result, dict)
        assert set(result.keys()) == {"results"}
        assert result["results"][0]["score"] == 0.9
        assert result["results"][1]["actor_id"] == "alice"
        MemoryResponseModel.model_validate(result["results"][0])
        MemoryResponseModel.model_validate(result["results"][1])

    def test_get_entities_shape(self):
        entities = [
            {"id": "u1", "type": "user", "total_memories": 10, "created_at": "2025"},
            {"id": "a1", "type": "agent", "total_memories": 3},
        ]
        result = normalize_response(entities)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["id"] == "u1"
        assert result[0]["type"] == "user"
        assert not any(is_memory_response_item(e) for e in result)
        assert all(is_entity_response_item(e) for e in result)
        for e in result:
            EntityResponseModel.model_validate(e)

    def test_put_memories_message_passthrough(self):
        update_msg = {"message": "Memory updated"}
        result = normalize_response(update_msg)
        assert result == update_msg
        assert not is_memory_response_item(result)

    def test_delete_message_passthrough(self):
        delete_msg = {"message": "Memory deleted successfully"}
        result = normalize_response(delete_msg)
        assert result == delete_msg
        assert not is_memory_response_item(result)

    def test_non_memory_list_passthrough(self):
        api_logs = [
            {"id": "log1", "method": "GET", "path": "/x"},
            {"id": "log2", "method": "POST", "path": "/y"},
        ]
        result = normalize_response(api_logs)
        assert result == api_logs

    def test_dict_with_non_memory_results_passthrough(self):
        response = {"results": [{"id": "log1", "method": "GET"}]}
        result = normalize_response(response)
        assert result == response
