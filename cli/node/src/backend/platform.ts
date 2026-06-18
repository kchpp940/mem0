/**
 * Platform (SaaS) backend — communicates with api.mem0.ai.
 */

import type { PlatformConfig } from "../config.js";
import { captureNotice, isAgentMode } from "../state.js";
import { CLI_VERSION } from "../version.js";
import {
	APIError,
	type AddOptions,
	AuthError,
	type Backend,
	type DeleteOptions,
	type EntityIds,
	type ListOptions,
	NotFoundError,
	type SearchOptions,
} from "./base.js";
import {
	buildAddPayload,
	buildFilters,
	buildListPayload,
	buildSearchPayload,
} from "./payloadBuilder.js";

export class PlatformBackend implements Backend {
	private baseUrl: string;
	private headers: Record<string, string>;

	constructor(config: PlatformConfig) {
		this.baseUrl = config.baseUrl.replace(/\/+$/, "");
		this.headers = {
			Authorization: `Token ${config.apiKey}`,
			"Content-Type": "application/json",
			"X-Mem0-Source": "cli",
			"X-Mem0-Client-Language": "node",
			"X-Mem0-Client-Version": CLI_VERSION,
		};
	}

	private async _request(
		method: string,
		path: string,
		opts?: { json?: unknown; params?: Record<string, string> },
	): Promise<unknown> {
		let url = `${this.baseUrl}${path}`;
		if (opts?.params) {
			const qs = new URLSearchParams(opts.params).toString();
			url += `?${qs}`;
		}

		const headers = {
			...this.headers,
			"X-Mem0-Caller-Type": isAgentMode() ? "agent" : "user",
		};

		const fetchOpts: RequestInit = {
			method,
			headers,
			signal: AbortSignal.timeout(30_000),
		};
		if (opts?.json) {
			fetchOpts.body = JSON.stringify(opts.json);
		}

		const resp = await fetch(url, fetchOpts);

		if (resp.status === 401) {
			throw new AuthError();
		}
		if (resp.status === 404) {
			throw new NotFoundError(path);
		}
		if (resp.status === 400) {
			let detail: string;
			try {
				const body = (await resp.json()) as Record<string, unknown>;
				detail =
					((body.detail ?? body.message ?? JSON.stringify(body)) as string) ??
					resp.statusText;
			} catch {
				detail = resp.statusText;
			}
			throw new APIError(path, detail);
		}
		if (!resp.ok) {
			let detail: string = resp.statusText;
			try {
				const body = (await resp.json()) as Record<string, unknown>;
				detail = (body.detail ?? body.message ?? resp.statusText) as string;
			} catch {
				/* ignore */
			}
			throw new Error(`HTTP ${resp.status}: ${detail}`);
		}
		if (resp.status === 204) {
			return {};
		}

		const data = await resp.json();

		// Pull the unclaimed-Agent-Mode notice out of the body (or the header
		// fallback for endpoints returning non-dict / non-dict-leading payloads)
		// and stash for end-of-command surfacing.
		let notice: string | null = null;
		if (
			data &&
			typeof data === "object" &&
			!Array.isArray(data) &&
			"mem0_notice" in data
		) {
			notice = (data as Record<string, unknown>).mem0_notice as string;
			// biome-ignore lint/performance/noDelete: intentional strip so downstream consumers don't see duplicate notice
			delete (data as Record<string, unknown>).mem0_notice;
		} else if (
			Array.isArray(data) &&
			data.length > 0 &&
			typeof data[0] === "object" &&
			data[0] !== null &&
			"mem0_notice" in data[0]
		) {
			notice = (data[0] as Record<string, unknown>).mem0_notice as string;
			// biome-ignore lint/performance/noDelete: see above.
			delete (data[0] as Record<string, unknown>).mem0_notice;
		}
		if (!notice) {
			notice = resp.headers.get("X-Mem0-Notice-Message") ?? null;
		}
		captureNotice(notice);

		return data;
	}

	async add(
		content?: string,
		messages?: Record<string, unknown>[],
		opts: AddOptions = {},
	): Promise<Record<string, unknown>> {
		const payload = buildAddPayload({
			content,
			messages,
			userId: opts.userId,
			agentId: opts.agentId,
			appId: opts.appId,
			runId: opts.runId,
			metadata: opts.metadata,
			immutable: opts.immutable,
			infer: opts.infer,
			expires: opts.expires,
			categories: opts.categories,
		});
		return (await this._request("POST", "/v3/memories/add/", {
			json: payload,
		})) as Record<string, unknown>;
	}

	private _buildFilters(opts: {
		userId?: string;
		agentId?: string;
		appId?: string;
		runId?: string;
		extraFilters?: Record<string, unknown>;
	}): Record<string, unknown> | undefined {
		/**
		 * Build a filters dict for v3 Platform API endpoints.
		 *
		 * Delegates to the shared payload builder to ensure consistency between
		 * Python and Node CLIs.
		 */
		return buildFilters(opts);
	}

	async search(
		query: string,
		opts: SearchOptions = {},
	): Promise<Record<string, unknown>[]> {
		const payload = buildSearchPayload(query, {
			userId: opts.userId,
			agentId: opts.agentId,
			appId: opts.appId,
			runId: opts.runId,
			topK: opts.topK,
			threshold: opts.threshold,
			rerank: opts.rerank,
			keyword: opts.keyword,
			filters: opts.filters,
			fields: opts.fields,
		});

		const result = (await this._request("POST", "/v3/memories/search/", {
			json: payload,
		})) as unknown;
		if (Array.isArray(result)) return result;
		const obj = result as Record<string, unknown>;
		return (obj.results ?? obj.memories ?? []) as Record<string, unknown>[];
	}

	async get(memoryId: string): Promise<Record<string, unknown>> {
		return (await this._request("GET", `/v1/memories/${memoryId}/`, {
			params: { source: "CLI" },
		})) as Record<string, unknown>;
	}

	async listMemories(
		opts: ListOptions = {},
	): Promise<Record<string, unknown>[]> {
		const { payload, params } = buildListPayload({
			userId: opts.userId,
			agentId: opts.agentId,
			appId: opts.appId,
			runId: opts.runId,
			category: opts.category,
			after: opts.after,
			before: opts.before,
		});
		params.page = String(opts.page ?? 1);
		params.page_size = String(opts.pageSize ?? 100);

		const result = (await this._request("POST", "/v3/memories/", {
			json: payload,
			params,
		})) as unknown;
		if (Array.isArray(result)) return result;
		const obj = result as Record<string, unknown>;
		return (obj.results ?? obj.memories ?? []) as Record<string, unknown>[];
	}

	async update(
		memoryId: string,
		content?: string,
		metadata?: Record<string, unknown>,
	): Promise<Record<string, unknown>> {
		const payload: Record<string, unknown> = {};
		if (content) payload.text = content;
		if (metadata) payload.metadata = metadata;
		payload.source = "CLI";
		return (await this._request("PUT", `/v1/memories/${memoryId}/`, {
			json: payload,
		})) as Record<string, unknown>;
	}

	async delete(
		memoryId?: string,
		opts: DeleteOptions = {},
	): Promise<Record<string, unknown>> {
		if (opts.all) {
			const params: Record<string, string> = { source: "CLI" };
			if (opts.userId) params.user_id = opts.userId;
			if (opts.agentId) params.agent_id = opts.agentId;
			if (opts.appId) params.app_id = opts.appId;
			if (opts.runId) params.run_id = opts.runId;
			return (await this._request("DELETE", "/v1/memories/", {
				params,
			})) as Record<string, unknown>;
		}
		if (memoryId) {
			return (await this._request("DELETE", `/v1/memories/${memoryId}/`, {
				params: { source: "CLI" },
			})) as Record<string, unknown>;
		}
		throw new Error("Either memoryId or --all is required");
	}

	async deleteEntities(opts: EntityIds): Promise<Record<string, unknown>> {
		// v2 endpoint: DELETE /v2/entities/{entity_type}/{entity_id}/
		const typeMap: [string, string | undefined][] = [
			["user", opts.userId],
			["agent", opts.agentId],
			["app", opts.appId],
			["run", opts.runId],
		];
		const entities = typeMap.filter(([, v]) => v) as [string, string][];
		if (entities.length === 0) {
			throw new Error("At least one entity ID is required for deleteEntities.");
		}
		// Delete each provided entity via the v2 path-based endpoint
		let result: Record<string, unknown> = {};
		for (const [entityType, entityId] of entities) {
			result = (await this._request(
				"DELETE",
				`/v2/entities/${entityType}/${entityId}/`,
				{ params: { source: "CLI" } },
			)) as Record<string, unknown>;
		}
		return result;
	}

	async ping(): Promise<Record<string, unknown>> {
		return (await this._request("GET", "/v1/ping/")) as Record<string, unknown>;
	}

	async status(
		opts: { userId?: string; agentId?: string } = {},
	): Promise<Record<string, unknown>> {
		try {
			await this.ping();
			return { connected: true, backend: "platform", base_url: this.baseUrl };
		} catch (e) {
			return {
				connected: false,
				backend: "platform",
				error: e instanceof Error ? e.message : String(e),
			};
		}
	}

	async entities(entityType: string): Promise<Record<string, unknown>[]> {
		const result = (await this._request("GET", "/v1/entities/")) as unknown;
		let items: Record<string, unknown>[];
		if (Array.isArray(result)) {
			items = result;
		} else {
			items = ((result as Record<string, unknown>).results ?? []) as Record<
				string,
				unknown
			>[];
		}

		const typeMap: Record<string, string> = {
			users: "user",
			agents: "agent",
			apps: "app",
			runs: "run",
		};
		const targetType = typeMap[entityType];
		if (targetType) {
			items = items.filter(
				(e) => (e.type as string | undefined)?.toLowerCase() === targetType,
			);
		}
		return items;
	}

	async listEvents(): Promise<Record<string, unknown>[]> {
		const result = (await this._request("GET", "/v1/events/")) as unknown;
		if (Array.isArray(result)) return result;
		return ((result as Record<string, unknown>).results ?? []) as Record<
			string,
			unknown
		>[];
	}

	async getEvent(eventId: string): Promise<Record<string, unknown>> {
		return (await this._request("GET", `/v1/event/${eventId}/`)) as Record<
			string,
			unknown
		>;
	}
}
