"""
Search execution pipeline with clear stage boundaries.

Architecture:
    SearchPipeline orchestrates a sequence of PipelineStep instances.
    Each step reads from and writes to a shared SearchContext.

    Flow:
        1. QueryNormalizationStep   -> trim query, validate & normalize filters
        2. QueryPreprocessingStep   -> lemmatize, extract entities, embed query
        3. SemanticRecallStep       -> vector_store.search (semantic)
        4. KeywordRecallStep        -> vector_store.keyword_search (BM25)
        5. EntityBoostRecallStep    -> entity_store.search + per-memory boosts
        6. CandidateMergeStep       -> build unified candidate set, normalize BM25
        7. ScoreFusionStep          -> additive score fusion + threshold + top-k
        8. RerankStep               -> reranker.rerank (optional)
        9. ResultFormatStep         -> MemoryItem construction, annotate, promote keys

Why this layout:
    - Adding a new recall strategy = implement RecallStep subclass + insert into pipeline
    - Swapping reranker         = swap RerankStep, no other changes
    - Adding profile/trace      = wrap SearchPipeline._run_step with hooks
    - Vector store adapters     = only map backend query / return shapes, never sort or explain
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from mem0.configs.base import MemoryItem
from mem0.memory.lifecycle import annotate_memory_result
from mem0.utils.lemmatization import lemmatize_for_bm25
from mem0.utils.entity_extraction import extract_entities
from mem0.utils.scoring import (
    ENTITY_BOOST_WEIGHT,
    get_bm25_params,
    normalize_bm25,
    score_and_rank,
)

logger = logging.getLogger(__name__)

PROMOTED_PAYLOAD_KEYS = ["user_id", "agent_id", "run_id", "actor_id", "role"]
CORE_AND_PROMOTED_KEYS = {
    "data",
    "hash",
    "created_at",
    "updated_at",
    "id",
    "text_lemmatized",
    "attributed_to",
    "expires_at",
    "ttl_source",
    *PROMOTED_PAYLOAD_KEYS,
}


# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------


@dataclass
class SearchContext:
    """Mutable context flowing through every pipeline step.

    Steps read fields they need and write fields they produce.  Unknown fields
    are allowed via the ``extra`` dict for experimental recall strategies.
    """

    # -- Input (set by caller / QueryNormalizationStep) --
    query: str = ""
    original_filters: Optional[Dict[str, Any]] = None
    normalized_filters: Dict[str, Any] = field(default_factory=dict)
    top_k: int = 20
    threshold: float = 0.1
    rerank: bool = False
    explain: bool = False

    # -- QueryPreprocessingStep --
    query_lemmatized: str = ""
    query_entities: List[Tuple[str, str]] = field(default_factory=list)
    query_embedding: List[float] = field(default_factory=list)

    # -- Recall steps --
    internal_limit: int = 0
    semantic_results: List[Any] = field(default_factory=list)
    keyword_results: Optional[List[Any]] = None
    entity_boosts: Dict[str, float] = field(default_factory=dict)
    bm25_scores: Dict[str, float] = field(default_factory=dict)

    # -- CandidateMergeStep --
    candidates: List[Dict[str, Any]] = field(default_factory=list)

    # -- ScoreFusionStep --
    scored_results: List[Dict[str, Any]] = field(default_factory=list)

    # -- RerankStep --
    reranked: bool = False

    # -- ResultFormatStep --
    formatted_results: List[Dict[str, Any]] = field(default_factory=list)

    # -- Trace / profile (always collected, consumer decides what to expose) --
    #
    # Schema for ctx.trace:
    #
    #   ctx.trace["step_durations_ms"]  : Dict[str, float]  -- per-step wall time
    #   ctx.trace["steps"]              : Dict[str, Dict]   -- per-step structured stats
    #   ctx.trace["total_elapsed_ms"]   : float             -- total pipeline wall time
    #   ctx.trace["query"]              : str               -- normalized query (for reference)
    #   ctx.trace["filters"]            : Dict              -- normalized filters
    #   ctx.trace["top_k"]              : int
    #   ctx.trace["threshold"]          : float
    #   ctx.trace["explain"]            : bool
    #   ctx.trace["results_count"]      : int               -- final formatted result count
    #
    # Each step writes ctx.trace["steps"][self.name] = {...}.  Step names are
    # the same ones used in ctx.trace["step_durations_ms"] so consumers can
    # correlate duration with structured output.
    trace: Dict[str, Any] = field(default_factory=dict)

    # -- Escape hatch for custom recall steps --
    extra: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Step abstraction
# ---------------------------------------------------------------------------


class PipelineStep(ABC):
    """Base class for every stage in the search pipeline.

    Subclasses implement :meth:`run_sync` and :meth:`run_async`.  Both receive
    the shared :class:`SearchContext` and are expected to mutate it in place
    (returning the same object is allowed for chaining convenience, but not
    required).

    :meth:`record_trace` is invoked *after* the step runs (by the pipeline
    orchestrator) so every step has a single, consistent place to write its
    structured statistics into ``ctx.trace["steps"]``.
    """

    name: str = "base_step"

    @abstractmethod
    def run_sync(self, ctx: SearchContext) -> SearchContext:
        ...

    @abstractmethod
    async def run_async(self, ctx: SearchContext) -> SearchContext:
        ...

    def record_trace(self, ctx: SearchContext) -> None:
        """Write per-step structured statistics into ``ctx.trace["steps"]``.

        Override in subclasses to record meaningful counters.  The default
        implementation writes an empty dict so ``ctx.trace["steps"]`` always
        contains a key for every executed step.
        """
        ctx.trace.setdefault("steps", {}).setdefault(self.name, {})


# ---------------------------------------------------------------------------
# 1. Query + filter normalization
# ---------------------------------------------------------------------------


class QueryNormalizationStep(PipelineStep):
    """Validate search parameters and normalize the filters dict.

    Responsibilities:
      * Strip whitespace from the query string.
      * Trim / validate entity IDs inside filters.
      * Expand advanced metadata filter operators (AND/OR/NOT, eq/ne/...).
      * Enforce the "at least one entity ID" rule.
    """

    name = "query_normalization"

    def __init__(
        self,
        *,
        validate_and_trim_query: Callable[[str], str],
        validate_and_trim_entity_id: Callable[[str, str], str],
        validate_search_params: Callable[..., None],
        reject_top_level_entity_params: Callable[[Dict[str, Any], str], None],
        has_advanced_operators: Callable[[Dict[str, Any]], bool],
        process_metadata_filters: Callable[[Dict[str, Any]], Dict[str, Any]],
        extra_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._validate_query = validate_and_trim_query
        self._validate_entity_id = validate_and_trim_entity_id
        self._validate_params = validate_search_params
        self._reject_top_level = reject_top_level_entity_params
        self._has_advanced = has_advanced_operators
        self._process_metadata = process_metadata_filters
        self._extra_kwargs = extra_kwargs or {}

    # -- helpers --

    def _do_normalize(self, ctx: SearchContext) -> None:
        self._reject_top_level(self._extra_kwargs, "search")
        self._validate_params(threshold=ctx.threshold, top_k=ctx.top_k)
        ctx.query = self._validate_query(ctx.query)

        effective = ctx.original_filters.copy() if ctx.original_filters else {}

        for entity_key in ("user_id", "agent_id", "run_id"):
            if entity_key in effective:
                effective[entity_key] = self._validate_entity_id(effective[entity_key], entity_key)

        if not any(k in effective for k in ("user_id", "agent_id", "run_id")):
            raise ValueError(
                "filters must contain at least one of: user_id, agent_id, run_id. "
                "Example: filters={'user_id': 'u1'}"
            )

        if self._has_advanced(effective):
            processed = self._process_metadata(effective)
            for logical_key in ("AND", "OR", "NOT"):
                effective.pop(logical_key, None)
            for fk in list(effective.keys()):
                if fk not in ("AND", "OR", "NOT", "user_id", "agent_id", "run_id") and isinstance(
                    effective.get(fk), dict
                ):
                    effective.pop(fk, None)
            effective.update(processed)

        ctx.normalized_filters = effective

    # -- interfaces --

    def run_sync(self, ctx: SearchContext) -> SearchContext:
        self._do_normalize(ctx)
        return ctx

    async def run_async(self, ctx: SearchContext) -> SearchContext:
        self._do_normalize(ctx)
        return ctx

    def record_trace(self, ctx: SearchContext) -> None:
        super().record_trace(ctx)
        ctx.trace["steps"][self.name] = {
            "filters_keys": sorted(ctx.normalized_filters.keys()),
            "has_advanced_operators": bool(
                set(ctx.normalized_filters.keys()) & {"AND", "OR", "NOT"}
            )
            or any(isinstance(v, dict) for v in ctx.normalized_filters.values()),
            "query_length": len(ctx.query),
        }


# ---------------------------------------------------------------------------
# 2. Query preprocessing (lemmatize, entities, embedding)
# ---------------------------------------------------------------------------


class QueryPreprocessingStep(PipelineStep):
    """Run CPU/IO heavy query preparation so recall steps start from inputs.

    Outputs written to ctx:
      * query_lemmatized
      * query_entities
      * query_embedding
      * internal_limit (over-fetch factor used by recall steps)
    """

    name = "query_preprocessing"

    def __init__(self, embedding_model: Any) -> None:
        self._embedding_model = embedding_model

    def run_sync(self, ctx: SearchContext) -> SearchContext:
        ctx.query_lemmatized = lemmatize_for_bm25(ctx.query)
        ctx.query_entities = extract_entities(ctx.query)
        ctx.query_embedding = self._embedding_model.embed(ctx.query, "search")
        ctx.internal_limit = max(ctx.top_k * 4, 60)
        return ctx

    async def run_async(self, ctx: SearchContext) -> SearchContext:
        ctx.query_lemmatized = await asyncio.to_thread(lemmatize_for_bm25, ctx.query)
        ctx.query_entities = await asyncio.to_thread(extract_entities, ctx.query)
        ctx.query_embedding = await asyncio.to_thread(self._embedding_model.embed, ctx.query, "search")
        ctx.internal_limit = max(ctx.top_k * 4, 60)
        return ctx

    def record_trace(self, ctx: SearchContext) -> None:
        super().record_trace(ctx)
        ctx.trace["steps"][self.name] = {
            "lemmatized_query_length": len(ctx.query_lemmatized),
            "entity_count": len(ctx.query_entities),
            "entity_types": sorted({et for et, _ in ctx.query_entities}),
            "embedding_dim": len(ctx.query_embedding),
            "internal_limit": ctx.internal_limit,
        }


# ---------------------------------------------------------------------------
# 3 / 4 / 5. Recall steps (semantic, keyword, entity-boost)
# ---------------------------------------------------------------------------


class SemanticRecallStep(PipelineStep):
    """Execute vector (semantic) search against the configured vector store."""

    name = "recall_semantic"

    def __init__(self, vector_store: Any) -> None:
        self._vector_store = vector_store

    def run_sync(self, ctx: SearchContext) -> SearchContext:
        ctx.semantic_results = self._vector_store.search(
            query=ctx.query,
            vectors=ctx.query_embedding,
            top_k=ctx.internal_limit,
            filters=ctx.normalized_filters,
        )
        return ctx

    async def run_async(self, ctx: SearchContext) -> SearchContext:
        ctx.semantic_results = await asyncio.to_thread(
            self._vector_store.search,
            query=ctx.query,
            vectors=ctx.query_embedding,
            top_k=ctx.internal_limit,
            filters=ctx.normalized_filters,
        )
        return ctx

    def record_trace(self, ctx: SearchContext) -> None:
        super().record_trace(ctx)
        scores = [r.get("score") if isinstance(r, dict) else getattr(r, "score", 0.0) for r in ctx.semantic_results]
        ctx.trace["steps"][self.name] = {
            "hits_count": len(ctx.semantic_results),
            "min_score": min(scores) if scores else None,
            "max_score": max(scores) if scores else None,
            "top_k_requested": ctx.internal_limit,
        }


class KeywordRecallStep(PipelineStep):
    """Execute keyword / BM25 search if the vector store supports it.

    Stores raw keyword results on ctx; normalization to [0,1] happens later
    inside CandidateMergeStep so vector stores never need to know about
    sigmoid parameters or scoring fusion.
    """

    name = "recall_keyword"

    def __init__(self, vector_store: Any) -> None:
        self._vector_store = vector_store

    def run_sync(self, ctx: SearchContext) -> SearchContext:
        ctx.keyword_results = self._vector_store.keyword_search(
            query=ctx.query_lemmatized,
            top_k=ctx.internal_limit,
            filters=ctx.normalized_filters,
        )
        return ctx

    async def run_async(self, ctx: SearchContext) -> SearchContext:
        ctx.keyword_results = await asyncio.to_thread(
            self._vector_store.keyword_search,
            query=ctx.query_lemmatized,
            top_k=ctx.internal_limit,
            filters=ctx.normalized_filters,
        )
        return ctx

    def record_trace(self, ctx: SearchContext) -> None:
        super().record_trace(ctx)
        ctx.trace["steps"][self.name] = {
            "supported": ctx.keyword_results is not None,
            "hits_count": len(ctx.keyword_results) if ctx.keyword_results is not None else 0,
            "query_lemmatized": ctx.query_lemmatized,
        }


class EntityBoostRecallStep(PipelineStep):
    """Search the entity store and translate entity hits into memory boosts.

    Each extracted entity is searched against the entity store.  For each
    entity match whose similarity >= 0.5 we boost *linked* memory IDs by
    ``similarity * ENTITY_BOOST_WEIGHT * memory_count_weight``.

    Entity searches run concurrently (up to 4 workers / semaphore slots).
    A failure in any single entity search is logged and swallowed so other
    boosts still contribute.
    """

    name = "recall_entity_boost"

    def __init__(
        self,
        embedding_model: Any,
        entity_store: Any,
        *,
        entity_store_getter: Optional[Callable[[], Any]] = None,
    ) -> None:
        """
        Args:
            embedding_model: The embedder used for entity texts.
            entity_store: The entity vector store (eager reference).
            entity_store_getter: Optional zero-arg callable that returns the
                entity store.  When provided, it is invoked *at execution time*
                rather than construction time, which is important for stores
                that are lazily initialized (e.g. Memory.entity_store).
        """
        self._embedding_model = embedding_model
        self._entity_store_eager = entity_store
        self._entity_store_getter = entity_store_getter

    def _get_entity_store(self) -> Any:
        if self._entity_store_getter is not None:
            return self._entity_store_getter()
        return self._entity_store_eager

    # -- helpers --

    @staticmethod
    def _dedupe(entities: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
        seen: set[str] = set()
        deduped: List[Tuple[str, str]] = []
        for entity_type, entity_text in entities[:8]:
            key = entity_text.strip().lower()
            if key and key not in seen:
                seen.add(key)
                deduped.append((entity_type, entity_text))
        return deduped

    @staticmethod
    def _search_filters(filters: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in filters.items() if k in ("user_id", "agent_id", "run_id") and v}

    def _compute_boosts_from_matches(
        self, matches: List[Any], memory_boosts: Dict[str, float]
    ) -> None:
        for match in matches:
            similarity = match.score if hasattr(match, "score") else 0.0
            if similarity < 0.5:
                continue

            payload = match.payload if hasattr(match, "payload") else {}
            linked_memory_ids = payload.get("linked_memory_ids", [])
            if not isinstance(linked_memory_ids, list):
                continue

            num_linked = max(len(linked_memory_ids), 1)
            memory_count_weight = 1.0 / (1.0 + 0.001 * ((num_linked - 1) ** 2))
            boost = similarity * ENTITY_BOOST_WEIGHT * memory_count_weight

            for memory_id in linked_memory_ids:
                if memory_id:
                    memory_key = str(memory_id)
                    memory_boosts[memory_key] = max(
                        memory_boosts.get(memory_key, 0.0), boost
                    )

    # -- sync --

    def run_sync(self, ctx: SearchContext) -> SearchContext:
        if not ctx.query_entities:
            return ctx

        deduped = self._dedupe(ctx.query_entities)
        if not deduped:
            return ctx

        search_filters = self._search_filters(ctx.normalized_filters)
        memory_boosts: Dict[str, float] = {}

        try:
            entity_texts = [text for _, text in deduped]
            embeddings = self._embedding_model.embed_batch(entity_texts, "search")

            if len(embeddings) != len(entity_texts):
                logger.warning(
                    "embed_batch returned %d vectors for %d texts — skipping entity boost",
                    len(embeddings),
                    len(entity_texts),
                )
                ctx.entity_boosts = memory_boosts
                return ctx

            def _search_one(entity_text: str, embedding: List[float]) -> List[Any]:
                return self._get_entity_store().search(
                    query=entity_text,
                    vectors=embedding,
                    top_k=500,
                    filters=search_filters,
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                futures = {
                    pool.submit(_search_one, text, emb): text
                    for text, emb in zip(entity_texts, embeddings)
                }
                for future in concurrent.futures.as_completed(futures):
                    try:
                        matches = future.result()
                    except Exception as e:
                        logger.warning("Entity boost search failed for one entity: %s", e)
                        continue
                    self._compute_boosts_from_matches(matches, memory_boosts)
        except Exception as e:
            logger.warning("Entity boost computation failed: %s", e)

        ctx.entity_boosts = memory_boosts
        return ctx

    # -- async --

    async def run_async(self, ctx: SearchContext) -> SearchContext:
        if not ctx.query_entities:
            return ctx

        deduped = self._dedupe(ctx.query_entities)
        if not deduped:
            return ctx

        search_filters = self._search_filters(ctx.normalized_filters)
        memory_boosts: Dict[str, float] = {}

        try:
            entity_texts = [text for _, text in deduped]
            embeddings = await asyncio.to_thread(
                self._embedding_model.embed_batch, entity_texts, "search"
            )

            if len(embeddings) != len(entity_texts):
                logger.warning(
                    "embed_batch returned %d vectors for %d texts — skipping entity boost",
                    len(embeddings),
                    len(entity_texts),
                )
                ctx.entity_boosts = memory_boosts
                return ctx

            sem = asyncio.Semaphore(4)

            async def _search_one(entity_text: str, embedding: List[float]) -> List[Any]:
                async with sem:
                    return await asyncio.to_thread(
                        self._get_entity_store().search,
                        query=entity_text,
                        vectors=embedding,
                        top_k=500,
                        filters=search_filters,
                    )

            results = await asyncio.gather(
                *(_search_one(text, emb) for text, emb in zip(entity_texts, embeddings)),
                return_exceptions=True,
            )

            for matches in results:
                if isinstance(matches, BaseException):
                    logger.warning("Entity boost search failed for one entity: %s", matches)
                    continue
                self._compute_boosts_from_matches(matches, memory_boosts)
        except Exception as e:
            logger.warning("Entity boost computation failed: %s", e)

        ctx.entity_boosts = memory_boosts
        return ctx

    def record_trace(self, ctx: SearchContext) -> None:
        super().record_trace(ctx)
        boosted_ids = [mid for mid, val in ctx.entity_boosts.items() if val > 0]
        boost_values = list(ctx.entity_boosts.values())
        ctx.trace["steps"][self.name] = {
            "queries_searched": len(ctx.query_entities),
            "queries_deduped": len(self._dedupe(ctx.query_entities)),
            "boosted_memory_count": len(boosted_ids),
            "total_boost": sum(boost_values),
            "max_boost": max(boost_values) if boost_values else 0.0,
            "boost_weight": ENTITY_BOOST_WEIGHT,
        }


# ---------------------------------------------------------------------------
# 6. Candidate merge + BM25 normalization
# ---------------------------------------------------------------------------


class CandidateMergeStep(PipelineStep):
    """Build the unified candidate set and normalize keyword scores.

    Responsibilities:
      * Convert semantic results into the candidate dict shape
        (id/score/payload), normalising attribute-access vs dict-access objects.
      * Sigmoid-normalise raw BM25 scores returned by keyword search.
        Vector stores themselves never see these parameters.
    """

    name = "candidate_merge"

    @staticmethod
    def _id_of(mem: Any) -> str:
        return str(mem.id) if hasattr(mem, "id") else str(mem.get("id", ""))

    @staticmethod
    def _score_of(mem: Any) -> float:
        return mem.score if hasattr(mem, "score") else mem.get("score", 0)

    @staticmethod
    def _payload_of(mem: Any) -> Dict[str, Any]:
        return mem.payload if hasattr(mem, "payload") else (mem.get("payload") or {})

    def _do_merge(self, ctx: SearchContext) -> None:
        # --- BM25 normalization ---
        bm25_scores: Dict[str, float] = {}
        if ctx.keyword_results is not None:
            midpoint, steepness = get_bm25_params(ctx.query, lemmatized=ctx.query_lemmatized)
            for mem in ctx.keyword_results:
                mem_id = self._id_of(mem)
                raw_score = self._score_of(mem)
                if raw_score and raw_score > 0:
                    bm25_scores[mem_id] = normalize_bm25(raw_score, midpoint, steepness)
        ctx.bm25_scores = bm25_scores

        # --- Build candidate list from semantic hits ---
        candidates: List[Dict[str, Any]] = []
        for mem in ctx.semantic_results:
            candidates.append(
                {
                    "id": self._id_of(mem),
                    "score": self._score_of(mem),
                    "payload": self._payload_of(mem),
                }
            )
        ctx.candidates = candidates

    def run_sync(self, ctx: SearchContext) -> SearchContext:
        self._do_merge(ctx)
        return ctx

    async def run_async(self, ctx: SearchContext) -> SearchContext:
        self._do_merge(ctx)
        return ctx

    def record_trace(self, ctx: SearchContext) -> None:
        super().record_trace(ctx)
        bm25_count = len([s for s in ctx.bm25_scores.values() if s > 0])
        bm25_values = list(ctx.bm25_scores.values())
        ctx.trace["steps"][self.name] = {
            "semantic_input_count": len(ctx.semantic_results),
            "keyword_input_count": len(ctx.keyword_results) if ctx.keyword_results is not None else 0,
            "merged_candidate_count": len(ctx.candidates),
            "bm25_scored_count": bm25_count,
            "bm25_max": max(bm25_values) if bm25_values else 0.0,
            "bm25_params": get_bm25_params(ctx.query, lemmatized=ctx.query_lemmatized),
        }


# ---------------------------------------------------------------------------
# 7. Score fusion + threshold + top-k cut
# ---------------------------------------------------------------------------


class ScoreFusionStep(PipelineStep):
    """Run additive score fusion via mem0.utils.scoring.score_and_rank.

    Decoupled from any specific recall strategy — new recall channels should
    write their contributions into ctx.bm25_scores / ctx.entity_boosts or
    extend ctx via the ``extra`` dict and subclass this step accordingly.
    """

    name = "score_fusion"

    def _do_fuse(self, ctx: SearchContext) -> None:
        if ctx.threshold is None:
            ctx.threshold = 0.1
        ctx.scored_results = score_and_rank(
            semantic_results=ctx.candidates,
            bm25_scores=ctx.bm25_scores,
            entity_boosts=ctx.entity_boosts,
            threshold=ctx.threshold,
            top_k=ctx.top_k,
            explain=ctx.explain,
        )

    def run_sync(self, ctx: SearchContext) -> SearchContext:
        self._do_fuse(ctx)
        return ctx

    async def run_async(self, ctx: SearchContext) -> SearchContext:
        self._do_fuse(ctx)
        return ctx

    def record_trace(self, ctx: SearchContext) -> None:
        super().record_trace(ctx)
        # Count how many candidates were filtered out by the semantic threshold.
        sem_scores_in = [
            c.get("score", 0.0) if isinstance(c, dict) else getattr(c, "score", 0.0)
            for c in ctx.candidates
        ]
        below_threshold = sum(1 for s in sem_scores_in if s < ctx.threshold)
        final_scores = [
            r.get("score", 0.0) if isinstance(r, dict) else getattr(r, "score", 0.0)
            for r in ctx.scored_results
        ]
        score_details_present = any(
            (r.get("score_details") if isinstance(r, dict) else None)
            for r in ctx.scored_results
        )
        # Reconstruct max_possible (mirrors scoring.score_and_rank logic).
        has_bm25 = bool(ctx.bm25_scores)
        has_entity = bool(ctx.entity_boosts)
        max_possible = 1.0
        if has_bm25:
            max_possible += 1.0
        if has_entity:
            max_possible += ENTITY_BOOST_WEIGHT
        ctx.trace["steps"][self.name] = {
            "candidate_count_before": len(ctx.candidates),
            "below_threshold_count": below_threshold,
            "kept_after_threshold": len(ctx.candidates) - below_threshold,
            "kept_after_top_k": len(ctx.scored_results),
            "threshold": ctx.threshold,
            "top_k_requested": ctx.top_k,
            "max_possible_score": max_possible,
            "has_bm25": has_bm25,
            "has_entity_boosts": has_entity,
            "score_details_present": score_details_present,
            "min_final_score": min(final_scores) if final_scores else None,
            "max_final_score": max(final_scores) if final_scores else None,
        }


# ---------------------------------------------------------------------------
# 8. Rerank (optional)
# ---------------------------------------------------------------------------


class RerankStep(PipelineStep):
    """Invoke the reranker when ctx.rerank == True and a reranker is available.

    Reranker operates on the already score-fused list.  The reranker is free
    to reorder and inject a ``rerank_score`` field; we keep whatever shape it
    returns so swapping reranker implementations never requires touching this
    step beyond config.
    """

    name = "rerank"

    def __init__(self, reranker: Optional[Any]) -> None:
        self._reranker = reranker

    def run_sync(self, ctx: SearchContext) -> SearchContext:
        if not (ctx.rerank and self._reranker and ctx.scored_results):
            return ctx

        try:
            # Reranker operates on formatted memory dicts (with 'memory' field)
            pre_rerank = _pre_rerank_format(ctx.scored_results)
            reranked = self._reranker.rerank(ctx.query, pre_rerank, ctx.top_k)
            ctx.scored_results = _post_rerank_restore(reranked, ctx.scored_results)
            ctx.reranked = True
        except Exception as e:
            logger.warning("Reranking failed, using original results: %s", e)
        return ctx

    async def run_async(self, ctx: SearchContext) -> SearchContext:
        if not (ctx.rerank and self._reranker and ctx.scored_results):
            return ctx

        try:
            pre_rerank = _pre_rerank_format(ctx.scored_results)
            reranked = await asyncio.to_thread(
                self._reranker.rerank, ctx.query, pre_rerank, ctx.top_k
            )
            ctx.scored_results = _post_rerank_restore(reranked, ctx.scored_results)
            ctx.reranked = True
        except Exception as e:
            logger.warning("Reranking failed, using original results: %s", e)
        return ctx

    def record_trace(self, ctx: SearchContext) -> None:
        super().record_trace(ctx)
        has_reranker = self._reranker is not None
        rerank_scores = [
            r.get("rerank_score")
            for r in ctx.scored_results
            if isinstance(r, dict) and r.get("rerank_score") is not None
        ]
        ctx.trace["steps"][self.name] = {
            "requested": ctx.rerank,
            "reranker_available": has_reranker,
            "executed": bool(ctx.reranked),
            "reranked_count": len(rerank_scores),
            "rerank_scores_present": bool(rerank_scores),
        }


def _pre_rerank_format(scored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert scored_results (id/score/payload) into the MemoryItem-like
    dicts rerankers expect (with a ``memory`` field)."""
    out: List[Dict[str, Any]] = []
    for s in scored:
        payload = s.get("payload") or {}
        item = {
            "id": s["id"],
            "memory": payload.get("data", ""),
            "score": s["score"],
            "hash": payload.get("hash"),
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
        }
        for k in PROMOTED_PAYLOAD_KEYS:
            if k in payload:
                item[k] = payload[k]
        if "score_details" in s:
            item["score_details"] = s["score_details"]
        out.append(item)
    return out


def _post_rerank_restore(
    reranked: List[Dict[str, Any]], original_scored: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Reattach payload/score_details from scored_results after reranker."""
    by_id = {s["id"]: s for s in original_scored}
    restored: List[Dict[str, Any]] = []
    for r in reranked:
        mem_id = r.get("id")
        orig = by_id.get(mem_id, {})
        entry = {
            "id": mem_id,
            "score": r.get("score") if r.get("score") is not None else orig.get("score", 0.0),
            "payload": orig.get("payload") or {},
        }
        # Preserve score_details if present originally + requested via explain
        if "score_details" in orig:
            entry["score_details"] = orig["score_details"]
        restored.append(entry)
    return restored


# ---------------------------------------------------------------------------
# 9. Result formatting
# ---------------------------------------------------------------------------


class ResultFormatStep(PipelineStep):
    """Build the final MemoryItem-compatible dict list returned to callers.

    Also performs:
      * TTL annotation (expires_at, ttl_state, ttl_source).
      * Extraction of promoted payload keys to the top level.
      * ``metadata`` bucket for any non-core payload fields.
    """

    name = "result_format"

    def _do_format(self, ctx: SearchContext) -> None:
        formatted: List[Dict[str, Any]] = []

        for scored in ctx.scored_results:
            payload = scored.get("payload") or {}
            if not payload.get("data"):
                continue

            memory_item_dict = MemoryItem(
                id=scored["id"],
                memory=payload.get("data", ""),
                hash=payload.get("hash"),
                created_at=payload.get("created_at"),
                updated_at=payload.get("updated_at"),
                expires_at=payload.get("expires_at"),
                ttl_source=payload.get("ttl_source"),
                score=scored["score"],
            ).model_dump()

            for key in PROMOTED_PAYLOAD_KEYS:
                if key in payload:
                    memory_item_dict[key] = payload[key]

            additional_metadata = {
                k: v for k, v in payload.items() if k not in CORE_AND_PROMOTED_KEYS
            }
            if additional_metadata:
                if not memory_item_dict.get("metadata"):
                    memory_item_dict["metadata"] = {}
                memory_item_dict["metadata"].update(additional_metadata)

            if ctx.explain and "score_details" in scored:
                memory_item_dict["score_details"] = scored["score_details"]

            annotate_memory_result(memory_item_dict)
            formatted.append(memory_item_dict)

        ctx.formatted_results = formatted

    def run_sync(self, ctx: SearchContext) -> SearchContext:
        self._do_format(ctx)
        return ctx

    async def run_async(self, ctx: SearchContext) -> SearchContext:
        self._do_format(ctx)
        return ctx

    def record_trace(self, ctx: SearchContext) -> None:
        super().record_trace(ctx)
        dropped = len(ctx.scored_results) - len(ctx.formatted_results)
        has_score_details = any("score_details" in r for r in ctx.formatted_results)
        ctx.trace["steps"][self.name] = {
            "input_count": len(ctx.scored_results),
            "output_count": len(ctx.formatted_results),
            "dropped_missing_data": max(dropped, 0),
            "score_details_attached": has_score_details,
            "explain_requested": ctx.explain,
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class SearchPipeline:
    """Ordered collection of :class:`PipelineStep` instances.

    Usage::

        pipeline = SearchPipeline([
            QueryNormalizationStep(...),
            QueryPreprocessingStep(...),
            ...
        ])
        ctx = SearchContext(query="...", top_k=10, ...)
        pipeline.run_sync(ctx)
        results = ctx.formatted_results

    Trace hooks (profile/trace) can be added by overriding :meth:`_run_step`
    (sync) and :meth:`_run_step_async` (async).  The default implementation
    records per-step wall time into ``ctx.trace["step_durations_ms"]``.
    """

    def __init__(self, steps: List[PipelineStep]) -> None:
        if not steps:
            raise ValueError("SearchPipeline requires at least one step")
        self._steps = list(steps)

    @property
    def steps(self) -> List[PipelineStep]:
        return list(self._steps)

    # -- hooks for profiling / tracing --

    def _run_step(self, step: PipelineStep, ctx: SearchContext) -> SearchContext:
        start = time.perf_counter()
        try:
            ctx = step.run_sync(ctx)
            return ctx
        finally:
            dur_ms = (time.perf_counter() - start) * 1000.0
            ctx.trace.setdefault("step_durations_ms", {})[step.name] = dur_ms
            step.record_trace(ctx)

    async def _run_step_async(self, step: PipelineStep, ctx: SearchContext) -> SearchContext:
        start = time.perf_counter()
        try:
            ctx = await step.run_async(ctx)
            return ctx
        finally:
            dur_ms = (time.perf_counter() - start) * 1000.0
            ctx.trace.setdefault("step_durations_ms", {})[step.name] = dur_ms
            step.record_trace(ctx)

    # -- public entry points --

    def run_sync(self, ctx: SearchContext) -> SearchContext:
        pipeline_start = time.perf_counter()
        for step in self._steps:
            ctx = self._run_step(step, ctx)
        ctx.trace["total_elapsed_ms"] = (time.perf_counter() - pipeline_start) * 1000.0
        ctx.trace.setdefault("query", ctx.query)
        ctx.trace.setdefault("filters", ctx.normalized_filters)
        ctx.trace.setdefault("top_k", ctx.top_k)
        ctx.trace.setdefault("threshold", ctx.threshold)
        ctx.trace.setdefault("explain", ctx.explain)
        ctx.trace.setdefault("results_count", len(ctx.formatted_results))
        return ctx

    async def run_async(self, ctx: SearchContext) -> SearchContext:
        pipeline_start = time.perf_counter()
        for step in self._steps:
            ctx = await self._run_step_async(step, ctx)
        ctx.trace["total_elapsed_ms"] = (time.perf_counter() - pipeline_start) * 1000.0
        ctx.trace.setdefault("query", ctx.query)
        ctx.trace.setdefault("filters", ctx.normalized_filters)
        ctx.trace.setdefault("top_k", ctx.top_k)
        ctx.trace.setdefault("threshold", ctx.threshold)
        ctx.trace.setdefault("explain", ctx.explain)
        ctx.trace.setdefault("results_count", len(ctx.formatted_results))
        return ctx
