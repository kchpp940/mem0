"""Canonical hybrid search schema — authoritative field contract.

This module defines the field names, types, and semantics for hybrid search
results shared between the Python SDK and the TypeScript SDK.  Both runtimes
MUST align their output to the definitions here; any field rename or addition
must start in this file and propagate to the TS interfaces in
``mem0-ts/src/oss/src/utils/scoring.ts`` and
``mem0-ts/src/oss/src/types/index.ts``.

Naming convention
-----------------
All field names use **snake_case**.  The Python SDK uses snake_case
natively.  The TypeScript SDK also exposes snake_case keys in its public
API (``score_details``, ``degraded_from_hybrid``) for cross-language
consistency, even though TypeScript idiomatic style would prefer camelCase.

Schema versioning
-----------------
A single ``SCHEMA_VERSION`` integer is exported.  Bump it when any field
is added, renamed, or has its semantics changed.  Downstream consumers
can check this to detect incompatible changes.
"""

from __future__ import annotations

from typing import List, Optional, TypedDict

SCHEMA_VERSION: int = 1


class PoolStatusSchema(TypedDict):
    """Status of each retrieval lane in the candidate pool.

    Fields
    ------
    semantic_ok : bool
        Whether the semantic (vector) search lane returned successfully.
    keyword_ok : bool
        Whether the keyword (BM25) search lane returned successfully.
    entity_ok : bool
        Whether the entity boost lane produced any hits.
    degraded : bool
        True when the semantic lane failed but keyword/entity lanes
        still returned results.  Callers should treat these results
        as degraded — they lack semantic ranking.
    degradation_reason : str | None
        Human-readable reason when ``degraded`` is True.
    """

    semantic_ok: bool
    keyword_ok: bool
    entity_ok: bool
    degraded: bool
    degradation_reason: Optional[str]


class ScoreDetailsSchema(TypedDict):
    """Per-result scoring breakdown, attached when ``explain=True``.

    Fields
    ------
    semantic_score : float
        Raw cosine similarity from vector search (0.0 if not in semantic pool).
    bm25_score : float
        Sigmoid-normalised BM25 score (0.0 if no keyword match).
    entity_boost : float
        Boost from entity-link matches (0.0 if no entity match).
    raw_score : float
        ``semantic_score + bm25_score + entity_boost`` before normalisation.
    max_possible_score : float
        Adaptive divisor based on which signals are active for this candidate.
    final_score : float
        ``raw_score / max_possible_score``, clamped to [0, 1].
    threshold : float
        The semantic threshold that was applied during gating.
    sources : list[str]
        Which retrieval lanes contributed to this candidate.
        Possible values: ``"semantic"``, ``"keyword"``, ``"entity"``.
    pool_status : PoolStatusSchema | None
        Full pool status snapshot (same for all results in one search call).
        None when the caller did not request explain or pool status was
        not tracked for that call.
    """

    semantic_score: float
    bm25_score: float
    entity_boost: float
    raw_score: float
    max_possible_score: float
    final_score: float
    threshold: float
    sources: List[str]
    pool_status: Optional[PoolStatusSchema]


class CandidateSchema(TypedDict):
    """Internal candidate produced by ``build_candidate_pool``.

    Fields
    ------
    id : str
        Memory ID.
    score : float
        Semantic score (0.0 for keyword/entity-only candidates).
    payload : dict
        Memory payload from the vector store.
    sources : list[str]
        Which retrieval lanes contributed.  Possible values:
        ``"semantic"``, ``"keyword"``, ``"entity"``.
    """

    id: str
    score: float
    payload: dict
    sources: List[str]


class SearchResultItemSchema(TypedDict):
    """A single result returned by ``search()``.

    This is the **canonical** shape of a search result item.  Both the
    Python SDK and the TypeScript SDK must produce objects that conform
    to this schema.

    Fields
    ------
    id : str
        Memory ID.
    memory : str
        The memory text.
    hash : str | None
        Content hash.
    created_at : str | None
        ISO timestamp when the memory was created.
    updated_at : str | None
        ISO timestamp when the memory was last updated.
    score : float
        Final combined score in [0, 1].
    metadata : dict | None
        Additional key-value pairs from the payload.
    score_details : ScoreDetailsSchema | None
        Present when ``explain=True``.
    degraded_from_hybrid : bool | None
        Present and True when the search result came from a degraded
        pool (semantic lane failed).  None / absent in normal hybrid results.
    user_id : str | None
        Propagated from payload when present.
    agent_id : str | None
        Propagated from payload when present.
    run_id : str | None
        Propagated from payload when present.
    """

    id: str
    memory: str
    hash: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    score: Optional[float]
    metadata: Optional[dict]
    score_details: Optional[ScoreDetailsSchema]
    degraded_from_hybrid: Optional[bool]
    user_id: Optional[str]
    agent_id: Optional[str]
    run_id: Optional[str]
