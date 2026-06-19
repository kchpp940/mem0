import { MemoryItem, RerankerConfig } from "../types";
import { BaseReranker } from "./base";

export interface SimpleRerankerConfig extends RerankerConfig {
  config?: {
    exactMatchWeight?: number;
    sequentialMatchWeight?: number;
    blendWithOriginalScore?: boolean;
    originalScoreWeight?: number;
  };
}

const DEFAULT_EXACT_MATCH_WEIGHT = 0.6;
const DEFAULT_SEQUENTIAL_MATCH_WEIGHT = 0.4;
const DEFAULT_BLEND_WITH_ORIGINAL = true;
const DEFAULT_ORIGINAL_SCORE_WEIGHT = 0.3;

export class SimpleReranker extends BaseReranker {
  private exactMatchWeight: number;
  private sequentialMatchWeight: number;
  private blendWithOriginalScore: boolean;
  private originalScoreWeight: number;

  constructor(config: SimpleRerankerConfig) {
    super(config);
    this.exactMatchWeight =
      config.config?.exactMatchWeight ?? DEFAULT_EXACT_MATCH_WEIGHT;
    this.sequentialMatchWeight =
      config.config?.sequentialMatchWeight ?? DEFAULT_SEQUENTIAL_MATCH_WEIGHT;
    this.blendWithOriginalScore =
      config.config?.blendWithOriginalScore ?? DEFAULT_BLEND_WITH_ORIGINAL;
    this.originalScoreWeight =
      config.config?.originalScoreWeight ?? DEFAULT_ORIGINAL_SCORE_WEIGHT;
  }

  async rerank(
    query: string,
    results: MemoryItem[],
    topK?: number,
  ): Promise<MemoryItem[]> {
    if (results.length === 0) return [];

    const scored = results.map((item) => {
      const relevanceScore = this._scoreRelevance(query, item.memory);
      const existingScore = item.score ?? 0;

      let finalScore: number;
      if (this.blendWithOriginalScore) {
        const rerankWeight = 1.0 - this.originalScoreWeight;
        finalScore =
          relevanceScore * rerankWeight + existingScore * this.originalScoreWeight;
      } else {
        finalScore = relevanceScore;
      }

      return {
        ...item,
        score: finalScore,
        metadata: {
          ...item.metadata,
          rerank_score: relevanceScore,
          rerank_method: "simple_token_match",
        },
      };
    });

    scored.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));

    if (topK !== undefined && topK > 0) {
      return scored.slice(0, topK);
    }
    return scored;
  }

  private _scoreRelevance(query: string, memory: string): number {
    const queryTokens = query.toLowerCase().split(/\s+/).filter(Boolean);
    const memoryTokens = memory.toLowerCase().split(/\s+/).filter(Boolean);

    if (queryTokens.length === 0 || memoryTokens.length === 0) return 0.5;

    const querySet = new Set(queryTokens);
    let matchCount = 0;
    for (const token of querySet) {
      if (memoryTokens.includes(token)) {
        matchCount++;
      }
    }

    const exactMatch = matchCount / querySet.size;

    let longestMatch = 0;
    let currentMatch = 0;
    for (const token of memoryTokens) {
      if (querySet.has(token)) {
        currentMatch++;
        longestMatch = Math.max(longestMatch, currentMatch);
      } else {
        currentMatch = 0;
      }
    }
    const sequentialMatch = longestMatch / querySet.size;

    const score =
      exactMatch * this.exactMatchWeight +
      sequentialMatch * this.sequentialMatchWeight;
    return Math.min(1.0, Math.max(0.0, score));
  }
}
