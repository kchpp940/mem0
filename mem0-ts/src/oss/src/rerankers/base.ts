import { MemoryItem } from "../types";

export interface Reranker {
  rerank(
    query: string,
    results: MemoryItem[],
    topK?: number,
  ): Promise<MemoryItem[]>;
}
