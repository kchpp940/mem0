import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from memory_utils import (
    USER_METADATA_EXCLUDE,
    extract_payload,
    format_memory_response,
    format_vector_store_row,
    is_memory_item,
    iter_formatted_rows,
    list_vector_store_memories,
    normalize_memory_item,
    normalize_memory_list,
    normalize_response,
)


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


class TestIsMemoryItem:
    def test_detects_memory_item_by_id(self):
        assert is_memory_item({"id": "abc", "memory": "test"}) is True

    def test_detects_memory_item_by_memory(self):
        assert is_memory_item({"memory": "test"}) is True

    def test_rejects_non_memory_dict(self):
        assert is_memory_item({"message": "hello"}) is False

    def test_rejects_non_dict(self):
        assert is_memory_item("not a dict") is False


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

    def test_non_dict_metadata_preserved(self):
        item = {"id": "abc", "memory": "test", "metadata": "some-string"}
        result = format_memory_response(item)
        assert result["metadata"] == "some-string"


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
    def test_dict_with_memory_normalized(self):
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

    def test_non_memory_dict_returned_as_is(self):
        assert normalize_memory_item({"message": "deleted"}) == {"message": "deleted"}

    def test_non_dict_returned_as_is(self):
        assert normalize_memory_item("not a dict") == "not a dict"

    def test_add_result_with_event(self):
        item = {"id": "abc", "memory": "test", "event": "ADD", "actor_id": "alice"}
        result = normalize_memory_item(item)
        assert result["event"] == "ADD"
        assert result["actor_id"] == "alice"


class TestNormalizeMemoryList:
    def test_formats_list(self):
        items = [
            {"id": "1", "memory": "first", "user_id": "u1"},
            {"id": "2", "memory": "second", "agent_id": "a1"},
            {"not": "a memory item"},
        ]
        result = normalize_memory_list(items)
        assert len(result) == 3
        assert result[0]["user_id"] == "u1"
        assert result[1]["agent_id"] == "a1"
        assert result[2] == {"not": "a memory item"}


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
        response = {"message": "Memory deleted successfully"}
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
