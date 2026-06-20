/**
 * Canonical schema contract for memory operations.
 *
 * This module is the TypeScript counterpart to `mem0/schema/fields.py`.
 * All field names, defaults, validation rules, and name mappings are
 * derived from the shared contract so that Python and Node CLI backends
 * stay in sync automatically.
 *
 * The contract JSON file (`contract/payload_contract.json`) is the
 * machine-readable version consumed at runtime. This module re-exports
 * its values as typed constants for compile-time safety.
 */

import contract from "../contract/payload_contract.json" with { type: "json" };

export const ENTITY_FIELDS = contract.filterBuilding
	.entityOrder as readonly string[];

export const ENTITY_FIELD_SET = new Set(ENTITY_FIELDS);

export const FIELD_DEFAULTS = contract.defaults as {
	readonly top_k: number;
	readonly threshold: number;
	readonly infer: boolean;
	readonly immutable: boolean;
	readonly rerank: boolean;
	readonly keyword: boolean;
};

export const FIELD_MAPPING = contract.fieldMapping as Record<string, string>;

export const REVERSE_FIELD_MAPPING: Record<string, string> = Object.fromEntries(
	Object.entries(FIELD_MAPPING).map(([k, v]) => [v, k]),
);

export const CLI_TO_API_MAP: Record<string, string> = {
	userId: "user_id",
	agentId: "agent_id",
	appId: "app_id",
	runId: "run_id",
	topK: "top_k",
	pageSize: "page_size",
	filterJson: "filters",
};

export const API_TO_CLI_MAP: Record<string, string> = Object.fromEntries(
	Object.entries(CLI_TO_API_MAP).map(([k, v]) => [v, k]),
);

export const SCOPE_DISPLAY_NAMES: Record<string, string> = {
	user_id: "user",
	agent_id: "agent",
	app_id: "app",
	run_id: "run",
};

export const EXPIRES_PATTERN = contract.validation.expires.pattern;
export const EXPIRES_FORMAT_ERROR = contract.validation.expires.formatError;
export const EXPIRES_FUTURE_ERROR = contract.validation.expires.futureError;

export const VALIDATION_RULES = {
	top_k: { min: 1, error: "--top-k must be >= 1." },
	threshold: {
		min: 0,
		max: 1,
		error: "--threshold must be between 0.0 and 1.0.",
	},
	page: { min: 1, error: "--page must be >= 1." },
	pageSize: { min: 1, error: "--page-size must be >= 1." },
} as const;

export interface FieldSpec {
	readonly apiName: string;
	readonly cliName: string;
	readonly tsName: string;
	readonly default?: unknown;
	readonly description: string;
	readonly required: boolean;
	readonly apiAlias?: string;
}

export const ENTITY_FIELD_SPECS: readonly FieldSpec[] = [
	{
		apiName: "user_id",
		cliName: "user-id",
		tsName: "userId",
		description: "ID of the user",
		required: false,
	},
	{
		apiName: "agent_id",
		cliName: "agent-id",
		tsName: "agentId",
		description: "ID of the agent",
		required: false,
	},
	{
		apiName: "app_id",
		cliName: "app-id",
		tsName: "appId",
		description: "ID of the app",
		required: false,
	},
	{
		apiName: "run_id",
		cliName: "run-id",
		tsName: "runId",
		description: "ID of the run",
		required: false,
	},
];

export const ADD_FIELD_SPECS: readonly FieldSpec[] = [
	...ENTITY_FIELD_SPECS,
	{
		apiName: "metadata",
		cliName: "metadata",
		tsName: "metadata",
		description: "Additional metadata",
		required: false,
	},
	{
		apiName: "infer",
		cliName: "infer",
		tsName: "infer",
		default: FIELD_DEFAULTS.infer,
		description: "Whether to infer memories",
		required: false,
	},
	{
		apiName: "immutable",
		cliName: "immutable",
		tsName: "immutable",
		default: FIELD_DEFAULTS.immutable,
		description: "Mark memory as immutable",
		required: false,
	},
	{
		apiName: "expires",
		cliName: "expires",
		tsName: "expires",
		description: "Expiration date (YYYY-MM-DD)",
		required: false,
		apiAlias: "expiration_date",
	},
	{
		apiName: "categories",
		cliName: "categories",
		tsName: "categories",
		description: "Categories for classification",
		required: false,
	},
];

export const SEARCH_FIELD_SPECS: readonly FieldSpec[] = [
	...ENTITY_FIELD_SPECS,
	{
		apiName: "filters",
		cliName: "filter",
		tsName: "filters",
		description: "Filters for the search",
		required: false,
	},
	{
		apiName: "top_k",
		cliName: "top-k",
		tsName: "topK",
		default: FIELD_DEFAULTS.top_k,
		description: "Number of results to return",
		required: false,
	},
	{
		apiName: "threshold",
		cliName: "threshold",
		tsName: "threshold",
		default: FIELD_DEFAULTS.threshold,
		description: "Minimum similarity score",
		required: false,
	},
	{
		apiName: "rerank",
		cliName: "rerank",
		tsName: "rerank",
		default: FIELD_DEFAULTS.rerank,
		description: "Whether to rerank results",
		required: false,
	},
	{
		apiName: "keyword",
		cliName: "keyword",
		tsName: "keyword",
		default: FIELD_DEFAULTS.keyword,
		description: "Enable keyword search",
		required: false,
		apiAlias: "keyword_search",
	},
	{
		apiName: "fields",
		cliName: "fields",
		tsName: "fields",
		description: "Fields to include in response",
		required: false,
	},
];

export const LIST_FIELD_SPECS: readonly FieldSpec[] = [
	...ENTITY_FIELD_SPECS,
	{
		apiName: "page",
		cliName: "page",
		tsName: "page",
		default: 1,
		description: "Page number",
		required: false,
	},
	{
		apiName: "page_size",
		cliName: "page-size",
		tsName: "pageSize",
		default: 100,
		description: "Items per page",
		required: false,
	},
	{
		apiName: "category",
		cliName: "category",
		tsName: "category",
		description: "Filter by category",
		required: false,
	},
	{
		apiName: "after",
		cliName: "after",
		tsName: "after",
		description: "Filter created on or after",
		required: false,
	},
	{
		apiName: "before",
		cliName: "before",
		tsName: "before",
		description: "Filter created on or before",
		required: false,
	},
];

export const UPDATE_FIELD_SPECS: readonly FieldSpec[] = [
	{
		apiName: "text",
		cliName: "text",
		tsName: "text",
		description: "New text content",
		required: false,
	},
	{
		apiName: "metadata",
		cliName: "metadata",
		tsName: "metadata",
		description: "Updated metadata",
		required: false,
	},
];

export function getAddApiKey(fieldName: string): string {
	const spec = ADD_FIELD_SPECS.find((s) => s.apiName === fieldName);
	if (spec?.apiAlias) return spec.apiAlias;
	return FIELD_MAPPING[fieldName] ?? fieldName;
}

export function getSearchApiKey(fieldName: string): string {
	const spec = SEARCH_FIELD_SPECS.find((s) => s.apiName === fieldName);
	if (spec?.apiAlias) return spec.apiAlias;
	return FIELD_MAPPING[fieldName] ?? fieldName;
}

export function cliToApi(cliName: string): string {
	return CLI_TO_API_MAP[cliName] ?? cliName;
}

export function apiToCli(apiName: string): string {
	return API_TO_CLI_MAP[apiName] ?? apiName;
}

export function buildScopeDict(
	entityIds: Record<string, string | undefined>,
): Record<string, string> {
	const result: Record<string, string> = {};
	for (const [k, v] of Object.entries(entityIds)) {
		if (v && ENTITY_FIELD_SET.has(k)) {
			result[k] = v;
		}
	}
	return result;
}

export function buildScopeDisplay(
	entityIds: Record<string, string | undefined>,
): string {
	const parts: string[] = [];
	for (const [field, value] of Object.entries(entityIds)) {
		if (value && ENTITY_FIELD_SET.has(field)) {
			const displayName = SCOPE_DISPLAY_NAMES[field] ?? field;
			parts.push(`${displayName}=${value}`);
		}
	}
	return parts.length > 0 ? parts.join(", ") : "ALL entities";
}

export function validateExpires(expires: string): string {
	if (!new RegExp(EXPIRES_PATTERN).test(expires)) {
		throw new Error(EXPIRES_FORMAT_ERROR);
	}
	if (new Date(expires) <= new Date()) {
		throw new Error(EXPIRES_FUTURE_ERROR);
	}
	return expires;
}

export function validateField(
	name: keyof typeof VALIDATION_RULES,
	value: number,
): void {
	const rule = VALIDATION_RULES[name];
	if ("min" in rule && value < rule.min) {
		throw new Error(rule.error);
	}
	if ("max" in rule && value > rule.max) {
		throw new Error(rule.error);
	}
}

export interface AddOptions {
	userId?: string;
	agentId?: string;
	appId?: string;
	runId?: string;
	metadata?: Record<string, unknown>;
	immutable?: boolean;
	infer?: boolean;
	expires?: string;
	categories?: string[];
}

export interface SearchOptions {
	userId?: string;
	agentId?: string;
	appId?: string;
	runId?: string;
	topK?: number;
	threshold?: number;
	rerank?: boolean;
	keyword?: boolean;
	filters?: Record<string, unknown>;
	fields?: string[];
}

export interface ListOptions {
	userId?: string;
	agentId?: string;
	appId?: string;
	runId?: string;
	page?: number;
	pageSize?: number;
	category?: string;
	after?: string;
	before?: string;
}

export interface DeleteOptions {
	all?: boolean;
	userId?: string;
	agentId?: string;
	appId?: string;
	runId?: string;
}

export interface EntityIds {
	userId?: string;
	agentId?: string;
	appId?: string;
	runId?: string;
}

export interface Backend {
	add(
		content?: string,
		messages?: Record<string, unknown>[],
		opts?: AddOptions,
	): Promise<Record<string, unknown>>;

	search(
		query: string,
		opts?: SearchOptions,
	): Promise<Record<string, unknown>[]>;

	get(memoryId: string): Promise<Record<string, unknown>>;

	listMemories(opts?: ListOptions): Promise<Record<string, unknown>[]>;

	update(
		memoryId: string,
		content?: string,
		metadata?: Record<string, unknown>,
	): Promise<Record<string, unknown>>;

	delete(
		memoryId?: string,
		opts?: DeleteOptions,
	): Promise<Record<string, unknown>>;

	deleteEntities(opts: EntityIds): Promise<Record<string, unknown>>;

	ping(): Promise<Record<string, unknown>>;

	status(opts?: { userId?: string; agentId?: string }): Promise<
		Record<string, unknown>
	>;

	entities(entityType: string): Promise<Record<string, unknown>[]>;

	listEvents(): Promise<Record<string, unknown>[]>;

	getEvent(eventId: string): Promise<Record<string, unknown>>;
}
