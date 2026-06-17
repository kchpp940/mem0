import pytest

from mem0.memory.utils import build_candidate_pool
from mem0.utils.scoring import (
    get_bm25_params,
    normalize_bm25,
    score_and_rank,
    ENTITY_BOOST_WEIGHT,
    PoolStatus,
)


class TestGetBm25Params:
    def test_short_query(self):
        midpoint, steepness = get_bm25_params("hello world", lemmatized="hello world")
        assert midpoint == 5.0
        assert steepness == 0.7

    def test_medium_query(self):
        midpoint, steepness = get_bm25_params("x", lemmatized="one two three four five")
        assert midpoint == 7.0
        assert steepness == 0.6

    def test_long_query(self):
        words = " ".join(f"word{i}" for i in range(20))
        midpoint, steepness = get_bm25_params("x", lemmatized=words)
        assert midpoint == 12.0
        assert steepness == 0.5

    def test_empty_lemmatized(self):
        midpoint, steepness = get_bm25_params("test", lemmatized="")
        # Empty string -> 1 term -> short query params
        assert midpoint == 5.0


class TestNormalizeBm25:
    def test_at_midpoint(self):
        score = normalize_bm25(5.0, 5.0, 0.7)
        assert abs(score - 0.5) < 0.01  # Should be ~0.5 at midpoint

    def test_high_score(self):
        score = normalize_bm25(20.0, 5.0, 0.7)
        assert score > 0.99  # Well above midpoint

    def test_low_score(self):
        score = normalize_bm25(0.0, 5.0, 0.7)
        assert score < 0.05  # Well below midpoint

    def test_range(self):
        for raw in [0, 1, 5, 10, 20, 50]:
            score = normalize_bm25(float(raw), 5.0, 0.7)
            assert 0.0 <= score <= 1.0


class TestScoreAndRank:
    def test_semantic_only(self):
        results = [
            {"id": "a", "score": 0.9, "payload": {"data": "mem a"}},
            {"id": "b", "score": 0.5, "payload": {"data": "mem b"}},
        ]
        scored = score_and_rank(results, {}, {}, threshold=0.1, top_k=10)
        assert len(scored) == 2
        # With no BM25/entity, max_possible=1.0, so scores stay the same
        assert scored[0]["score"] == pytest.approx(0.9)
        assert scored[1]["score"] == pytest.approx(0.5)

    def test_semantic_plus_bm25(self):
        results = [
            {"id": "a", "score": 0.8, "payload": {"data": "mem a"}},
            {"id": "b", "score": 0.6, "payload": {"data": "mem b"}},
        ]
        bm25 = {"a": 0.3, "b": 0.9}
        scored = score_and_rank(results, bm25, {}, threshold=0.1, top_k=10)
        # max_possible = 2.0 (semantic + bm25)
        # a: (0.8 + 0.3) / 2.0 = 0.55
        # b: (0.6 + 0.9) / 2.0 = 0.75
        assert scored[0]["id"] == "b"  # b should rank higher due to BM25
        assert scored[0]["score"] == pytest.approx(0.75)
        assert scored[1]["id"] == "a"
        assert scored[1]["score"] == pytest.approx(0.55)

    def test_all_three_signals(self):
        results = [{"id": "a", "score": 0.8, "payload": {"data": "mem a"}}]
        bm25 = {"a": 0.6}
        entity = {"a": 0.3}
        scored = score_and_rank(results, bm25, entity, threshold=0.1, top_k=10)
        # max_possible = 2.5
        expected = (0.8 + 0.6 + 0.3) / 2.5
        assert scored[0]["score"] == pytest.approx(expected)

    def test_threshold_gates_semantic_only_candidates(self):
        results = [
            {"id": "a", "score": 0.05, "payload": {"data": "mem a"}},
            {"id": "b", "score": 0.5, "payload": {"data": "mem b"}},
        ]
        bm25 = {"a": 0.99}
        scored = score_and_rank(results, bm25, {}, threshold=0.1, top_k=10)
        assert len(scored) == 2
        assert scored[0]["id"] == "a"
        assert scored[1]["id"] == "b"

    def test_semantic_below_threshold_no_other_signal_excluded(self):
        results = [
            {"id": "a", "score": 0.05, "payload": {"data": "mem a"}},
            {"id": "b", "score": 0.5, "payload": {"data": "mem b"}},
        ]
        scored = score_and_rank(results, {}, {}, threshold=0.1, top_k=10)
        assert len(scored) == 1
        assert scored[0]["id"] == "b"

    def test_top_k_limit(self):
        results = [{"id": str(i), "score": 0.5, "payload": {}} for i in range(20)]
        scored = score_and_rank(results, {}, {}, threshold=0.1, top_k=5)
        assert len(scored) == 5

    def test_adaptive_divisor_semantic_only(self):
        results = [{"id": "a", "score": 0.8, "payload": {}}]
        scored = score_and_rank(results, {}, {}, threshold=0.1, top_k=10)
        # max_possible = 1.0 (no bm25, no entity)
        assert scored[0]["score"] == pytest.approx(0.8)

    def test_adaptive_divisor_semantic_plus_entity(self):
        results = [{"id": "a", "score": 0.8, "payload": {}}]
        entity = {"a": 0.3}
        scored = score_and_rank(results, {}, entity, threshold=0.1, top_k=10)
        # max_possible = 1.5 (semantic + entity)
        expected = (0.8 + 0.3) / 1.5
        assert scored[0]["score"] == pytest.approx(expected)

    def test_empty_results(self):
        scored = score_and_rank([], {}, {}, threshold=0.1, top_k=10)
        assert scored == []

    def test_none_score_treated_as_zero(self):
        """Defensive: score=None must not crash on None < threshold comparison."""
        results = [{"id": "a", "score": None, "payload": {"data": "mem a"}}]
        # Should not raise TypeError; None score is treated as 0.0 and filtered out
        scored = score_and_rank(results, {}, {}, threshold=0.1, top_k=10)
        assert scored == []

    def test_score_clamped_to_1(self):
        results = [{"id": "a", "score": 1.0, "payload": {}}]
        bm25 = {"a": 1.0}
        entity = {"a": 0.5}
        scored = score_and_rank(results, bm25, entity, threshold=0.1, top_k=10)
        assert scored[0]["score"] <= 1.0

    def test_explain_includes_score_details(self):
        results = [{"id": "a", "score": 0.8, "payload": {"data": "mem a"}}]
        bm25 = {"a": 0.6}
        entity = {"a": 0.3}
        scored = score_and_rank(results, bm25, entity, threshold=0.1, top_k=10, explain=True)

        details = scored[0]["score_details"]
        assert details == {
            "semantic_score": 0.8,
            "bm25_score": 0.6,
            "entity_boost": 0.3,
            "raw_score": pytest.approx(1.7),
            "max_possible_score": 2.5,
            "final_score": pytest.approx(0.68),
            "threshold": 0.1,
            "sources": [],
        }

    def test_score_details_are_omitted_by_default(self):
        results = [{"id": "a", "score": 0.8, "payload": {"data": "mem a"}}]
        scored = score_and_rank(results, {}, {}, threshold=0.1, top_k=10)
        assert "score_details" not in scored[0]

    def test_keyword_only_candidate_included(self):
        results = [
            {"id": "a", "score": 0.0, "payload": {"data": "keyword memory"}},
            {"id": "b", "score": 0.8, "payload": {"data": "semantic memory"}},
        ]
        bm25 = {"a": 0.9}
        scored = score_and_rank(results, bm25, {}, threshold=0.1, top_k=10)
        ids = [s["id"] for s in scored]
        assert "a" in ids
        assert "b" in ids

    def test_entity_only_candidate_included(self):
        results = [
            {"id": "a", "score": 0.0, "payload": {"data": "entity memory"}},
            {"id": "b", "score": 0.8, "payload": {"data": "semantic memory"}},
        ]
        entity = {"a": 0.4}
        scored = score_and_rank(results, {}, entity, threshold=0.1, top_k=10)
        ids = [s["id"] for s in scored]
        assert "a" in ids
        assert "b" in ids

    def test_no_signal_candidate_excluded(self):
        results = [
            {"id": "a", "score": 0.0, "payload": {"data": "no signal"}},
            {"id": "b", "score": 0.8, "payload": {"data": "semantic memory"}},
        ]
        scored = score_and_rank(results, {}, {}, threshold=0.1, top_k=10)
        ids = [s["id"] for s in scored]
        assert "a" not in ids
        assert "b" in ids

    def test_entity_only_score_divisor(self):
        results = [{"id": "a", "score": 0.0, "payload": {"data": "entity only"}}]
        entity = {"a": 0.4}
        scored = score_and_rank(results, {}, entity, threshold=0.1, top_k=10)
        expected = 0.4 / ENTITY_BOOST_WEIGHT
        assert scored[0]["score"] == pytest.approx(expected)

    def test_bm25_only_score_divisor(self):
        results = [{"id": "a", "score": 0.0, "payload": {"data": "bm25 only"}}]
        bm25 = {"a": 0.7}
        scored = score_and_rank(results, bm25, {}, threshold=0.1, top_k=10)
        expected = 0.7 / 1.0
        assert scored[0]["score"] == pytest.approx(expected)


class TestEntityBoostWeight:
    def test_weight_value(self):
        assert ENTITY_BOOST_WEIGHT == 0.5


class TestBuildCandidatePool:
    def test_merges_semantic_and_keyword(self):
        semantic = [{"id": "a", "score": 0.9, "payload": {"data": "a"}}]
        keyword = {"b": {"data": "b"}}
        entity = {}
        candidates, status = build_candidate_pool(semantic, keyword, entity, None)
        ids = [c["id"] for c in candidates]
        assert "a" in ids
        assert "b" in ids
        assert status["semantic_ok"] is True
        assert status["keyword_ok"] is True
        assert status["entity_ok"] is False
        assert status["degraded"] is False

    def test_marks_sources_for_overlapping_hits(self):
        semantic = [{"id": "a", "score": 0.9, "payload": {"data": "a"}}]
        keyword = {"a": {"data": "a"}}
        entity = {"a": 0.3}
        candidates, _ = build_candidate_pool(semantic, keyword, entity, None)
        assert len(candidates) == 1
        assert set(candidates[0]["sources"]) == {"semantic", "keyword", "entity"}

    def test_semantic_none_marks_keyword_only(self):
        keyword = {"a": {"data": "a"}}
        candidates, status = build_candidate_pool(None, keyword, {}, None)
        assert status["semantic_ok"] is False
        assert status["keyword_ok"] is True
        assert status["degraded"] is True
        assert status["degradation_reason"] is not None
        assert candidates[0]["sources"] == ["keyword"]

    def test_semantic_none_no_other_lanes_returns_empty_not_degraded(self):
        candidates, status = build_candidate_pool(None, {}, {}, None)
        assert status["semantic_ok"] is False
        assert status["keyword_ok"] is False
        assert status["entity_ok"] is False
        assert status["degraded"] is False
        assert len(candidates) == 0

    def test_entity_only_payload_fetched_via_get(self):
        def fake_get(mem_id):
            return {"id": mem_id, "payload": {"data": f"payload-{mem_id}"}}

        semantic = []
        keyword = {}
        entity = {"x": 0.3}
        candidates, status = build_candidate_pool(semantic, keyword, entity, fake_get)
        assert len(candidates) == 1
        assert candidates[0]["id"] == "x"
        assert candidates[0]["payload"]["data"] == "payload-x"
        assert candidates[0]["sources"] == ["entity"]

    def test_precomputed_payloads_used_over_get(self):
        def fake_get(_):
            raise AssertionError("get should not be called when precomputed provided")

        semantic = []
        keyword = {}
        entity = {"x": 0.3}
        precomputed = {"x": {"data": "precomputed-payload"}}
        candidates, _ = build_candidate_pool(semantic, keyword, entity, fake_get, precomputed)
        assert len(candidates) == 1
        assert candidates[0]["payload"]["data"] == "precomputed-payload"

    def test_get_failure_logged_but_not_fatal(self):
        def fake_get(_):
            raise RuntimeError("simulated get failure")

        semantic = []
        keyword = {}
        entity = {"x": 0.3}
        candidates, _ = build_candidate_pool(semantic, keyword, entity, fake_get)
        assert len(candidates) == 0

    def test_deduplication_preserves_semantic_score(self):
        semantic = [{"id": "a", "score": 0.9, "payload": {"data": "a"}}]
        keyword = {"a": {"data": "from-keyword"}}
        candidates, _ = build_candidate_pool(semantic, keyword, {}, None)
        assert len(candidates) == 1
        assert candidates[0]["score"] == 0.9
        assert candidates[0]["payload"]["data"] == "a"


class TestScoreAndRankWithSources:
    def test_sources_preserved_in_explain(self):
        candidates = [
            {
                "id": "a",
                "score": 0.8,
                "payload": {"data": "a"},
                "sources": ["semantic", "keyword"],
            }
        ]
        scored = score_and_rank(candidates, {}, {}, 0.1, 10, explain=True)
        assert scored[0]["score_details"]["sources"] == ["semantic", "keyword"]

    def test_pool_status_preserved_in_explain(self):
        pool_status: PoolStatus = {
            "semantic_ok": True,
            "keyword_ok": True,
            "entity_ok": False,
            "degraded": False,
        }
        candidates = [{"id": "a", "score": 0.8, "payload": {"data": "a"}, "sources": ["semantic"]}]
        scored = score_and_rank(candidates, {}, {}, 0.1, 10, explain=True, pool_status=pool_status)
        assert scored[0]["score_details"]["pool_status"] == pool_status

    def test_degraded_pool_marks_result(self):
        pool_status: PoolStatus = {
            "semantic_ok": False,
            "keyword_ok": True,
            "entity_ok": False,
            "degraded": True,
            "degradation_reason": "Semantic search failed",
        }
        candidates = [{"id": "a", "score": 0.0, "payload": {"data": "a"}, "sources": ["keyword"]}]
        bm25 = {"a": 0.8}
        scored = score_and_rank(candidates, bm25, {}, 0.1, 10, explain=True, pool_status=pool_status)
        assert scored[0]["degraded_from_hybrid"] is True
        assert scored[0]["score_details"]["pool_status"]["degraded"] is True
