/**
 * OSS unit tests — Reranker execution chain.
 * Covers SimpleReranker, LLMReranker fallback, topK truncation,
 * profile-driven rerank config wiring, and explain output fields.
 */
/// <reference types="jest" />
import { SimpleReranker } from "../src/rerankers/simple";
import { LLMReranker } from "../src/rerankers/llm";
import { MemoryItem, RerankerConfig } from "../src/types";
import { RerankerFactory } from "../src/utils/factory";

jest.setTimeout(15000);

// Mock Google modules to prevent @google/genai crash in CI
jest.mock("../src/embeddings/google", () => ({
  GoogleEmbedder: jest.fn(),
}));
jest.mock("../src/llms/google", () => ({
  GoogleLLM: jest.fn().mockImplementation(() => ({
    generateChat: jest.fn().mockResolvedValue({ content: "0.5" }),
  })),
}));

// Mock other LLM providers (they will fail during construction without keys,
// which is the intended fallback path)
jest.mock("../src/llms/anthropic", () => ({
  AnthropicLLM: jest.fn().mockImplementation(() => {
    throw new Error("No API key");
  }),
}));
jest.mock("../src/llms/groq", () => ({
  GroqLLM: jest.fn().mockImplementation(() => {
    throw new Error("No API key");
  }),
}));
jest.mock("../src/llms/openai", () => ({
  OpenAILLM: jest.fn().mockImplementation(() => ({
    generateChat: jest.fn().mockResolvedValue({ content: "0.8" }),
  })),
}));

function buildItems(count: number, prefix: string = "item"): MemoryItem[] {
  const items: MemoryItem[] = [];
  for (let i = 0; i < count; i++) {
    items.push({
      id: `${prefix}-${i}`,
      memory: `This is the content of memory ${i}. Contains keyword ${prefix}.`,
      hash: `hash-${i}`,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      score: 1.0 - i * 0.05,
      metadata: { category: `cat-${i % 3}` },
    });
  }
  return items;
}

describe("SimpleReranker (local token matching)", () => {
  it("is registered under provider names: simple, default, token_match", () => {
    expect(
      RerankerFactory.create("simple", { provider: "simple" }),
    ).toBeInstanceOf(SimpleReranker);
    expect(
      RerankerFactory.create("default", { provider: "default" }),
    ).toBeInstanceOf(SimpleReranker);
    expect(
      RerankerFactory.create("token_match", { provider: "token_match" }),
    ).toBeInstanceOf(SimpleReranker);
  });

  it("ranks items with exact token matches higher than pure positional", async () => {
    const items: MemoryItem[] = [
      {
        id: "a",
        memory: "foo bar baz qux",
        hash: "ha",
        createdAt: new Date().toISOString(),
        score: 0.5,
        metadata: {},
      },
      {
        id: "b",
        memory: "something else entirely different",
        hash: "hb",
        createdAt: new Date().toISOString(),
        score: 0.9, // higher original but no overlap
        metadata: {},
      },
      {
        id: "c",
        memory: "foo bar something",
        hash: "hc",
        createdAt: new Date().toISOString(),
        score: 0.6,
        metadata: {},
      },
    ];

    const reranker = new SimpleReranker({ provider: "simple" });
    const ranked = await reranker.rerank("foo bar", items);
    expect(ranked[0].id).toBe("c");
    expect(ranked[1].id).toBe("a");
    expect(ranked[2].id).toBe("b");
  });

  it("applies topK truncation correctly", async () => {
    const items = buildItems(10);
    const reranker = new SimpleReranker({ provider: "simple" });
    const ranked = await reranker.rerank("item", items, 3);
    expect(ranked).toHaveLength(3);
  });

  it("does not truncate when topK is omitted", async () => {
    const items = buildItems(5);
    const reranker = new SimpleReranker({ provider: "simple" });
    const ranked = await reranker.rerank("item", items);
    expect(ranked).toHaveLength(5);
  });

  it("returns empty for empty input", async () => {
    const reranker = new SimpleReranker({ provider: "simple" });
    const ranked = await reranker.rerank("query", []);
    expect(ranked).toEqual([]);
  });

  it("adds rerank_score and rerank_method metadata to each item", async () => {
    const items = buildItems(3);
    const reranker = new SimpleReranker({ provider: "simple" });
    const ranked = await reranker.rerank("item", items);
    for (const item of ranked) {
      expect(typeof item.metadata.rerank_score).toBe("number");
      expect(item.metadata.rerank_score).toBeGreaterThanOrEqual(0);
      expect(item.metadata.rerank_score).toBeLessThanOrEqual(1);
      expect(item.metadata.rerank_method).toBe("simple_token_match");
    }
  });

  it("honors custom blending weights from config", async () => {
    const items: MemoryItem[] = [
      {
        id: "x",
        memory: "fully matching query tokens here",
        hash: "hx",
        createdAt: new Date().toISOString(),
        score: 0.2, // low original
        metadata: {},
      },
      {
        id: "y",
        memory: "no overlap whatsoever",
        hash: "hy",
        createdAt: new Date().toISOString(),
        score: 0.95, // high original
        metadata: {},
      },
    ];

    // Blend favoring original score → y should win
    const config: RerankerConfig = {
      provider: "simple",
      config: {
        blendWithOriginalScore: true,
        originalScoreWeight: 0.95,
        exactMatchWeight: 0.6,
        sequentialMatchWeight: 0.4,
      },
    };
    const reranker = new SimpleReranker(config);
    const ranked = await reranker.rerank("fully matching query tokens", items);
    expect(ranked[0].id).toBe("y");
  });
});

describe("LLMReranker (true LLM-based) with fallback", () => {
  it("is registered under provider names: llm, openai, anthropic, groq, gemini", () => {
    // The provider names are mapped to LLMReranker class; instantiation will
    // either build the LLM client or fall back (depending on mock setup).
    const names = ["llm", "openai", "anthropic", "groq", "gemini"];
    for (const name of names) {
      const inst = RerankerFactory.create(name, { provider: name });
      expect(inst).toBeInstanceOf(LLMReranker);
    }
  });

  it("falls back to simple scoring when LLM client cannot be built", async () => {
    const items: MemoryItem[] = [
      {
        id: "hit",
        memory: "query terms appear here",
        hash: "h1",
        createdAt: new Date().toISOString(),
        score: 0.5,
        metadata: {},
      },
      {
        id: "miss",
        memory: "nothing relevant",
        hash: "h2",
        createdAt: new Date().toISOString(),
        score: 0.5,
        metadata: {},
      },
    ];
    // `anthropic` mock throws → triggers fallback path
    const reranker = new LLMReranker({ provider: "anthropic" });
    const ranked = await reranker.rerank("query terms appear", items);
    expect(ranked[0].id).toBe("hit");
    expect(ranked[0].metadata.rerank_method).toBe("simple_fallback");
  });

  it("applies topK even on fallback path", async () => {
    const items = buildItems(7);
    const reranker = new LLMReranker({ provider: "llm" });
    const ranked = await reranker.rerank("item", items, 2);
    expect(ranked).toHaveLength(2);
  });

  it("returns empty for empty input on fallback path", async () => {
    const reranker = new LLMReranker({ provider: "llm" });
    const ranked = await reranker.rerank("anything", []);
    expect(ranked).toEqual([]);
  });
});

describe("RerankerFactory - unknown provider throws", () => {
  it("throws a descriptive error for unsupported providers", () => {
    expect(() =>
      RerankerFactory.create("nonsense", { provider: "nonsense" }),
    ).toThrow(/Unsupported reranker provider/);
  });
});
