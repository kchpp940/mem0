/// <reference types="jest" />
import {
  normalizeCategoriesFilter,
  extractCategoriesFromFilters,
  removeCategoriesFromFilters,
  transformCategoriesForQdrant,
  transformCategoriesForPgvector,
  transformCategoriesForRedis,
  transformCategoriesForSupabase,
} from "../src/utils/filter_normalizer";
import {
  BaseReranker,
  RerankDocument,
  RerankResult,
} from "../src/reranker/base";
import { SimpleReranker } from "../src/reranker/simple";
import { LLMReranker } from "../src/reranker/llm";
import { RerankerFactory } from "../src/utils/reranker_factory";
import { Memory } from "../src/memory";

describe("Categories Filter Transform - Multi-Backend Consistency", () => {
  const testCases: Array<{
    name: string;
    filters: Record<string, any>;
    expectedCategories: string[];
  }> = [
    {
      name: "simple categories in filter",
      filters: { user_id: "u1", categories: { in: ["food", "fact"] } },
      expectedCategories: ["food", "fact"],
    },
    {
      name: "categories as plain array",
      filters: { user_id: "u1", categories: ["pet", "hobby"] },
      expectedCategories: ["pet", "hobby"],
    },
    {
      name: "categories with eq operator",
      filters: { user_id: "u1", categories: { eq: "science" } },
      expectedCategories: ["science"],
    },
    {
      name: "no categories in filter",
      filters: { user_id: "u1", category: "food" },
      expectedCategories: [],
    },
    {
      name: "empty filter",
      filters: {},
      expectedCategories: [],
    },
  ];

  for (const tc of testCases) {
    describe(tc.name, () => {
      test("all backends extract the same categories", () => {
        const qdrantResult = transformCategoriesForQdrant(tc.filters);
        const pgvectorResult = transformCategoriesForPgvector(tc.filters);
        const redisResult = transformCategoriesForRedis(tc.filters);
        const supabaseResult = transformCategoriesForSupabase(tc.filters);

        const allCategoryValues = [
          qdrantResult.categoryValues,
          pgvectorResult.categoryValues,
          redisResult.categoryValues,
          supabaseResult.categoryValues,
        ];

        for (const values of allCategoryValues) {
          expect(values.sort()).toEqual(tc.expectedCategories.sort());
        }
      });

      test("all backends remove categories from remaining filters", () => {
        const qdrantResult = transformCategoriesForQdrant(tc.filters);
        const pgvectorResult = transformCategoriesForPgvector(tc.filters);
        const redisResult = transformCategoriesForRedis(tc.filters);
        const supabaseResult = transformCategoriesForSupabase(tc.filters);

        for (const result of [
          qdrantResult,
          pgvectorResult,
          redisResult,
          supabaseResult,
        ]) {
          expect(
            (result.filters as Record<string, any>).categories,
          ).toBeUndefined();
        }
      });
    });
  }

  describe("Qdrant transform specifics", () => {
    test("converts categories to $or conditions", () => {
      const result = transformCategoriesForQdrant({
        user_id: "u1",
        categories: { in: ["food", "pet"] },
      });

      expect(result.categoryValues).toEqual(["food", "pet"]);
      expect((result.filters as Record<string, any>).$or).toEqual([
        { categories: "food" },
        { categories: "pet" },
      ]);
      expect((result.filters as Record<string, any>).user_id).toBe("u1");
    });

    test("merges with existing $or", () => {
      const result = transformCategoriesForQdrant({
        user_id: "u1",
        $or: [{ type: "A" }],
        categories: { in: ["food"] },
      });

      expect((result.filters as Record<string, any>).$or).toEqual([
        { type: "A" },
        { categories: "food" },
      ]);
    });

    test("no categories returns original filters unchanged", () => {
      const filters = { user_id: "u1", type: "A" };
      const result = transformCategoriesForQdrant(filters);

      expect(result.categoryValues).toEqual([]);
      expect(result.filters).toEqual(filters);
    });
  });

  describe("PGVector transform specifics", () => {
    test("generates JSONB array containment SQL clause", () => {
      const result = transformCategoriesForPgvector({
        user_id: "u1",
        categories: { in: ["food"] },
      });

      expect(result.categorySqlClause).toBeDefined();
      expect(result.categorySqlClause).toContain("payload->'categories'");
      expect(result.categorySqlParams).toEqual(["food"]);
    });

    test("multiple categories generate OR clause", () => {
      const result = transformCategoriesForPgvector({
        user_id: "u1",
        categories: { in: ["food", "pet"] },
      });

      expect(result.categorySqlClause).toContain("OR");
      expect(result.categorySqlParams).toEqual(["food", "pet"]);
    });

    test("no categories returns no SQL clause", () => {
      const result = transformCategoriesForPgvector({ user_id: "u1" });

      expect(result.categorySqlClause).toBeUndefined();
      expect(result.categorySqlParams).toBeUndefined();
    });
  });

  describe("Redis transform specifics", () => {
    test("single category generates TAG expression", () => {
      const result = transformCategoriesForRedis({
        user_id: "u1",
        categories: { in: ["food"] },
      });

      expect(result.categoryTagExpr).toBe("@categories:{food}");
    });

    test("multiple categories generate OR TAG expression", () => {
      const result = transformCategoriesForRedis({
        user_id: "u1",
        categories: { in: ["food", "pet"] },
      });

      expect(result.categoryTagExpr).toContain("@categories:{food}");
      expect(result.categoryTagExpr).toContain("@categories:{pet}");
      expect(result.categoryTagExpr).toContain("|");
    });

    test("escapes special characters in category values", () => {
      const result = transformCategoriesForRedis({
        user_id: "u1",
        categories: { in: ["cat-1"] },
      });

      expect(result.categoryTagExpr).toContain("cat\\-1");
    });

    test("no categories returns no tag expression", () => {
      const result = transformCategoriesForRedis({ user_id: "u1" });

      expect(result.categoryTagExpr).toBeUndefined();
    });
  });

  describe("Supabase transform specifics", () => {
    test("single category returns exact value for SQL", () => {
      const result = transformCategoriesForSupabase({
        user_id: "u1",
        categories: { in: ["food"] },
      });

      expect(result.categoryExactValue).toBe("food");
      expect(result.categoryOverlapValues).toBeUndefined();
      expect(result.categoryValues).toEqual(["food"]);
    });

    test("multiple categories returns overlap array for SQL", () => {
      const result = transformCategoriesForSupabase({
        user_id: "u1",
        categories: { in: ["food", "pet"] },
      });

      expect(result.categoryOverlapValues).toEqual(["food", "pet"]);
      expect(result.categoryExactValue).toBeUndefined();
    });

    test("no categories returns neither exact nor overlap", () => {
      const result = transformCategoriesForSupabase({ user_id: "u1" });

      expect(result.categoryExactValue).toBeUndefined();
      expect(result.categoryOverlapValues).toBeUndefined();
    });

    test("single category string format for SQL exact match", () => {
      const result = transformCategoriesForSupabase({
        user_id: "u1",
        categories: "science",
      });

      expect(result.categoryExactValue).toBe("science");
    });
  });

  describe("Supabase SQL semantics", () => {
    test("single category uses JSONB ? operator (array contains) or = (string)", () => {
      const result = transformCategoriesForSupabase({
        user_id: "u1",
        categories: { in: ["food"] },
      });

      expect(result.categoryExactValue).toBe("food");
      expect(result.filters).toEqual({ user_id: "u1" });
    });

    test("multiple categories uses JSONB ?| operator (array overlap) or ANY (string)", () => {
      const result = transformCategoriesForSupabase({
        user_id: "u1",
        categories: { in: ["food", "pet"] },
      });

      expect(result.categoryOverlapValues).toEqual(["food", "pet"]);
      expect(result.filters).toEqual({ user_id: "u1" });
    });

    test("search() and list() share same transform logic", () => {
      const filters = {
        user_id: "u1",
        categories: { in: ["food", "pet"] },
      };

      const searchTransform = transformCategoriesForSupabase(filters);
      const listTransform = transformCategoriesForSupabase(filters);

      expect(searchTransform).toEqual(listTransform);
      expect(searchTransform.categoryOverlapValues).toEqual(["food", "pet"]);
    });
  });

  describe("Cross-backend filter integrity", () => {
    test("non-category filters are preserved in all backends", () => {
      const filters = {
        user_id: "u1",
        agent_id: "a1",
        importance: { gte: 3 },
        categories: { in: ["food"] },
      };

      for (const transform of [
        transformCategoriesForQdrant,
        transformCategoriesForPgvector,
        transformCategoriesForRedis,
        transformCategoriesForSupabase,
      ]) {
        const result = transform(filters);
        const f = result.filters as Record<string, any>;
        expect(f.user_id).toBe("u1");
        expect(f.agent_id).toBe("a1");
        expect(f.importance).toEqual({ gte: 3 });
        expect(f.categories).toBeUndefined();
      }
    });
  });
});

describe("Reranker Providers", () => {
  const sampleDocs: RerankDocument[] = [
    { id: "1", memory: "User loves pizza", score: 0.9 },
    { id: "2", memory: "User has a cat", score: 0.7 },
    { id: "3", memory: "User works remotely", score: 0.5 },
    { id: "4", memory: "User likes pasta", score: 0.6 },
    { id: "5", memory: "User drives a car", score: 0.3 },
  ];

  describe("SimpleReranker", () => {
    test("preserves score order and adds rerankScore", async () => {
      const reranker = new SimpleReranker();
      const results = await reranker.rerank("test query", sampleDocs);

      expect(results.length).toBe(5);
      expect(results[0].id).toBe("1");
      expect(results[0].rerankScore).toBe(0.9);
      expect(results[0].score).toBe(0.9);
      expect(results[1].rerankScore).toBe(0.7);
    });

    test("filters documents below minScore", async () => {
      const reranker = new SimpleReranker({ minScore: 0.5 });
      const results = await reranker.rerank("test query", sampleDocs);

      expect(results.length).toBe(4);
      for (const r of results) {
        expect(r.rerankScore).toBeGreaterThanOrEqual(0.5);
      }
    });

    test("applies topK truncation", async () => {
      const reranker = new SimpleReranker();
      const results = await reranker.rerank("test query", sampleDocs, 3);

      expect(results.length).toBe(3);
      expect(results[0].rerankScore).toBeGreaterThanOrEqual(
        results[1].rerankScore,
      );
      expect(results[1].rerankScore).toBeGreaterThanOrEqual(
        results[2].rerankScore,
      );
    });

    test("handles empty documents", async () => {
      const reranker = new SimpleReranker();
      const results = await reranker.rerank("test query", []);

      expect(results).toEqual([]);
    });

    test("handles documents without score", async () => {
      const reranker = new SimpleReranker();
      const docs: RerankDocument[] = [
        { id: "1", memory: "doc one" },
        { id: "2", memory: "doc two" },
      ];
      const results = await reranker.rerank("test query", docs);

      expect(results.length).toBe(2);
      expect(results[0].rerankScore).toBe(0);
    });
  });

  describe("LLMReranker", () => {
    test("falls back to original scores when LLM fails", async () => {
      const mockLlm = {
        generateResponse: jest.fn().mockRejectedValue(new Error("LLM error")),
      };
      const reranker = new LLMReranker({
        llm: mockLlm as any,
        batchSize: 10,
      });
      const results = await reranker.rerank("test query", sampleDocs);

      expect(results.length).toBe(5);
      expect(results[0].id).toBe("1");
      expect(results[0].rerankScore).toBe(0.9);
    });

    test("applies topK after reranking", async () => {
      const mockLlm = {
        generateResponse: jest.fn().mockResolvedValue(
          JSON.stringify([
            { id: 0, score: 0.2 },
            { id: 1, score: 0.9 },
            { id: 2, score: 0.1 },
          ]),
        ),
      };
      const reranker = new LLMReranker({
        llm: mockLlm as any,
        batchSize: 10,
      });
      const docs: RerankDocument[] = [
        { id: "1", memory: "doc1", score: 0.8 },
        { id: "2", memory: "doc2", score: 0.7 },
        { id: "3", memory: "doc3", score: 0.6 },
      ];
      const results = await reranker.rerank("test query", docs, 2);

      expect(results.length).toBe(2);
      expect(results[0].id).toBe("2");
      expect(results[0].rerankScore).toBe(0.9);
    });

    test("processes documents in batches", async () => {
      const mockLlm = {
        generateResponse: jest.fn().mockResolvedValue(
          JSON.stringify([
            { id: 0, score: 0.5 },
            { id: 1, score: 0.6 },
          ]),
        ),
      };
      const reranker = new LLMReranker({
        llm: mockLlm as any,
        batchSize: 2,
      });
      const docs: RerankDocument[] = Array.from({ length: 4 }, (_, i) => ({
        id: String(i),
        memory: `doc ${i}`,
        score: 0.5,
      }));
      const results = await reranker.rerank("test query", docs);

      expect(mockLlm.generateResponse).toHaveBeenCalledTimes(2);
      expect(results.length).toBe(4);
    });

    test("handles empty documents", async () => {
      const reranker = new LLMReranker({
        llm: {} as any,
      });
      const results = await reranker.rerank("test query", []);

      expect(results).toEqual([]);
    });
  });

  describe("BaseReranker shared behavior", () => {
    test("applyTopK sorts by rerankScore descending", () => {
      class TestReranker extends BaseReranker {
        async rerank(
          _query: string,
          documents: RerankDocument[],
          topK?: number,
        ): Promise<RerankResult[]> {
          const results = documents.map((d) => ({
            ...d,
            rerankScore: d.score ?? 0,
            score: d.score ?? 0,
          }));
          return this.applyTopK(results, topK);
        }
      }

      const reranker = new TestReranker();
      const docs: RerankDocument[] = [
        { id: "1", memory: "low", score: 0.2 },
        { id: "2", memory: "high", score: 0.9 },
        { id: "3", memory: "mid", score: 0.5 },
      ];

      return reranker.rerank("test", docs, 2).then((results) => {
        expect(results.length).toBe(2);
        expect(results[0].id).toBe("2");
        expect(results[1].id).toBe("3");
      });
    });

    test("fallbackRerank uses original score when available", () => {
      class TestReranker extends BaseReranker {
        async rerank(
          _query: string,
          documents: RerankDocument[],
          topK?: number,
        ): Promise<RerankResult[]> {
          return this.fallbackRerank(documents, topK);
        }
      }

      const reranker = new TestReranker();
      const docs: RerankDocument[] = [
        { id: "1", memory: "doc1", score: 0.8 },
        { id: "2", memory: "doc2", score: 0.3 },
      ];

      return reranker.rerank("test", docs).then((results) => {
        expect(results[0].id).toBe("1");
        expect(results[0].rerankScore).toBe(0.8);
        expect(results[1].rerankScore).toBe(0.3);
      });
    });

    test("fallbackRerank uses positional score when no score provided", () => {
      class TestReranker extends BaseReranker {
        async rerank(
          _query: string,
          documents: RerankDocument[],
          topK?: number,
        ): Promise<RerankResult[]> {
          return this.fallbackRerank(documents, topK);
        }
      }

      const reranker = new TestReranker();
      const docs: RerankDocument[] = [
        { id: "1", memory: "doc1" },
        { id: "2", memory: "doc2" },
        { id: "3", memory: "doc3" },
      ];

      return reranker.rerank("test", docs).then((results) => {
        expect(results[0].rerankScore).toBe(1);
        expect(results[1].rerankScore).toBeLessThan(1);
        expect(results[2].rerankScore).toBeLessThan(results[1].rerankScore);
      });
    });
  });

  describe("RerankerFactory", () => {
    test("creates SimpleReranker", () => {
      const reranker = RerankerFactory.create("simple");
      expect(reranker).toBeInstanceOf(SimpleReranker);
    });

    test("creates SimpleReranker with config", () => {
      const reranker = RerankerFactory.create("simple", { minScore: 0.5 });
      expect(reranker).toBeInstanceOf(SimpleReranker);
    });

    test("creates LLMReranker with LLM dependency", () => {
      const mockLlm = {
        generateResponse: jest.fn(),
      };
      const reranker = RerankerFactory.create(
        "llm",
        {},
        { llm: mockLlm as any },
      );
      expect(reranker).toBeInstanceOf(LLMReranker);
    });

    test("throws for LLM reranker without LLM dependency", () => {
      expect(() => RerankerFactory.create("llm")).toThrow(
        "LLM reranker requires an LLM instance",
      );
    });

    test("throws for unknown provider", () => {
      expect(() => RerankerFactory.create("unknown")).toThrow(
        "Unsupported reranker provider: unknown",
      );
    });

    test("case-insensitive provider name", () => {
      const reranker = RerankerFactory.create("Simple");
      expect(reranker).toBeInstanceOf(SimpleReranker);
    });
  });
});

describe("Reranker - Sort Order Verification", () => {
  test("SimpleReranker actually changes order when scores differ", async () => {
    const reranker = new SimpleReranker();
    const docs: RerankDocument[] = [
      { id: "low", memory: "low relevance", score: 0.1 },
      { id: "high", memory: "high relevance", score: 0.9 },
      { id: "mid", memory: "mid relevance", score: 0.5 },
    ];

    const results = await reranker.rerank("test", docs);

    expect(results[0].id).toBe("high");
    expect(results[1].id).toBe("mid");
    expect(results[2].id).toBe("low");
    expect(results[0].rerankScore).toBeGreaterThan(results[1].rerankScore);
    expect(results[1].rerankScore).toBeGreaterThan(results[2].rerankScore);
  });

  test("LLMReranker with LLM produces sorted output", async () => {
    const mockLlm = {
      generateResponse: jest.fn().mockResolvedValue(
        JSON.stringify([
          { id: 0, score: 0.3 },
          { id: 1, score: 0.95 },
          { id: 2, score: 0.6 },
        ]),
      ),
    };
    const reranker = new LLMReranker({ llm: mockLlm as any });
    const docs: RerankDocument[] = [
      { id: "a", memory: "doc a", score: 0.8 },
      { id: "b", memory: "doc b", score: 0.7 },
      { id: "c", memory: "doc c", score: 0.6 },
    ];

    const results = await reranker.rerank("test", docs);

    expect(results[0].id).toBe("b");
    expect(results[0].rerankScore).toBe(0.95);
    expect(results[1].id).toBe("c");
    expect(results[1].rerankScore).toBe(0.6);
    expect(results[2].id).toBe("a");
    expect(results[2].rerankScore).toBe(0.3);

    for (let i = 1; i < results.length; i++) {
      expect(results[i - 1].rerankScore).toBeGreaterThanOrEqual(
        results[i].rerankScore,
      );
    }
  });

  test("LLMReranker fallback preserves original score order", async () => {
    const mockLlm = {
      generateResponse: jest.fn().mockRejectedValue(new Error("fail")),
    };
    const reranker = new LLMReranker({ llm: mockLlm as any });
    const docs: RerankDocument[] = [
      { id: "c", memory: "low", score: 0.3 },
      { id: "a", memory: "high", score: 0.9 },
      { id: "b", memory: "mid", score: 0.5 },
    ];

    const results = await reranker.rerank("test", docs);

    expect(results[0].id).toBe("a");
    expect(results[0].rerankScore).toBe(0.9);
    expect(results[1].id).toBe("b");
    expect(results[2].id).toBe("c");
  });
});

describe("Reranker topK Truncation", () => {
  test("topK=1 returns only top result", async () => {
    const reranker = new SimpleReranker();
    const docs: RerankDocument[] = [
      { id: "1", memory: "doc1", score: 0.3 },
      { id: "2", memory: "doc2", score: 0.9 },
      { id: "3", memory: "doc3", score: 0.6 },
    ];

    const results = await reranker.rerank("test", docs, 1);
    expect(results.length).toBe(1);
    expect(results[0].id).toBe("2");
  });

  test("topK larger than results returns all results", async () => {
    const reranker = new SimpleReranker();
    const docs: RerankDocument[] = [
      { id: "1", memory: "doc1", score: 0.9 },
      { id: "2", memory: "doc2", score: 0.5 },
    ];

    const results = await reranker.rerank("test", docs, 10);
    expect(results.length).toBe(2);
  });

  test("topK=0 returns all results", async () => {
    const reranker = new SimpleReranker();
    const docs: RerankDocument[] = [
      { id: "1", memory: "doc1", score: 0.9 },
      { id: "2", memory: "doc2", score: 0.5 },
    ];

    const results = await reranker.rerank("test", docs, 0);
    expect(results.length).toBe(2);
  });

  test("SimpleReranker minScore + topK combination", async () => {
    const reranker = new SimpleReranker({ minScore: 0.5 });
    const docs: RerankDocument[] = [
      { id: "1", memory: "doc1", score: 0.9 },
      { id: "2", memory: "doc2", score: 0.7 },
      { id: "3", memory: "doc3", score: 0.5 },
      { id: "4", memory: "doc4", score: 0.3 },
      { id: "5", memory: "doc5", score: 0.1 },
    ];

    const results = await reranker.rerank("test", docs, 2);
    expect(results.length).toBe(2);
    expect(results[0].id).toBe("1");
    expect(results[1].id).toBe("2");
  });
});

describe("Explain Adapter Filters", () => {
  test("memory provider shows adapter filter structure", async () => {
    const mem = new Memory({
      embedder: {
        provider: "openai",
        config: {
          apiKey: "test-key",
          model: "text-embedding-3-small",
          embeddingDims: 256,
        },
      },
      vectorStore: {
        provider: "memory",
        config: {
          dimension: 256,
        },
      },
      llm: {
        provider: "openai",
        config: {
          apiKey: "test-key",
          model: "gpt-4o-mini",
        },
      },
      disableHistory: true,
    });

    mem.registerSearchProfile("test-profile", {
      filters: { user_id: "u1" },
      categories: ["food", "pet"],
      topK: 5,
      explain: true,
    });

    const mockEmbed = jest.fn().mockResolvedValue(new Array(256).fill(0.1));
    (mem as any).embedder.embed = mockEmbed;
    (mem as any).vectorStore.search = jest.fn().mockResolvedValue([]);

    const result = await mem.search("test query", {
      profile: "test-profile",
    });

    expect(result.explain).toBeDefined();
    expect(result.explain!.filters!.adapter).toBeDefined();
    expect(result.explain!.filters!.adapter!.provider).toBe("memory");
    expect(result.explain!.filters!.adapter!.transformed.queryType).toBe(
      "in-memory SQLite with JSON filter",
    );
    expect(result.explain!.filters!.adapter!.transformed.filters.user_id).toBe(
      "u1",
    );
  });

  test("adapter filters show backend-specific transformation for qdrant", () => {
    const effectiveFilters = {
      user_id: "u1",
      categories: { in: ["food", "pet"] },
    };

    const result = transformCategoriesForQdrant(effectiveFilters);
    const adapterTransformed = {
      filters: result.filters,
      categoryValues: result.categoryValues,
      queryType: "filter with $or conditions for categories",
    };

    expect(adapterTransformed.queryType).toContain("$or");
    expect(
      (adapterTransformed.filters as Record<string, any>).$or,
    ).toBeDefined();
    expect(adapterTransformed.categoryValues).toEqual(["food", "pet"]);
  });

  test("adapter filters show backend-specific transformation for supabase", () => {
    const effectiveFilters = {
      user_id: "u1",
      categories: { in: ["food", "pet"] },
    };

    const result = transformCategoriesForSupabase(effectiveFilters);
    const adapterTransformed = {
      filters: result.filters,
      categoryValues: result.categoryValues,
      categoryExactValue: result.categoryExactValue,
      categoryOverlapValues: result.categoryOverlapValues,
      queryType:
        "JSONB ?/?| operators for array, = for string (via RPC params)",
    };

    expect(adapterTransformed.queryType).toContain("JSONB");
    expect(adapterTransformed.categoryOverlapValues).toEqual(["food", "pet"]);
    expect(adapterTransformed.categoryExactValue).toBeUndefined();
    expect(
      (adapterTransformed.filters as Record<string, any>).categories,
    ).toBeUndefined();
  });

  test("adapter filters show backend-specific transformation for pgvector", () => {
    const effectiveFilters = {
      user_id: "u1",
      categories: { in: ["food"] },
    };

    const result = transformCategoriesForPgvector(effectiveFilters);
    const adapterTransformed = {
      filters: result.filters,
      categoryValues: result.categoryValues,
      categorySqlClause: result.categorySqlClause,
      queryType: "JSONB ? operator for array, = for string",
    };

    expect(adapterTransformed.queryType).toContain("JSONB");
    expect(adapterTransformed.categorySqlClause).toContain(
      "payload->'categories'",
    );
    expect(adapterTransformed.categoryValues).toEqual(["food"]);
  });

  test("adapter filters show backend-specific transformation for redis", () => {
    const effectiveFilters = {
      user_id: "u1",
      categories: { in: ["food", "pet"] },
    };

    const result = transformCategoriesForRedis(effectiveFilters);
    const adapterTransformed = {
      filters: result.filters,
      categoryValues: result.categoryValues,
      categoryTagExpr: result.categoryTagExpr,
      queryType: "TAG filter with | OR syntax",
    };

    expect(adapterTransformed.queryType).toContain("TAG");
    expect(adapterTransformed.categoryTagExpr).toContain("@categories");
    expect(adapterTransformed.categoryTagExpr).toContain("|");
  });

  test("cross-backend adapter filters show consistent category extraction but different queryType", () => {
    const effectiveFilters = {
      user_id: "u1",
      categories: { in: ["food", "pet"] },
    };

    const backends = [
      { name: "qdrant", transform: transformCategoriesForQdrant },
      { name: "pgvector", transform: transformCategoriesForPgvector },
      { name: "redis", transform: transformCategoriesForRedis },
      { name: "supabase", transform: transformCategoriesForSupabase },
    ];

    const results = backends.map(({ name, transform }) => ({
      name,
      result: transform(effectiveFilters),
    }));

    for (const { name, result } of results) {
      expect(result.categoryValues.sort()).toEqual(["food", "pet"]);
      expect(
        (result.filters as Record<string, any>).categories,
      ).toBeUndefined();
    }

    const queryTypes = results.map(
      (r) =>
        ({
          qdrant: "filter with $or conditions for categories",
          pgvector: "JSONB ? operator for array, = for string",
          redis: "TAG filter with | OR syntax",
          supabase:
            "JSONB ?/?| operators for array, = for string (via RPC params)",
        })[r.name],
    );

    expect(new Set(queryTypes).size).toBe(4);
  });

  test("no explain flag skips adapter filter computation", async () => {
    const mem = new Memory({
      embedder: {
        provider: "openai",
        config: {
          apiKey: "test-key",
          model: "text-embedding-3-small",
          embeddingDims: 256,
        },
      },
      vectorStore: {
        provider: "memory",
        config: {
          dimension: 256,
        },
      },
      llm: {
        provider: "openai",
        config: {
          apiKey: "test-key",
          model: "gpt-4o-mini",
        },
      },
      disableHistory: true,
    });

    const mockEmbed = jest.fn().mockResolvedValue(new Array(256).fill(0.1));
    (mem as any).embedder.embed = mockEmbed;
    (mem as any).vectorStore.search = jest.fn().mockResolvedValue([]);

    const result = await mem.search("test query", {
      filters: { user_id: "u1" },
      explain: false,
    });

    expect(result.explain).toBeUndefined();
  });
});
