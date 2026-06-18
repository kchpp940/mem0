import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from memory_utils import (
    EntityResponseItem,
    EntityResponseModel,
    MemoryListResponse,
    MemoryResponseItem,
    MemoryResponseModel,
    USER_METADATA_EXCLUDE,
    VALID_ENTITY_TYPES,
    extract_payload,
    format_memory_response,
    format_vector_store_row,
    is_entity_response_item,
    is_memory_response_item,
    iter_formatted_rows,
    list_vector_store_memories,
    normalize_memory_item,
    normalize_memory_list,
    normalize_response,
)


class TestTypedDictSchemas:
    def test_memory_response_item_fields(self):
        item = MemoryResponseItem(
            id="abc",
            memory="hello",
            user_id="u1",
            agent_id="a1",
            run_id="r1",
            actor_id="alice",
            role="user",
            hash="h1",
            metadata={"tag": "x"},
            score=0.9,
            score_details={"semantic": 0.8},
            event="ADD",
            created_at="2025-01-01",
            updated_at="2025-01-02",
        )
        assert item["id"] == "abc"
        assert item["memory"] == "hello"
        assert item["user_id"] == "u1"
        assert item["actor_id"] == "alice"
        assert item["score"] == 0.9

    def test_memory_response_item_partial(self):
        item = MemoryResponseItem(id="abc", memory="hello")
        assert item["id"] == "abc"
        assert item["memory"] == "hello"

    def test_entity_response_item_fields(self):
        entity = EntityResponseItem(
            id="u1",
            type="user",
            total_memories=10,
            created_at="2025-01-01",
            updated_at="2025-01-02",
        )
        assert entity["id"] == "u1"
        assert entity["type"] == "user"
        assert entity["total_memories"] == 10

    def test_memory_list_response(self):
        item = MemoryResponseItem(id="x", memory="y")
        resp = MemoryListResponse(results=[item])
        assert len(resp["results"]) == 1
        assert resp["results"][0]["id"] == "x"

    def test_entity_type_values(self):
        assert VALID_ENTITY_TYPES == {"user", "agent", "run"}


class TestIsMemoryResponseItem:
    def test_true_with_both_id_and_memory(self):
        assert is_memory_response_item({"id": "abc", "memory": "hello"}) is True

    def test_true_with_extra_fields(self):
        assert is_memory_response_item({"id": "abc", "memory": "hello", "user_id": "u1"}) is True

    def test_false_with_only_id(self):
        assert is_memory_response_item({"id": "abc", "name": "John"}) is False

    def test_false_with_only_memory(self):
        assert is_memory_response_item({"memory": "hello"}) is False

    def test_false_with_api_log_dict(self):
        log = {"id": "req-123", "method": "GET", "path": "/memories", "status_code": 200}
        assert is_memory_response_item(log) is False

    def test_false_with_api_key_dict(self):
        key = {"id": "k1", "label": "test", "key_prefix": "sk-", "created_at": "2025"}
        assert is_memory_response_item(key) is False

    def test_false_with_entity_dict(self):
        entity = {"id": "u1", "type": "user", "total_memories": 5}
        assert is_memory_response_item(entity) is False

    def test_false_non_dict(self):
        assert is_memory_response_item("not a dict") is False
        assert is_memory_response_item(None) is False
        assert is_memory_response_item(123) is False


class TestIsEntityResponseItem:
    def test_true_with_all_required_fields(self):
        assert is_entity_response_item({"id": "u1", "type": "user", "total_memories": 10}) is True

    def test_true_with_timestamp_fields(self):
        assert is_entity_response_item({
            "id": "a1", "type": "agent", "total_memories": 5,
            "created_at": "2025", "updated_at": "2025",
        }) is True

    def test_false_missing_id(self):
        assert is_entity_response_item({"type": "user", "total_memories": 5}) is False

    def test_false_missing_type(self):
        assert is_entity_response_item({"id": "u1", "total_memories": 5}) is False

    def test_false_missing_total_memories(self):
        assert is_entity_response_item({"id": "u1", "type": "user"}) is False

    def test_false_invalid_type_value(self):
        assert is_entity_response_item({"id": "u1", "type": "invalid", "total_memories": 5}) is False
        assert is_entity_response_item({"id": "u1", "type": "project", "total_memories": 5}) is False

    def test_false_memory_item_not_entity(self):
        assert is_entity_response_item({"id": "abc", "memory": "hello"}) is False

    def test_false_non_dict(self):
        assert is_entity_response_item("not a dict") is False


class TestExtractPayload:
    def test_extracts_payload_dict(self):
        class FakeRow:
            payload = {"data": "hello", "user_id": "u1"}
        assert extract_payload(FakeRow()) == {"data": "hello", "user_id": "u1"}

    def test_handles_none_payload(self):
        class FakeRow:
            payload = None
        assert extract_payload(FakeRow()) == {}

    def test_handles_missing_payload(self):
        class FakeRow:
            pass
        assert extract_payload(FakeRow()) == {}


class TestFormatMemoryResponse:
    def test_basic_fields_preserved(self):
        item = {
            "id": "abc-123",
            "memory": "Likes hiking",
            "hash": "deadbeef",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-02T00:00:00Z",
        }
        result = format_memory_response(item)
        assert result["id"] == "abc-123"
        assert result["memory"] == "Likes hiking"
        assert result["hash"] == "deadbeef"
        assert "metadata" not in result

    def test_promoted_keys_lifted_to_top_level(self):
        item = {
            "id": "abc",
            "memory": "test",
            "user_id": "u1",
            "agent_id": "a1",
            "run_id": "r1",
            "actor_id": "alice",
            "role": "user",
        }
        result = format_memory_response(item)
        assert result["user_id"] == "u1"
        assert result["agent_id"] == "a1"
        assert result["run_id"] == "r1"
        assert result["actor_id"] == "alice"
        assert result["role"] == "user"

    def test_internal_fields_filtered_from_metadata(self):
        item = {
            "id": "abc",
            "memory": "test",
            "metadata": {
                "category": "sports",
                "text_lemmatized": "like hike",
                "attributed_to": "alice",
                "custom_field": "value",
            },
        }
        result = format_memory_response(item)
        assert result["metadata"]["category"] == "sports"
        assert result["metadata"]["custom_field"] == "value"
        assert "text_lemmatized" not in result["metadata"]
        assert "attributed_to" not in result["metadata"]
        assert "text_lemmatized" not in result
        assert "attributed_to" not in result

    def test_score_and_score_details(self):
        item = {"id": "abc", "memory": "test"}
        result = format_memory_response(item, score=0.95, score_details={"semantic": 0.9, "bm25": 0.8})
        assert result["score"] == 0.95
        assert result["score_details"]["semantic"] == 0.9

    def test_event_passthrough(self):
        item = {"id": "abc", "memory": "test", "event": "ADD"}
        result = format_memory_response(item)
        assert result["event"] == "ADD"

    def test_none_metadata_excluded(self):
        item = {"id": "abc", "memory": "test", "metadata": None}
        result = format_memory_response(item)
        assert "metadata" not in result

    def test_empty_metadata_excluded(self):
        item = {"id": "abc", "memory": "test", "metadata": {}}
        result = format_memory_response(item)
        assert "metadata" not in result

    def test_returns_typed_dict(self):
        result = format_memory_response({"id": "x", "memory": "y"})
        assert isinstance(result, dict)
        assert "id" in result and "memory" in result


class TestFormatVectorStoreRow:
    def test_basic_row(self):
        class FakeRow:
            id = "row-1"
            payload = {
                "data": "Likes hiking",
                "user_id": "u1",
                "agent_id": "a1",
                "run_id": "r1",
                "actor_id": "alice",
                "role": "user",
                "hash": "h1",
                "created_at": "2025-01-01",
                "updated_at": "2025-01-02",
            }

        result = format_vector_store_row(FakeRow())
        assert result["id"] == "row-1"
        assert result["memory"] == "Likes hiking"
        assert result["user_id"] == "u1"
        assert result["actor_id"] == "alice"
        assert result["role"] == "user"
        assert result["hash"] == "h1"
        assert "metadata" not in result

    def test_internal_fields_excluded_from_metadata(self):
        class FakeRow:
            id = "row-2"
            payload = {
                "data": "test",
                "user_id": "u1",
                "text_lemmatized": "test lemma",
                "attributed_to": "bob",
                "custom_key": "visible",
            }

        result = format_vector_store_row(FakeRow())
        assert result["memory"] == "test"
        assert "text_lemmatized" not in result
        assert "attributed_to" not in result
        assert "text_lemmatized" not in result.get("metadata", {})
        assert "attributed_to" not in result.get("metadata", {})
        assert result["metadata"]["custom_key"] == "visible"

    def test_empty_payload(self):
        class FakeRow:
            id = "row-3"
            payload = None
        result = format_vector_store_row(FakeRow())
        assert result["id"] == "row-3"
        assert result["memory"] == ""


class TestNormalizeMemoryItem:
    def test_dict_with_both_id_and_memory_normalized(self):
        item = {
            "id": "abc",
            "memory": "test",
            "user_id": "u1",
            "actor_id": "alice",
            "metadata": {"category": "sports", "text_lemmatized": "test"},
            "score": 0.9,
        }
        result = normalize_memory_item(item)
        assert result["user_id"] == "u1"
        assert result["actor_id"] == "alice"
        assert result["score"] == 0.9
        assert result["metadata"]["category"] == "sports"
        assert "text_lemmatized" not in result["metadata"]

    def test_id_only_not_normalized(self):
        item = {"id": "req-123", "method": "GET", "path": "/memories"}
        result = normalize_memory_item(item)
        assert result == item

    def test_memory_only_not_normalized(self):
        item = {"memory": "incomplete item"}
        result = normalize_memory_item(item)
        assert result == item

    def test_non_dict_returned_as_is(self):
        assert normalize_memory_item("not a dict") == "not a dict"

    def test_add_result_with_event(self):
        item = {"id": "abc", "memory": "test", "event": "ADD", "actor_id": "alice"}
        result = normalize_memory_item(item)
        assert result["event"] == "ADD"
        assert result["actor_id"] == "alice"


class TestNormalizeMemoryList:
    def test_formats_only_valid_memory_items(self):
        items = [
            {"id": "1", "memory": "first", "user_id": "u1"},
            {"id": "2", "memory": "second", "agent_id": "a1"},
            {"id": "log1", "path": "/memories", "method": "GET"},
            {"not": "a memory item"},
        ]
        result = normalize_memory_list(items)
        assert len(result) == 4
        assert result[0]["user_id"] == "u1"
        assert result[1]["agent_id"] == "a1"
        assert result[2] == {"id": "log1", "path": "/memories", "method": "GET"}
        assert result[3] == {"not": "a memory item"}


class TestNormalizeResponse:
    def test_preserves_dict_with_results_shape(self):
        response = {"results": [{"id": "1", "memory": "first"}, {"id": "2", "memory": "second"}]}
        result = normalize_response(response)
        assert isinstance(result, dict)
        assert "results" in result
        assert len(result["results"]) == 2
        assert set(result.keys()) == {"results"}

    def test_preserves_plain_list_shape(self):
        response = [{"id": "1", "memory": "first"}, {"id": "2", "memory": "second"}]
        result = normalize_response(response)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_preserves_single_memory_dict_shape(self):
        response = {"id": "abc", "memory": "a single memory"}
        result = normalize_response(response)
        assert isinstance(result, dict)
        assert result["memory"] == "a single memory"

    def test_preserves_other_response_shapes(self):
        msg = {"message": "Memory deleted successfully"}
        assert normalize_response(msg) == msg

    def test_preserves_entity_list_shape(self):
        entities = [
            {"id": "u1", "type": "user", "total_memories": 5},
            {"id": "a1", "type": "agent", "total_memories": 3},
        ]
        result = normalize_response(entities)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["id"] == "u1"
        assert result[0]["type"] == "user"

    def test_preserves_dict_with_non_memory_results(self):
        response = {"results": [{"id": "log1", "method": "GET", "path": "/x"}]}
        result = normalize_response(response)
        assert result == response

    def test_preserves_non_memory_plain_list(self):
        response = [{"id": "log1", "method": "GET"}, {"id": "log2", "method": "POST"}]
        result = normalize_response(response)
        assert result == response

    def test_normalizes_inner_items_in_results_dict(self):
        response = {
            "results": [
                {"id": "1", "memory": "first", "metadata": {"text_lemmatized": "xxx", "category": "a"}},
                {"id": "2", "memory": "second", "actor_id": "alice"},
            ]
        }
        result = normalize_response(response)
        assert "text_lemmatized" not in result["results"][0]["metadata"]
        assert result["results"][0]["metadata"]["category"] == "a"
        assert result["results"][1]["actor_id"] == "alice"

    def test_normalizes_inner_items_in_plain_list(self):
        response = [
            {"id": "1", "memory": "first", "metadata": {"attributed_to": "bob", "tag": "sports"}},
        ]
        result = normalize_response(response)
        assert "attributed_to" not in result[0]["metadata"]
        assert result[0]["metadata"]["tag"] == "sports"


class TestIterFormattedRows:
    def test_formats_multiple_rows(self):
        class FakeRow1:
            id = "r1"
            payload = {"data": "mem1", "user_id": "u1", "text_lemmatized": "x"}

        class FakeRow2:
            id = "r2"
            payload = {"data": "mem2", "agent_id": "a1", "custom": "val"}

        rows = [FakeRow1(), FakeRow2()]
        result = iter_formatted_rows(rows)
        assert len(result) == 2
        assert result[0]["memory"] == "mem1"
        assert result[0]["user_id"] == "u1"
        assert "text_lemmatized" not in result[0]
        assert result[1]["memory"] == "mem2"
        assert result[1]["agent_id"] == "a1"
        assert result[1]["metadata"]["custom"] == "val"


class TestListVectorStoreMemories:
    def test_handles_nested_list_structure(self):
        class FakeRow:
            id = "r1"
            payload = {"data": "hello", "user_id": "u1"}

        class FakeVS:
            def list(self, top_k):
                return [[FakeRow()]]

        result = list_vector_store_memories(FakeVS(), limit=10)
        assert len(result) == 1
        assert result[0]["memory"] == "hello"
        assert result[0]["user_id"] == "u1"

    def test_handles_flat_list_structure(self):
        class FakeRow:
            id = "r1"
            payload = {"data": "hi", "actor_id": "alice"}

        class FakeVS:
            def list(self, top_k):
                return [FakeRow()]

        result = list_vector_store_memories(FakeVS(), limit=10)
        assert len(result) == 1
        assert result[0]["memory"] == "hi"
        assert result[0]["actor_id"] == "alice"

    def test_passes_limit(self):
        class FakeVS:
            def list(self, top_k):
                self.called_top_k = top_k
                return []

        vs = FakeVS()
        list_vector_store_memories(vs, limit=42)
        assert vs.called_top_k == 42

    def test_handles_none_result(self):
        class FakeVS:
            def list(self, top_k):
                return None

        result = list_vector_store_memories(FakeVS(), limit=10)
        assert result == []


class TestInternalFieldConsistency:
    def test_all_excluded_fields_are_in_internal_keys(self):
        for field in USER_METADATA_EXCLUDE:
            assert field in {"data", "hash", "created_at", "updated_at", "id", "text_lemmatized", "attributed_to", "user_id", "agent_id", "run_id", "actor_id", "role"}

    def test_promoted_keys_not_in_metadata_after_format(self):
        item = {
            "id": "abc",
            "memory": "test",
            "user_id": "u1",
            "agent_id": "a1",
            "run_id": "r1",
            "actor_id": "alice",
            "role": "user",
            "metadata": {"extra": "value"},
        }
        result = format_memory_response(item)
        for key in ("user_id", "agent_id", "run_id", "actor_id", "role"):
            assert key in result
            assert key not in result.get("metadata", {})

    def test_internal_fields_never_leak_to_response(self):
        item = {
            "id": "abc",
            "memory": "test",
            "text_lemmatized": "should not appear",
            "attributed_to": "should not appear",
            "metadata": {
                "text_lemmatized": "also should not appear",
                "attributed_to": "also should not appear",
            },
        }
        result = format_memory_response(item)
        for key in ("text_lemmatized", "attributed_to"):
            assert key not in result
            assert key not in result.get("metadata", {})

    def test_strict_detection_prevents_false_positives(self):
        non_memory_objects = [
            {"id": "req-1", "path": "/memories", "method": "GET"},
            {"id": "key-1", "label": "production", "key_prefix": "sk-"},
            {"id": "user-1", "type": "user", "total_memories": 10},
            {"message": "ok"},
            {"id": "x", "data": "something without memory field"},
        ]
        for obj in non_memory_objects:
            assert is_memory_response_item(obj) is False, f"Should not detect as memory: {obj}"
            assert normalize_response(obj) == obj


class TestPydanticModelValidation:
    def test_memory_model_validates_format_output(self):
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

    def test_memory_model_validates_vector_store_row(self):
        class FakeRow:
            id = "r1"
            payload = {"data": "hi", "user_id": "u1"}

        item = format_vector_store_row(FakeRow())
        validated = MemoryResponseModel.model_validate(item)
        assert validated.id == "r1"
        assert validated.memory == "hi"
        assert validated.user_id == "u1"

    def test_entity_model_validates_entity_item(self):
        entity = {"id": "u1", "type": "user", "total_memories": 10}
        validated = EntityResponseModel.model_validate(entity)
        assert validated.id == "u1"
        assert validated.type == "user"
        assert validated.total_memories == 10

    def test_memory_model_rejects_internal_fields(self):
        for field in ("text_lemmatized", "attributed_to", "data"):
            assert field not in MemoryResponseModel.model_fields, f"Internal field '{field}' in model"


class TestSchemaParity:
    def test_memory_typed_dict_matches_pydantic(self):
        td_keys = set(MemoryResponseItem.__annotations__.keys())
        pydantic_keys = set(MemoryResponseModel.model_fields.keys())
        assert td_keys == pydantic_keys, (
            f"Memory TypedDict != Pydantic.\n  TD only: {td_keys - pydantic_keys}\n  Pydantic only: {pydantic_keys - td_keys}"
        )

    def test_entity_typed_dict_matches_pydantic(self):
        td_keys = set(EntityResponseItem.__annotations__.keys())
        pydantic_keys = set(EntityResponseModel.model_fields.keys())
        assert td_keys == pydantic_keys, (
            f"Entity TypedDict != Pydantic.\n  TD only: {td_keys - pydantic_keys}\n  Pydantic only: {pydantic_keys - td_keys}"
        )

    def test_memory_typed_dict_matches_ts_interface(self):
        ts_path = os.path.join(
            os.path.dirname(__file__), "..", "server", "dashboard", "src", "types", "api.ts"
        )
        if not os.path.exists(ts_path):
            return
        import re
        ts_content = open(ts_path).read()
        pattern = r"export\s+interface\s+Memory\s*\{([^}]*)\}"
        match = re.search(pattern, ts_content)
        assert match, "Could not find Memory interface in api.ts"
        ts_fields = set()
        for line in match.group(1).strip().split("\n"):
            line = line.strip().rstrip(";").rstrip(",")
            if not line:
                continue
            parts = line.split(":")
            if len(parts) >= 2:
                name = parts[0].strip().rstrip("?")
                if name.isidentifier():
                    ts_fields.add(name)
        td_keys = set(MemoryResponseItem.__annotations__.keys())
        assert td_keys == ts_fields, (
            f"Memory TypedDict != TS interface.\n  TD only: {td_keys - ts_fields}\n  TS only: {ts_fields - td_keys}"
        )

    def test_entity_typed_dict_matches_ts_interface(self):
        ts_path = os.path.join(
            os.path.dirname(__file__), "..", "server", "dashboard", "src", "types", "api.ts"
        )
        if not os.path.exists(ts_path):
            return
        import re
        ts_content = open(ts_path).read()
        pattern = r"export\s+interface\s+Entity\s*\{([^}]*)\}"
        match = re.search(pattern, ts_content)
        assert match, "Could not find Entity interface in api.ts"
        ts_fields = set()
        for line in match.group(1).strip().split("\n"):
            line = line.strip().rstrip(";").rstrip(",")
            if not line:
                continue
            parts = line.split(":")
            if len(parts) >= 2:
                name = parts[0].strip().rstrip("?")
                if name.isidentifier():
                    ts_fields.add(name)
        td_keys = set(EntityResponseItem.__annotations__.keys())
        assert td_keys == ts_fields, (
            f"Entity TypedDict != TS interface.\n  TD only: {td_keys - ts_fields}\n  TS only: {ts_fields - td_keys}"
        )

    def test_entity_type_values_match_ts(self):
        ts_path = os.path.join(
            os.path.dirname(__file__), "..", "server", "dashboard", "src", "types", "api.ts"
        )
        if not os.path.exists(ts_path):
            return
        import re
        ts_content = open(ts_path).read()
        pattern = r'export\s+type\s+EntityType\s*=\s*([^;]+);'
        match = re.search(pattern, ts_content)
        if not match:
            return
        ts_values = {v.strip().strip('"').strip("'") for v in match.group(1).split("|")}
        assert ts_values == VALID_ENTITY_TYPES, f"Backend: {VALID_ENTITY_TYPES}, TS: {ts_values}"


class TestEndpointResponseShapeCompatibility:
    def test_post_memories_list_shape(self):
        result = normalize_response([{"id": "m1", "memory": "a", "event": "ADD"}])
        assert isinstance(result, list)
        MemoryResponseModel.model_validate(result[0])

    def test_post_memories_dict_shape(self):
        result = normalize_response({"results": [{"id": "m1", "memory": "a", "event": "ADD"}]})
        assert isinstance(result, dict) and set(result.keys()) == {"results"}
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
        assert isinstance(outer, dict) and set(outer.keys()) == {"results"}
        assert "text_lemmatized" not in outer["results"][0]
        MemoryResponseModel.model_validate(outer["results"][0])

    def test_get_memories_with_filter_list_shape(self):
        result = normalize_response([{"id": "m1", "memory": "a", "user_id": "u1"}])
        assert isinstance(result, list)
        MemoryResponseModel.model_validate(result[0])

    def test_get_memories_with_filter_dict_shape(self):
        result = normalize_response({"results": [{"id": "m1", "memory": "a", "user_id": "u1"}]})
        assert isinstance(result, dict) and "results" in result
        MemoryResponseModel.model_validate(result["results"][0])

    def test_get_memory_by_id_shape(self):
        result = normalize_response({"id": "m1", "memory": "hi", "actor_id": "bob", "metadata": {"custom": "y"}})
        assert isinstance(result, dict)
        MemoryResponseModel.model_validate(result)

    def test_post_search_shape(self):
        result = normalize_response({
            "results": [
                {"id": "m1", "memory": "a", "score": 0.9, "metadata": {"category": "sports"}},
                {"id": "m2", "memory": "b", "score": 0.8, "actor_id": "alice"},
            ]
        })
        assert isinstance(result, dict) and set(result.keys()) == {"results"}
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
        assert isinstance(result, list) and len(result) == 2
        assert not any(is_memory_response_item(e) for e in result)
        assert all(is_entity_response_item(e) for e in result)
        for e in result:
            EntityResponseModel.model_validate(e)

    def test_put_memories_message_passthrough(self):
        assert normalize_response({"message": "Memory updated"}) == {"message": "Memory updated"}

    def test_delete_message_passthrough(self):
        msg = {"message": "Memory deleted successfully"}
        result = normalize_response(msg)
        assert result == msg and not is_memory_response_item(result)

    def test_non_memory_list_passthrough(self):
        api_logs = [{"id": "l1", "method": "GET"}, {"id": "l2", "method": "POST"}]
        assert normalize_response(api_logs) == api_logs

    def test_dict_with_non_memory_results_passthrough(self):
        response = {"results": [{"id": "log1", "method": "GET"}]}
        assert normalize_response(response) == response
