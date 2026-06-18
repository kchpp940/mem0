const CAMEL_TO_SNAKE: Record<string, string> = {
  userId: "user_id",
  agentId: "agent_id",
  runId: "run_id",
};

const ENTITY_KEYS_SNAKE = new Set(["user_id", "agent_id", "run_id"]);
const ENTITY_KEYS_CAMEL = new Set(["userId", "agentId", "runId"]);

function isDefinedValue(value: unknown): boolean {
  return value !== undefined && value !== null;
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
