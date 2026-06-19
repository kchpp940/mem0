import type { SearchFilters } from "../types";

export interface NormalizedFilter {
  field: string;
  operator: string;
  value: any;
}

export const LOGICAL_OPERATORS = new Set([
  "$and",
  "$or",
  "$not",
  "AND",
  "OR",
  "NOT",
]);

const STANDARD_OP_MAP: Record<string, string> = {
  eq: "eq",
  ne: "ne",
  gt: "gt",
  gte: "gte",
  lt: "lt",
  lte: "lte",
  in: "in",
  nin: "nin",
  contains: "contains",
  icontains: "icontains",
  $eq: "eq",
  $ne: "ne",
  $gt: "gt",
  $gte: "gte",
  $lt: "lt",
  $lte: "lte",
  $in: "in",
  $nin: "nin",
};

function isLogicalOp(key: string): boolean {
  return LOGICAL_OPERATORS.has(key) || LOGICAL_OPERATORS.has(key.toUpperCase());
}

function normalizeLogicalOp(op: string): string {
  const upper = op.toUpperCase();
  if (upper === "$AND") return "AND";
  if (upper === "$OR") return "OR";
  if (upper === "$NOT") return "NOT";
  return upper;
}

export function normalizeCategoriesFilter(
  filters: SearchFilters | undefined,
  categories?: string[],
): SearchFilters {
  const result: Record<string, any> = { ...(filters ?? {}) };

  if (categories && categories.length > 0) {
    if (result.categories) {
      const existing = result.categories;
      if (typeof existing === "object" && !Array.isArray(existing)) {
        const existingIn = existing.in ?? [];
        const combined = Array.from(
          new Set([
            ...(Array.isArray(existingIn) ? existingIn : [existingIn]),
            ...categories,
          ]),
        );
        result.categories = { ...existing, in: combined };
      } else if (Array.isArray(existing)) {
        result.categories = {
          in: Array.from(new Set([...existing, ...categories])),
        };
      } else {
        result.categories = {
          in: Array.from(new Set([String(existing), ...categories])),
        };
      }
    } else {
      result.categories = { in: [...categories] };
    }
  }

  return result;
}

export function extractCategoriesFromFilters(
  filters: SearchFilters | undefined,
): string[] | undefined {
  if (!filters) return undefined;

  const cats = filters.categories;
  if (!cats) return undefined;

  if (Array.isArray(cats)) {
    return [...cats];
  }

  if (typeof cats === "object" && cats !== null) {
    if (Array.isArray(cats.in)) {
      return [...cats.in];
    }
    if (cats.eq !== undefined) {
      return [String(cats.eq)];
    }
  }

  return [String(cats)];
}

export function normalizeFilterStructure(
  filters: SearchFilters | undefined,
): SearchFilters {
  if (!filters) return {};

  const result: Record<string, any> = {};

  for (const [key, value] of Object.entries(filters)) {
    if (isLogicalOp(key)) {
      const normKey = normalizeLogicalOp(key);
      if (Array.isArray(value)) {
        result[normKey] = value.map((item) => normalizeFilterStructure(item));
      } else {
        result[normKey] = value;
      }
      continue;
    }

    if (value === undefined || value === null) continue;

    if (typeof value === "object" && !Array.isArray(value)) {
      const normalizedOps: Record<string, any> = {};
      for (const [op, opVal] of Object.entries(value)) {
        const standardOp = STANDARD_OP_MAP[op] ?? op;
        normalizedOps[standardOp] = opVal;
      }
      result[key] = normalizedOps;
    } else {
      result[key] = value;
    }
  }

  return result;
}

export function flattenSimpleFilters(
  filters: SearchFilters | undefined,
): Record<string, any> {
  const result: Record<string, any> = {};
  if (!filters) return result;

  for (const [key, value] of Object.entries(filters)) {
    if (isLogicalOp(key)) continue;

    if (typeof value === "object" && !Array.isArray(value)) {
      if ("eq" in value) {
        result[key] = value.eq;
      } else if (
        "in" in value &&
        Array.isArray(value.in) &&
        value.in.length === 1
      ) {
        result[key] = value.in[0];
      }
    } else {
      result[key] = value;
    }
  }

  return result;
}

export function getFilterCategories(
  filters: SearchFilters | undefined,
): string[] {
  const cats = extractCategoriesFromFilters(filters);
  return cats ?? [];
}

export function removeCategoriesFromFilters(
  filters: SearchFilters | undefined,
): SearchFilters {
  if (!filters) return {};
  const result: Record<string, any> = { ...filters };
  delete result.categories;
  return result;
}

export function transformCategoriesForQdrant(
  filters: SearchFilters | undefined,
): { filters: SearchFilters; categoryValues: string[] } {
  const categories = extractCategoriesFromFilters(filters);
  const withoutCategories = removeCategoriesFromFilters(filters);

  if (!categories || categories.length === 0) {
    return { filters: withoutCategories, categoryValues: [] };
  }

  const orConditions = categories.map((cat) => ({ categories: cat }));
  const existingOr = (withoutCategories as Record<string, any>).$or;
  if (Array.isArray(existingOr)) {
    (withoutCategories as Record<string, any>).$or = [
      ...existingOr,
      ...orConditions,
    ];
  } else {
    (withoutCategories as Record<string, any>).$or = orConditions;
  }

  return { filters: withoutCategories, categoryValues: categories };
}

export function transformCategoriesForPgvector(
  filters: SearchFilters | undefined,
): {
  filters: SearchFilters;
  categoryValues: string[];
  categorySqlClause?: string;
  categorySqlParams?: string[];
} {
  const categories = extractCategoriesFromFilters(filters);
  const withoutCategories = removeCategoriesFromFilters(filters);

  if (!categories || categories.length === 0) {
    return { filters: withoutCategories, categoryValues: [] };
  }

  const conditions: string[] = [];
  const params: string[] = [];
  for (const cat of categories) {
    conditions.push(
      `(payload->'categories' ? $%PGV_PARAM% OR payload->>'categories' = $%PGV_PARAM%)`,
    );
    params.push(cat);
  }
  const clause =
    conditions.length === 1
      ? conditions[0]
      : "(" + conditions.join(" OR ") + ")";

  return {
    filters: withoutCategories,
    categoryValues: categories,
    categorySqlClause: clause,
    categorySqlParams: params,
  };
}

export function transformCategoriesForRedis(
  filters: SearchFilters | undefined,
): {
  filters: SearchFilters;
  categoryValues: string[];
  categoryTagExpr?: string;
} {
  const categories = extractCategoriesFromFilters(filters);
  const withoutCategories = removeCategoriesFromFilters(filters);

  if (!categories || categories.length === 0) {
    return { filters: withoutCategories, categoryValues: [] };
  }

  const tagExpr =
    categories.length === 1
      ? `@categories:{${_escapeRedisTagValue(categories[0])}}`
      : `(${categories.map((c) => `@categories:{${_escapeRedisTagValue(c)}}`).join("|")})`;

  return {
    filters: withoutCategories,
    categoryValues: categories,
    categoryTagExpr: tagExpr,
  };
}

export function transformCategoriesForSupabase(
  filters: SearchFilters | undefined,
): {
  filters: SearchFilters;
  categoryValues: string[];
  categoryExactValue?: string;
  categoryOverlapValues?: string[];
} {
  const categories = extractCategoriesFromFilters(filters);
  const withoutCategories = removeCategoriesFromFilters(filters);

  if (!categories || categories.length === 0) {
    return { filters: withoutCategories, categoryValues: [] };
  }

  if (categories.length === 1) {
    return {
      filters: withoutCategories,
      categoryValues: categories,
      categoryExactValue: categories[0],
    };
  }

  return {
    filters: withoutCategories,
    categoryValues: categories,
    categoryOverlapValues: categories,
  };
}

function _escapeRedisTagValue(value: unknown): string {
  return String(value).replace(
    /([,.<>{}\[\]"':;!@#$%^&*()\-+=~|/\\\s])/g,
    "\\$1",
  );
}
