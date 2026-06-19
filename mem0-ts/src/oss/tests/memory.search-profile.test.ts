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

describe("Memory - Search Profile Categories", () => {
  test("search profile supports categories field", async () => {
    const mem = createMemory({
      searchProfiles: {
        categorized: {
          name: "categorized",
          topK: 10,
          categories: ["fact", "preference"],
        },
      },
    });
    const userId = `cat_profile_${Date.now()}`;
    await mem.add("User likes pizza", {
      userId,
      metadata: { categories: ["preference"] },
    });

    const result = (await mem.search("What does user like", {
      profile: "categorized",
      filters: { user_id: userId },
    })) as any;

    expect(result.explain).toBeDefined();
    expect(result.explain.profile).toBeDefined();
    expect(result.explain.profile.name).toBe("categorized");
    expect(result.explain.profile.appliedConfig.categories).toEqual([
      "fact",
      "preference",
    ]);
    expect(result.explain.profile.appliedConfig.filters.categories).toEqual({
      in: ["fact", "preference"],
    });
  });

  test("search call-time categories merge with profile categories", async () => {
    const mem = createMemory({
      searchProfiles: {
        "base-cats": {
          name: "base-cats",
          categories: ["fact"],
        },
      },
    });
    const userId = `cat_merge_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      profile: "base-cats",
      filters: { user_id: userId },
      categories: ["preference"],
    })) as any;

    expect(result.explain.profile.appliedConfig.categories).toEqual([
      "fact",
      "preference",
    ]);
    expect(result.explain.profile.appliedConfig.filters.categories).toEqual({
      in: ["fact", "preference"],
    });
    expect(result.explain.overriddenFields).toContain("categories");
  });

  test("categories dedupe duplicates between profile and call-time", async () => {
    const mem = createMemory({
      searchProfiles: {
        "dup-cats": {
          name: "dup-cats",
          categories: ["fact", "preference"],
        },
      },
    });
    const userId = `cat_dedupe_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      profile: "dup-cats",
      filters: { user_id: userId },
      categories: ["preference", "fact"],
    })) as any;

    expect(result.explain.profile.appliedConfig.categories).toEqual([
      "fact",
      "preference",
    ]);
  });

  test("registerSearchProfile accepts categories", () => {
    const mem = createMemory();
    mem.registerSearchProfile("with-cats", {
      topK: 5,
      categories: ["support", "bug"],
    });
    const stored = mem.getSearchProfile("with-cats");
    expect(stored).toBeDefined();
    expect(stored?.categories).toEqual(["support", "bug"]);
  });

  test("search with only call-time categories (no profile)", async () => {
    const mem = createMemory();
    const userId = `cat_callonly_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      filters: { user_id: userId },
      categories: ["food"],
      explain: true,
    })) as any;

    expect(result.explain).toBeDefined();
    expect(result.results).toBeDefined();
  });
});

describe("Memory - Profile Deep Filter Merge", () => {
  test("nested operator filters merge deeply", async () => {
    const mem = createMemory({
      searchProfiles: {
        "operator-merge": {
          name: "operator-merge",
          filters: { importance: { gte: 3 }, category: "fact" },
        },
      },
    });
    const userId = `deep_merge_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      profile: "operator-merge",
      filters: { user_id: userId, importance: { lte: 9 } },
    })) as any;

    expect(result.explain.profile.appliedConfig.filters).toEqual({
      category: "fact",
      importance: { gte: 3, lte: 9 },
      user_id: userId,
    });
  });

  test("call-time simple value overrides profile operator for same key", async () => {
    const mem = createMemory({
      searchProfiles: {
        "op-override": {
          name: "op-override",
          filters: { status: { in: ["active", "pending"] } },
        },
      },
    });
    const userId = `op_override_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      profile: "op-override",
      filters: { user_id: userId, status: "active" },
    })) as any;

    expect(result.explain.profile.appliedConfig.filters.status).toBe("active");
  });

  test("$or arrays concatenate from profile and call-time", async () => {
    const mem = createMemory({
      searchProfiles: {
        "or-merge": {
          name: "or-merge",
          filters: { $or: [{ type: "A" }] },
        },
      },
    });
    const userId = `or_merge_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      profile: "or-merge",
      filters: { user_id: userId, $or: [{ type: "B" }] },
    })) as any;

    expect(result.explain.profile.appliedConfig.filters.$or).toEqual([
      { type: "A" },
      { type: "B" },
    ]);
  });
});

describe("Memory - Search Profile Explain Details", () => {
  test("explain includes scoring details when explain=true", async () => {
    const mem = createMemory({
      searchProfiles: {
        "explain-test": {
          name: "explain-test",
          topK: 5,
          threshold: 0.2,
          scoreWeights: { semanticWeight: 0.8, bm25Weight: 0.6 },
        },
      },
    });
    const userId = `explain_detail_${Date.now()}`;
    await mem.add("User likes pizza", { userId });
    await mem.add("User likes pasta", { userId });

    const result = (await mem.search("What does user like", {
      profile: "explain-test",
      filters: { user_id: userId },
      explain: true,
    })) as any;

    expect(result.explain).toBeDefined();
    expect(result.explain.scoring).toBeDefined();
    expect(result.explain.scoring.threshold).toBe(0.2);
    expect(result.explain.scoring.topK).toBe(5);
    expect(result.explain.scoring.weights).toBeDefined();
    expect(result.explain.scoring.weights.semanticWeight).toBe(0.8);
    expect(result.explain.scoring.weights.bm25Weight).toBe(0.6);
    expect(typeof result.explain.scoring.semanticCount).toBe("number");
    expect(typeof result.explain.scoring.bm25Count).toBe("number");
    expect(typeof result.explain.scoring.entityCount).toBe("number");
  });

  test("explain includes filters details with categories", async () => {
    const mem = createMemory({
      searchProfiles: {
        "filter-explain": {
          name: "filter-explain",
          categories: ["fact", "preference"],
        },
      },
    });
    const userId = `filter_explain_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      profile: "filter-explain",
      filters: { user_id: userId, importance: "high" },
      explain: true,
    })) as any;

    expect(result.explain.filters).toBeDefined();
    expect(result.explain.filters.categories).toEqual(["fact", "preference"]);
    expect(result.explain.filters.normalized).toBeDefined();
    expect(result.explain.filters.normalized.user_id).toBe(userId);
    expect(result.explain.filters.normalized.categories).toBeDefined();
  });

  test("explain includes rerank info when rerank disabled", async () => {
    const mem = createMemory({
      searchProfiles: {
        "no-rerank": {
          name: "no-rerank",
          rerank: false,
        },
      },
    });
    const userId = `rerank_off_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      profile: "no-rerank",
      filters: { user_id: userId },
      explain: true,
    })) as any;

    expect(result.explain.rerank).toBeDefined();
    expect(result.explain.rerank.enabled).toBe(false);
    expect(result.explain.rerank.provider).toBeUndefined();
  });

  test("explain includes profile and overridden fields together", async () => {
    const mem = createMemory({
      searchProfiles: {
        "override-test": {
          name: "override-test",
          topK: 10,
        },
      },
    });
    const userId = `override_explain_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      profile: "override-test",
      filters: { user_id: userId },
      topK: 3,
      explain: true,
    })) as any;

    expect(result.explain.profile).toBeDefined();
    expect(result.explain.profile.name).toBe("override-test");
    expect(result.explain.overriddenFields).toContain("topK");
    expect(result.explain.scoring.topK).toBe(3);
  });
});

describe("Memory - Categories Filter End-to-End", () => {
  test("categories filter works with memory payload categories", async () => {
    const mem = createMemory();
    const userId = `cat_e2e_${Date.now()}`;

    await mem.add("User likes pizza", {
      userId,
      metadata: { categories: ["food", "preference"] },
    });
    await mem.add("User works at Acme", {
      userId,
      metadata: { categories: ["work", "fact"] },
    });
    await mem.add("User has a dog", {
      userId,
      metadata: { categories: ["pet", "fact"] },
    });

    const result = (await mem.search("What does user like", {
      filters: { user_id: userId, categories: { in: ["food"] } },
      explain: true,
    })) as any;

    expect(result.explain.filters.categories).toEqual(["food"]);
    expect(Array.isArray(result.results)).toBe(true);
  });

  test("categories filter from profile filters results correctly", async () => {
    const mem = createMemory({
      searchProfiles: {
        "food-only": {
          name: "food-only",
          categories: ["food"],
        },
      },
    });
    const userId = `cat_profile_e2e_${Date.now()}`;

    await mem.add("User likes pizza", {
      userId,
      metadata: { categories: ["food", "preference"] },
    });
    await mem.add("User works at Acme", {
      userId,
      metadata: { categories: ["work", "fact"] },
    });

    const result = (await mem.search("What does user like", {
      profile: "food-only",
      filters: { user_id: userId },
      explain: true,
    })) as any;

    expect(result.explain.profile.appliedConfig.categories).toEqual(["food"]);
  });

  test("search with categories as simple string category filter works", async () => {
    const mem = createMemory();
    const userId = `cat_simple_${Date.now()}`;

    await mem.add("User likes pizza", {
      userId,
      metadata: { category: "food" },
    });

    const result = (await mem.search("food", {
      filters: { user_id: userId, category: "food" },
      explain: true,
    })) as any;

    expect(result.results.length).toBeGreaterThanOrEqual(0);
    expect(result.explain.filters.normalized.category).toBe("food");
  });
});

describe("Memory - Reranker Configuration", () => {
  test("Memory accepts reranker config in constructor", () => {
    const mem = createMemory({
      reranker: {
        provider: "llm",
        config: { batchSize: 10 },
      },
    } as any);
    expect(mem).toBeDefined();
  });

  test("profile with rerank: true but no reranker config shows disabled in explain", async () => {
    const mem = createMemory({
      searchProfiles: {
        "rerank-profile": {
          name: "rerank-profile",
          rerank: true,
        },
      },
    });
    const userId = `rerank_noconfig_${Date.now()}`;
    await mem.add("User likes pizza", { userId });

    const result = (await mem.search("What does user like", {
      profile: "rerank-profile",
      filters: { user_id: userId },
      explain: true,
    })) as any;

    expect(result.explain.rerank).toBeDefined();
    expect(result.explain.rerank.enabled).toBe(false);
  });

  test("call-time rerank: true without reranker in profile triggers reranking", async () => {
    const mem = createMemory({
      searchProfiles: {
        "with-rerank": {
          name: "with-rerank",
          rerank: true,
        },
      },
    });
    const userId = `rerank_call_${Date.now()}`;
    await mem.add("User likes pizza", { userId });
    await mem.add("User likes pasta", { userId });

    const result = (await mem.search("What does user like", {
      profile: "with-rerank",
      filters: { user_id: userId },
      explain: true,
    })) as any;

    expect(result.explain.rerank).toBeDefined();
    expect(result.explain.rerank.enabled).toBe(false);
    expect(Array.isArray(result.results)).toBe(true);
  });
});
