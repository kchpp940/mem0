// AUTO-GENERATED FILE — DO NOT EDIT DIRECTLY
// Generated from mem0/schema/ (Python single source of truth)
// Run `python -m mem0.schema.generator --output cli/node/src/schema/` to regenerate


// ─── Entity identifiers ───────────────────────────────────────────────
/** Canonical entity identifier field names (snake_case, API format). */
export const ENTITY_FIELDS: readonly string[] = ["user_id", "agent_id", "app_id", "run_id"] as const;

// ─── CLI ↔ API name mappings ────────────────────────────────────────
/** Map from TypeScript/CLI camelCase field names to API snake_case names. */
export const CLI_TO_API_MAP = {
  "userId": "user_id",
  "agentId": "agent_id",
  "appId": "app_id",
  "runId": "run_id",
  "topK": "top_k",
  "pageSize": "page_size",
  "filterJson": "filters",
  "feedbackReason": "feedback_reason",
  "memoryExportId": "memory_export_id",
  "exportInstructions": "export_instructions",
  "startDate": "start_date",
  "endDate": "end_date",
} as const;

/** Reverse map from API snake_case field names to TypeScript/CLI camelCase names. */
export const API_TO_CLI_MAP = {
  "user_id": "userId",
  "agent_id": "agentId",
  "app_id": "appId",
  "run_id": "runId",
  "top_k": "topK",
  "page_size": "pageSize",
  "filters": "filterJson",
  "feedback_reason": "feedbackReason",
  "memory_export_id": "memoryExportId",
  "export_instructions": "exportInstructions",
  "start_date": "startDate",
  "end_date": "endDate",
} as const;

// ─── Default values ──────────────────────────────────────────────────
/** Default values for optional memory operation parameters. */
export const FIELD_DEFAULTS = {
  "top_k": 10,
  "threshold": 0.3,
  "page": 1,
  "page_size": 100,
  "infer": true,
  "rerank": false,
  "keyword": false,
  "immutable": false,
} as const;

// ─── Expires validation ──────────────────────────────────────────────
/** Regular expression for validating expires date format (YYYY-MM-DD). */
export const EXPIRES_PATTERN = /\d{4}-\d{2}-\d{2}/;

/** Human-readable display format for expires date validation errors. */
export const EXPIRES_FORMAT_DISPLAY = "YYYY-MM-DD";

/** Error message for invalid expires date format. */
export const EXPIRES_FORMAT_ERROR = "Invalid date format for --expires. Use YYYY-MM-DD (e.g. 2025-12-31).";

// ─── Validation rules ───────────────────────────────────────────────
/** Validation rules for numeric fields (min/max and error messages). Keys are CLI option names (camelCase). */
export const VALIDATION_RULES = {
  "topK": {"min": 1, "error": "--top-k must be >= 1."},
  "threshold": {"min": 0.0, "max": 1.0, "error": "--threshold must be between 0.0 and 1.0."},
  "page": {"min": 1, "error": "--page must be >= 1."},
  "pageSize": {"min": 1, "error": "--page-size must be >= 1."},
} as const;

// ─── API field aliases ──────────────────────────────────────────────
/** Field name aliases for add-memory API payloads (logical name → payload key). */
export const ADD_API_FIELD_MAP = {
  "expires": "expiration_date",
  "keyword": "keyword_search",
} as const;

/** Field name aliases for search API payloads (logical name → payload key). */
export const SEARCH_API_FIELD_MAP = {
  "keyword": "keyword_search",
} as const;

// ─── Scope display names ────────────────────────────────────────────
/** Human-readable display names for entity scope fields. */
export const SCOPE_DISPLAY_NAMES = {
  "user_id": "user",
  "agent_id": "agent",
  "app_id": "app",
  "run_id": "run",
} as const;

// ─── Response / payload field classification ────────────────────────
/** Core payload keys that are always present and map to top-level response fields. */
export const CORE_PAYLOAD_KEYS: readonly string[] = ["data", "hash", "created_at", "updated_at", "id", "text_lemmatized", "attributed_to", "expires_at", "ttl_source", "ttl_state"] as const;

/** Payload keys that should be promoted to top-level response fields (not nested under metadata). */
export const PROMOTED_PAYLOAD_KEYS: readonly string[] = ["user_id", "agent_id", "run_id", "actor_id", "role", "categories", "feedback_status", "operation_id"] as const;

// ─── Memory response field order ────────────────────────────────────
/** Canonical field ordering for memory response objects. */
export const MEMORY_RESPONSE_FIELDS: readonly string[] = ["id", "memory", "hash", "user_id", "agent_id", "run_id", "actor_id", "role", "categories", "created_at", "updated_at", "expires_at", "ttl_state", "ttl_source", "score", "feedback_status", "operation_id", "metadata"] as const;

// ─── History response fields ────────────────────────────────────────
/** Canonical field ordering for history response objects. */
export const HISTORY_RESPONSE_FIELDS: readonly string[] = ["id", "memory_id", "old_memory", "new_memory", "event", "created_at", "updated_at", "is_deleted", "actor_id", "role"] as const;

// ─── Feedback values ────────────────────────────────────────────────
/** Allowed feedback values. */
export const FEEDBACK_VALUES: readonly string[] = ["POSITIVE", "NEGATIVE", "VERY_NEGATIVE"] as const;

// ─── Export / Import ───────────────────────────────────────────────
/** Fields related to memory export operations. */
export const EXPORT_FIELDS: readonly string[] = ["schema", "filters", "export_instructions"] as const;

/** Fields related to memory import operations. */
export const IMPORT_FIELDS: readonly string[] = ["data", "format", "mode"] as const;

// ─── CLI option interfaces ────────────────────────────────────────
/** Entity identifier fields used for scoping operations. */
export interface EntityIds {
  /** ID of the user */

  userId?: string;
  /** ID of the agent */

  agentId?: string;
  /** ID of the app */

  appId?: string;
  /** ID of the run */

  runId?: string;
}

/** Options for the memory add command. */
export interface AddOptions {
  /** ID of the user */

  userId?: string;
  /** ID of the agent */

  agentId?: string;
  /** ID of the app */

  appId?: string;
  /** ID of the run */

  runId?: string;
  /** Additional metadata for the memory */

  metadata?: Record<string, any>;
  /** Whether to infer memories from the input */

  infer?: boolean;
  /** Mark memory as immutable */

  immutable?: boolean;
  /** Expiration date (YYYY-MM-DD) */

  expires?: string;
  /** Categories for memory classification */

  categories?: string[];
  /** Custom categories for memory classification */

  customCategories?: Record<string, any>[];
  /** Custom instructions for fact extraction */

  customInstructions?: string;
  /** Type of memory (e.g. procedural_memory) */

  memoryType?: string;
  /** Custom prompt for fact extraction */

  prompt?: string;
}

/** Options for the memory search command. */
export interface SearchOptions {
  /** ID of the user */

  userId?: string;
  /** ID of the agent */

  agentId?: string;
  /** ID of the app */

  appId?: string;
  /** ID of the run */

  runId?: string;
  /** Filters for the search */

  filters?: Record<string, any>;
  /** Number of results to return */

  topK?: number;
  /** Minimum similarity score */

  threshold?: number;
  /** Whether to rerank results */

  rerank?: boolean;
  /** Enable keyword search */

  keyword?: boolean;
  /** Fields to include in response */

  fields?: string[];
  /** Categories to filter by */

  categories?: string[];
  /** Include score details */

  explain?: boolean;
}

/** Options for the memory list command. */
export interface ListOptions {
  /** ID of the user */

  userId?: string;
  /** ID of the agent */

  agentId?: string;
  /** ID of the app */

  appId?: string;
  /** ID of the run */

  runId?: string;
  /** Filters for retrieval */

  filters?: Record<string, any>;
  /** Page number */

  page?: number;
  /** Items per page */

  pageSize?: number;
  /** Categories to filter by */

  categories?: string[];
  /** Filter memories created on or after (ISO 8601) */

  startDate?: string;
  /** Filter memories created on or before (ISO 8601) */

  endDate?: string;
}

/** Options for the memory delete-all command. */
export interface DeleteOptions {
  /** ID of the user */

  userId?: string;
  /** ID of the agent */

  agentId?: string;
  /** ID of the app */

  appId?: string;
  /** ID of the run */

  runId?: string;
}

// ─── Helper functions ──────────────────────────────────────────────

/**
 * Map a TypeScript/CLI camelCase field name to an API snake_case name.
 * @param cliName The camelCase field name
 * @returns The snake_case API field name
 */
export function cliToApi(cliName: string): string {
  return (CLI_TO_API_MAP as Record<string, string>)[cliName] ?? cliName;
}

/**
 * Map an API snake_case field name to a TypeScript/CLI camelCase name.
 * @param apiName The snake_case API field name
 * @returns The camelCase field name
 */
export function apiToCli(apiName: string): string {
  return (API_TO_CLI_MAP as Record<string, string>)[apiName] ?? apiName;
}

/**
 * Get the API payload key for an add-memory field (handles aliases like expires → expiration_date).
 * @param fieldName The logical field name
 * @returns The key to use in the API payload
 */
export function getAddApiKey(fieldName: string): string {
  return (ADD_API_FIELD_MAP as Record<string, string>)[fieldName] ?? fieldName;
}

/**
 * Get the API payload key for a search field (handles aliases like keyword → keyword_search).
 * @param fieldName The logical field name
 * @returns The key to use in the API payload
 */
export function getSearchApiKey(fieldName: string): string {
  return (SEARCH_API_FIELD_MAP as Record<string, string>)[fieldName] ?? fieldName;
}

/**
 * Build a scope display string from entity IDs (e.g. "user=alice, agent=bot").
 * @param entityIds Object with entity ID values
 * @returns Human-readable scope string
 */
export function buildScopeDisplay(entityIds: Record<string, string | null | undefined>): string {
  const parts: string[] = [];
  for (const field of ENTITY_FIELDS) {
    const value = entityIds[field];
    if (value) {
      const displayName = (SCOPE_DISPLAY_NAMES as Record<string, string>)[field] ?? field;
      parts.push(`${displayName}=${value}`);
    }
  }
  return parts.length > 0 ? parts.join(", ") : "ALL entities";
}

/**
 * Validate an expires date string (format and future check).
 * @param expires Date string in YYYY-MM-DD format
 * @returns The validated date string
 * @throws Error if the date is invalid or in the past
 */
export function validateExpires(expires: string): string {
  if (!EXPIRES_PATTERN.test(expires)) {
    throw new Error(EXPIRES_FORMAT_ERROR);
  }
  const date = new Date(expires);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  if (date <= today) {
    throw new Error("--expires date must be in the future.");
  }
  return expires;
}

/**
 * Validate that a feedback value is one of the allowed values.
 * @param feedback The feedback value to validate
 * @returns The uppercased feedback value if valid
 * @throws Error if the feedback value is not valid
 */
export function validateFeedbackValue(feedback: string): string {
  const upper = feedback.toUpperCase();
  if (!(FEEDBACK_VALUES as readonly string[]).includes(upper)) {
    throw new Error(
      `Invalid feedback value '${feedback}'. ` +
      `Must be one of: ${FEEDBACK_VALUES.join(", ")}.`
    );
  }
  return upper;
}
