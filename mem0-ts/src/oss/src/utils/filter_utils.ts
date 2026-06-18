const CAMEL_TO_SNAKE: Record<string, string> = {
  userId: "user_id",
  agentId: "agent_id",
  runId: "run_id",
};

const ENTITY_KEYS_SNAKE = new Set(["user_id", "agent_id", "run_id"]);
const ENTITY_KEYS_CAMEL = new Set(["userId", "agentId", "runId"]);

const LOGICAL_KEYS = new Set(["AND", "OR", "NOT", "$and", "$or", "$not"]);

const COMPARISON_OPS = new Set([
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
]);

function isDefinedValue(value: unknown): boolean {
  return value !== undefined && value !== null;
}

export type FilterOp =
  | "eq"
  | "ne"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "in"
  | "nin"
  | "contains"
  | "icontains";

export interface FieldCondition {
  type: "field";
  key: string;
  op: FilterOp;
  value: any;
}

export interface AndCondition {
  type: "and";
  children: FilterNode[];
}

export interface OrCondition {
  type: "or";
  children: FilterNode[];
}

export interface NotCondition {
  type: "not";
  children: FilterNode[];
}

export interface ExistsCondition {
  type: "exists";
  key: string;
}

export type FilterNode =
  | FieldCondition
  | AndCondition
  | OrCondition
  | NotCondition
  | ExistsCondition;

export interface FilterResult {
  conditions: string[];
  values: any[];
  paramIndex: number;
}

const NORMALIZE_KEY: Record<string, string> = {
  userId: "user_id",
  agentId: "agent_id",
  runId: "run_id",
  $and: "AND",
  $or: "OR",
  $not: "NOT",
};

function normalizeKey(key: string): string {
  return NORMALIZE_KEY[key] || key;
}

function parseFilterObject(obj: Record<string, any>): FilterNode[] {
  const nodes: FilterNode[] = [];

  for (const [rawKey, rawValue] of Object.entries(obj)) {
    const key = normalizeKey(rawKey);

    if (
      LOGICAL_KEYS.has(key) ||
      key === "AND" ||
      key === "OR" ||
      key === "NOT"
    ) {
      if (!Array.isArray(rawValue)) continue;
      const logicalChildren: FilterNode[] = [];
      for (const sub of rawValue) {
        if (typeof sub === "object" && sub !== null && !Array.isArray(sub)) {
          logicalChildren.push(...parseFilterObject(sub));
        }
      }
      if (logicalChildren.length === 0) continue;
      if (key === "AND") {
        nodes.push({ type: "and", children: logicalChildren });
      } else if (key === "OR") {
        nodes.push({ type: "or", children: logicalChildren });
      } else if (key === "NOT") {
        nodes.push({ type: "not", children: logicalChildren });
      }
      continue;
    }

    if (!isDefinedValue(rawValue)) continue;

    if (rawValue === "*") {
      nodes.push({ type: "exists", key });
      continue;
    }

    if (Array.isArray(rawValue)) {
      nodes.push({ type: "field", key, op: "in", value: rawValue });
      continue;
    }

    if (typeof rawValue === "object" && rawValue !== null) {
      const objKeys = Object.keys(rawValue);
      for (const opKey of objKeys) {
        if (!COMPARISON_OPS.has(opKey)) {
          throw new Error(
            `Unsupported filter operator(s) for field '${key}': ${opKey}. ` +
              `Supported operators: ${Array.from(COMPARISON_OPS).join(", ")}`,
          );
        }
      }
      for (const opKey of objKeys) {
        const opValue = rawValue[opKey];
        if (!isDefinedValue(opValue)) continue;
        nodes.push({
          type: "field",
          key,
          op: opKey as FilterOp,
          value: opValue,
        });
      }
      continue;
    }

    nodes.push({ type: "field", key, op: "eq", value: rawValue });
  }

  return nodes;
}

export function parseFilters(
  filters: Record<string, any> | undefined | null,
): FilterNode[] {
  if (!filters) return [];
  if (typeof filters !== "object") return [];
  if (Array.isArray(filters)) return [];
  return parseFilterObject(filters);
}

export function normalizeEntityFilters(
  filters: Record<string, any> | undefined,
): Record<string, any> {
  if (!filters) return {};

  const result: Record<string, any> = {};

  for (const [key, value] of Object.entries(filters)) {
    if (ENTITY_KEYS_CAMEL.has(key)) {
      const snakeKey = CAMEL_TO_SNAKE[key];
      if (isDefinedValue(value)) {
        result[snakeKey] = value;
      }
    } else if (ENTITY_KEYS_SNAKE.has(key)) {
      if (isDefinedValue(value)) {
        result[key] = value;
      }
    } else {
      if (isDefinedValue(value)) {
        result[key] = value;
      }
    }
  }

  return result;
}

export function normalizeAdvancedFilters(
  filters: Record<string, any>,
): Record<string, any> {
  const result: Record<string, any> = {};

  for (const [key, value] of Object.entries(filters)) {
    if (key === "AND" || key === "OR" || key === "NOT") {
      if (Array.isArray(value)) {
        result[key] = value.map(normalizeAdvancedFilters);
      } else {
        result[key] = value;
      }
    } else if (ENTITY_KEYS_CAMEL.has(key)) {
      const snakeKey = CAMEL_TO_SNAKE[key];
      if (isDefinedValue(value)) {
        result[snakeKey] = value;
      }
    } else if (ENTITY_KEYS_SNAKE.has(key)) {
      if (isDefinedValue(value)) {
        result[key] = value;
      }
    } else {
      if (isDefinedValue(value)) {
        result[key] = value;
      }
    }
  }

  return result;
}

function wrapGroup(parts: string[], sep: string): string {
  if (parts.length === 0) return "";
  if (parts.length === 1) return parts[0];
  return "(" + parts.join(sep) + ")";
}

export interface QdrantCondition {
  key: string;
  match?: { value?: any; any?: any[]; except?: any[]; text?: string };
  range?: {
    gte?: number | string;
    gt?: number | string;
    lte?: number | string;
    lt?: number | string;
  };
  is_empty?: { key: string; is_empty: boolean };
}

export interface QdrantFilter {
  must?: (QdrantCondition | QdrantFilter)[];
  must_not?: (QdrantCondition | QdrantFilter)[];
  should?: (QdrantCondition | QdrantFilter)[];
}

function buildQdrantFieldCondition(
  node: FieldCondition,
): QdrantCondition | null {
  switch (node.op) {
    case "eq":
      return { key: node.key, match: { value: node.value } };
    case "ne":
      return { key: node.key, match: { except: [node.value] } };
    case "in":
      return { key: node.key, match: { any: node.value } };
    case "nin":
      return { key: node.key, match: { except: node.value } };
    case "contains":
    case "icontains":
      return { key: node.key, match: { text: node.value } };
    case "gt":
    case "gte":
    case "lt":
    case "lte": {
      const range: Record<string, any> = {};
      range[node.op] = node.value;
      return { key: node.key, range };
    }
  }
  return null;
}

export function buildQdrantFilter(
  nodes: FilterNode[],
): QdrantFilter | undefined {
  if (nodes.length === 0) return undefined;

  const must: (QdrantCondition | QdrantFilter)[] = [];
  const should: (QdrantCondition | QdrantFilter)[] = [];
  const mustNot: (QdrantCondition | QdrantFilter)[] = [];

  for (const node of nodes) {
    switch (node.type) {
      case "field": {
        const cond = buildQdrantFieldCondition(node);
        if (cond) must.push(cond);
        break;
      }
      case "exists":
        break;
      case "and": {
        const built = buildQdrantFilter(node.children);
        if (built) must.push(built);
        break;
      }
      case "or": {
        for (const child of node.children) {
          const built = buildQdrantFilter([child]);
          if (built) should.push(built);
        }
        break;
      }
      case "not": {
        for (const child of node.children) {
          const built = buildQdrantFilter([child]);
          if (built) mustNot.push(built);
        }
        break;
      }
    }
  }

  if (must.length === 0 && should.length === 0 && mustNot.length === 0) {
    return undefined;
  }

  const result: QdrantFilter = {};
  if (must.length > 0) result.must = must;
  if (should.length > 0) result.should = should;
  if (mustNot.length > 0) result.must_not = mustNot;
  return result;
}

const OPERATOR_SQL_MAP: Record<
  FilterOp,
  { template: string; numeric: boolean }
> = {
  eq: { template: "payload->>'%KEY%' = $%IDX%", numeric: false },
  ne: { template: "payload->>'%KEY%' != $%IDX%", numeric: false },
  gt: { template: "(payload->>'%KEY%')::numeric > $%IDX%", numeric: true },
  gte: { template: "(payload->>'%KEY%')::numeric >= $%IDX%", numeric: true },
  lt: { template: "(payload->>'%KEY%')::numeric < $%IDX%", numeric: true },
  lte: { template: "(payload->>'%KEY%')::numeric <= $%IDX%", numeric: true },
  in: { template: "payload->>'%KEY%' = ANY($%IDX%::text[])", numeric: false },
  nin: {
    template: "NOT (payload->>'%KEY%' = ANY($%IDX%::text[]))",
    numeric: false,
  },
  contains: {
    template: "payload->>'%KEY%' LIKE $%IDX% ESCAPE '\\'",
    numeric: false,
  },
  icontains: {
    template: "payload->>'%KEY%' ILIKE $%IDX% ESCAPE '\\'",
    numeric: false,
  },
};

const SAFE_IDENTIFIER_RE = /^[a-zA-Z_][a-zA-Z0-9_]{0,127}$/;

function escapeFilterKey(key: string): string {
  if (!SAFE_IDENTIFIER_RE.test(key)) {
    throw new Error(
      `Invalid filter key '${key}': only letters, digits, and underscores are allowed.`,
    );
  }
  return key;
}

function processPGVectorField(
  node: FieldCondition,
  conditions: string[],
  values: any[],
  paramIndex: number,
): number {
  const safeKey = escapeFilterKey(node.key);
  const mapping = OPERATOR_SQL_MAP[node.op];
  if (!mapping) return paramIndex;

  const clause = mapping.template
    .replace("%KEY%", safeKey)
    .replace("%IDX%", String(paramIndex));
  conditions.push(clause);

  if (node.op === "in" || node.op === "nin") {
    values.push((node.value as any[]).map(String));
  } else if (node.op === "contains" || node.op === "icontains") {
    const escaped = String(node.value)
      .replace(/\\/g, "\\\\")
      .replace(/%/g, "\\%")
      .replace(/_/g, "\\_");
    values.push(`%${escaped}%`);
  } else if (mapping.numeric) {
    values.push(Number(node.value));
  } else {
    values.push(String(node.value));
  }
  return paramIndex + 1;
}

function processPGVectorGroup(
  children: FilterNode[],
  startIndex: number,
): { sql: string; values: any[]; nextIndex: number } | null {
  const conditions: string[] = [];
  const values: any[] = [];
  let pIdx = startIndex;

  for (const child of children) {
    const out = buildPGVectorRecursive(child, conditions, values, pIdx);
    pIdx = out;
  }

  if (conditions.length === 0) return null;
  return {
    sql: wrapGroup(conditions, " AND "),
    values,
    nextIndex: pIdx,
  };
}

function buildPGVectorRecursive(
  node: FilterNode,
  parentConditions: string[],
  parentValues: any[],
  paramIndex: number,
): number {
  switch (node.type) {
    case "field":
      return processPGVectorField(
        node,
        parentConditions,
        parentValues,
        paramIndex,
      );
    case "exists":
      parentConditions.push(`payload ? $${paramIndex}`);
      parentValues.push(node.key);
      return paramIndex + 1;
    case "and": {
      const group = processPGVectorGroup(node.children, paramIndex);
      if (group) {
        parentConditions.push(group.sql);
        parentValues.push(...group.values);
        return group.nextIndex;
      }
      return paramIndex;
    }
    case "or": {
      const orGroups: string[] = [];
      let pIdx = paramIndex;
      for (const child of node.children) {
        const subConds: string[] = [];
        const subVals: any[] = [];
        const sub = buildPGVectorRecursive(child, subConds, subVals, pIdx);
        if (subConds.length > 0) {
          orGroups.push(wrapGroup(subConds, " AND "));
          parentValues.push(...subVals);
          pIdx = sub;
        }
      }
      if (orGroups.length > 0) {
        parentConditions.push("(" + orGroups.join(" OR ") + ")");
      }
      return pIdx;
    }
    case "not": {
      const notGroups: string[] = [];
      let pIdx = paramIndex;
      for (const child of node.children) {
        const subConds: string[] = [];
        const subVals: any[] = [];
        const sub = buildPGVectorRecursive(child, subConds, subVals, pIdx);
        if (subConds.length > 0) {
          notGroups.push(wrapGroup(subConds, " AND "));
          parentValues.push(...subVals);
          pIdx = sub;
        }
      }
      if (notGroups.length > 0) {
        parentConditions.push("NOT (" + notGroups.join(" OR ") + ")");
      }
      return pIdx;
    }
  }
  return paramIndex;
}

export function buildPGVectorFilter(
  filters: Record<string, any> | undefined,
  startIndex: number,
): FilterResult {
  const conditions: string[] = [];
  const values: any[] = [];
  const nodes = parseFilters(filters);
  let pIdx = startIndex;

  for (const node of nodes) {
    pIdx = buildPGVectorRecursive(node, conditions, values, pIdx);
  }

  return { conditions, values, paramIndex: pIdx };
}

function matchFieldCondition(
  payload: Record<string, any>,
  node: FieldCondition,
): boolean {
  const payloadValue = payload[node.key];
  switch (node.op) {
    case "eq":
      return payloadValue === node.value;
    case "ne":
      return payloadValue !== node.value;
    case "gt":
      return payloadValue > node.value;
    case "gte":
      return payloadValue >= node.value;
    case "lt":
      return payloadValue < node.value;
    case "lte":
      return payloadValue <= node.value;
    case "in":
      return Array.isArray(node.value) && node.value.includes(payloadValue);
    case "nin":
      return !Array.isArray(node.value) || !node.value.includes(payloadValue);
    case "contains":
      return (
        typeof payloadValue === "string" && payloadValue.includes(node.value)
      );
    case "icontains":
      return (
        typeof payloadValue === "string" &&
        payloadValue.toLowerCase().includes(node.value.toLowerCase())
      );
  }
  return true;
}

export function matchMemoryStoreFilter(
  payload: Record<string, any>,
  nodes: FilterNode[],
): boolean {
  for (const node of nodes) {
    switch (node.type) {
      case "field":
        if (!matchFieldCondition(payload, node)) return false;
        break;
      case "exists":
        if (!(node.key in payload)) return false;
        break;
      case "and":
        if (!node.children.every((c) => matchMemoryStoreFilter(payload, [c])))
          return false;
        break;
      case "or":
        if (!node.children.some((c) => matchMemoryStoreFilter(payload, [c])))
          return false;
        break;
      case "not":
        if (node.children.some((c) => matchMemoryStoreFilter(payload, [c])))
          return false;
        break;
    }
  }
  return true;
}

export function buildSimpleEqualityFilter(
  filters: Record<string, any> | undefined,
): Record<string, any> {
  const result: Record<string, any> = {};
  const nodes = parseFilters(filters);

  for (const node of nodes) {
    if (node.type === "field" && node.op === "eq") {
      result[node.key] = node.value;
    }
  }
  return result;
}

export function buildAzureODataFilter(
  filters: Record<string, any> | undefined,
): string {
  const nodes = parseFilters(filters);
  const parts: string[] = [];

  for (const node of nodes) {
    if (node.type !== "field") continue;
    const sanitizedKey = node.key.replace(/[^\w]/g, "");
    if (node.op === "eq") {
      if (typeof node.value === "string") {
        const safeValue = node.value.replace(/'/g, "''");
        parts.push(`${sanitizedKey} eq '${safeValue}'`);
      } else {
        parts.push(`${sanitizedKey} eq ${node.value}`);
      }
    }
  }
  return parts.join(" and ");
}

export function buildRedisFilterExpr(
  filters: Record<string, any> | undefined,
  escapeValue: (v: unknown) => string,
): string {
  const nodes = parseFilters(filters);
  const parts: string[] = [];

  for (const node of nodes) {
    if (node.type !== "field") continue;
    if (node.op === "eq") {
      parts.push(`@${node.key}:{${escapeValue(node.value)}}`);
    }
  }
  return parts.length > 0 ? parts.join(" ") : "*";
}

export function buildSupabaseEqualityFilter(
  filters: Record<string, any> | undefined,
): Record<string, any> | undefined {
  const result = buildSimpleEqualityFilter(filters);
  return Object.keys(result).length > 0 ? result : undefined;
}
