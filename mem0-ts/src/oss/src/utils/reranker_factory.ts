import { BaseReranker } from "../reranker/base";
import { LLMReranker } from "../reranker/llm";
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
      default:
        throw new Error(
          `Unsupported reranker provider: ${provider}. Supported: llm`,
        );
    }
  }
}
