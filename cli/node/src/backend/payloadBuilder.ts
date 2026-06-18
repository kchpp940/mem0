/**
 * Contract-driven payload builder for Platform API requests.
 *
 * All field names, defaults, error messages, filter merge order, and PENDING
 * dedup rules are derived from the shared payload_contract.json so Python and
 * Node CLIs produce identical request payloads with consistent behaviour.
 */

import { printError } from "../branding.js";
import contractData from "../contract/payload_contract.json" with {
	type: "json",
};

const C = contractData as Record<string, unknown>;

function _validation(): Record<string, unknown> {
	return C.validation as Record<string, unknown>;
}

function _fieldMapping(): Record<string, string> {
	return C.fieldMapping as Record<string, string>;
}

function _filterBuilding(): Record<string, unknown> {
	return C.filterBuilding as Record<string, unknown>;
}

export function _pendingDedup(): Record<string, unknown> {
	return C.pendingDedup as Record<string, unknown>;
}

export function _agentPickFields(): Record<string, unknown> {
	return C.agentPickFields as Record<string, unknown>;
}

function _resolveApiName(fieldDef: Record<string, unknown>): string {
	const fromName = (fieldDef.from as string) ?? (fieldDef.api as string);
	if (fieldDef.mapped && fromName in _fieldMapping()) {
		return _fieldMapping()[fromName];
	}
	return fieldDef.api as string;
}

interface FieldDef {
	api: string;
	from?: string;
	type?: string;
	rule?: string;
	mapped?: boolean;
	literal?: unknown;
	hasDefault?: boolean;
	built?: boolean;
	required?: boolean;
}

export class ValidationError extends Error {
	constructor(message: string) {
		super(message);
		this.name = "ValidationError";
	}
}

export function normalizeCategories(
	raw: string | undefined,
): string[] | undefined {
	if (!raw) return undefined;
	const v = _validation().categories as Record<string, string>;
	try {
		const parsed = JSON.parse(raw);
		if (!Array.isArray(parsed)) {
			throw new ValidationError(v.arrayError);
		}
		return parsed
			.map((c: unknown) => String(c).trim())
			.filter((c: string) => c);
	} catch (e) {
		if (e instanceof ValidationError) throw e;
		return raw
			.split(",")
			.map((c) => c.trim())
			.filter((c) => c);
	}
}

export function validateExpires(raw: string | undefined): string | undefined {
	if (!raw) return undefined;
	const v = _validation().expires as Record<string, string>;
	if (!new RegExp(v.pattern).test(raw)) {
		throw new ValidationError(v.formatError);
	}
	if (new Date(raw) <= new Date()) {
		throw new ValidationError(v.futureError);
	}
	return raw;
}

export function parseFilterJson(
	raw: string | undefined,
): Record<string, unknown> | undefined {
	if (!raw) return undefined;
	const v = _validation().filters as Record<string, string>;
	try {
		const parsed = JSON.parse(raw);
		if (
			typeof parsed !== "object" ||
			Array.isArray(parsed) ||
			parsed === null
		) {
			throw new ValidationError(v.objectError);
		}
		return parsed as Record<string, unknown>;
	} catch (e) {
		if (e instanceof ValidationError) throw e;
		throw new ValidationError(v.jsonError.replace("{error}", String(e)));
	}
}

export function buildFilters(opts: {
	userId?: string;
	agentId?: string;
	appId?: string;
	runId?: string;
	extraFilters?: Record<string, unknown>;
}): Record<string, unknown> | undefined {
	const fb = _filterBuilding();

	if (opts.extraFilters) {
		for (const key of fb.passthroughKeys as string[]) {
			if (key in opts.extraFilters) {
				return opts.extraFilters;
			}
		}
	}

	const entityOrder = fb.entityOrder as string[];
	const entityValues: Record<string, string | undefined> = {
		user_id: opts.userId,
		agent_id: opts.agentId,
		app_id: opts.appId,
		run_id: opts.runId,
	};

	const andConditions: Record<string, unknown>[] = [];
	for (const fieldName of entityOrder) {
		const val = entityValues[fieldName];
		if (val) andConditions.push({ [fieldName]: val });
	}

	if (opts.extraFilters) {
		for (const [k, v] of Object.entries(opts.extraFilters)) {
			andConditions.push({ [k]: v });
		}
	}

	if (andConditions.length === 1) return andConditions[0];
	if (andConditions.length > 1)
		return { [fb.combineOperator as string]: andConditions };
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
	const payload: Record<string, unknown> = {};
	const source = C.source as string;
	const role = C.addMessageRole as string;

	const localVars: Record<string, unknown> = {
		messages: opts.messages,
		user_id: opts.userId,
		agent_id: opts.agentId,
		app_id: opts.appId,
		run_id: opts.runId,
		metadata: opts.metadata,
		immutable: opts.immutable,
		infer: opts.infer,
		expires: opts.expires,
		categories: opts.categories,
	};

	for (const fieldDef of C.addFields as FieldDef[]) {
		const apiName = _resolveApiName(
			fieldDef as unknown as Record<string, unknown>,
		);
		const fromName = fieldDef.from ?? "";

		if ("literal" in fieldDef && fieldDef.literal !== undefined) {
			payload[apiName] = fieldDef.literal;
			continue;
		}

		if (fieldDef.type === "messages_or_content") {
			if (opts.messages) {
				payload[apiName] = opts.messages;
			} else if (opts.content) {
				payload[apiName] = [{ role, content: opts.content }];
			}
			continue;
		}

		const value = localVars[fromName];
		if (value === undefined || value === null) continue;

		if (fieldDef.rule === "includeWhenTrue" && !value) continue;
		if (fieldDef.rule === "includeWhenFalse" && value) continue;

		payload[apiName] = value;
	}

	if (!("source" in payload)) payload.source = source;

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
	const defaults = C.defaults as Record<string, unknown>;
	const source = C.source as string;

	const payload: Record<string, unknown> = {
		query,
		top_k: opts.topK ?? defaults.top_k,
		threshold: opts.threshold ?? defaults.threshold,
	};

	const apiFilters = buildFilters({
		userId: opts.userId,
		agentId: opts.agentId,
		appId: opts.appId,
		runId: opts.runId,
		extraFilters: opts.filters,
	});
	if (apiFilters) payload.filters = apiFilters;

	const localVars: Record<string, unknown> = {
		rerank: opts.rerank,
		keyword: opts.keyword,
		fields: opts.fields,
	};

	for (const fieldDef of C.searchFields as FieldDef[]) {
		const apiName = _resolveApiName(
			fieldDef as unknown as Record<string, unknown>,
		);
		const fromName = fieldDef.from ?? "";

		if ("literal" in fieldDef && fieldDef.literal !== undefined) {
			payload[apiName] = fieldDef.literal;
			continue;
		}

		if (
			apiName in payload ||
			["query", "top_k", "threshold", "filters"].includes(fromName)
		)
			continue;

		const value = localVars[fromName];
		if (value === undefined || value === null) continue;

		if (fieldDef.rule === "includeWhenTrue" && !value) continue;
		if (fieldDef.rule === "includeWhenFalse" && value) continue;

		payload[apiName] = value;
	}

	if (!("source" in payload)) payload.source = source;

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
	const payload: Record<string, unknown> = {};
	const params: Record<string, string> = {};

	const listExtra = (_filterBuilding().listExtra ?? {}) as Record<
		string,
		Record<string, string>
	>;
	const extra: Record<string, unknown> = {};

	if (opts.category && "category" in listExtra) {
		const spec = listExtra.category;
		extra[spec.field] = { [spec.op]: opts.category };
	}

	const createdAtParts: Record<string, string> = {};
	if (opts.after && "after" in listExtra) {
		const spec = listExtra.after;
		createdAtParts[spec.op] = opts.after;
	}
	if (opts.before && "before" in listExtra) {
		const spec = listExtra.before;
		createdAtParts[spec.op] = opts.before;
	}
	if (Object.keys(createdAtParts).length > 0 && "after" in listExtra) {
		const spec = listExtra.after;
		extra[spec.field] = createdAtParts;
	}

	const apiFilters = buildFilters({
		userId: opts.userId,
		agentId: opts.agentId,
		appId: opts.appId,
		runId: opts.runId,
		extraFilters: Object.keys(extra).length > 0 ? extra : undefined,
	});
	if (apiFilters) payload.filters = apiFilters;
	payload.source = C.source;

	return { payload, params };
}

export function handleValidationError(err: ValidationError): never {
	printError(err.message);
	process.exit(1);
}
