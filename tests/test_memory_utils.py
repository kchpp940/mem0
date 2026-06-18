import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from memory_utils import (
    USER_METADATA_EXCLUDE,
    format_memory_list,
    format_memory_response,
    format_vector_store_row,
    normalize_sdk_result,
)


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
        assert result["created_at"] == "2025-01-01T00:00:00Z"
        assert result["updated_at"] == "2025-01-02T00:00:00Z"
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
        assert result["agent_id"] == "a1"
        assert result["run_id"] == "r1"
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


class TestNormalizeSdkResult:
    def test_dict_with_memory_normalized(self):
        item = {
            "id": "abc",
            "memory": "test",
            "user_id": "u1",
            "actor_id": "alice",
            "metadata": {"category": "sports", "text_lemmatized": "test"},
            "score": 0.9,
        }
        result = normalize_sdk_result(item)
        assert result["user_id"] == "u1"
        assert result["actor_id"] == "alice"
        assert result["score"] == 0.9
        assert result["metadata"]["category"] == "sports"
        assert "text_lemmatized" not in result["metadata"]

    def test_non_dict_returned_as_is(self):
        assert normalize_sdk_result("not a dict") == "not a dict"

    def test_dict_without_memory_returned_as_is(self):
        item = {"message": "Memory deleted successfully"}
        assert normalize_sdk_result(item) == item

    def test_add_result_with_event(self):
        item = {"id": "abc", "memory": "test", "event": "ADD", "actor_id": "alice"}
        result = normalize_sdk_result(item)
        assert result["event"] == "ADD"
        assert result["actor_id"] == "alice"


class TestFormatMemoryList:
    def test_formats_list(self):
        items = [
            {"id": "1", "memory": "first", "user_id": "u1"},
            {"id": "2", "memory": "second", "agent_id": "a1"},
        ]
        result = format_memory_list(items)
        assert "results" in result
        assert len(result["results"]) == 2
        assert result["results"][0]["user_id"] == "u1"
        assert result["results"][1]["agent_id"] == "a1"


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
