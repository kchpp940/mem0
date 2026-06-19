import { MemoryItem, RerankerConfig } from "../types";

export interface Reranker {
  rerank(
    query: string,
    results: MemoryItem[],
    topK?: number,
  ): Promise<MemoryItem[]>;
}

export abstract class BaseReranker implements Reranker {
  protected config: RerankerConfig;

  constructor(config: RerankerConfig) {
    this.config = config;
  }

  abstract rerank(
    query: string,
    results: MemoryItem[],
    topK?: number,
  ): Promise<MemoryItem[]>;
}
