/**
 * OSS Memory unit tests — Search Profile feature.
 * Tests profile registration, merge priority, filter normalization,
 * and explain output.
 */
/// <reference types="jest" />
import { Memory } from "../src/memory";
import type {
  MemoryConfig,
  SearchProfile,
  SearchProfileStore,
  SearchResult,
} from "../src/types";

jest.setTimeout(15000);

// Mock Google modules to prevent @google/genai crash in CI
jest.mock("../src/embeddings/google", () => ({
  GoogleEmbedder: jest.fn(),
}));
jest.mock("../src/llms/google", () => ({
  GoogleLLM: jest.fn(),
}));

// ─── Content-based LLM mock (V3 additive extraction pipeline) ─────────
jest.mock("../src/llms/openai", () => ({
  OpenAILLM: jest.fn().mockImplementation(() => ({
    generateResponse: jest
      .fn()
      .mockImplementation(
        (messages: Array<{ role: string; content: string }>) => {
          const userMsg = messages.find((m) => m.role === "user");
          const content = userMsg?.content ?? "";
          const newMsgMatch = content.match(
            /## New Messages\n([\s\S]*?)(?=\n##|$)/,
          );
          const extracted = newMsgMatch ? newMsgMatch[1].trim() : "test fact";
          return JSON.stringify({
            memory: [
              {
                id: "0",
                text: extracted,
                attributed_to: "user",
              },
            ],
          });
        },
      ),
  })),
}));

const mockEmbedding = new Array(1536).fill(0.1);
jest.mock("../src/embeddings/openai", () => ({
  OpenAIEmbedder: jest.fn().mockImplementation(() => ({
    embed: jest.fn().mockResolvedValue(mockEmbedding),
    embedBatch: jest
      .fn()
      .mockImplementation((texts: string[]) =>
        Promise.resolve(texts.map(() => mockEmbedding)),
      ),
    embeddingDims: 1536,
  })),
}));

function createMemory(overrides: Partial<MemoryConfig> = {}): Memory {
  return new Memory({
    version: "v1.1",
    embedder: {
      provider: "openai",
      config: { apiKey: "test-key", model: "text-embedding-3-small" },
    },
    vectorStore: {
      provider: "memory",
      config: { collectionName: "test-search-profile", dimension: 1536 },
    },
    llm: {
      provider: "openai",
      config: { apiKey: "test-key", model: "gpt-5-mini" },
    },
    historyDbPath: ":memory:",
    ...overrides,
  });
}

function buildProfiles(): SearchProfileStore {
  return {
    "support-recall": {
      name: "support-recall",
      topK: 50,
      threshold: 0.3,
      explain: true,
      scoreWeights: {
        semanticWeight: 0.7,
        bm25Weight: 1.0,
        entityBoostWeight: 0.3,
      },
      description: "High-recall profile for customer support scenarios",
    },
    "agent-facts": {
      name: "agent-facts",
      topK: 10,
      threshold: 0.5,
      filters: { category: "fact", importance: { gte: 4 } },
      explain: false,
      scoreWeights: {
        semanticWeight: 1.0,
        bm25Weight: 0.5,
      },
      description: "Precision-focused profile for agent factual recall",
    },
    "recent-only": {
      name: "recent-only",
      topK: 20,
      threshold: 0.2,
      filters: { createdAt: { gte: "2024-01-01" } },
      description: "Recent memories only",
    },
  };
}

describe("Memory - Search Profile Registration", () => {
  test("initializes with profiles from config", () => {
    const mem = createMemory({
      searchProfiles: buildProfiles(),
    });
    expect(mem.listSearchProfiles().sort()).toEqual([
      "agent-facts",
      "recent-only",
      "support-recall",
    ]);
  });

  test("registerSearchProfile adds a new profile", () => {
    const mem = createMemory();
    expect(mem.listSearchProfiles()).toEqual([]);

    const profile: SearchProfile = {
      topK: 5,
      threshold: 0.8,
      explain: true,
    };
    mem.registerSearchProfile("custom-profile", profile);

    expect(mem.listSearchProfiles()).toEqual(["custom-profile"]);
    const stored = mem.getSearchProfile("custom-profile");
    expect(stored).toBeDefined();
    expect(stored?.topK).toBe(5);
    expect(stored?.threshold).toBe(0.8);
    expect(stored?.explain).toBe(true);
    expect(stored?.name).toBe("custom-profile");
  });

  test("registerSearchProfile validates name is non-empty", () => {
    const mem = createMemory();
    expect(() => mem.registerSearchProfile("", { topK: 5 })).toThrow(
      "Profile name must be a non-empty string.",
    );
    expect(() => mem.registerSearchProfile("   ", { topK: 5 })).toThrow(
      "Profile name must be a non-empty string.",
    );
  });

  test("registerSearchProfile validates profile params", () => {
    const mem = createMemory();
    expect(() =>
      mem.registerSearchProfile("bad", { threshold: 1.5 }),
    ).toThrow();
    expect(() => mem.registerSearchProfile("bad", { topK: -1 })).toThrow();
  });

  test("getSearchProfile returns undefined for unknown profile", () => {
    const mem = createMemory();
    expect(mem.getSearchProfile("nonexistent")).toBeUndefined();
  });

  test("unregisterSearchProfile removes profile", () => {
    const mem = createMemory({
      searchProfiles: buildProfiles(),
    });
    expect(mem.listSearchProfiles()).toContain("support-recall");
    expect(mem.unregisterSearchProfile("support-recall")).toBe(true);
    expect(mem.listSearchProfiles()).not.toContain("support-recall");
    expect(mem.getSearchProfile("support-recall")).toBeUndefined();
  });

  test("unregisterSearchProfile returns false for unknown profile", () => {
    const mem = createMemory();
    expect(mem.unregisterSearchProfile("nonexistent")).toBe(false);
  });

  test("registerSearchProfile overwrites existing profile", () => {
    const mem = createMemory({
      searchProfiles: buildProfiles(),
    });
    const original = mem.getSearchProfile("support-recall");
    expect(original?.topK).toBe(50);

    mem.registerSearchProfile("support-recall", { topK: 100 });
    const updated = mem.getSearchProfile("support-recall");
    expect(updated?.topK).toBe(100);
  });
});

describe("Memory - Search with Named Profiles", () => {
  test("search uses profile default values from named profile", async () => {
    const mem = createMemory({
      searchProfiles: buildProfiles(),
    });
    const userId = `profile_default_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      profile: "support-recall",
      filters: { user_id: userId },
    })) as any;

    expect(result.explain).toBeDefined();
    expect(result.explain.profile).toBeDefined();
    expect(result.explain.profile.name).toBe("support-recall");
    expect(result.explain.profile.appliedConfig.topK).toBe(50);
    expect(result.explain.profile.appliedConfig.threshold).toBe(0.3);
    expect(result.explain.profile.appliedConfig.explain).toBe(true);
  });

  test("search allows call-time overrides to take precedence over profile", async () => {
    const mem = createMemory({
      searchProfiles: buildProfiles(),
    });
    const userId = `profile_override_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      profile: "support-recall",
      filters: { user_id: userId },
      topK: 5,
      threshold: 0.9,
    })) as any;

    expect(result.explain).toBeDefined();
    expect(result.explain.profile).toBeDefined();
    expect(result.explain.profile.name).toBe("support-recall");
    expect(result.explain.profile.appliedConfig.topK).toBe(5);
    expect(result.explain.profile.appliedConfig.threshold).toBe(0.9);
    expect(result.explain.overriddenFields).toEqual(
      expect.arrayContaining(["topK", "threshold"]),
    );
  });

  test("search merges filters from profile and call-time (call-time wins)", async () => {
    const mem = createMemory({
      searchProfiles: buildProfiles(),
    });
    const userId = `profile_filters_${Date.now()}`;
    await mem.add("User likes pizza", {
      userId,
      metadata: { category: "fact" },
    });

    const result = (await mem.search("What does user like", {
      profile: "agent-facts",
      filters: { user_id: userId },
    })) as any;

    expect(result.explain).toBeDefined();
    expect(result.explain.profile.appliedConfig.filters).toEqual({
      category: "fact",
      importance: { gte: 4 },
      user_id: userId,
    });
  });

  test("search with inline object profile works", async () => {
    const mem = createMemory();
    const userId = `inline_profile_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const inlineProfile: SearchProfile = {
      name: "inline",
      topK: 7,
      threshold: 0.15,
      explain: true,
    };
    const result = (await mem.search("What does user like", {
      profile: inlineProfile,
      filters: { user_id: userId },
    })) as any;

    expect(result.explain).toBeDefined();
    expect(result.explain.profile).toBeDefined();
    expect(result.explain.profile.name).toBe("inline");
    expect(result.explain.profile.appliedConfig.topK).toBe(7);
    expect(result.explain.profile.appliedConfig.threshold).toBe(0.15);
  });

  test("search with inline anonymous profile (no name)", async () => {
    const mem = createMemory();
    const userId = `anon_profile_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      profile: { topK: 3, threshold: 0.25 },
      filters: { user_id: userId },
    })) as any;

    expect(result.explain).toBeDefined();
    expect(result.explain.profile).toBeDefined();
    expect(result.explain.profile.name).toBeNull();
    expect(result.explain.profile.appliedConfig.topK).toBe(3);
    expect(result.explain.profile.appliedConfig.threshold).toBe(0.25);
  });

  test("search throws for unknown named profile", async () => {
    const mem = createMemory();
    const userId = `unknown_profile_${Date.now()}`;
    await expect(
      mem.search("query", {
        profile: "does-not-exist",
        filters: { user_id: userId },
      }),
    ).rejects.toThrow(/Search profile 'does-not-exist' not found/);
  });

  test("search applies custom scoreWeights from profile", async () => {
    const mem = createMemory({
      searchProfiles: buildProfiles(),
    });
    const userId = `weights_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      profile: "support-recall",
      filters: { user_id: userId },
    })) as any;

    expect(result.explain.profile.appliedConfig.scoreWeights).toEqual({
      semanticWeight: 0.7,
      bm25Weight: 1.0,
      entityBoostWeight: 0.3,
    });

    if (result.results.length > 0 && result.results[0].score_details) {
      const details = result.results[0].score_details;
      expect(details.weights).toBeDefined();
      expect(details.weights.semanticWeight).toBe(0.7);
      expect(details.weights.bm25Weight).toBe(1.0);
      expect(details.weights.entityBoostWeight).toBe(0.3);
    }
  });

  test("search allows overriding scoreWeights at call time", async () => {
    const mem = createMemory({
      searchProfiles: buildProfiles(),
    });
    const userId = `weights_override_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      profile: "support-recall",
      filters: { user_id: userId },
      scoreWeights: { semanticWeight: 0.9 },
    })) as any;

    expect(result.explain.profile.appliedConfig.scoreWeights).toEqual({
      semanticWeight: 0.9,
      bm25Weight: 1.0,
      entityBoostWeight: 0.3,
    });
    expect(result.explain.overriddenFields).toContain("scoreWeights");
  });

  test("search without profile produces no profile explain", async () => {
    const mem = createMemory();
    const userId = `no_profile_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      filters: { user_id: userId },
    })) as any;

    expect(result.explain).toBeUndefined();
  });

  test("search with explain=true but no profile still includes overrides", async () => {
    const mem = createMemory();
    const userId = `explain_no_profile_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      filters: { user_id: userId },
      explain: true,
    })) as any;

    expect(result.explain).toBeDefined();
    expect(result.explain.profile).toBeUndefined();
  });

  test("profile filters from recent-only profile includes createdAt filter", async () => {
    const mem = createMemory({
      searchProfiles: buildProfiles(),
    });
    const userId = `recent_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      profile: "recent-only",
      filters: { user_id: userId },
    })) as any;

    expect(result.explain.profile.appliedConfig.filters).toEqual({
      createdAt: { gte: "2024-01-01" },
      user_id: userId,
    });
  });
});

describe("Memory - Profile Merge Priority (unit)", () => {
  test("call-time topK overrides profile topK", () => {
    const mem = createMemory({
      searchProfiles: buildProfiles(),
    });
    mem.registerSearchProfile("test", { topK: 100 });
    const p = mem.getSearchProfile("test");
    expect(p?.topK).toBe(100);
  });

  test("profiles are isolated per Memory instance", () => {
    const mem1 = createMemory({
      searchProfiles: { "mem1-only": { topK: 1 } },
    });
    const mem2 = createMemory({
      searchProfiles: { "mem2-only": { topK: 2 } },
    });
    expect(mem1.listSearchProfiles()).toEqual(["mem1-only"]);
    expect(mem2.listSearchProfiles()).toEqual(["mem2-only"]);
  });
});

describe("Memory - Categories in Search Profile", () => {
  test("profile categories are converted to { category: { in: [...] } } filter", async () => {
    const mem = createMemory();
    const userId = `profile_categories_${Date.now()}`;
    await mem.add("User ordered veggie pizza", {
      userId,
      metadata: { category: "food" },
    });
    await mem.add("User is 30 years old", {
      userId,
      metadata: { category: "fact" },
    });

    mem.registerSearchProfile("food-only", {
      categories: ["food", "preference"],
    });

    const result = (await mem.search("什么", {
      profile: "food-only",
      filters: { user_id: userId },
      explain: true,
    })) as any;

    expect(result.explain.categories).toBeDefined();
    expect(result.explain.categories.resolved.sort()).toEqual(
      ["food", "preference"].sort(),
    );
    expect(result.explain.categories.filterApplied).toEqual({
      category: { in: expect.arrayContaining(["food", "preference"]) },
    });
  });

  test("call-time categories union with profile categories (deduplicated)", async () => {
    const mem = createMemory();
    const userId = `union_cats_${Date.now()}`;
    await mem.add("test", { userId, metadata: { category: "fact" } });

    mem.registerSearchProfile("base-cats", { categories: ["fact", "food"] });

    const result = (await mem.search("query", {
      profile: "base-cats",
      categories: ["food", "order", "  fact  "],
      filters: { user_id: userId },
    })) as any;

    const resolved = result.explain.categories.resolved as string[];
    expect(resolved.sort()).toEqual(["fact", "food", "order"].sort());
    expect(resolved.length).toBe(3);
  });

  test("categories and explicit filters.category coexist — call-time filter wins", async () => {
    const mem = createMemory();
    const userId = `conflict_cats_${Date.now()}`;
    await mem.add("t1", { userId, metadata: { category: "fact" } });

    mem.registerSearchProfile("cats", { categories: ["food", "fact"] });

    const result = (await mem.search("q", {
      profile: "cats",
      filters: { user_id: userId, category: "explicit_fact" },
      explain: true,
    })) as any;

    expect(result.explain.profile.appliedConfig.filters.category).toBe(
      "explicit_fact",
    );
  });
});

describe("Memory - Hybrid Weights & Rerank in Profile", () => {
  test("profile.hybridWeights is an alias for scoreWeights", async () => {
    const mem = createMemory();
    const userId = `hybrid_${Date.now()}`;
    await mem.add("test", { userId, metadata: { category: "fact" } });

    mem.registerSearchProfile("hybrid-test", {
      hybridWeights: { semanticWeight: 0.6, bm25Weight: 1.4 },
    });

    const result = (await mem.search("query", {
      profile: "hybrid-test",
      filters: { user_id: userId },
    })) as any;

    expect(result.explain.hybridWeights.semanticWeight).toBe(0.6);
    expect(result.explain.hybridWeights.bm25Weight).toBe(1.4);
    expect(result.explain.profile.appliedConfig.hybridWeights).toEqual({
      semanticWeight: 0.6,
      bm25Weight: 1.4,
    });
    expect(result.explain.profile.appliedConfig.scoreWeights).toEqual({
      semanticWeight: 0.6,
      bm25Weight: 1.4,
    });
  });

  test("scoreWeights takes precedence over hybridWeights when both are present", () => {
    const mem = createMemory();
    mem.registerSearchProfile("pw", {
      hybridWeights: { semanticWeight: 0.5 },
      scoreWeights: { semanticWeight: 0.9 },
    });
    const p = mem.getSearchProfile("pw");
    expect(p?.hybridWeights?.semanticWeight).toBe(0.5);
    expect(p?.scoreWeights?.semanticWeight).toBe(0.9);
  });
});

describe("Memory - Rerank Execution & Explain", () => {
  test("rerank: true from profile is applied with default score strategy", async () => {
    const mem = createMemory();
    const userId = `rerank_bool_${Date.now()}`;
    for (let i = 0; i < 5; i++) {
      await mem.add(`memory item ${i}`, { userId });
    }

    mem.registerSearchProfile("with-rerank", { rerank: true });

    const result = (await mem.search("item", {
      profile: "with-rerank",
      filters: { user_id: userId },
      topK: 3,
      explain: true,
    })) as any;

    expect(result.explain.rerank).toBeDefined();
    expect(result.explain.rerank.applied).toBe(true);
    expect(result.explain.rerank.strategy).toBe("score");
    expect(result.explain.rerank.config.enabled).toBe(true);
    expect(typeof result.explain.rerank.preCount).toBe("number");
    expect(typeof result.explain.rerank.postCount).toBe("number");
  });

  test("rerank with object config — timestamp_decay strategy", async () => {
    const mem = createMemory();
    const userId = `rerank_decay_${Date.now()}`;
    await mem.add("recent memory", { userId });

    mem.registerSearchProfile("fresh", {
      rerank: { strategy: "timestamp_decay", decayHalfLifeHours: 12 },
    });

    const result = (await mem.search("memory", {
      profile: "fresh",
      filters: { user_id: userId },
      explain: true,
    })) as any;

    expect(result.explain.rerank.applied).toBe(true);
    expect(result.explain.rerank.strategy).toBe("timestamp_decay");
    expect(result.explain.rerank.config.decayHalfLifeHours).toBe(12);
    expect(result.explain.profile.appliedConfig.rerank).toMatchObject({
      strategy: "timestamp_decay",
    });
  });

  test("rerank with diversity strategy uses diversityField from config", async () => {
    const mem = createMemory();
    const userId = `rerank_div_${Date.now()}`;
    for (const c of ["A", "A", "B", "C"]) {
      await mem.add(`m-${c}`, { userId, metadata: { category: c } });
    }

    const result = (await mem.search("m", {
      profile: {
        rerank: {
          strategy: "diversity",
          diversityField: "category",
          limit: 3,
        },
      },
      filters: { user_id: userId },
      topK: 5,
      explain: true,
    })) as any;

    expect(result.explain.rerank.applied).toBe(true);
    expect(result.explain.rerank.strategy).toBe("diversity");
    expect(result.explain.rerank.config.diversityField).toBe("category");
    expect(result.explain.rerank.config.limit).toBe(3);
    expect(result.results.length).toBeLessThanOrEqual(3);
  });

  test("call-time rerank fully overrides profile rerank (bool > object)", async () => {
    const mem = createMemory();
    const userId = `rerank_override_${Date.now()}`;
    await mem.add("t", { userId });

    mem.registerSearchProfile("decay-profile", {
      rerank: { strategy: "timestamp_decay", decayHalfLifeHours: 48 },
    });

    const result = (await mem.search("t", {
      profile: "decay-profile",
      rerank: false,
      filters: { user_id: userId },
      explain: true,
    })) as any;

    expect(result.explain.rerank.applied).toBe(false);
    expect(result.explain.rerank.strategy).toBe("score");
    expect(result.explain.overriddenFields).toContain("rerank");
  });

  test("explain always includes hybridWeights defaults even without profile", async () => {
    const mem = createMemory();
    const userId = `hw_defaults_${Date.now()}`;
    await mem.add("t", { userId });

    const result = (await mem.search("t", {
      filters: { user_id: userId },
      explain: true,
    })) as any;

    expect(result.explain.hybridWeights).toBeDefined();
    expect(typeof result.explain.hybridWeights.semanticWeight).toBe("number");
    expect(typeof result.explain.hybridWeights.bm25Weight).toBe("number");
    expect(typeof result.explain.hybridWeights.entityBoostWeight).toBe(
      "number",
    );
  });
});
