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
}
