import { MemoryItem, RerankerConfig } from "../types";
import { BaseReranker } from "./base";
import { LLMFactory } from "../utils/factory";
import { LLM } from "../llms/base";

export interface LLMRerankerConfig extends RerankerConfig {
  config?: {
    promptTemplate?: string;
    maxBatchSize?: number;
    useStructuredOutput?: boolean;
  };
}

const DEFAULT_PROMPT_TEMPLATE = `You are a relevance scoring expert. Given a query and a memory passage, rate the memory's relevance to the query on a scale of 0.0 to 1.0.

Scoring guidelines:
- 1.0: Perfectly relevant - the memory directly answers or addresses the query
- 0.7: Highly relevant - the memory contains significant information related to the query
- 0.5: Moderately relevant - the memory is somewhat related but not directly answering
- 0.3: Slightly relevant - the memory has minor tangential connection
- 0.0: Not relevant at all

Return ONLY a single number between 0.0 and 1.0 with no explanation.

Query: {query}

Memory: {memory}

Score:`;

export class LLMReranker extends BaseReranker {
  private llm: LLM | null = null;
  private promptTemplate: string;
  private maxBatchSize: number;
  private useStructuredOutput: boolean;

  constructor(config: LLMRerankerConfig) {
    super(config);
    this.promptTemplate =
      config.config?.promptTemplate ?? DEFAULT_PROMPT_TEMPLATE;
    this.maxBatchSize = config.config?.maxBatchSize ?? 10;
    this.useStructuredOutput = config.config?.useStructuredOutput ?? false;

    try {
      const llmProvider = config.provider || "openai";
      const llmConfig: any = {
        provider: llmProvider,
        apiKey: config.apiKey,
        baseURL: config.baseURL,
        model: config.model,
      };
      if (config.config) {
        llmConfig.config = config.config;
      }
      this.llm = LLMFactory.create(llmProvider, llmConfig);
    } catch (e) {
      console.warn(
        `LLMReranker: Failed to initialize LLM provider '${config.provider}': ${e}. ` +
          `Falling back to simple token-based reranking.`,
      );
      this.llm = null;
    }
  }

  async rerank(
    query: string,
    results: MemoryItem[],
    topK?: number,
  ): Promise<MemoryItem[]> {
    if (results.length === 0) return [];

    if (!this.llm) {
      return this._fallbackRerank(query, results, topK);
    }

    const scored = await this._llmRerank(query, results);

    scored.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));

    if (topK !== undefined && topK > 0) {
      return scored.slice(0, topK);
    }
    return scored;
  }

  private async _llmRerank(
    query: string,
    results: MemoryItem[],
  ): Promise<MemoryItem[]> {
    const scored: MemoryItem[] = [];

    for (let i = 0; i < results.length; i += this.maxBatchSize) {
      const batch = results.slice(i, i + this.maxBatchSize);
      const batchScores = await Promise.all(
        batch.map((item) => this._scoreWithLLM(query, item.memory)),
      );

      for (let j = 0; j < batch.length; j++) {
        const item = batch[j];
        const llmScore = batchScores[j];
        const existingScore = item.score ?? 0;

        scored.push({
          ...item,
          score: llmScore * 0.8 + existingScore * 0.2,
          metadata: {
            ...item.metadata,
            rerank_score: llmScore,
            rerank_method: "llm",
          },
        });
      }
    }

    return scored;
  }

  private async _scoreWithLLM(query: string, memory: string): Promise<number> {
    if (!this.llm) return 0.5;

    const prompt = this.promptTemplate
      .replace("{query}", query)
      .replace("{memory}", memory);

    try {
      const response = await this.llm.generateChat([
        { role: "user", content: prompt },
      ]);

      const content = response.content?.trim() || "";
      const match = content.match(/^(\d+\.?\d*)/);
      if (match) {
        const score = parseFloat(match[1]);
        if (!isNaN(score) && score >= 0 && score <= 1) {
          return score;
        }
      }

      return 0.5;
    } catch (e) {
      console.warn(`LLM scoring failed, using fallback: ${e}`);
      return 0.5;
    }
  }

  private _fallbackRerank(
    query: string,
    results: MemoryItem[],
    topK?: number,
  ): MemoryItem[] {
    const scored = results.map((item) => {
      const relevanceScore = this._simpleScore(query, item.memory);
      const existingScore = item.score ?? 0;
      return {
        ...item,
        score: relevanceScore * 0.7 + existingScore * 0.3,
        metadata: {
          ...item.metadata,
          rerank_score: relevanceScore,
          rerank_method: "simple_fallback",
        },
      };
    });

    scored.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));

    if (topK !== undefined && topK > 0) {
      return scored.slice(0, topK);
    }
    return scored;
  }

  private _simpleScore(query: string, memory: string): number {
    const queryTokens = query.toLowerCase().split(/\s+/).filter(Boolean);
    const memoryTokens = memory.toLowerCase().split(/\s+/).filter(Boolean);

    if (queryTokens.length === 0 || memoryTokens.length === 0) return 0.5;

    const querySet = new Set(queryTokens);
    let matchCount = 0;
    for (const token of querySet) {
      if (memoryTokens.includes(token)) matchCount++;
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

    return Math.min(1.0, Math.max(0.0, exactMatch * 0.6 + sequentialMatch * 0.4));
  }
}
