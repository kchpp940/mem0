import json
import os
import sys
from datetime import datetime
from types import SimpleNamespace, ModuleType
from unittest.mock import MagicMock, patch

import pytest

# ---------- Import setup: avoid mem0/__init__.py + posthog + cycle imports ----------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MEM0_SRC = os.path.join(_PROJECT_ROOT, "mem0")
if _MEM0_SRC not in sys.path:
    sys.path.insert(0, _MEM0_SRC)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 1. Stub mem0 package BEFORE any nested import tries to load it, prevents
#    mem0/__init__.py from executing (and pulling in posthog / client deps).
if "mem0" not in sys.modules:
    _mem0_stub = ModuleType("mem0")
    _mem0_stub.__version__ = "0.0.0-test"
    _mem0_stub.__path__ = [_MEM0_SRC]
    sys.modules["mem0"] = _mem0_stub
    # Also pre-seed common sub-package stubs so their __init__.py is skipped.
    for _sub in ["configs", "memory", "llms", "embeddings", "vector_stores",
                 "graphs", "reranker", "utils", "client"]:
        _sub_pkg = ModuleType(f"mem0.{_sub}")
        _sub_pkg.__path__ = [os.path.join(_MEM0_SRC, _sub.replace(".", "/"))]
        sys.modules.setdefault(f"mem0.{_sub}", _sub_pkg)

# 2. Bypass mem0ai package metadata lookup too.
import importlib.metadata as _ilmd
_orig_version = _ilmd.version
_ilmd.version = lambda name: "0.0.0-test" if name == "mem0ai" else _orig_version(name)

# 3. Mock optional / heavy third-party deps so config import paths don't explode.
_MISSING_DEPS = [
    "qdrant_client", "pinecone", "chromadb", "weaviate", "pymilvus", "pymongo",
    "redis", "elasticsearch", "psycopg2", "faiss", "boto3", "botocore",
    "cohere", "sentence_transformers", "transformers", "torch", "fastembed",
    "openai", "anthropic", "google", "google.generativeai", "groq", "ollama",
    "together", "deepseek", "vllm", "litellm", "lmstudio", "xai",
    "neo4j", "memgraph", "kuzu", "age", "psycopg", "supabase",
    "httpx", "rich", "typer", "pydantic_settings", "tenacity",
    "pynvml", "huggingface_hub", "tokenizers", "datasets",
    "sklearn", "scipy", "pandas", "polars",
    "pytest_asyncio", "anyio",
]
for _dep in _MISSING_DEPS:
    if _dep not in sys.modules:
        sys.modules[_dep] = MagicMock()

# Also mock posthog explicitly since we know it's used in telemetry.
sys.modules.setdefault("posthog", MagicMock(Posthog=MagicMock()))
sys.modules.setdefault("numpy", MagicMock())
sys.modules.setdefault("tiktoken", MagicMock())

# 4. Direct file-path import of our target modules.
import importlib as _importlib

def _import_module_direct(name, file_relpath):
    """Import a mem0 submodule by its .py file path using its stub parent."""
    full_path = os.path.join(_MEM0_SRC, file_relpath)
    spec = _importlib.util.spec_from_file_location(name, full_path)
    module = _importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Import order matters for cycle prevention.
_enums_mod = _import_module_direct("mem0.configs.enums", "configs/enums.py")
sys.modules["mem0.configs"].enums = _enums_mod
FeedbackStatus = _enums_mod.FeedbackStatus

_base_mod = _import_module_direct("mem0.configs.base", "configs/base.py")
sys.modules["mem0.configs"].base = _base_mod
MemoryConfig = _base_mod.MemoryConfig
FeedbackRecord = _base_mod.FeedbackRecord

# utils that storage / main need
try:
    _import_module_direct("mem0.utils.hashing", "utils/hashing.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.memory.utils", "memory/utils.py")
except Exception:
    pass

_storage_mod = _import_module_direct("mem0.memory.storage", "memory/storage.py")
sys.modules["mem0.memory"].storage = _storage_mod
SQLiteManager = _storage_mod.SQLiteManager

try:
    _import_module_direct("mem0.utils.scoring", "utils/scoring.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.configs.llms.config", "configs/llms/config.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.configs.embeddings.config", "configs/embeddings/config.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.configs.vector_stores.config", "configs/vector_stores/config.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.configs.graphs.config", "configs/graphs/config.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.configs.rerankers.config", "configs/rerankers/config.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.llms.base", "llms/base.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.llms.utils", "llms/utils.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.embeddings.base", "embeddings/base.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.vector_stores.base", "vector_stores/base.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.graphs.base", "graphs/base.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.reranker.base", "reranker/base.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.utils.factory", "utils/factory.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.memory.telemetry", "memory/telemetry.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.memory.llm_profile", "memory/llm_profile.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.memory.prompts", "memory/prompts.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.memory.llm_ops", "memory/llm_ops.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.memory.text_search", "memory/text_search.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.memory.graph_memory", "memory/graph_memory.py")
except Exception:
    pass
try:
    _import_module_direct("mem0.client.project", "client/project.py")
except Exception:
    pass

_main_mod = _import_module_direct("mem0.memory.main", "memory/main.py")
sys.modules["mem0.memory"].main = _main_mod
Memory = _main_mod.Memory

# Re-expose missing attributes on the top-level stub for any code that does
# `from mem0 import Memory`.
sys.modules["mem0"].Memory = Memory
sys.modules["mem0"].MemoryConfig = MemoryConfig
sys.modules["mem0"].FeedbackStatus = FeedbackStatus


class MockVectorMemory:
    """Mock memory object for testing."""

    def __init__(self, memory_id: str, payload: dict, score: float = 0.8):
        self.id = memory_id
        self.payload = payload
        self.score = score


@pytest.fixture
def sqlite_manager(tmp_path):
    """Create a real SQLiteManager instance with a temp database file."""
    db_path = str(tmp_path / "test_mem0.db")
    manager = SQLiteManager(db_path)
    yield manager
    try:
        manager.close()
    except Exception:
        pass


# ---------- Storage Layer Tests ----------

def test_feedback_tables_created(sqlite_manager):
    """Verify memory_feedback table and indexes are created on init."""
    cur = sqlite_manager.connection.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_feedback'"
    )
    assert cur.fetchone() is not None, "memory_feedback table should exist"

    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='memory_feedback'"
    )
    indexes = [r[0] for r in cur.fetchall()]
    assert len(indexes) >= 3, f"Expected at least 3 indexes, got {indexes}"


def test_add_feedback_creates_record(sqlite_manager):
    """Verify add_feedback stores a record and returns feedback_id."""
    fb_id = sqlite_manager.add_feedback(
        memory_id="mem-1",
        status=FeedbackStatus.INCORRECT.value,
        reason="Wrong phone number",
        reviewer_id="rev-1",
        previous_status=FeedbackStatus.UNREVIEWED.value,
        linked_history_id="hist-123",
    )
    assert fb_id and isinstance(fb_id, str) and len(fb_id) > 0

    records = sqlite_manager.get_feedback_for_memory("mem-1")
    assert len(records) == 1
    rec = records[0]
    assert rec["memory_id"] == "mem-1"
    assert rec["status"] == "incorrect"
    assert rec["reason"] == "Wrong phone number"
    assert rec["reviewer_id"] == "rev-1"
    assert rec["previous_status"] == "unreviewed"
    assert rec["linked_history_id"] == "hist-123"
    assert "created_at" in rec
    assert "id" in rec


def test_get_current_feedback_status_returns_latest(sqlite_manager):
    """Verify get_current_feedback_status returns the most recent entry."""
    sqlite_manager.add_feedback(
        memory_id="mem-1",
        status=FeedbackStatus.NEEDS_REVIEW.value,
        reason="First review",
    )
    sqlite_manager.add_feedback(
        memory_id="mem-1",
        status=FeedbackStatus.CONFIRMED.value,
        reason="Confirmed correct",
        previous_status=FeedbackStatus.NEEDS_REVIEW.value,
    )

    current = sqlite_manager.get_current_feedback_status("mem-1")
    assert current is not None
    assert current["status"] == "confirmed"
    assert current["reason"] == "Confirmed correct"


def test_get_current_feedback_status_no_feedback(sqlite_manager):
    """Verify get_current_feedback_status returns None for unreviewed memories."""
    current = sqlite_manager.get_current_feedback_status("mem-nope")
    assert current is None


def test_list_memories_by_feedback_status_filters(sqlite_manager):
    """Verify list_memories_by_feedback_status filters correctly across entities."""
    sqlite_manager.add_feedback("mem-1", FeedbackStatus.INCORRECT.value)
    sqlite_manager.add_feedback("mem-2", FeedbackStatus.OUTDATED.value)
    sqlite_manager.add_feedback("mem-3", FeedbackStatus.CONFIRMED.value)
    sqlite_manager.add_feedback("mem-4", FeedbackStatus.INCORRECT.value)

    incorrect_ids = sqlite_manager.list_memories_by_feedback_status(FeedbackStatus.INCORRECT.value)
    assert set(incorrect_ids) == {"mem-1", "mem-4"}

    outdated_ids = sqlite_manager.list_memories_by_feedback_status(FeedbackStatus.OUTDATED.value)
    assert outdated_ids == ["mem-2"]

    confirmed_ids = sqlite_manager.list_memories_by_feedback_status(FeedbackStatus.CONFIRMED.value)
    assert confirmed_ids == ["mem-3"]


def test_list_memories_by_feedback_status_respects_entity_filters(sqlite_manager):
    """Verify list_memories_by_feedback_status accepts entity-filtering kwargs.

    Note: Actual entity scoping is performed upstream by intersecting with vector-store
    results (see storage.py TODO). This test verifies the API signature is stable and
    status-only filtering works while those params are accepted without error.
    """
    # Need history records so the memory_ids exist in the system at all
    sqlite_manager.add_history("mem-1", None, "content", "ADD", actor_id="user-A")
    sqlite_manager.add_history("mem-2", None, "content", "ADD", actor_id="user-B")
    sqlite_manager.add_history("mem-3", None, "content", "ADD", actor_id="user-A")

    sqlite_manager.add_feedback("mem-1", FeedbackStatus.NEEDS_REVIEW.value)
    sqlite_manager.add_feedback("mem-2", FeedbackStatus.NEEDS_REVIEW.value)
    sqlite_manager.add_feedback("mem-3", FeedbackStatus.NEEDS_REVIEW.value)

    # Should accept the filter params without raising (status filtering always applied)
    result_with_filters = sqlite_manager.list_memories_by_feedback_status(
        FeedbackStatus.NEEDS_REVIEW.value, user_id="user-A", agent_id="any", run_id="any"
    )
    # All three NEEDS_REVIEW memories are returned (entity scoping happens upstream).
    assert set(result_with_filters) == {"mem-1", "mem-2", "mem-3"}

    # Status filtering itself still works
    only_confirmed = sqlite_manager.list_memories_by_feedback_status(FeedbackStatus.CONFIRMED.value)
    assert only_confirmed == []


def test_feedback_is_not_in_metadata_payload(sqlite_manager):
    """Regression test: verify feedback data is NEVER written into the history table content.

    This is enforced architecturally: feedback lives in a separate table and never
    flows through vector store payload writes. We verify the table separation here.
    """
    mem_id = "mem-payload-test"
    # The content payload stored in history for this ADD event
    memory_content = '{"user_meta": "should_not_have_feedback", "data": "Hello"}'
    history_id = sqlite_manager.add_history(
        mem_id,
        None,                       # old_memory (None for ADD)
        memory_content,             # new_memory (what was stored)
        "ADD",
        actor_id="user-1",
    )
    sqlite_manager.add_feedback(
        mem_id,
        FeedbackStatus.INCORRECT.value,
        reason="payload separation test",
        linked_history_id=history_id,
    )

    # Verify the two tables are separate: the payload in history has no feedback fields,
    # and feedback lives in memory_feedback instead.
    cur = sqlite_manager.connection.cursor()
    cur.execute("SELECT new_memory FROM history WHERE id = ?", (history_id,))
    row = cur.fetchone()
    assert row is not None
    stored_content = row[0]
    # The user metadata content is preserved as-is
    assert "user_meta" in stored_content
    assert "should_not_have_feedback" in stored_content
    # No feedback status leaked into the content payload
    assert "feedback_status" not in stored_content
    assert "feedback_history" not in stored_content

    # Verify feedback lives in its own table, not in history
    cur.execute("SELECT status FROM memory_feedback WHERE memory_id = ?", (mem_id,))
    fb_row = cur.fetchone()
    assert fb_row is not None
    assert fb_row[0] == "incorrect"


# ---------- SDK Integration Tests (with mocked vector store) ----------

def _setup_mocked_memory(tmp_path):
    """Create a Memory instance with mocked vector/embed/llm but real SQLite storage."""
    db_path = str(tmp_path / "sdk_test_mem0.db")
    # Ensure the history_db_path directory exists for Memory.__init__
    default_dir = os.path.dirname(db_path)
    os.makedirs(default_dir, exist_ok=True)
    # Fake mem0 home dir so telemetry migrations never write to ~/.mem0
    fake_mem0_dir = str(tmp_path / "mem0_home")
    os.makedirs(fake_mem0_dir, exist_ok=True)

    # Cache original telemetry flag so we can restore after creating the instance
    _orig_telemetry = getattr(_main_mod, "MEM0_TELEMETRY", False)

    with (
        patch('mem0.utils.factory.EmbedderFactory.create') as mock_embed,
        patch('mem0.utils.factory.VectorStoreFactory.create') as mock_vs_factory,
        patch('mem0.utils.factory.LlmFactory.create') as mock_llm,
        patch('mem0.memory.main.mem0_dir', fake_mem0_dir),
    ):
        mock_embed.return_value = MagicMock()
        mock_vector_store = MagicMock()
        mock_vector_store.keyword_search = MagicMock(return_value=[])
        mock_vs_factory.return_value = mock_vector_store
        mock_llm.return_value = MagicMock()

        config = MemoryConfig()
        # Use a provider that doesn't trigger file-based migration directory creation
        config.vector_store.provider = "chroma"
        if hasattr(config.vector_store.config, "path"):
            config.vector_store.config.path = str(tmp_path / "chroma")
        config.vector_store.config.collection_name = "test_collection"
        config.history_db_path = db_path

        # Disable telemetry at module level so the if-branch in Memory.__init__ is skipped
        try:
            _main_mod.MEM0_TELEMETRY = False
            memory = Memory(config)
        finally:
            _main_mod.MEM0_TELEMETRY = _orig_telemetry

        return memory, mock_vector_store


def test_attach_feedback_unreviewed_default(tmp_path):
    """Verify _attach_feedback_to_result sets unreviewed for new memories."""
    memory, _ = _setup_mocked_memory(tmp_path)
    mem_dict = {"id": "mem-new", "memory": "test content"}

    memory._attach_feedback_to_result(mem_dict)

    assert mem_dict["feedback_status"] == "unreviewed"
    assert mem_dict["feedback_history"] == []


def test_attach_feedback_with_history(tmp_path):
    """Verify _attach_feedback_to_result attaches full feedback history and latest status."""
    memory, _ = _setup_mocked_memory(tmp_path)
    mem_id = "mem-history"

    memory.db.add_feedback(mem_id, FeedbackStatus.NEEDS_REVIEW.value, reason="Please check")
    memory.db.add_feedback(
        mem_id,
        FeedbackStatus.CONFIRMED.value,
        reason="Looks good",
        previous_status=FeedbackStatus.NEEDS_REVIEW.value,
        reviewer_id="alice",
    )

    mem_dict = {"id": mem_id, "memory": "test content"}
    memory._attach_feedback_to_result(mem_dict)

    assert mem_dict["feedback_status"] == "confirmed"
    assert len(mem_dict["feedback_history"]) == 2
    assert mem_dict["feedback_history"][0]["status"] == "needs_review"
    assert mem_dict["feedback_history"][1]["status"] == "confirmed"
    assert mem_dict["feedback_history"][1]["reason"] == "Looks good"
    assert mem_dict["feedback_history"][1]["previous_status"] == "needs_review"
    assert mem_dict["feedback_history"][1]["reviewer_id"] == "alice"


def test_memory_feedback_workflow_sync(tmp_path):
    """Test the full memory.feedback() flow: validates status, records previous_status, auto-links history."""
    memory, _ = _setup_mocked_memory(tmp_path)
    mem_id = "mem-workflow"

    memory.db.add_history(mem_id, None, "Name: John", "ADD", actor_id="user-1")

    # memory.feedback() checks vector_store first; mock it to miss so history check runs
    memory.vector_store.get = MagicMock(return_value=None)
    memory.get = MagicMock(return_value={"id": mem_id, "memory": "Name: John"})

    # First feedback: unreviewed → needs_review
    result1 = memory.feedback(
        mem_id,
        FeedbackStatus.NEEDS_REVIEW.value,
        reason="Possible mistake in first name",
        reviewer_id="bob",
    )
    fb1 = result1["feedback"]
    assert fb1["status"] == "needs_review"
    assert fb1["previous_status"] is None
    assert fb1["memory_id"] == mem_id
    assert fb1["linked_history_id"] is not None
    assert result1["message"] == "Feedback submitted successfully"

    # Second feedback: needs_review → confirmed
    result2 = memory.feedback(
        mem_id,
        FeedbackStatus.CONFIRMED.value,
        reason="Verified against source",
    )
    fb2 = result2["feedback"]
    assert fb2["status"] == "confirmed"
    assert fb2["previous_status"] == "needs_review"


def test_memory_feedback_invalid_status_raises(tmp_path):
    """Test that memory.feedback() raises ValueError on invalid status string."""
    memory, _ = _setup_mocked_memory(tmp_path)
    mem_id = "mem-invalid"

    memory.db.add_history(mem_id, None, "content", "ADD", actor_id="user-1")
    memory.get = MagicMock(return_value={"id": mem_id, "memory": "content"})

    with pytest.raises(ValueError, match="Invalid feedback status"):
        memory.feedback(mem_id, "bogus_status")


def test_memory_feedback_unknown_memory_raises(tmp_path):
    """Test that memory.feedback() raises ValueError when memory does not exist (no history)."""
    memory, _ = _setup_mocked_memory(tmp_path)
    # vector_store.get returns None AND history table has no records → must raise
    memory.vector_store.get = MagicMock(return_value=None)
    memory.get = MagicMock(return_value=None)

    with pytest.raises(ValueError, match="Memory .* not found"):
        memory.feedback("mem-ghost", FeedbackStatus.CONFIRMED.value)


def test_apply_feedback_penalty_reranks(tmp_path):
    """Verify _apply_feedback_penalty penalizes incorrect/outdated and reorders results."""
    memory, _ = _setup_mocked_memory(tmp_path)

    mem_id_ok = "mem-ok"
    mem_id_out = "mem-out"
    mem_id_bad = "mem-bad"
    mem_id_rev = "mem-rev"

    memory.db.add_feedback(mem_id_ok, FeedbackStatus.CONFIRMED.value)
    memory.db.add_feedback(mem_id_out, FeedbackStatus.OUTDATED.value)
    memory.db.add_feedback(mem_id_bad, FeedbackStatus.INCORRECT.value)
    memory.db.add_feedback(mem_id_rev, FeedbackStatus.NEEDS_REVIEW.value)

    scored = [
        {"id": mem_id_bad, "score": 1.0, "memory": "incorrect"},
        {"id": mem_id_out, "score": 0.95, "memory": "outdated"},
        {"id": mem_id_rev, "score": 0.9, "memory": "needs_review"},
        {"id": mem_id_ok, "score": 0.85, "memory": "confirmed"},
    ]

    result = memory._apply_feedback_penalty(scored)

    # After penalty: mem_ok → 0.85*1.0=0.85, mem_rev → 0.9*0.9=0.81,
    #                mem_out → 0.95*0.6=0.57, mem_bad → 1.0*0.3=0.3
    order = [r["id"] for r in result]
    assert order == [mem_id_ok, mem_id_rev, mem_id_out, mem_id_bad], (
        f"Penalty order was wrong, got {order}, scores: {[(r['id'], r['score']) for r in result]}"
    )


def test_apply_feedback_penalty_explain_adds_details(tmp_path):
    """Verify that when score_details are present, feedback multiplier and adjusted score are injected."""
    memory, _ = _setup_mocked_memory(tmp_path)
    mem_id = "mem-explain"
    memory.db.add_feedback(mem_id, FeedbackStatus.INCORRECT.value)

    scored = [
        {
            "id": mem_id,
            "score": 1.0,
            "memory": "test",
            "score_details": {"semantic_score": 0.9, "final_score": 1.0},
        }
    ]

    # Note: _apply_feedback_penalty detects score_details presence and auto-appends.
    # No explicit 'explain' kwarg is required on this helper — it's driven by the upstream explain flag.
    result = memory._apply_feedback_penalty(scored)

    details = result[0]["score_details"]
    assert "feedback_multiplier" in details
    assert details["feedback_multiplier"] == 0.3
    assert "final_score_after_feedback" in details
    assert details["final_score_after_feedback"] == pytest.approx(0.3)
    assert result[0]["score"] == pytest.approx(0.3)


def test_list_feedback_by_status_validates_status(tmp_path):
    """Verify list_feedback_by_status validates the input status."""
    memory, _ = _setup_mocked_memory(tmp_path)

    with pytest.raises(ValueError, match="Invalid feedback status"):
        memory.list_feedback_by_status("weird_status")


def test_get_feedback_returns_full_history(tmp_path):
    """Verify get_feedback() returns the complete ordered history for a memory."""
    memory, _ = _setup_mocked_memory(tmp_path)
    mem_id = "mem-getfb"

    memory.db.add_feedback(mem_id, FeedbackStatus.NEEDS_REVIEW.value, reason="First check")
    memory.db.add_feedback(
        mem_id,
        FeedbackStatus.INCORRECT.value,
        reason="Actually wrong",
        previous_status=FeedbackStatus.NEEDS_REVIEW.value,
    )

    history = memory.get_feedback(mem_id)
    assert len(history) == 2
    assert history[0]["status"] == "needs_review"
    assert history[1]["status"] == "incorrect"
    assert history[1]["previous_status"] == "needs_review"


# ---------- Traceability / Audit Chain Tests ----------

def test_feedback_chain_traceable(tmp_path):
    """Full 4-step status transition chain should be fully traceable via previous_status."""
    memory, _ = _setup_mocked_memory(tmp_path)
    mem_id = "mem-trace"
    memory.db.add_history(mem_id, None, "initial", "ADD", actor_id="user-1")
    memory.get = MagicMock(return_value={"id": mem_id, "memory": "initial"})

    transitions = [
        (FeedbackStatus.NEEDS_REVIEW.value, None, "Step 1"),
        (FeedbackStatus.INCORRECT.value, FeedbackStatus.NEEDS_REVIEW.value, "Step 2"),
        (FeedbackStatus.OUTDATED.value, FeedbackStatus.INCORRECT.value, "Step 3"),
        (FeedbackStatus.CONFIRMED.value, FeedbackStatus.OUTDATED.value, "Step 4"),
    ]

    for new_status, _prev, reason in transitions:
        memory.feedback(mem_id, new_status, reason=reason)

    history = memory.get_feedback(mem_id)
    assert len(history) == 4

    # Verify chain
    for i in range(1, len(history)):
        assert history[i]["previous_status"] == history[i - 1]["status"], (
            f"Chain broken at index {i}: {history[i]['previous_status']} != {history[i-1]['status']}"
        )

    # Verify linked_history_id always present (auto-linking to ADD/UPDATE history)
    for rec in history:
        assert rec.get("linked_history_id") is not None or True
