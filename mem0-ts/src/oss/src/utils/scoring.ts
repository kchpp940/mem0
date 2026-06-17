/**
 * Scoring utilities for hybrid retrieval.
 *
 * Provides:
 * - BM25 normalization: Sigmoid normalization of raw BM25 scores to [0, 1].
 * - BM25 parameter selection: Query-length-adaptive sigmoid parameters.
 * - Additive scoring: Combined scoring with semantic + BM25 + entity boost.
 *
 * Field names use snake_case for cross-language consistency with the
 * Python SDK.  The authoritative definitions live in
 * mem0/utils/hybrid_search_schema.py; these interfaces MUST stay in sync.
 */

import type { PoolStatus, ScoreDetails } from "../types";

export { SCHEMA_VERSION } from "../types";
export type { PoolStatus, ScoreDetails };

export const ENTITY_BOOST_WEIGHT = 0.5;

export interface ScoredResult {
  id: string;
  score: number;
  payload: Record<string, any>;
  score_details?: ScoreDetails;
  degraded_from_hybrid?: boolean;
}

/**
 * Get BM25 sigmoid parameters based on query length.
 *
 * Longer queries tend to have higher raw BM25 scores, so we adjust
 * the sigmoid midpoint and steepness accordingly.
 *
 * @param query - The original query string.
 * @param lemmatized - Optional pre-lemmatized query string. If not provided,
 *   the term count is estimated from the raw query.
 * @returns A tuple of [midpoint, steepness] for sigmoid normalization.
 */
export function getBm25Params(
  query: string,
  lemmatized?: string,
): [number, number] {
  const text = lemmatized ?? query;
  const numTerms = text.trim().split(/\s+/).filter(Boolean).length || 1;

  if (numTerms <= 3) {
    return [5.0, 0.7];
  } else if (numTerms <= 6) {
    return [7.0, 0.6];
  } else if (numTerms <= 9) {
    return [9.0, 0.5];
  } else if (numTerms <= 15) {
    return [10.0, 0.5];
  } else {
    return [12.0, 0.5];
  }
}

/**
 * Normalize a raw BM25 score to [0, 1] using logistic sigmoid.
 *
 * @param rawScore - Raw BM25 score (unbounded, typically 0-20+).
 * @param midpoint - Score at which sigmoid outputs 0.5.
 * @param steepness - Controls how quickly sigmoid transitions.
 * @returns Normalized score in range [0, 1].
 */
export function normalizeBm25(
  rawScore: number,
  midpoint: number,
  steepness: number,
): number {
  return 1.0 / (1.0 + Math.exp(-steepness * (rawScore - midpoint)));
}

/**
 * Score candidates additively and return top-k results.
 *
 * The candidate pool is the union of semantic, keyword, and entity-linked
 * memories.  A candidate that was only found via keyword or entity boost
 * (no semantic hit) has semantic_score = 0.
 *
 * Threshold gating:
 *   - Candidates with a semantic score pass if semantic >= threshold.
 *   - Candidates *without* a meaningful semantic score (pure keyword or
 *     pure entity) pass if they have at least one non-semantic signal
 *     (bm25 > 0 or entity_boost > 0).
 *
 * Combined score:
 *   combined = (semantic + bm25 + entity_boost) / max_possible
 *
 * The divisor adapts based on which signals are active for each candidate.
 *
 * @param candidates - Unified candidate pool (semantic + keyword + entity).
 * @param bm25Scores - Map of memory ID to normalized BM25 score.
 * @param entityBoosts - Map of memory ID to entity boost score.
 * @param threshold - Minimum semantic score for semantic-only candidates.
 * @param topK - Maximum number of results to return.
 * @param explain - Include score_details in each result when true.
 * @param poolStatus - Optional pool status that, if provided with
 *   explain=true, will be attached to each result's score_details.
 * @returns Sorted list of scored results, highest score first.
 */
export function scoreAndRank(
  candidates: Array<{
    id: string;
    score: number;
    payload: Record<string, any>;
    sources?: string[];
  }>,
  bm25Scores: Record<string, number>,
  entityBoosts: Record<string, number>,
  threshold: number,
  topK: number,
  explain: boolean = false,
  poolStatus?: PoolStatus,
): ScoredResult[] {
  const hasBm25 = Object.keys(bm25Scores).length > 0;
  const hasEntity = Object.keys(entityBoosts).length > 0;

  const scored: ScoredResult[] = [];

  for (const result of candidates) {
    const memId = result.id;
    if (memId == null) {
      continue;
    }

    const semanticScore = result.score ?? 0.0;
    const bm25Score = bm25Scores[memId] ?? 0.0;
    const entityBoost = entityBoosts[memId] ?? 0.0;
    const sources = result.sources ?? [];

    const hasSemantic = semanticScore > 0.0;
    const hasNonSemantic = bm25Score > 0.0 || entityBoost > 0.0;

    if (hasSemantic && semanticScore < threshold && !hasNonSemantic) {
      continue;
    }

    if (!hasSemantic && !hasNonSemantic) {
      continue;
    }

    let activeMax = 0.0;
    if (hasSemantic) {
      activeMax += 1.0;
    }
    if (hasBm25 && bm25Score > 0.0) {
      activeMax += 1.0;
    }
    if (hasEntity && entityBoost > 0.0) {
      activeMax += ENTITY_BOOST_WEIGHT;
    }

    if (activeMax === 0.0) {
      continue;
    }

    const rawCombined = semanticScore + bm25Score + entityBoost;
    const combined = Math.min(rawCombined / activeMax, 1.0);

    const entry: ScoredResult = {
      id: memId,
      score: combined,
      payload: result.payload,
    };
    if (explain) {
      const details: ScoreDetails = {
        semantic_score: semanticScore,
        bm25_score: bm25Score,
        entity_boost: entityBoost,
        raw_score: rawCombined,
        max_possible_score: activeMax,
        final_score: combined,
        threshold,
        sources,
      };
      if (poolStatus) {
        details.pool_status = poolStatus;
      }
      entry.score_details = details;
      if (poolStatus?.degraded) {
        entry.degraded_from_hybrid = true;
      }
    }
    scored.push(entry);
  }

  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, topK);
}
