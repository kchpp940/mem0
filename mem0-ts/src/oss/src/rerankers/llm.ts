import { MemoryItem, RerankerConfig } from "../types";
import { BaseReranker } from "./base";

export interface LLMRerankerConfig extends RerankerConfig {
  config?: {
    promptTemplate?: string;
    maxConcurrency?: number;
  };
}

const DEFAULT_PROMPT_TEMPLATE = `You are a relevance scorer. Given a query and a memory, rate the memory's relevance to the query on a scale of 0.0 to 1.0, where 1.0 is perfectly relevant and 0.0 is completely irrelevant.

Query: {query}

Memory: {memory}

Return only a single number between 0.0 and 1.0.`;

export class LLMReranker extends BaseReranker {
  private promptTemplate: string;

  constructor(config: LLMRerankerConfig) {
    super(config);
    this.promptTemplate =
      config.config?.promptTemplate ?? DEFAULT_PROMPT_TEMPLATE;
  }

  async rerank(
    query: string,
    results: MemoryItem[],
    topK?: number,
  ): Promise<MemoryItem[]> {
    if (results.length === 0) return [];

    const scored = await Promise.all(
      results.map(async (item) => {
        const relevanceScore = await this._scoreRelevance(query, item.memory);
        const existingScore = item.score ?? 0;
        return {
          ...item,
          score: relevanceScore * 0.7 + existingScore * 0.3,
          metadata: {
            ...item.metadata,
            rerank_score: relevanceScore,
          },
        };
      }),
    );

    scored.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));

    if (topK !== undefined && topK > 0) {
      return scored.slice(0, topK);
    }
    return scored;
  }

  private async _scoreRelevance(query: string, memory: string): Promise<number> {
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

    const score = exactMatch * 0.6 + sequentialMatch * 0.4;
    return Math.min(1.0, Math.max(0.0, score));
  }
}
