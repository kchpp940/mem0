export interface RerankerConfig {
  provider: string;
  config?: Record<string, any>;
  topN?: number;
}

export interface RerankDocument {
  id: string;
  memory: string;
  score?: number;
  metadata?: Record<string, any>;
  [key: string]: any;
}

export interface RerankResult {
  id: string;
  memory: string;
  score: number;
  rerankScore: number;
  metadata?: Record<string, any>;
  [key: string]: any;
}

export abstract class BaseReranker {
  abstract rerank(
    query: string,
    documents: RerankDocument[],
    topK?: number,
  ): Promise<RerankResult[]>;

  protected applyTopK(results: RerankResult[], topK?: number): RerankResult[] {
    results.sort((a, b) => b.rerankScore - a.rerankScore);
    if (topK !== undefined && topK > 0) {
      return results.slice(0, topK);
    }
    return results;
  }

  protected fallbackRerank(
    documents: RerankDocument[],
    topK?: number,
  ): RerankResult[] {
    const results = documents.map((doc, idx) => ({
      ...doc,
      rerankScore: doc.score ?? 1 - idx / Math.max(documents.length, 1),
      score: doc.score ?? 1 - idx / Math.max(documents.length, 1),
    }));
    return this.applyTopK(results, topK);
  }
}
