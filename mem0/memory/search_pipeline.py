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

    # -- Trace collector (single source of truth) --
    #
    # If ``None`` (default), the pipeline lazily creates a fresh
    # SearchTraceCollector so code that constructs SearchContexts manually
    # still gets trace collection for free.
    trace_collector: Optional["SearchTraceCollector"] = None

    # -- Escape hatch for custom recall steps --
    extra: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Backward-compatible ``ctx.trace`` dict — delegates to the collector.
    # Existing tests / code that read or mutate ``ctx.trace`` keep working:
    #   reads  → ctx.trace_collector.to_dict()
    #   writes → forwarded to the underlying collector where possible,
    #             otherwise stored in a shadow dict.
    # ------------------------------------------------------------------
    @property
    def trace(self) -> Dict[str, Any]:
        """Return a collector-backed view compatible with the old ``ctx.trace`` dict.

        Reading returns a fresh copy each time so consumers get immutable
        snapshots.  In-place mutation via ``ctx.trace["foo"] = bar`` writes
        through to a shadow dict that overlays the collector's serialisation
        (see ``_trace_overrides``).
        """
        if self.trace_collector is None:
            if not hasattr(self, "_trace_overrides") or self._trace_overrides is None:
                self._trace_overrides: Dict[str, Any] = {}
            return self._trace_overrides
        base = self.trace_collector.to_dict()
        if hasattr(self, "_trace_overrides") and self._trace_overrides:
            base.update(self._trace_overrides)
        return base

    @trace.setter
    def trace(self, value: Dict[str, Any]) -> None:
        # Assigning ``ctx.trace = {...}`` clears the shadow dict.
        self._trace_overrides = dict(value)

    def ensure_trace_collector(self) -> "SearchTraceCollector":
        """Return ctx.trace_collector, creating one if necessary.

        The pipeline calls this before running steps so the collector is
        always present by the time the first step emits stats.
        """
        if self.trace_collector is None:
            self.trace_collector = SearchTraceCollector()
        return self.trace_collector


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Unified trace collector — single source of truth for search pipeline traces
# ---------------------------------------------------------------------------

class SearchTraceCollector:
    """Single collector for search pipeline observations.

    All downstream consumers — ``explain=True`` payloads, CLI ``--trace``
    output, and anonymous telemetry properties — read from the same
    ``SearchTraceCollector`` instance so the pipeline never emits two
    different-shaped traces for one search.

    Usage pattern inside the pipeline::

        collector = SearchTraceCollector()
        collector.set_meta(query=..., filters=..., top_k=..., threshold=..., explain=...)

        for step in steps:
            collector.start_step(step.name)
            step.run_sync(ctx)
            collector.end_step(step.name, duration_ms=..., stats=step.build_trace_stats(ctx))

        collector.finalize(results_count=len(formatted_results))

    Consumers then pick their preferred view::

        collector.to_dict()           # explain=True  payload (ctx.trace)
        collector.telemetry_props()   # capture_event additional_data
        collector.summary()           # CLI --trace human-readable
    """

    # Canonical order for CLI summary / dict iteration.
    STEP_ORDER = (
        "query_normalization",
        "query_preprocessing",
        "recall_semantic",
        "recall_keyword",
        "recall_entity_boost",
        "candidate_merge",
        "score_fusion",
        "rerank",
        "result_format",
    )

    def __init__(self) -> None:
        self._step_durations_ms: Dict[str, float] = {}
        self._step_stats: Dict[str, Dict[str, Any]] = {}
        self._meta: Dict[str, Any] = {}
        self._total_elapsed_ms: Optional[float] = None
        self._results_count: Optional[int] = None
        # Pending start timestamps keyed by step name (for nesting safety).
        self._pending_start: Dict[str, float] = {}

    # -- meta ----------------------------------------------------------------

    def set_meta(
        self,
        *,
        query: str,
        filters: Dict[str, Any],
        top_k: int,
        threshold: float,
        explain: bool,
    ) -> None:
        """Record top-level search parameters captured before the pipeline runs."""
        self._meta.update(
            {
                "query": query,
                "filters": filters,
                "top_k": top_k,
                "threshold": threshold,
                "explain": explain,
            }
        )

    # -- step collection -----------------------------------------------------

    def start_step(self, name: str) -> None:
        """Mark the instant a step begins.

        Paired with :meth:`end_step` which reads the stored start timestamp
        when ``duration_ms`` is not passed explicitly.
        """
        self._pending_start[name] = time.perf_counter()

    def end_step(self, name: str, *, stats: Dict[str, Any], duration_ms: Optional[float] = None) -> None:
        """Finalise one step's trace entry.

        ``duration_ms`` is filled in from the matching :meth:`start_step`
        call when omitted (the common path).  Steps that measure themselves
        (e.g. batch async gather) can override it.
        """
        if duration_ms is None:
            start = self._pending_start.pop(name, None)
            duration_ms = 0.0 if start is None else (time.perf_counter() - start) * 1000.0
        else:
            # Remove any stray pending start so nesting stays consistent.
            self._pending_start.pop(name, None)

        self._step_durations_ms[name] = duration_ms
        self._step_stats[name] = stats or {}

    def finalize(self, *, results_count: int, total_elapsed_ms: Optional[float] = None) -> None:
        """Freeze the collector once the pipeline finishes.

        ``total_elapsed_ms`` defaults to the sum of step durations, which
        is accurate enough for profile- and telemetry-grade reports.  Callers
        that wall-time the entire pipeline can override for exactness.
        """
        self._results_count = results_count
        if total_elapsed_ms is None:
            total_elapsed_ms = sum(self._step_durations_ms.values())
        self._total_elapsed_ms = total_elapsed_ms

    # -- consumer views ------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return the ``explain=True``-compatible trace dict (ctx.trace shape).

        This view is identical to the previous ``ctx.trace`` dict so existing
        tests / clients that peek into ``result["trace"]`` keep working.
        """
        return {
            "step_durations_ms": dict(self._step_durations_ms),
            "steps": {name: dict(self._step_stats.get(name, {})) for name in self.STEP_ORDER if name in self._step_stats},
            "total_elapsed_ms": self._total_elapsed_ms if self._total_elapsed_ms is not None else 0.0,
            "query": self._meta.get("query"),
            "filters": self._meta.get("filters", {}),
            "top_k": self._meta.get("top_k"),
            "threshold": self._meta.get("threshold"),
            "explain": bool(self._meta.get("explain", False)),
            "results_count": self._results_count if self._results_count is not None else 0,
        }

    def telemetry_props(self) -> Dict[str, Any]:
        """Return a PostHog-friendly flat property dict for anonymous telemetry.

        Long strings (e.g. the raw query) are truncated, nested values are
        collapsed to counts / booleans / small strings so the event stays
        under PostHog property-size limits.
        """
        props: Dict[str, Any] = {}

        # Top-level meta (sanitised)
        props["query_len"] = len(self._meta.get("query", ""))
        props["top_k"] = self._meta.get("top_k")
        props["threshold"] = self._meta.get("threshold")
        props["explain"] = bool(self._meta.get("explain", False))
        filters = self._meta.get("filters") or {}
        props["filter_keys"] = sorted(filters.keys())[:8]
        props["filter_count"] = len(filters)
        props["results_count"] = self._results_count

        # Total / per-step durations (ms) — round to sub-ms precision
        if self._total_elapsed_ms is not None:
            props["total_elapsed_ms"] = round(self._total_elapsed_ms, 2)
        for step_name, dur in self._step_durations_ms.items():
            props[f"step_dur_ms__{step_name}"] = round(dur, 2)

        # Key per-step counters — expose only the low-cardinality ones
        sf_stats = self._step_stats.get("score_fusion", {})
        props["candidates_before_fusion"] = sf_stats.get("candidate_count_before")
        props["kept_after_threshold"] = sf_stats.get("kept_after_threshold")
        props["kept_after_top_k"] = sf_stats.get("kept_after_top_k")
        props["max_possible_score"] = sf_stats.get("max_possible_score")
        props["has_bm25"] = sf_stats.get("has_bm25")
        props["has_entity_boosts"] = sf_stats.get("has_entity_boosts")

        sem_stats = self._step_stats.get("recall_semantic", {})
        props["semantic_hits"] = sem_stats.get("hits_count")
        props["semantic_top_k_requested"] = sem_stats.get("top_k_requested")

        kw_stats = self._step_stats.get("recall_keyword", {})
        props["keyword_supported"] = kw_stats.get("supported")
        props["keyword_hits"] = kw_stats.get("hits_count")

        ent_stats = self._step_stats.get("recall_entity_boost", {})
        props["entity_queries_deduped"] = ent_stats.get("queries_deduped")
        props["entity_boosted_count"] = ent_stats.get("boosted_memory_count")

        rr_stats = self._step_stats.get("rerank", {})
        props["rerank_requested"] = rr_stats.get("requested")
        props["rerank_executed"] = rr_stats.get("executed")

        return props

    def summary(self) -> str:
        """Return a human-readable CLI ``--trace`` summary string.

        Multi-line, tabular output intended for terminal display.
        """
        lines: List[str] = []
        lines.append("=== Search Pipeline Trace ===")
        if self._total_elapsed_ms is not None:
            lines.append(f"Total: {self._total_elapsed_ms:.2f} ms  "
                         f"(results: {self._results_count})")
        lines.append("")
        lines.append(f"{'Step':<26} {'ms':>8}   Key stats")
        lines.append("-" * 80)
        for step_name in self.STEP_ORDER:
            if step_name not in self._step_stats:
                continue
            dur = self._step_durations_ms.get(step_name, 0.0)
            stats = self._step_stats.get(step_name, {})
            brief = self._summarise_step_stats(step_name, stats)
            lines.append(f"{step_name:<26} {dur:>8.2f}   {brief}")
        lines.append("-" * 80)
        return "\n".join(lines)

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _summarise_step_stats(step_name: str, stats: Dict[str, Any]) -> str:
        """Pick the most interesting 1-2 counters from a step's stats dict."""
        if step_name == "query_normalization":
            return f"filters={stats.get('filter_count', 0)}  " \
                   f"advanced={stats.get('has_advanced_operators', False)}"
        if step_name == "query_preprocessing":
            return f"entities={stats.get('entity_count', 0)}  " \
                   f"internal_limit={stats.get('internal_limit', 0)}"
        if step_name == "recall_semantic":
            return f"hits={stats.get('hits_count', 0)}  " \
                   f"score_range=({stats.get('min_score')}, {stats.get('max_score')})"
        if step_name == "recall_keyword":
            return f"supported={stats.get('supported', False)}  " \
                   f"hits={stats.get('hits_count', 0)}"
        if step_name == "recall_entity_boost":
            return f"boosted={stats.get('boosted_memory_count', 0)}  " \
                   f"total_boost={stats.get('total_boost', 0):.3f}"
        if step_name == "candidate_merge":
            return f"merged={stats.get('merged_candidate_count', 0)}  " \
                   f"bm25_scored={stats.get('bm25_scored_count', 0)}"
        if step_name == "score_fusion":
            return f"kept_after_threshold={stats.get('kept_after_threshold', 0)}  " \
                   f"final={stats.get('kept_after_top_k', 0)}  " \
                   f"threshold={stats.get('threshold')}"
        if step_name == "rerank":
            return f"executed={stats.get('executed', False)}  " \
                   f"reranked={stats.get('reranked_count', 0)}"
        if step_name == "result_format":
            return f"output={stats.get('output_count', 0)}  " \
                   f"dropped={stats.get('dropped_missing_data', 0)}"
        return ""


# ---------------------------------------------------------------------------
# Step abstraction
# ---------------------------------------------------------------------------


class PipelineStep(ABC):
    """Base class for every stage in the search pipeline.

    Subclasses implement :meth:`run_sync` and :meth:`run_async`.  Both receive
    the shared :class:`SearchContext` and are expected to mutate it in place
    (returning the same object is allowed for chaining convenience, but not
    required).

    :meth:`build_trace_stats` replaces the old ``record_trace`` mechanism.
    Each step returns a JSON-serialisable dict of its counters; the pipeline
    orchestrator (``SearchPipeline``) writes that dict into the *single*
    ``SearchTraceCollector`` owned by the :class:`SearchContext`.  This way
    ``explain=True`` payloads, CLI ``--trace`` output, and anonymous
    telemetry properties all read from one collector — never two different
    trace shapes for the same search.
    """

    name: str = "base_step"

    @abstractmethod
    def run_sync(self, ctx: SearchContext) -> SearchContext:
        ...

    @abstractmethod
    async def run_async(self, ctx: SearchContext) -> SearchContext:
        ...

    def build_trace_stats(self, ctx: SearchContext) -> Dict[str, Any]:
        """Return structured counters for this step's last execution.

        Default implementation returns an empty dict.  Subclasses override to
        expose interesting statistics.  The returned dict MUST be
        JSON-serialisable (no raw LLM responses, no numpy arrays, etc.) and
        should prefer counts / booleans / small strings over large blobs.
        """
        return {}

    # ------------------------------------------------------------------
    # Legacy shim — kept so code that monkeypatches ``step.record_trace``
    # still works during the transition.  New code MUST NOT override this.
    # ------------------------------------------------------------------
    def record_trace(self, ctx: SearchContext) -> None:
        # Delegate to the unified collector via ctx.trace_collector.
        if ctx.trace_collector is not None:
            ctx.trace_collector.end_step(self.name, stats=self.build_trace_stats(ctx))



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

    def build_trace_stats(self, ctx: SearchContext) -> Dict[str, Any]:
        filter_keys = sorted(ctx.normalized_filters.keys())
        has_advanced = bool(
            set(filter_keys) & {"AND", "OR", "NOT"}
        ) or any(isinstance(v, dict) for v in ctx.normalized_filters.values())
        return {
            "filters_keys": filter_keys,
            "filter_count": len(filter_keys),
            "has_advanced_operators": has_advanced,
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

    def build_trace_stats(self, ctx: SearchContext) -> Dict[str, Any]:
        return {
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

    def build_trace_stats(self, ctx: SearchContext) -> Dict[str, Any]:
        scores = [r.get("score") if isinstance(r, dict) else getattr(r, "score", 0.0) for r in ctx.semantic_results]
        return {
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

    def build_trace_stats(self, ctx: SearchContext) -> Dict[str, Any]:
        return {
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

    def build_trace_stats(self, ctx: SearchContext) -> Dict[str, Any]:
        boosted_ids = [mid for mid, val in ctx.entity_boosts.items() if val > 0]
        boost_values = list(ctx.entity_boosts.values())
        return {
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

    def build_trace_stats(self, ctx: SearchContext) -> Dict[str, Any]:
        bm25_values = list(ctx.bm25_scores.values())
        return {
            "semantic_input_count": len(ctx.semantic_results),
            "keyword_input_count": len(ctx.keyword_results) if ctx.keyword_results is not None else 0,
            "merged_candidate_count": len(ctx.candidates),
            "bm25_scored_count": len([s for s in bm25_values if s > 0]),
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

    def build_trace_stats(self, ctx: SearchContext) -> Dict[str, Any]:
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
        has_bm25 = bool(ctx.bm25_scores)
        has_entity = bool(ctx.entity_boosts)
        max_possible = 1.0
        if has_bm25:
            max_possible += 1.0
        if has_entity:
            max_possible += ENTITY_BOOST_WEIGHT
        return {
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

    def build_trace_stats(self, ctx: SearchContext) -> Dict[str, Any]:
        has_reranker = self._reranker is not None
        rerank_scores = [
            r.get("rerank_score")
            for r in ctx.scored_results
            if isinstance(r, dict) and r.get("rerank_score") is not None
        ]
        return {
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

    def build_trace_stats(self, ctx: SearchContext) -> Dict[str, Any]:
        dropped = len(ctx.scored_results) - len(ctx.formatted_results)
        has_score_details = any("score_details" in r for r in ctx.formatted_results)
        return {
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

    The pipeline owns exactly one :class:`SearchTraceCollector` (lazily
    created on the context).  :meth:`_run_step` and :meth:`_run_step_async`
    write per-step duration + structured counters into that collector.
    Downstream consumers — ``explain=True`` payload, CLI ``--trace``, and
    anonymous telemetry — all read from the SAME collector so they always
    see identical pipeline traces.  Never expose the collector via two
    different serialisations.
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
        """Run one step and emit its trace into the unified collector."""
        collector = ctx.ensure_trace_collector()
        collector.start_step(step.name)
        try:
            ctx = step.run_sync(ctx)
            return ctx
        finally:
            stats = step.build_trace_stats(ctx)
            collector.end_step(step.name, stats=stats)

    async def _run_step_async(self, step: PipelineStep, ctx: SearchContext) -> SearchContext:
        """Run one step async and emit its trace into the unified collector."""
        collector = ctx.ensure_trace_collector()
        collector.start_step(step.name)
        try:
            ctx = await step.run_async(ctx)
            return ctx
        finally:
            stats = step.build_trace_stats(ctx)
            collector.end_step(step.name, stats=stats)

    # -- public entry points --

    def run_sync(self, ctx: SearchContext) -> SearchContext:
        collector = ctx.ensure_trace_collector()
        # Populate top-level meta if caller hasn't already.
        if not collector._meta:
            collector.set_meta(
                query=ctx.query,
                filters=ctx.normalized_filters or (ctx.original_filters or {}),
                top_k=ctx.top_k,
                threshold=ctx.threshold,
                explain=ctx.explain,
            )
        for step in self._steps:
            ctx = self._run_step(step, ctx)
        collector.finalize(results_count=len(ctx.formatted_results))
        return ctx

    async def run_async(self, ctx: SearchContext) -> SearchContext:
        collector = ctx.ensure_trace_collector()
        if not collector._meta:
            collector.set_meta(
                query=ctx.query,
                filters=ctx.normalized_filters or (ctx.original_filters or {}),
                top_k=ctx.top_k,
                threshold=ctx.threshold,
                explain=ctx.explain,
            )
        for step in self._steps:
            ctx = await self._run_step_async(step, ctx)
        collector.finalize(results_count=len(ctx.formatted_results))
        return ctx
