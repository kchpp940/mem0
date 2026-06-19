import { BaseReranker, RerankDocument, RerankResult } from "./base";

export interface SimpleRerankerConfig {
  minScore?: number;
  scoreThreshold?: number;
}

export class SimpleReranker extends BaseReranker {
  private minScore: number;

  constructor(config?: SimpleRerankerConfig) {
    super();
    this.minScore = config?.minScore ?? config?.scoreThreshold ?? 0;
  }

  async rerank(
    _query: string,
    documents: RerankDocument[],
    topK?: number,
  ): Promise<RerankResult[]> {
    if (documents.length === 0) return [];

    const results: RerankResult[] = documents
      .filter((doc) => (doc.score ?? 0) >= this.minScore)
      .map((doc) => ({
        ...doc,
        rerankScore: doc.score ?? 0,
        score: doc.score ?? 0,
      }));

    return this.applyTopK(results, topK);
  }
}
