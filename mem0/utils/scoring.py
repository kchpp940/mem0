"""
Scoring utilities for hybrid retrieval.

Provides:
- **BM25 normalization**: Sigmoid normalization of raw BM25 scores to [0, 1].
- **BM25 parameter selection**: Query-length-adaptive sigmoid parameters.
- **Additive scoring**: Combined scoring with semantic + BM25 + entity boost.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


def get_bm25_params(query: str, *, lemmatized: Optional[str] = None) -> tuple:
    """Get BM25 sigmoid parameters based on query length.

    Longer queries tend to have higher raw BM25 scores, so we adjust
    the sigmoid midpoint and steepness accordingly.

    Returns:
        (midpoint, steepness) for sigmoid normalization.
    """
    if lemmatized is None:
        from mem0.utils.lemmatization import lemmatize_for_bm25

        lemmatized = lemmatize_for_bm25(query)
    num_terms = len(lemmatized.split()) if lemmatized else 1

    if num_terms <= 3:
        return 5.0, 0.7
    elif num_terms <= 6:
        return 7.0, 0.6
    elif num_terms <= 9:
        return 9.0, 0.5
    elif num_terms <= 15:
        return 10.0, 0.5
    else:
        return 12.0, 0.5


def normalize_bm25(raw_score: float, midpoint: float, steepness: float) -> float:
    """Normalize BM25 score to [0, 1] using logistic sigmoid.

    Args:
        raw_score: Raw BM25 score (unbounded, typically 0-20+).
        midpoint: Score at which sigmoid outputs 0.5.
        steepness: Controls how quickly sigmoid transitions.

    Returns:
        Normalized score in range [0, 1].
    """
    return 1.0 / (1.0 + math.exp(-steepness * (raw_score - midpoint)))


ENTITY_BOOST_WEIGHT = 0.5


def score_and_rank(
    candidates: List[Dict[str, Any]],
    bm25_scores: Dict[str, float],
    entity_boosts: Dict[str, float],
    threshold: float,
    top_k: int,
    explain: bool = False,
) -> List[Dict[str, Any]]:
    """Score candidates additively and return top-k results.

    The candidate pool is the union of semantic, keyword, and entity-linked
    memories.  A candidate that was only found via keyword or entity boost
    (no semantic hit) has semantic_score = 0.0.

    Threshold gating:
        - Candidates with a semantic score pass if semantic >= threshold.
        - Candidates *without* a meaningful semantic score (pure keyword or
          pure entity) pass if they have at least one non-semantic signal
          (bm25 > 0 or entity_boost > 0).  This prevents purely semantic
          low-quality hits from leaking through while allowing keyword /
          entity-only matches to participate in ranking.

    Combined score:
        combined = (semantic + bm25 + entity_boost) / max_possible

    The divisor adapts based on which signals are active:
        - Semantic only: max_possible = 1.0
        - Semantic + BM25: max_possible = 2.0
        - Semantic + BM25 + entity: max_possible = 2.5
        - Semantic + entity (no BM25): max_possible = 1.5
        - BM25 only (no semantic): max_possible = 1.0
        - Entity only (no semantic): max_possible = ENTITY_BOOST_WEIGHT

    Args:
        candidates: Unified candidate pool (semantic + keyword + entity).
            Each dict must have "id", and may have "score" (semantic),
            "payload", "bm25_score", and "entity_boost".
        bm25_scores: Normalized keyword scores keyed by memory ID.
        entity_boosts: Entity-link boosts keyed by memory ID.
        threshold: Minimum semantic score required for semantic-only candidates.
        top_k: Maximum number of results to return.
        explain: Include score_details in each result when true.

    Returns:
        List of scored result dicts sorted by combined score descending.
    """
    has_bm25 = bool(bm25_scores)
    has_entity = bool(entity_boosts)

    scored: List[Dict[str, Any]] = []

    for result in candidates:
        mem_id = result.get("id")
        if mem_id is None:
            continue

        mem_id_str = str(mem_id)
        semantic_score = result.get("score") or 0.0
        bm25_score = bm25_scores.get(mem_id_str, result.get("bm25_score", 0.0))
        entity_boost = entity_boosts.get(mem_id_str, result.get("entity_boost", 0.0))

        has_semantic = semantic_score > 0.0
        has_non_semantic = bm25_score > 0.0 or entity_boost > 0.0

        if has_semantic and semantic_score < threshold and not has_non_semantic:
            continue

        if not has_semantic and not has_non_semantic:
            continue

        active_max = 0.0
        if has_semantic:
            active_max += 1.0
        if has_bm25 and bm25_score > 0.0:
            active_max += 1.0
        if has_entity and entity_boost > 0.0:
            active_max += ENTITY_BOOST_WEIGHT

        if active_max == 0.0:
            continue

        raw_combined = semantic_score + bm25_score + entity_boost
        combined = min(raw_combined / active_max, 1.0)

        scored_result = {
            "id": mem_id_str,
            "score": combined,
            "payload": result.get("payload"),
        }
        if explain:
            scored_result["score_details"] = {
                "semantic_score": semantic_score,
                "bm25_score": bm25_score,
                "entity_boost": entity_boost,
                "raw_score": raw_combined,
                "max_possible_score": active_max,
                "final_score": combined,
                "threshold": threshold,
            }
        scored.append(scored_result)

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]
