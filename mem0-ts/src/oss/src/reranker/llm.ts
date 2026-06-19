import { BaseReranker, RerankDocument, RerankResult } from "./base";
import { LLM } from "../llms/base";
import { extractJson } from "../prompts";

const RERANK_PROMPT = `You are a relevance scoring assistant. Rate how relevant each document is to the query on a scale of 0 to 1.

Query: {{query}}

Documents:
{{documents}}

Respond with a JSON array of scores in the same order as the documents. Each item should have an "id" (the document index, 0-based) and a "score" (number between 0 and 1).

Example response:
[{"id": 0, "score": 0.85}, {"id": 1, "score": 0.3}]`;

export interface LLMRerankerConfig {
  llm: LLM;
  batchSize?: number;
}

export class LLMReranker extends BaseReranker {
  private llm: LLM;
  private batchSize: number;

  constructor(config: LLMRerankerConfig) {
    super();
    this.llm = config.llm;
    this.batchSize = config.batchSize ?? 20;
  }

  async rerank(
    query: string,
    documents: RerankDocument[],
    topK?: number,
  ): Promise<RerankResult[]> {
    if (documents.length === 0) return [];

    const results: RerankResult[] = [];

    for (let i = 0; i < documents.length; i += this.batchSize) {
      const batch = documents.slice(i, i + this.batchSize);
      const batchScores = await this._rerankBatch(query, batch);

      for (let j = 0; j < batch.length; j++) {
        const doc = batch[j];
        const rerankScore = batchScores[j] ?? 0;
        results.push({
          ...doc,
          rerankScore,
          score: rerankScore,
        });
      }
    }

    results.sort((a, b) => b.rerankScore - a.rerankScore);

    if (topK !== undefined && topK > 0) {
      return results.slice(0, topK);
    }

    return results;
  }

  private async _rerankBatch(
    query: string,
    documents: RerankDocument[],
  ): Promise<number[]> {
    const docList = documents
      .map((doc, idx) => `${idx}. ${doc.memory}`)
      .join("\n\n");

    const prompt = RERANK_PROMPT.replace("{{query}}", query).replace(
      "{{documents}}",
      docList,
    );

    try {
      const response = await this.llm.generateResponse([
        { role: "user", content: prompt },
      ]);

      const text = typeof response === "string" ? response : response?.content;
      const parsed = extractJson(text);

      if (Array.isArray(parsed)) {
        const scores: number[] = new Array(documents.length).fill(0);
        for (const item of parsed) {
          const idx = Number(item.id ?? item.index);
          if (!isNaN(idx) && idx >= 0 && idx < documents.length) {
            const score = Number(item.score ?? 0);
            scores[idx] = isNaN(score) ? 0 : Math.max(0, Math.min(1, score));
          }
        }
        return scores;
      }
    } catch (e) {
      console.warn("LLM reranking failed, falling back to original order:", e);
    }

    return documents.map((_, idx) => 1 - idx / documents.length);
  }
}
