import { SearchFilters } from "../types";

// ============================================================
// Shared Filter Normalization Layer
// ============================================================
// Purpose: Unify filter contract across all vector store adapters.
// In particular, the `categories: string[]` field must be translated
// into a backend-appropriate "array overlap / contains any" filter
// so that the same profile produces identical results on any backend.
// ============================================================

export const FIELD_CATEGORIES = "categories";

const SNAKE_CASE_RE = /[A-Z]/g;

export function toSnakeCaseKey(key: string): string {
  return key.replace(SNAKE_CASE_RE, (letter) => `_${letter.toLowerCase()}`);
}

export function toSnakeCaseObject(
  obj: Record<string, any>,
): Record<string, any> {
  if (typeof obj !== "object" || obj === null || Array.isArray(obj)) return obj;
  return Object.fromEntries(
    Object.entries(obj).map(([key, value]) => [toSnakeCaseKey(key), value]),
  );
}

// ------------------------------------------------------------
// 1. Pre-process a raw SearchFilters object:
//    - normalize userId/agentId/runId → user_id/agent_id/run_id
//    - normalize categories → proper array-overlap semantics
// ------------------------------------------------------------

export interface NormalizedFilters {
  raw: Record<string, any>;
  entityFilters: Record<string, any>;
  categories: string[] | undefined;
  // If the adapter supports native array overlap, use:
  //   { categories: string[] } → "payload.categories overlaps with this array"
  // If the adapter only supports scalar `in` checks, call:
  //   translateCategoriesToInForAdapter(...)
}

export function normalizeFilters(
  filters: SearchFilters | Record<string, any> | undefined,
): NormalizedFilters {
  if (!filters) {
    return { raw: {}, entityFilters: {}, categories: undefined };
  }

  const raw: Record<string, any> = {};
  const entityFilters: Record<string, any> = {};
  let categories: string[] | undefined = undefined;

  for (const [rawKey, rawValue] of Object.entries(filters)) {
    if (rawValue === undefined || rawValue === null) continue;

    let key = rawKey;
    // normalize well-known entity aliases
    if (rawKey === "userId") key = "user_id";
    else if (rawKey === "agentId") key = "agent_id";
    else if (rawKey === "runId") key = "run_id";

    if (key === FIELD_CATEGORIES) {
      // Guarantee string[] form
      if (Array.isArray(rawValue)) {
        const arr = rawValue.filter(
          (c) => typeof c === "string" && c.length > 0,
        );
        if (arr.length > 0) categories = arr;
      } else if (typeof rawValue === "object" && rawValue !== null) {
        // Advanced operator form: { in: ["a","b"] } or { contains: "x" }
        const op = rawValue as Record<string, any>;
        const collected: string[] = [];
        const opKeys = Object.keys(op);
        if (opKeys.includes("in") && Array.isArray(op["in"])) {
          collected.push(
            ...op["in"].filter(
              (c: any) => typeof c === "string" && c.length > 0,
            ),
          );
        }
        if (opKeys.includes("nin") && Array.isArray(op["nin"])) {
          // Keep it as-is in raw; no "positive" categories list for it
          raw[key] = rawValue;
          continue;
        }
        if (opKeys.includes("contains") && typeof op["contains"] === "string") {
          collected.push(op["contains"]);
        }
        if (collected.length > 0) categories = collected;
        if (collected.length === 0 && opKeys.every((k) => k !== "nin")) {
          // Unknown operator - forward to backend to decide
          raw[key] = rawValue;
        }
        continue;
      } else if (typeof rawValue === "string" && rawValue.length > 0) {
        categories = [rawValue];
      }
      continue;
    }

    // Entity fields
    if (key === "user_id" || key === "agent_id" || key === "run_id") {
      if (typeof rawValue === "string" && rawValue.trim().length === 0)
        continue;
      entityFilters[key] = rawValue;
      raw[key] = rawValue;
      continue;
    }

    // Plain metadata field
    raw[key] = rawValue;
  }

  if (categories) {
    raw[FIELD_CATEGORIES] = categories;
  }

  return { raw, entityFilters, categories };
}

// ------------------------------------------------------------
// 2. Adapter-specific translations
// ------------------------------------------------------------

// --- In-Memory (MemoryVectorStore) filter translation ---
//
// The in-memory adapter already supports array-overlap semantics for
// `{ categories: ["a", "b"] }` and advanced op `{ in: [...] }`.
// We simply produce the normalized filter dict; no further translation
// is needed for this adapter.
export function buildInMemoryFilters(
  filters: SearchFilters | undefined,
): Record<string, any> {
  const normalized = normalizeFilters(filters);
  return normalized.raw;
}

// --- Qdrant filter translation ---
//
// For a `categories` string[] array we need Qdrant's "match any" on a
// repeated / list field. Qdrant JS client supports:
//   { key: "categories", match: { any: ["a", "b"] } }
// which will match any payload whose `categories` list overlaps with the
// provided list.
export interface QdrantCondition {
  key: string;
  match?: { value?: any; any?: any[]; except?: any[]; text?: string };
  range?: {
    gte?: number | string;
    gt?: number | string;
    lte?: number | string;
    lt?: number | string;
  };
}

export interface QdrantFilter {
  must?: (QdrantCondition | QdrantFilter)[];
  must_not?: (QdrantCondition | QdrantFilter)[];
  should?: (QdrantCondition | QdrantFilter)[];
}

const QDRANT_KEY_MAP: Record<string, string> = {
  $and: "AND",
  $or: "OR",
  $not: "NOT",
};

export function buildQdrantFilters(
  filters?: SearchFilters,
): QdrantFilter | undefined {
  const normalized = normalizeFilters(filters);
  const raw = normalized.raw;
  if (!raw || Object.keys(raw).length === 0) return undefined;

  const mapped: Record<string, any> = {};
  for (const [key, value] of Object.entries(raw)) {
    const normKey = QDRANT_KEY_MAP[key] || key;
    if (!(normKey in mapped)) mapped[normKey] = value;
  }

  const must: (QdrantCondition | QdrantFilter)[] = [];
  const should: (QdrantCondition | QdrantFilter)[] = [];
  const mustNot: (QdrantCondition | QdrantFilter)[] = [];

  for (const [key, value] of Object.entries(mapped)) {
    if (key === "AND" || key === "OR" || key === "NOT") {
      if (!Array.isArray(value)) continue;
      if (key === "AND") {
        for (const sub of value) {
          const built = buildQdrantFilters(sub);
          if (built) must.push(built);
        }
      } else if (key === "OR") {
        for (const sub of value) {
          const built = buildQdrantFilters(sub);
          if (built) should.push(built);
        }
      } else if (key === "NOT") {
        for (const sub of value) {
          const built = buildQdrantFilters(sub);
          if (built) mustNot.push(built);
        }
      }
      continue;
    }

    const condition = buildQdrantFieldCondition(key, value);
    if (condition) must.push(condition);
  }

  if (must.length === 0 && should.length === 0 && mustNot.length === 0) {
    return undefined;
  }
  return {
    must: must.length > 0 ? must : undefined,
    should: should.length > 0 ? should : undefined,
    must_not: mustNot.length > 0 ? mustNot : undefined,
  };
}

function buildQdrantFieldCondition(
  key: string,
  value: any,
): QdrantCondition | null {
  if (typeof value !== "object" || value === null) {
    if (value === "*") return null;
    // categories short-form: single string → treat as contains (match any with 1 element)
    if (key === FIELD_CATEGORIES && typeof value === "string") {
      return { key, match: { any: [value] } };
    }
    return { key, match: { value } };
  }

  // Array form: for `categories` → any-overlap; for other fields → any-of-scalar
  if (Array.isArray(value)) {
    return { key, match: { any: value } };
  }

  const ops = Object.keys(value);
  const rangeOps = ["gt", "gte", "lt", "lte"];
  const hasRange = ops.some((op) => rangeOps.includes(op));

  if (hasRange) {
    const range: Record<string, number | string> = {};
    for (const op of rangeOps) if (op in value) range[op] = value[op];
    return { key, range };
  }

  if ("eq" in value) return { key, match: { value: value.eq } };
  if ("ne" in value) return { key, match: { except: [value.ne] } };
  if ("in" in value) {
    // categories: { in: ["a", "b"] } → overlap
    return { key, match: { any: value.in } };
  }
  if ("nin" in value) return { key, match: { except: value.nin } };
  if ("contains" in value || "icontains" in value) {
    const text = value.contains || value.icontains;
    if (key === FIELD_CATEGORIES) {
      return { key, match: { any: [text] } };
    }
    return { key, match: { text } };
  }

  // Unknown operator — forward to backend (may error, same as before)
  const supported = [
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "nin",
    "contains",
    "icontains",
  ];
  throw new Error(
    `Unsupported filter operator(s) for field '${key}': ${ops.join(", ")}. ` +
      `Supported: ${supported.join(", ")}`,
  );
}

// --- PGVector (Postgres JSONB) filter translation ---
//
// Postgres `payload->'categories'` is a JSON array. The "overlap"
// semantics is achieved via `payload->'categories' ?| array['a','b']`
// (operator ?| = any key exists in JSONB array / object).
//
// For scalar equality we keep using `payload->>'key'`, but for the
// categories key we need to switch to JSON operators.
export interface PGFilterResult {
  conditions: string[];
  values: any[];
}

const PG_NUMERIC_OPS = new Set(["gt", "gte", "lt", "lte"]);

export function buildPgFilterConditions(
  filters: SearchFilters | Record<string, any> | undefined,
  startIndex: number,
): PGFilterResult {
  const conditions: string[] = [];
  const values: any[] = [];
  let idx = startIndex;

  if (!filters) return { conditions, values };

  const normalized = normalizeFilters(filters);
  const raw = normalized.raw;

  for (const [rawKey, rawValue] of Object.entries(raw)) {
    if (rawKey === "$or") {
      const orGroups: string[] = [];
      for (const orFilter of rawValue as Record<string, any>[]) {
        const sub = buildPgFilterConditions(orFilter, idx);
        if (sub.conditions.length > 0) {
          orGroups.push("(" + sub.conditions.join(" AND ") + ")");
          values.push(...sub.values);
          idx = sub.conditions.length; // unused; `idx` is positional so we should not advance it this way
          // We re-compute below via values.length + startIndex for true positional safety.
        }
      }
      if (orGroups.length > 0)
        conditions.push("(" + orGroups.join(" OR ") + ")");
      idx = startIndex + values.length;
      continue;
    }

    if (rawKey === "$not") {
      const notGroups: string[] = [];
      for (const notFilter of rawValue as Record<string, any>[]) {
        const sub = buildPgFilterConditions(notFilter, idx);
        if (sub.conditions.length > 0) {
          notGroups.push("(" + sub.conditions.join(" AND ") + ")");
          values.push(...sub.values);
        }
      }
      if (notGroups.length > 0)
        conditions.push("NOT (" + notGroups.join(" OR ") + ")");
      idx = startIndex + values.length;
      continue;
    }

    // Use positional index from values array
    // `paramIndex()` returns the SQL 1-based parameter index ($1, $2, ...)
    // and pushes a null placeholder into values.
    // Use `values[values.length - 1] = x` to set the value after calling.
    const paramIndex = () => {
      values.push(null);
      return startIndex + values.length - 1;
    };
    const setLastValue = (v: any) => {
      values[values.length - 1] = v;
    };

    const safeKey = pgSafeIdentifier(rawKey);

    // --- categories special-casing: use JSONB array operators ---
    // ALL categories filters use ?| (array-overlap) for consistent
    // semantics across backends. Even a single string value is wrapped
    // as an array so the predicate semantics (overlap) are identical to
    // the multi-valued case and to other backends (Qdrant match.any, etc.)
    if (rawKey === FIELD_CATEGORIES) {
      if (Array.isArray(rawValue)) {
        const i = paramIndex();
        setLastValue(rawValue);
        conditions.push(`payload->'${safeKey}' ?| $${i}::text[]`);
        continue;
      }
      if (typeof rawValue === "object" && rawValue !== null) {
        const op = rawValue as Record<string, any>;
        if ("in" in op && Array.isArray(op["in"])) {
          const i = paramIndex();
          setLastValue(op["in"]);
          conditions.push(`payload->'${safeKey}' ?| $${i}::text[]`);
          continue;
        }
        if ("nin" in op && Array.isArray(op["nin"])) {
          const i = paramIndex();
          setLastValue(op["nin"]);
          conditions.push(`NOT (payload->'${safeKey}' ?| $${i}::text[])`);
          continue;
        }
        if ("contains" in op && typeof op["contains"] === "string") {
          // Wrap single value in array for consistent overlap semantics
          const i = paramIndex();
          setLastValue([op["contains"]]);
          conditions.push(`payload->'${safeKey}' ?| $${i}::text[]`);
          continue;
        }
      }
      // Plain string → wrap in array for overlap semantics
      if (typeof rawValue === "string") {
        const i = paramIndex();
        setLastValue([rawValue]);
        conditions.push(`payload->'${safeKey}' ?| $${i}::text[]`);
        continue;
      }
    }

    // --- Wildcard ---
    if (rawValue === "*") {
      conditions.push(`payload ? $${paramIndex()}`);
      values[values.length - 1] = rawKey;
      continue;
    }

    // --- Advanced op-style filter ---
    if (
      typeof rawValue === "object" &&
      rawValue !== null &&
      !Array.isArray(rawValue)
    ) {
      for (const [op, opValue] of Object.entries(rawValue)) {
        if (PG_NUMERIC_OPS.has(op)) {
          const template =
            op === "gt"
              ? `(payload->>'${safeKey}')::numeric > $${paramIndex()}`
              : op === "gte"
                ? `(payload->>'${safeKey}')::numeric >= $${paramIndex()}`
                : op === "lt"
                  ? `(payload->>'${safeKey}')::numeric < $${paramIndex()}`
                  : `(payload->>'${safeKey}')::numeric <= $${paramIndex()}`;
          conditions.push(template);
          values[values.length - 1] = Number(opValue);
        } else if (op === "eq") {
          conditions.push(`payload->>'${safeKey}' = $${paramIndex()}`);
          values[values.length - 1] = String(opValue);
        } else if (op === "ne") {
          conditions.push(`payload->>'${safeKey}' != $${paramIndex()}`);
          values[values.length - 1] = String(opValue);
        } else if (op === "in") {
          conditions.push(
            `payload->>'${safeKey}' = ANY($${paramIndex()}::text[])`,
          );
          values[values.length - 1] = (opValue as any[]).map(String);
        } else if (op === "nin") {
          conditions.push(
            `NOT (payload->>'${safeKey}' = ANY($${paramIndex()}::text[]))`,
          );
          values[values.length - 1] = (opValue as any[]).map(String);
        } else if (op === "contains" || op === "icontains") {
          const escaped = String(opValue)
            .replace(/\\/g, "\\\\")
            .replace(/%/g, "\\%")
            .replace(/_/g, "\\_");
          const likeOp = op === "icontains" ? "ILIKE" : "LIKE";
          conditions.push(
            `payload->>'${safeKey}' ${likeOp} $${paramIndex()} ESCAPE '\\'`,
          );
          values[values.length - 1] = `%${escaped}%`;
        } else {
          throw new Error(`Unsupported filter operator: ${op}`);
        }
      }
      continue;
    }

    // --- Plain array shorthand (non-categories) → in-array ---
    if (Array.isArray(rawValue)) {
      conditions.push(`payload->>'${safeKey}' = ANY($${paramIndex()}::text[])`);
      values[values.length - 1] = rawValue.map(String);
      continue;
    }

    // --- Plain scalar equality ---
    const i = paramIndex();
    if (typeof rawValue === "boolean") {
      setLastValue(JSON.stringify(rawValue));
    } else {
      setLastValue(String(rawValue));
    }
    conditions.push(`payload->>'${safeKey}' = $${i}`);
  }

  return { conditions, values };
}

function pgSafeIdentifier(key: string): string {
  if (!/^[a-zA-Z_][a-zA-Z0-9_]{0,127}$/.test(key)) {
    throw new Error(
      `Invalid filter key '${key}': only letters, digits, and underscores are allowed.`,
    );
  }
  return key;
}

// --- Redis (RediSearch) filter translation ---
//
// `categories` is stored as JSON inside `metadata` in Redis adapter
// today, but Redis RediSearch does not natively support JSON array
// containment within TAG filters for arbitrary nested keys. For
// correctness we emit a warning and translate to a best-effort text
// MATCH on the metadata text field; callers that rely on precise
// `categories` filtering on Redis should migrate to a separate TAG
// field for categories (future enhancement).
export interface RedisFilterResult {
  expression: string; // "*" if no filters
}

function redisEscapeTag(value: unknown): string {
  return String(value).replace(
    /([,.<>{}\[\]"':;!@#$%^&*()\-+=~|/\\\s])/g,
    "\\$1",
  );
}

export function buildRedisFilters(
  filters: SearchFilters | Record<string, any> | undefined,
): RedisFilterResult {
  if (!filters) return { expression: "*" };

  const normalized = normalizeFilters(filters);
  const raw = normalized.raw;

  const pieces: string[] = [];

  for (const [key, value] of Object.entries(raw)) {
    if (value === null || value === undefined) continue;

    // categories: best-effort text containment on metadata field
    if (key === FIELD_CATEGORIES) {
      let categoriesList: string[] = [];
      if (Array.isArray(value)) categoriesList = value;
      else if (typeof value === "string") categoriesList = [value];
      else if (typeof value === "object" && value !== null) {
        const op = value as Record<string, any>;
        if ("in" in op && Array.isArray(op["in"])) categoriesList = op["in"];
        if ("contains" in op && typeof op["contains"] === "string")
          categoriesList = [op["contains"]];
      }
      for (const cat of categoriesList) {
        pieces.push(`@metadata:"${redisEscapeTag(cat)}"`);
      }
      continue;
    }

    const snakeKey = toSnakeCaseKey(key);

    if (typeof value === "object" && value !== null && !Array.isArray(value)) {
      const ops = Object.keys(value);
      for (const op of ops) {
        const opVal = (value as Record<string, any>)[op];
        if (op === "in" && Array.isArray(opVal)) {
          // RediSearch TAG: {a|b|c} (OR via pipe inside braces)
          const joined = opVal.map((v: any) => redisEscapeTag(v)).join("|");
          pieces.push(`@${snakeKey}:{${joined}}`);
        } else if (op === "contains" || op === "icontains") {
          pieces.push(`@${snakeKey}:"${redisEscapeTag(opVal)}"`);
        } else if (op === "eq") {
          pieces.push(`@${snakeKey}:{${redisEscapeTag(opVal)}}`);
        } else if (op === "ne") {
          // Negated match — RediSearch minus operator
          pieces.push(`-@${snakeKey}:{${redisEscapeTag(opVal)}}`);
        } else if (op === "gt" || op === "gte" || op === "lt" || op === "lte") {
          const lb = op === "gt" ? `(${opVal}` : `[${opVal}`;
          const ub = op === "lt" ? `${opVal})` : `${opVal}]`;
          const range =
            op === "gt" || op === "gte" ? `${lb} +inf]` : `[-inf ${ub}`;
          pieces.push(`@${snakeKey}:${range}`);
        }
      }
      continue;
    }

    if (Array.isArray(value)) {
      const joined = value.map((v: any) => redisEscapeTag(v)).join("|");
      pieces.push(`@${snakeKey}:{${joined}}`);
      continue;
    }

    if (value === "*") {
      // Wildcard — include key existence check via @snakeKey:* (TEXT field)
      pieces.push(`@${snakeKey}:*`);
      continue;
    }

    pieces.push(`@${snakeKey}:{${redisEscapeTag(value)}}`);
  }

  if (pieces.length === 0) return { expression: "*" };
  return { expression: pieces.join(" ") };
}

// --- Supabase (Postgres JSONB via RPC function) filter translation ---
//
// Supabase has two paths:
//   1. `search()` uses an SQL RPC function `match_vectors` that accepts a
//      JSONB `filter` parameter. The default function uses `@>` (contains)
//      which cannot handle array overlap. We emit a structured filter dict
//      with a sentinel key `$categoriesOverlap` so the SQL function can
//      switch to `?|` for categories.
//   2. `list()` uses Supabase JS client query builder, so we emit SQL
//      conditions like pgvector adapter.
//
// For maximum backward compatibility, we build two separate outputs:
//   - `rpcFilter`: JSONB-compatible dict with `$categoriesOverlap` sentinel
//   - `clientConditions`: SQL conditions + values for JS client query builder

export interface SupabaseFilterResult {
  rpcFilter: Record<string, any>;
  clientConditions: string[];
  values: any[];
}

export function buildSupabaseFilters(
  filters: SearchFilters | Record<string, any> | undefined,
  startIndex: number = 1,
): SupabaseFilterResult {
  const rpcFilter: Record<string, any> = {};
  const clientConditions: string[] = [];
  const values: any[] = [];
  let idx = startIndex;

  if (!filters) return { rpcFilter: {}, clientConditions: [], values: [] };

  const normalized = normalizeFilters(filters);
  const raw = normalized.raw;

  const paramIndex = () => {
    values.push(null);
    return startIndex + values.length - 1;
  };
  const setLastValue = (v: any) => {
    values[values.length - 1] = v;
  };

  for (const [rawKey, rawValue] of Object.entries(raw)) {
    const safeKey = pgSafeIdentifier(rawKey);

    if (rawKey === FIELD_CATEGORIES) {
      // Sentinel for RPC function to use ?| overlap
      let categoriesList: string[] = [];
      let ninList: string[] | undefined;

      if (Array.isArray(rawValue)) {
        categoriesList = rawValue;
      } else if (typeof rawValue === "string") {
        categoriesList = [rawValue];
      } else if (typeof rawValue === "object" && rawValue !== null) {
        const op = rawValue as Record<string, any>;
        if ("in" in op && Array.isArray(op["in"])) categoriesList = op["in"];
        if ("nin" in op && Array.isArray(op["nin"])) ninList = op["nin"];
        if ("contains" in op && typeof op["contains"] === "string")
          categoriesList = [op["contains"]];
      }

      if (categoriesList.length > 0) {
        rpcFilter[`$categoriesOverlap`] = categoriesList;
        const i = paramIndex();
        setLastValue(categoriesList);
        clientConditions.push(`metadata->'${safeKey}' ?| $${i}::text[]`);
      }
      if (ninList && ninList.length > 0) {
        rpcFilter[`$categoriesNin`] = ninList;
        const i = paramIndex();
        setLastValue(ninList);
        clientConditions.push(`NOT (metadata->'${safeKey}' ?| $${i}::text[])`);
      }
      continue;
    }

    // Scalar fields go through normally for RPC @> containment
    rpcFilter[rawKey] = rawValue;

    // JS client builder condition
    if (
      typeof rawValue === "object" &&
      rawValue !== null &&
      !Array.isArray(rawValue)
    ) {
      const op = rawValue as Record<string, any>;
      for (const [opKey, opVal] of Object.entries(op)) {
        if (opKey === "eq") {
          const i = paramIndex();
          setLastValue(String(opVal));
          clientConditions.push(`metadata->>'${safeKey}' = $${i}`);
        } else if (opKey === "in" && Array.isArray(opVal)) {
          const i = paramIndex();
          setLastValue(opVal.map(String));
          clientConditions.push(`metadata->>'${safeKey}' = ANY($${i}::text[])`);
        } else if (opKey === "nin" && Array.isArray(opVal)) {
          const i = paramIndex();
          setLastValue(opVal.map(String));
          clientConditions.push(
            `NOT (metadata->>'${safeKey}' = ANY($${i}::text[]))`,
          );
        } else if (PG_NUMERIC_OPS.has(opKey)) {
          const template =
            opKey === "gt"
              ? `(metadata->>'${safeKey}')::numeric > $${paramIndex()}`
              : opKey === "gte"
                ? `(metadata->>'${safeKey}')::numeric >= $${paramIndex()}`
                : opKey === "lt"
                  ? `(metadata->>'${safeKey}')::numeric < $${paramIndex()}`
                  : `(metadata->>'${safeKey}')::numeric <= $${paramIndex()}`;
          clientConditions.push(template);
          setLastValue(Number(opVal));
        }
      }
    } else if (Array.isArray(rawValue)) {
      const i = paramIndex();
      setLastValue(rawValue.map(String));
      clientConditions.push(`metadata->>'${safeKey}' = ANY($${i}::text[])`);
    } else {
      const i = paramIndex();
      setLastValue(String(rawValue));
      clientConditions.push(`metadata->>'${safeKey}' = $${i}`);
    }
  }

  return { rpcFilter, clientConditions, values };
}
