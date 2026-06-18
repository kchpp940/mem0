/// <reference types="jest" />

import {
  parseFilters,
  buildSimpleEqualityFilter,
  buildSupabaseEqualityFilter,
  buildAzureODataFilter,
  buildRedisFilterExpr,
  buildQdrantFilter,
  buildPGVectorFilter,
  matchMemoryStoreFilter,
  FilterCapability,
  FilterCapabilityError,
} from "../src/utils/filter_utils";

describe("parseFilters - Python SDK compatibility", () => {
  describe("$-prefixed comparison operators", () => {
    test("$eq operator normalizes to eq", () => {
      const nodes = parseFilters({ status: { $eq: "active" } });
      expect(nodes).toEqual([
        { type: "field", key: "status", op: "eq", value: "active" },
      ]);
    });

    test("$ne operator normalizes to ne", () => {
      const nodes = parseFilters({ status: { $ne: "deleted" } });
      expect(nodes).toEqual([
        { type: "field", key: "status", op: "ne", value: "deleted" },
      ]);
    });

    test("$gt operator normalizes to gt", () => {
      const nodes = parseFilters({ price: { $gt: 100 } });
      expect(nodes).toEqual([
        { type: "field", key: "price", op: "gt", value: 100 },
      ]);
    });

    test("$gte operator normalizes to gte", () => {
      const nodes = parseFilters({ price: { $gte: 100 } });
      expect(nodes).toEqual([
        { type: "field", key: "price", op: "gte", value: 100 },
      ]);
    });

    test("$lt operator normalizes to lt", () => {
      const nodes = parseFilters({ price: { $lt: 50 } });
      expect(nodes).toEqual([
        { type: "field", key: "price", op: "lt", value: 50 },
      ]);
    });

    test("$lte operator normalizes to lte", () => {
      const nodes = parseFilters({ price: { $lte: 50 } });
      expect(nodes).toEqual([
        { type: "field", key: "price", op: "lte", value: 50 },
      ]);
    });

    test("$in operator normalizes to in", () => {
      const nodes = parseFilters({ category: { $in: ["a", "b"] } });
      expect(nodes).toEqual([
        { type: "field", key: "category", op: "in", value: ["a", "b"] },
      ]);
    });

    test("$nin operator normalizes to nin", () => {
      const nodes = parseFilters({ category: { $nin: ["x", "y"] } });
      expect(nodes).toEqual([
        { type: "field", key: "category", op: "nin", value: ["x", "y"] },
      ]);
    });

    test("$contains operator normalizes to contains", () => {
      const nodes = parseFilters({ title: { $contains: "hello" } });
      expect(nodes).toEqual([
        { type: "field", key: "title", op: "contains", value: "hello" },
      ]);
    });

    test("$icontains operator normalizes to icontains", () => {
      const nodes = parseFilters({ title: { $icontains: "HELLO" } });
      expect(nodes).toEqual([
        { type: "field", key: "title", op: "icontains", value: "HELLO" },
      ]);
    });

    test("mixed $-prefixed and unprefixed operators on same field", () => {
      const nodes = parseFilters({ price: { $gte: 10, lte: 100 } });
      expect(nodes).toEqual([
        { type: "field", key: "price", op: "gte", value: 10 },
        { type: "field", key: "price", op: "lte", value: 100 },
      ]);
    });
  });

  describe("$-prefixed logical operators", () => {
    test("$and normalizes to AND", () => {
      const nodes = parseFilters({
        $and: [{ status: "active" }, { user_id: "alice" }],
      });
      expect(nodes).toEqual([
        {
          type: "and",
          children: [
            { type: "field", key: "status", op: "eq", value: "active" },
            { type: "field", key: "user_id", op: "eq", value: "alice" },
          ],
        },
      ]);
    });

    test("$or normalizes to OR", () => {
      const nodes = parseFilters({
        $or: [{ category: "books" }, { category: "movies" }],
      });
      expect(nodes).toEqual([
        {
          type: "or",
          children: [
            { type: "field", key: "category", op: "eq", value: "books" },
            { type: "field", key: "category", op: "eq", value: "movies" },
          ],
        },
      ]);
    });

    test("$not normalizes to NOT", () => {
      const nodes = parseFilters({
        $not: [{ status: "deleted" }],
      });
      expect(nodes).toEqual([
        {
          type: "not",
          children: [
            { type: "field", key: "status", op: "eq", value: "deleted" },
          ],
        },
      ]);
    });

    test("nested $-prefixed logical operators", () => {
      const nodes = parseFilters({
        $and: [
          { user_id: "alice" },
          { $or: [{ status: "active" }, { status: "pending" }] },
        ],
      });
      expect(nodes[0].type).toBe("and");
      expect((nodes[0] as any).children).toHaveLength(2);
      expect((nodes[0] as any).children[0]).toEqual({
        type: "field",
        key: "user_id",
        op: "eq",
        value: "alice",
      });
      expect((nodes[0] as any).children[1].type).toBe("or");
    });
  });

  describe("unprefixed TS legacy syntax still works", () => {
    test("unprefixed eq operator", () => {
      const nodes = parseFilters({ status: { eq: "active" } });
      expect(nodes).toEqual([
        { type: "field", key: "status", op: "eq", value: "active" },
      ]);
    });

    test("unprefixed OR operator", () => {
      const nodes = parseFilters({
        OR: [{ category: "books" }, { category: "movies" }],
      });
      expect(nodes[0].type).toBe("or");
    });

    test("unprefixed AND operator", () => {
      const nodes = parseFilters({
        AND: [{ status: "active" }, { user_id: "alice" }],
      });
      expect(nodes[0].type).toBe("and");
    });
  });

  describe("camelCase entity key normalization", () => {
    test("userId normalizes to user_id", () => {
      const nodes = parseFilters({ userId: "alice" });
      expect(nodes).toEqual([
        { type: "field", key: "user_id", op: "eq", value: "alice" },
      ]);
    });

    test("agentId normalizes to agent_id", () => {
      const nodes = parseFilters({ agentId: "bot-1" });
      expect(nodes).toEqual([
        { type: "field", key: "agent_id", op: "eq", value: "bot-1" },
      ]);
    });

    test("runId normalizes to run_id", () => {
      const nodes = parseFilters({ runId: "run-123" });
      expect(nodes).toEqual([
        { type: "field", key: "run_id", op: "eq", value: "run-123" },
      ]);
    });

    test("userId inside $or normalizes correctly", () => {
      const nodes = parseFilters({
        $or: [{ userId: "alice" }, { userId: "bob" }],
      });
      const orNode = nodes[0] as any;
      expect(orNode.children[0].key).toBe("user_id");
      expect(orNode.children[1].key).toBe("user_id");
    });
  });

  describe("unknown nested object values", () => {
    test("throws for unknown operator keys in object (matching Python)", () => {
      expect(() => {
        parseFilters({ customField: { unknownOp: "value" } });
      }).toThrow(
        /Unsupported filter operator\(s\) for field 'customField': unknownOp/,
      );
    });

    test("throws for mixed known and unknown operators", () => {
      expect(() => {
        parseFilters({ price: { gt: 10, unknown: 20 } });
      }).toThrow(/Unsupported filter operator\(s\) for field 'price': unknown/);
    });
  });

  describe("null and undefined handling", () => {
    test("skips null values", () => {
      const nodes = parseFilters({ status: null, user_id: "alice" });
      expect(nodes).toEqual([
        { type: "field", key: "user_id", op: "eq", value: "alice" },
      ]);
    });

    test("skips undefined values", () => {
      const nodes = parseFilters({ status: undefined, user_id: "alice" });
      expect(nodes).toEqual([
        { type: "field", key: "user_id", op: "eq", value: "alice" },
      ]);
    });

    test("skips null values inside operator objects", () => {
      const nodes = parseFilters({ price: { gte: 10, lte: null } });
      expect(nodes).toEqual([
        { type: "field", key: "price", op: "gte", value: 10 },
      ]);
    });
  });
});

describe("filter capability model", () => {
  describe("reject capability (langchain — no filter support at all)", () => {
    test("buildSimpleEqualityFilter throws FilterCapabilityError on eq with reject", () => {
      expect(() => {
        buildSimpleEqualityFilter({ user_id: "alice" }, "reject");
      }).toThrow(FilterCapabilityError);
    });

    test("buildSimpleEqualityFilter throws FilterCapabilityError on non-eq with reject", () => {
      try {
        buildSimpleEqualityFilter({ price: { gt: 100 } }, "reject");
        fail("Expected FilterCapabilityError");
      } catch (e) {
        expect(e).toBeInstanceOf(FilterCapabilityError);
        const err = e as FilterCapabilityError;
        expect(err.capability).toBe("reject");
        expect(err.message).toContain("does not support any filter conditions");
      }
    });

    test("buildSimpleEqualityFilter throws FilterCapabilityError on $or with reject", () => {
      expect(() => {
        buildSimpleEqualityFilter(
          { $or: [{ category: "books" }, { category: "movies" }] },
          "reject",
        );
      }).toThrow(FilterCapabilityError);
    });

    test("buildSimpleEqualityFilter with reject returns empty for no filters", () => {
      const result = buildSimpleEqualityFilter({}, "reject");
      expect(result).toEqual({});
    });
  });

  describe("equality-only capability (redis, supabase, azure, vectorize)", () => {
    test("extracts eq from mixed conditions silently", () => {
      const result = buildSimpleEqualityFilter(
        { user_id: "alice", price: { gt: 100 } },
        "equality-only",
      );
      expect(result).toEqual({ user_id: "alice" });
    });

    test("extracts eq from $or with eq children", () => {
      const result = buildSimpleEqualityFilter(
        {
          user_id: "alice",
          $or: [{ category: "books" }],
        },
        "equality-only",
      );
      expect(result).toEqual({ user_id: "alice", category: "books" });
    });

    test("buildSupabaseEqualityFilter with equality-only works for eq-only", () => {
      const result = buildSupabaseEqualityFilter(
        { user_id: "alice", price: { gt: 100 } },
        "equality-only",
      );
      expect(result).toEqual({ user_id: "alice" });
    });

    test("buildAzureODataFilter with equality-only extracts eq conditions", () => {
      const result = buildAzureODataFilter(
        { user_id: "alice", price: { gt: 100 } },
        "equality-only",
      );
      expect(result).toContain("user_id eq 'alice'");
      expect(result).not.toContain("gt");
    });

    test("buildRedisFilterExpr with equality-only extracts eq conditions", () => {
      const escapeValue = (v: unknown) => String(v);
      const result = buildRedisFilterExpr(
        { user_id: "alice", price: { gt: 100 } },
        escapeValue,
        "equality-only",
      );
      expect(result).toContain("@user_id:{alice}");
      expect(result).not.toContain("gt");
    });
  });

  describe("advanced capability (qdrant, pgvector, memory)", () => {
    test("buildSimpleEqualityFilter with advanced returns all eq fields", () => {
      const result = buildSimpleEqualityFilter(
        { user_id: "alice", price: { gt: 100 } },
        "advanced",
      );
      expect(result).toEqual({ user_id: "alice" });
    });

    test("buildSimpleEqualityFilter with advanced does not throw on $or", () => {
      const result = buildSimpleEqualityFilter(
        {
          user_id: "alice",
          $or: [{ category: "books" }],
        },
        "advanced",
      );
      expect(result).toEqual({ user_id: "alice", category: "books" });
    });
  });

  describe("FilterCapabilityError properties", () => {
    test("reject error has correct name and properties", () => {
      try {
        buildSimpleEqualityFilter({ user_id: "alice" }, "reject");
        fail("Expected FilterCapabilityError");
      } catch (e) {
        expect(e).toBeInstanceOf(FilterCapabilityError);
        const err = e as FilterCapabilityError;
        expect(err.name).toBe("FilterCapabilityError");
        expect(err.capability).toBe("reject");
        expect(err.unsupportedConditions).toContain("user_id.eq");
      }
    });

    test("default parameter uses reject capability", () => {
      expect(() => {
        buildSimpleEqualityFilter({ user_id: "alice" });
      }).toThrow(FilterCapabilityError);
    });
  });
});

describe("advanced filter adapters - $-prefixed operators", () => {
  test("buildQdrantFilter handles $gte and $lte", () => {
    const result = buildQdrantFilter(
      parseFilters({ price: { $gte: 10, $lte: 100 } }),
    );
    expect(result?.must).toHaveLength(2);
    expect((result?.must![0] as any).range?.gte).toBe(10);
    expect((result?.must![1] as any).range?.lte).toBe(100);
  });

  test("buildPGVectorFilter handles $gt", () => {
    const result = buildPGVectorFilter({ price: { $gt: 100 } }, 1);
    expect(result.conditions[0]).toContain("::numeric > $1");
    expect(result.values).toEqual([100]);
  });

  test("buildPGVectorFilter handles $contains", () => {
    const result = buildPGVectorFilter({ title: { $contains: "hello" } }, 1);
    expect(result.conditions[0]).toContain("LIKE");
    expect(result.values).toEqual(["%hello%"]);
  });

  test("matchMemoryStoreFilter handles $in", () => {
    const nodes = parseFilters({ category: { $in: ["books", "movies"] } });
    expect(matchMemoryStoreFilter({ category: "books" }, nodes)).toBe(true);
    expect(matchMemoryStoreFilter({ category: "games" }, nodes)).toBe(false);
  });

  test("matchMemoryStoreFilter handles $and with $or", () => {
    const nodes = parseFilters({
      $and: [
        { userId: "alice" },
        { $or: [{ status: "active" }, { status: "pending" }] },
      ],
    });
    expect(
      matchMemoryStoreFilter({ user_id: "alice", status: "active" }, nodes),
    ).toBe(true);
    expect(
      matchMemoryStoreFilter({ user_id: "alice", status: "deleted" }, nodes),
    ).toBe(false);
    expect(
      matchMemoryStoreFilter({ user_id: "bob", status: "active" }, nodes),
    ).toBe(false);
  });
});
