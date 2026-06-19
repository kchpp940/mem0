/**
 * OSS unit tests — Shared Filter Normalizer and Categories contract.
 * Tests normalizeFilters() plus backend-specific builders (In-Memory,
 * Qdrant, PGVector, Redis) and validates that categories semantics
 * (array overlap / contains any) is identical across adapters.
 */
/// <reference types="jest" />
import {
  normalizeFilters,
  buildInMemoryFilters,
  buildQdrantFilters,
  buildPgFilterConditions,
  buildRedisFilters,
} from "../src/utils/filter_normalizer";

jest.setTimeout(15000);

describe("normalizeFilters — unified categories + entity alias contract", () => {
  it("normalizes userId/agentId/runId camelCase to snake_case", () => {
    const result = normalizeFilters({
      userId: "u-1",
      agentId: "a-2",
      runId: "r-3",
    });
    expect(result.raw["user_id"]).toBe("u-1");
    expect(result.raw["agent_id"]).toBe("a-2");
    expect(result.raw["run_id"]).toBe("r-3");
    expect(result.raw["userId"]).toBeUndefined();
    expect(result.entityFilters["user_id"]).toBe("u-1");
  });

  it("treats single-string categories as 1-element array", () => {
    const r = normalizeFilters({ categories: "support" });
    expect(r.categories).toEqual(["support"]);
    expect(r.raw["categories"]).toEqual(["support"]);
  });

  it("normalizes multi-string categories to same array", () => {
    const r = normalizeFilters({ categories: ["a", "b"] });
    expect(r.categories).toEqual(["a", "b"]);
    expect(r.raw["categories"]).toEqual(["a", "b"]);
  });

  it("filters out empty strings from categories array", () => {
    const r = normalizeFilters({ categories: ["a", "", "b", "  "] });
    // Whitespace strings are kept as-is (non-empty); only truly empty are stripped
    expect(r.categories).toContain("a");
    expect(r.categories).toContain("b");
  });

  it("handles op-style `{ in: [...] }` for categories", () => {
    const r = normalizeFilters({
      categories: { in: ["fact", "memory"] },
    });
    expect(r.categories).toEqual(["fact", "memory"]);
  });

  it("handles op-style `{ contains: 'x' }` for categories", () => {
    const r = normalizeFilters({
      categories: { contains: "fact" },
    });
    expect(r.categories).toEqual(["fact"]);
  });

  it("leaves `nin` (not in) categories op untouched in raw", () => {
    const r = normalizeFilters({
      categories: { nin: ["draft", "spam"] },
    });
    expect(r.raw["categories"]).toEqual({ nin: ["draft", "spam"] });
    expect(r.categories).toBeUndefined();
  });

  it("returns undefined categories for empty inputs", () => {
    expect(normalizeFilters({}).categories).toBeUndefined();
    expect(normalizeFilters({ categories: [] }).categories).toBeUndefined();
    expect(normalizeFilters({ categories: "" }).categories).toBeUndefined();
    expect(normalizeFilters(undefined).categories).toBeUndefined();
  });

  it("trims blank entity filters", () => {
    const r = normalizeFilters({ user_id: "   " });
    expect(r.raw["user_id"]).toBeUndefined();
  });

  it("preserves arbitrary metadata filters", () => {
    const r = normalizeFilters({
      channel: "slack",
      priority: { gte: 4 },
    });
    expect(r.raw["channel"]).toBe("slack");
    expect(r.raw["priority"]).toEqual({ gte: 4 });
  });

  it("combines categories + entity filters + metadata filters", () => {
    const r = normalizeFilters({
      userId: "u-99",
      categories: ["fact", "note"],
      priority: { gte: 3 },
    });
    expect(r.raw["user_id"]).toBe("u-99");
    expect(r.raw["categories"]).toEqual(["fact", "note"]);
    expect(r.raw["priority"]).toEqual({ gte: 3 });
  });
});

describe("buildInMemoryFilters — categories in-memory ready", () => {
  it("produces categories as array (for vector store overlap match)", () => {
    const f = buildInMemoryFilters({ categories: ["x", "y"] });
    expect(f["categories"]).toEqual(["x", "y"]);
  });
});

describe("buildQdrantFilters — Qdrant-specific match.any for categories", () => {
  it("emits match.any for categories array (overlap semantics)", () => {
    const f = buildQdrantFilters({ categories: ["a", "b", "c"] })!;
    expect(f.must).toHaveLength(1);
    const cond = f.must![0] as any;
    expect(cond.key).toBe("categories");
    expect(cond.match).toEqual({ any: ["a", "b", "c"] });
  });

  it("emits match.any for single categories string", () => {
    const f = buildQdrantFilters({ categories: "fact" })!;
    const cond = f.must![0] as any;
    expect(cond.match).toEqual({ any: ["fact"] });
  });

  it("emits match.any for categories { in: [...] }", () => {
    const f = buildQdrantFilters({ categories: { in: ["a", "b"] } })!;
    const cond = f.must![0] as any;
    expect(cond.match).toEqual({ any: ["a", "b"] });
  });

  it("emits match.any for categories { contains: 'x' }", () => {
    const f = buildQdrantFilters({ categories: { contains: "fact" } })!;
    const cond = f.must![0] as any;
    expect(cond.match).toEqual({ any: ["fact"] });
  });

  it("returns undefined when filters are empty", () => {
    expect(buildQdrantFilters(undefined)).toBeUndefined();
    expect(buildQdrantFilters({})).toBeUndefined();
  });
});

describe("buildPgFilterConditions — Postgres JSONB array operators for categories", () => {
  it("emits `payload->'categories' ?| $idx::text[]` for array categories", () => {
    const { conditions, values } = buildPgFilterConditions(
      { categories: ["fact", "note"] },
      1,
    );
    expect(conditions).toHaveLength(1);
    expect(conditions[0]).toMatch(/payload->'categories' \?\| \$1::text\[\]/);
    expect(values[0]).toEqual(["fact", "note"]);
  });

  it("emits array-overlap `?|` even for single string categories (consistent with multi-val)", () => {
    const { conditions, values } = buildPgFilterConditions(
      { categories: "fact" },
      1,
    );
    expect(conditions[0]).toMatch(/payload->'categories' \?\| \$1::text\[\]/);
    expect(values[0]).toEqual(["fact"]);
  });

  it("emits `NOT ... ?|` for categories { nin: [...] }", () => {
    const { conditions, values } = buildPgFilterConditions(
      { categories: { nin: ["draft", "spam"] } },
      1,
    );
    expect(conditions[0]).toMatch(
      /NOT \(payload->'categories' \?\| \$1::text\[\]\)/,
    );
    expect(values[0]).toEqual(["draft", "spam"]);
  });

  it("emits array-overlap `?|` for categories { contains: 'x' } (consistent semantics)", () => {
    const { conditions, values } = buildPgFilterConditions(
      { categories: { contains: "x" } },
      1,
    );
    expect(conditions[0]).toMatch(/payload->'categories' \?\| \$1::text\[\]/);
    expect(values[0]).toEqual(["x"]);
  });
});

describe("buildRedisFilters — RediSearch expression including categories", () => {
  it("emits metadata TEXT contains for each category (best-effort)", () => {
    const expr = buildRedisFilters({ categories: ["fact", "note"] }).expression;
    expect(expr).toContain('@metadata:"fact"');
    expect(expr).toContain('@metadata:"note"');
  });

  it("escapes special characters in category names", () => {
    const expr = buildRedisFilters({ categories: ["a-b", "c.d"] }).expression;
    // The minus and dot must be escaped
    expect(expr).toContain("a\\-b");
    expect(expr).toContain("c\\.d");
  });

  it("returns `*` when no filters", () => {
    expect(buildRedisFilters(undefined).expression).toBe("*");
    expect(buildRedisFilters({}).expression).toBe("*");
  });

  it("combines categories with entity filters", () => {
    const expr = buildRedisFilters({
      categories: ["x"],
      user_id: "u1",
    }).expression;
    expect(expr).toContain('@metadata:"x"');
    expect(expr).toContain("@user_id:{u1}");
  });
});
