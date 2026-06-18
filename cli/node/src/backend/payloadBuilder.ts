/**
 * Shared payload builder for Platform API requests.
 *
 * Centralizes parameter normalization, validation, filter building, and payload
 * construction for add/search/list operations so Python and Node CLIs produce
 * identical request payloads with consistent error messages.
 */

import { printError } from "../branding.js";

export class ValidationError extends Error {
	constructor(message: string) {
		super(message);
		this.name = "ValidationError";
	}
}

export function normalizeCategories(
	raw: string | undefined,
): string[] | undefined {
	/**
	 * Parse categories from CLI input (JSON array or comma-separated string).
	 *
	 * @param raw - Raw categories string from CLI (e.g. '["work","personal"]' or 'work,personal')
	 * @returns List of category strings, or undefined if raw is undefined/empty.
	 * @throws ValidationError If JSON is provided but invalid.
	 */
	if (!raw) return undefined;
	try {
		const parsed = JSON.parse(raw);
		if (!Array.isArray(parsed)) {
			throw new ValidationError("--categories JSON must be an array.");
		}
		return parsed
			.map((c: unknown) => String(c).trim())
			.filter((c: string) => c);
	} catch {
		return raw
			.split(",")
			.map((c) => c.trim())
			.filter((c) => c);
	}
}

export function validateExpires(raw: string | undefined): string | undefined {
	/**
	 * Validate expires date format and ensure it's in the future.
	 *
	 * @param raw - Raw expires string from CLI (expected: YYYY-MM-DD)
	 * @returns Validated date string if provided.
	 * @throws ValidationError If format is invalid or date is not in the future.
	 */
	if (!raw) return undefined;
	if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
		throw new ValidationError(
			"Invalid date format for --expires. Use YYYY-MM-DD (e.g. 2025-12-31).",
		);
	}
	if (new Date(raw) <= new Date()) {
		throw new ValidationError("--expires date must be in the future.");
	}
	return raw;
}

export function parseFilterJson(
	raw: string | undefined,
): Record<string, unknown> | undefined {
	/**
	 * Parse JSON filter string from CLI.
	 *
	 * @param raw - Raw JSON filter string from --filter flag.
	 * @returns Parsed filter dict, or undefined if raw is undefined.
	 * @throws ValidationError If JSON is invalid.
	 */
	if (!raw) return undefined;
	try {
		const parsed = JSON.parse(raw);
		if (
			typeof parsed !== "object" ||
			Array.isArray(parsed) ||
			parsed === null
		) {
			throw new ValidationError("--filter must be a JSON object.");
		}
		return parsed as Record<string, unknown>;
	} catch (e) {
		if (e instanceof ValidationError) throw e;
		throw new ValidationError(`Invalid JSON in --filter: ${e}`);
	}
}

export function buildFilters(opts: {
	userId?: string;
	agentId?: string;
	appId?: string;
	runId?: string;
	extraFilters?: Record<string, unknown>;
}): Record<string, unknown> | undefined {
	/**
	 * Build a filters dict for v3 Platform API endpoints.
	 *
	 * Entity IDs are ANDed (all provided IDs must match). Extra filters (date
	 * ranges, categories) are also ANDed. If caller passes a pre-built filter
	 * structure (e.g. with AND/OR keys), it is returned as-is.
	 *
	 * @param opts.userId - User ID filter.
	 * @param opts.agentId - Agent ID filter.
	 * @param opts.appId - App ID filter.
	 * @param opts.runId - Run ID filter.
	 * @param opts.extraFilters - Additional filters to merge (e.g. from --filter flag).
	 * @returns Filter structure ready for API payload, or undefined if no filters.
	 */
	if (
		opts.extraFilters &&
		("AND" in opts.extraFilters || "OR" in opts.extraFilters)
	) {
		return opts.extraFilters;
	}

	const andConditions: Record<string, unknown>[] = [];
	if (opts.userId) andConditions.push({ user_id: opts.userId });
	if (opts.agentId) andConditions.push({ agent_id: opts.agentId });
	if (opts.appId) andConditions.push({ app_id: opts.appId });
	if (opts.runId) andConditions.push({ run_id: opts.runId });

	if (opts.extraFilters) {
		for (const [k, v] of Object.entries(opts.extraFilters)) {
			andConditions.push({ [k]: v });
		}
	}

	if (andConditions.length === 1) return andConditions[0];
	if (andConditions.length > 1) return { AND: andConditions };
	return undefined;
}

export function buildAddPayload(opts: {
	content?: string;
	messages?: Record<string, unknown>[];
	userId?: string;
	agentId?: string;
	appId?: string;
	runId?: string;
	metadata?: Record<string, unknown>;
	immutable?: boolean;
	infer?: boolean;
	expires?: string;
	categories?: string[];
}): Record<string, unknown> {
	/**
	 * Build payload for POST /v3/memories/add/.
	 *
	 * @param opts.content - Raw text content (wrapped in user message if no messages).
	 * @param opts.messages - Pre-constructed message array (takes precedence over content).
	 * @param opts.userId - User ID to attach.
	 * @param opts.agentId - Agent ID to attach.
	 * @param opts.appId - App ID to attach.
	 * @param opts.runId - Run ID to attach.
	 * @param opts.metadata - Metadata dict.
	 * @param opts.immutable - Whether memory is immutable.
	 * @param opts.infer - Whether to enable inference.
	 * @param opts.expires - Validated expiration date (YYYY-MM-DD).
	 * @param opts.categories - List of categories.
	 * @returns Complete add payload ready for the API.
	 */
	const payload: Record<string, unknown> = {};

	if (opts.messages) {
		payload.messages = opts.messages;
	} else if (opts.content) {
		payload.messages = [{ role: "user", content: opts.content }];
	}

	if (opts.userId) payload.user_id = opts.userId;
	if (opts.agentId) payload.agent_id = opts.agentId;
	if (opts.appId) payload.app_id = opts.appId;
	if (opts.runId) payload.run_id = opts.runId;
	if (opts.metadata) payload.metadata = opts.metadata;
	if (opts.immutable) payload.immutable = true;
	if (opts.infer === false) payload.infer = false;
	if (opts.expires) payload.expiration_date = opts.expires;
	if (opts.categories) payload.categories = opts.categories;
	payload.source = "CLI";

	return payload;
}

export function buildSearchPayload(
	query: string,
	opts: {
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
	},
): Record<string, unknown> {
	/**
	 * Build payload for POST /v3/memories/search/.
	 *
	 * @param query - Search query string.
	 * @param opts.userId - User ID filter.
	 * @param opts.agentId - Agent ID filter.
	 * @param opts.appId - App ID filter.
	 * @param opts.runId - Run ID filter.
	 * @param opts.topK - Number of results to return.
	 * @param opts.threshold - Minimum similarity threshold.
	 * @param opts.rerank - Whether to enable reranking.
	 * @param opts.keyword - Whether to use keyword search.
	 * @param opts.filters - Pre-built filters dict (from buildFilters()).
	 * @param opts.fields - List of fields to return.
	 * @returns Complete search payload ready for the API.
	 */
	const payload: Record<string, unknown> = {
		query,
		top_k: opts.topK ?? 10,
		threshold: opts.threshold ?? 0.3,
	};

	const apiFilters = buildFilters({
		userId: opts.userId,
		agentId: opts.agentId,
		appId: opts.appId,
		runId: opts.runId,
		extraFilters: opts.filters,
	});
	if (apiFilters) payload.filters = apiFilters;
	if (opts.rerank) payload.rerank = true;
	if (opts.keyword) payload.keyword_search = true;
	if (opts.fields) payload.fields = opts.fields;
	payload.source = "CLI";

	return payload;
}

export function buildListPayload(opts: {
	userId?: string;
	agentId?: string;
	appId?: string;
	runId?: string;
	category?: string;
	after?: string;
	before?: string;
}): {
	payload: Record<string, unknown>;
	params: Record<string, string>;
} {
	/**
	 * Build payload and query params for POST /v3/memories/.
	 *
	 * @param opts.userId - User ID filter.
	 * @param opts.agentId - Agent ID filter.
	 * @param opts.appId - App ID filter.
	 * @param opts.runId - Run ID filter.
	 * @param opts.category - Category filter (contains match).
	 * @param opts.after - Created-at lower bound (ISO date).
	 * @param opts.before - Created-at upper bound (ISO date).
	 * @returns Object containing payload and query params.
	 */
	const payload: Record<string, unknown> = {};
	const params: Record<string, string> = {};

	const extra: Record<string, unknown> = {};
	if (opts.category) {
		extra.categories = { contains: opts.category };
	}
	if (opts.after) {
		extra.created_at = {
			...(extra.created_at as Record<string, unknown> | undefined),
			gte: opts.after,
		};
	}
	if (opts.before) {
		extra.created_at = {
			...(extra.created_at as Record<string, unknown> | undefined),
			lte: opts.before,
		};
	}

	const apiFilters = buildFilters({
		userId: opts.userId,
		agentId: opts.agentId,
		appId: opts.appId,
		runId: opts.runId,
		extraFilters: Object.keys(extra).length > 0 ? extra : undefined,
	});
	if (apiFilters) payload.filters = apiFilters;
	payload.source = "CLI";

	return { payload, params };
}

export function handleValidationError(err: ValidationError): never {
	/**
	 * Print a validation error to stderr and exit.
	 *
	 * This provides a single exit point for validation errors so both CLIs show
	 * the same error formatting.
	 *
	 * @param err - The ValidationError to handle.
	 */
	printError(err.message);
	process.exit(1);
}
