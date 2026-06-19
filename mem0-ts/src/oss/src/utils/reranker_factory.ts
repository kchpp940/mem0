import { BaseReranker } from "../reranker/base";
import { LLMReranker } from "../reranker/llm";
import { SimpleReranker } from "../reranker/simple";
import { LLM } from "../llms/base";

export class RerankerFactory {
  static create(
    provider: string,
    config: Record<string, any> = {},
    dependencies?: { llm?: LLM },
  ): BaseReranker {
    switch (provider.toLowerCase()) {
      case "llm":
        if (!dependencies?.llm) {
          throw new Error(
            "LLM reranker requires an LLM instance. Provide it via dependencies.llm",
          );
        }
        return new LLMReranker({
          llm: dependencies.llm,
          batchSize: config.batchSize,
        });
      case "simple":
        return new SimpleReranker({
          minScore: config.minScore ?? config.scoreThreshold,
        });
      default:
        throw new Error(
          `Unsupported reranker provider: ${provider}. Supported: llm, simple`,
        );
    }
  }
}
