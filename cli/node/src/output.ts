/**
 * Output rendering for mem0 CLI — text, JSON, table, quiet, agent modes.
 *
 * This module centralizes all output formatting and rendering logic.
 * Formatting rules follow the shared CLI contract in `cli/cli-spec.json`
 * and `src/contract/payload_contract.json`.
 */

import boxen from "boxen";
import Table from "cli-table3";
import { colors, sym } from "./branding.js";
import { takeNotice } from "./state.js";
import contract from "./contract/payload_contract.json" with { type: "json" };

const { brand, accent, success, error: errorColor, dim } = colors;

const sanitization = (contract as Record<string, unknown>).agentSanitization as Record<string, unknown> || {};
const batchStatus = (contract as Record<string, unknown>).batchStatus as Record<string, unknown> || {};

function pluralize(template: string, count: number): string {
	let result = template.replace("{count}", String(count));
	result = result.replaceAll("{s}", count === 1 ? "" : "s");

	result = result.replace(/\{([^}]+)\/([^}]+)\}/g, (_match, singular: string, plural: string) =>
		count === 1 ? singular : plural,
	);
	return result;
}

function formatDate(dtStr?: string): string | undefined {
	if (!dtStr) return undefined;
	try {
		const dt = new Date(dtStr.replace("Z", "+00:00"));
		return dt.toISOString().slice(0, 10);
	} catch {
		return dtStr?.slice(0, 10);
	}
}

export function formatMemoriesText(
	memories: Record<string, unknown>[],
	title = "memories",
): void {
	const count = memories.length;
	console.log(`\n${brand(`Found ${count} ${title}:`)}\n`);

	for (let i = 0; i < memories.length; i++) {
		const mem = memories[i];
		const memoryText = (mem.memory ?? mem.text ?? "") as string;
		const memId = ((mem.id as string) ?? "").slice(0, 8);
		const score = mem.score as number | undefined;
		const created = formatDate(mem.created_at as string | undefined);
		let category: string | undefined;
		const cats = mem.categories;
		if (Array.isArray(cats)) {
			category = cats[0] as string | undefined;
		}

		console.log(`  ${i + 1}. ${memoryText}`);

		const details: string[] = [];
		if (score !== undefined) details.push(`Score: ${score.toFixed(2)}`);
		if (memId) details.push(`ID: ${memId}`);
		if (created) details.push(`Created: ${created}`);
		if (category) details.push(`Category: ${category}`);

		if (details.length > 0) {
			console.log(`     ${dim(details.join(" · "))}`);
		}
		console.log();
	}
}

export function formatMemoriesTable(
	memories: Record<string, unknown>[],
	opts: { showScore?: boolean } = {},
): void {
	const head = opts.showScore
		? [
				accent("ID"),
				accent("Score"),
				accent("Memory"),
				accent("Category"),
				accent("Created"),
			]
		: [accent("ID"), accent("Memory"), accent("Category"), accent("Created")];
	const colWidths = opts.showScore ? [38, 8, 40, 16, 14] : [38, 40, 16, 14];
	const table = new Table({
		head,
		colWidths,
		wordWrap: true,
		style: { head: [], border: [] },
	});

	for (const mem of memories) {
		const memId = (mem.id as string) ?? "";
		let memoryText = (mem.memory ?? mem.text ?? "") as string;
		if (memoryText.length > 60) {
			memoryText = `${memoryText.slice(0, 57)}...`;
		}
		const categories = mem.categories;
		const cat =
			Array.isArray(categories) && categories.length > 0
				? categories.length > 1
					? `${categories[0]} (+${categories.length - 1})`
					: (categories[0] as string)
				: "—";
		const created = formatDate(mem.created_at as string | undefined) ?? "—";
		if (opts.showScore) {
			const score = mem.score as number | undefined;
			const scoreStr = score !== undefined ? score.toFixed(2) : "—";
			table.push([dim(memId), scoreStr, memoryText, cat, created]);
		} else {
			table.push([dim(memId), memoryText, cat, created]);
		}
	}

	console.log();
	console.log(table.toString());
	console.log();
}

export function formatJson(data: unknown): void {
	console.log(JSON.stringify(data, null, 2));
}

export function formatSingleMemory(
	mem: Record<string, unknown>,
	output = "text",
): void {
	if (output === "json") {
		formatJson(mem);
		return;
	}

	const memoryText = (mem.memory ?? mem.text ?? "") as string;
	const memId = (mem.id ?? "") as string;

	const lines: string[] = [];
	lines.push(`  ${memoryText}`);
	lines.push("");

	if (memId) lines.push(`  ${dim("ID:")}         ${memId}`);
	const created = formatDate(mem.created_at as string | undefined);
	if (created) lines.push(`  ${dim("Created:")}    ${created}`);
	const updated = formatDate(mem.updated_at as string | undefined);
	if (updated) lines.push(`  ${dim("Updated:")}    ${updated}`);
	const meta = mem.metadata;
	if (meta) lines.push(`  ${dim("Metadata:")}   ${JSON.stringify(meta)}`);
	const categories = mem.categories;
	if (categories) {
		const catStr = Array.isArray(categories)
			? categories.join(", ")
			: String(categories);
		lines.push(`  ${dim("Categories:")} ${catStr}`);
	}

	const content = lines.join("\n");
	console.log();
	console.log(
		boxen(content, {
			title: brand("Memory"),
			titleAlignment: "left",
			borderColor: "magenta",
			padding: 1,
		}),
	);
	console.log();
}

export function formatAddResult(
	result: Record<string, unknown> | Record<string, unknown>[],
	output = "text",
): void {
	if (output === "json") {
		formatJson(result);
		return;
	}
	if (output === "quiet") return;

	const results: Record<string, unknown>[] = Array.isArray(result)
		? result
		: ((result.results as Record<string, unknown>[]) ?? [result]);

	if (!results.length) {
		console.log(`  ${dim("No memories extracted.")}`);
		return;
	}

	console.log();
	const seenPendingEvents = new Set<string>();
	for (const r of results) {
		// Detect async PENDING response
		if (r.status === "PENDING") {
			const eventId = (r.event_id as string) ?? "";
			// Deduplicate PENDING entries with the same event_id
			if (eventId && seenPendingEvents.has(eventId)) continue;
			if (eventId) seenPendingEvents.add(eventId);
			const icon = accent(sym("⧗", "..."));
			const parts = [
				`  ${icon} ${dim("Queued".padEnd(10))}`,
				"Processing in background",
			];
			console.log(parts.join("  "));
			if (eventId) {
				console.log(`  ${dim(`  event_id: ${eventId}`)}`);
				console.log(
					`  ${dim(`  → Check status: mem0 event status ${eventId}`)}`,
				);
			}
			continue;
		}

		const event = (r.event ?? "ADD") as string;
		const memory = (r.memory ?? r.text ?? r.content ?? r.data ?? "") as string;
		const memId = ((r.id as string) ?? (r.memory_id as string) ?? "").slice(
			0,
			8,
		);

		let icon: string;
		let label: string;
		if (event === "ADD") {
			icon = success("+");
			label = "Added";
		} else if (event === "UPDATE") {
			icon = accent("~");
			label = "Updated";
		} else if (event === "DELETE") {
			icon = errorColor("-");
			label = "Deleted";
		} else if (event === "NOOP") {
			icon = dim("·");
			label = "No change";
		} else {
			icon = dim("?");
			label = event;
		}

		const parts = [`  ${icon} ${dim(label.padEnd(10))}`];
		if (memory) parts.push(memory);
		if (memId) parts.push(dim(`(${memId})`));
		console.log(parts.join("  "));
	}
	console.log();
}

export function formatJsonEnvelope(opts: {
	command: string;
	data: unknown;
	durationMs?: number;
	scope?: Record<string, string | undefined>;
	count?: number;
	status?: string;
	error?: string;
}): void {
	const envelope: Record<string, unknown> = {
		status: opts.status ?? "success",
		command: opts.command,
	};
	if (opts.durationMs !== undefined) envelope.duration_ms = opts.durationMs;
	if (opts.scope !== undefined) envelope.scope = opts.scope;
	if (opts.count !== undefined) envelope.count = opts.count;
	if (opts.error) envelope.error = opts.error;
	envelope.data = opts.data;

	// If the platform flagged this as an unclaimed Agent Mode account, surface
	// the notice inside the JSON envelope so an agent consuming the output
	// sees it without needing to inspect HTTP headers.
	// eslint-disable-next-line @typescript-eslint/no-require-imports
	const { takeNotice } = require("./state.js");
	const notice = takeNotice();
	if (notice) envelope.mem0_notice = notice;

	console.log(JSON.stringify(envelope, null, 2));
}

function pick(
	obj: Record<string, unknown>,
	keys: string[],
): Record<string, unknown> {
	const result: Record<string, unknown> = {};
	for (const key of keys) {
		if (key in obj) result[key] = obj[key];
	}
	return result;
}

export function sanitizeAgentData(command: string, data: unknown): unknown {
	if (data === null || data === undefined) return data;

	switch (command) {
		case "add": {
			const items = Array.isArray(data) ? data : [data];
			return items.map((item) => {
				const r = item as Record<string, unknown>;
				if (r.status === "PENDING") return pick(r, ["status", "event_id"]);
				return pick(r, ["id", "memory", "event"]);
			});
		}
		case "search":
			return (data as Record<string, unknown>[]).map((r) =>
				pick(r, ["id", "memory", "score", "created_at", "categories"]),
			);
		case "list":
			return (data as Record<string, unknown>[]).map((r) =>
				pick(r, ["id", "memory", "created_at", "categories"]),
			);
		case "get": {
			const r = data as Record<string, unknown>;
			return pick(r, [
				"id",
				"memory",
				"created_at",
				"updated_at",
				"categories",
				"metadata",
			]);
		}
		case "update": {
			const r = data as Record<string, unknown>;
			return pick(r, ["id", "memory"]);
		}
		case "delete":
		case "delete-all":
		case "entity delete":
			return data;
		case "entity list":
			return (data as Record<string, unknown>[]).map((r) => ({
				name: (r.name ?? r.id) as string,
				...pick(r, ["type", "count"]),
			}));
		case "event list":
			return (data as Record<string, unknown>[]).map((r) =>
				pick(r, ["id", "event_type", "status", "latency", "created_at"]),
			);
		case "event status": {
			const ev = data as Record<string, unknown>;
			const rawResults =
				(ev.results as Record<string, unknown>[] | undefined) ?? [];
			const sanitizedResults = rawResults.map((r) => {
				const nested = r.data as Record<string, unknown> | undefined;
				return {
					id: r.id,
					event: r.event,
					user_id: r.user_id,
					memory: nested?.memory ?? null,
				};
			});
			return {
				...pick(ev, [
					"id",
					"event_type",
					"status",
					"latency",
					"created_at",
					"updated_at",
				]),
				results: sanitizedResults,
			};
		}
		default:
			return data;
	}
}

export function formatAgentEnvelope(opts: {
	command: string;
	data: unknown;
	durationMs?: number;
	scope?: Record<string, string | undefined>;
	count?: number;
}): void {
	const envelope: Record<string, unknown> = {
		status: "success",
		command: opts.command,
	};
	if (opts.durationMs !== undefined) envelope.duration_ms = opts.durationMs;
	if (opts.scope) {
		const filtered = Object.fromEntries(
			Object.entries(opts.scope).filter(([, v]) => v),
		);
		if (Object.keys(filtered).length > 0) envelope.scope = filtered;
	}
	if (opts.count !== undefined) envelope.count = opts.count;
	envelope.data = sanitizeAgentData(opts.command, opts.data);

	// Surface the unclaimed-Agent-Mode notice (if any) in the envelope so an
	// agent reading the JSON output sees it without inspecting HTTP headers.
	const notice = takeNotice();
	if (notice) envelope.mem0_notice = notice;

	console.log(JSON.stringify(envelope, null, 2));
}

export function printResultSummary(opts: {
	count: number;
	durationSecs?: number;
	page?: number;
	scopeIds?: Record<string, string | undefined>;
}): void {
	const parts = [`${opts.count} result${opts.count !== 1 ? "s" : ""}`];
	if (opts.page !== undefined) parts.push(`page ${opts.page}`);
	if (opts.scopeIds) {
		const scopeParts = Object.entries(opts.scopeIds)
			.filter(([, v]) => v)
			.map(([k, v]) => `${k}=${v}`);
		if (scopeParts.length > 0) parts.push(scopeParts.join(", "));
	}
	if (opts.durationSecs !== undefined)
		parts.push(`${opts.durationSecs.toFixed(2)}s`);

	console.log(`  ${dim(parts.join(" · "))}`);
	console.log();
}

export interface OutputRendererOptions {
	outputFormat?: string;
	command?: string;
	scope?: Record<string, string> | null;
}

export class OutputRenderer {
	private outputFormat: string;
	private command: string;
	private scope: Record<string, string> | null;
	private durationMs: number | null = null;

	constructor(opts: OutputRendererOptions = {}) {
		this.outputFormat = opts.outputFormat ?? "text";
		this.command = opts.command ?? "";
		this.scope = opts.scope ?? null;
	}

	setDuration(ms: number): void;
	setDuration(opts: { ms?: number; seconds?: number }): void;
	setDuration(value: number | { ms?: number; seconds?: number }): void {
		if (typeof value === "number") {
			this.durationMs = value;
		} else {
			if (value.ms !== undefined) {
				this.durationMs = value.ms;
			} else if (value.seconds !== undefined) {
				this.durationMs = Math.floor(value.seconds * 1000);
			}
		}
	}

	private buildEnvelope(opts: {
		data: unknown;
		status?: string;
		error?: string;
		count?: number;
	}): Record<string, unknown> {
		const envelope: Record<string, unknown> = {
			status: opts.status ?? "success",
			command: this.command,
		};
		if (this.durationMs !== null) envelope.duration_ms = this.durationMs;
		if (this.scope && Object.keys(this.scope).length > 0) {
			const filtered = Object.fromEntries(
				Object.entries(this.scope).filter(([, v]) => v),
			);
			if (Object.keys(filtered).length > 0) envelope.scope = filtered;
		}
		if (opts.count !== undefined) envelope.count = opts.count;
		if (opts.error) envelope.error = opts.error;
		envelope.data = opts.data;

		const notice = takeNotice();
		if (notice) envelope.mem0_notice = notice;

		return envelope;
	}

	private sanitize(data: unknown): unknown {
		return sanitizeAgentData(this.command, data);
	}

	memoryList(
		memories: Record<string, unknown>[],
		opts: { title?: string; showScore?: boolean; page?: number } = {},
	): void {
		const count = memories.length;
		const fmt = this.outputFormat;

		if (fmt === "json") {
			const envelope = this.buildEnvelope({ data: memories, count });
			console.log(JSON.stringify(envelope, null, 2));
			return;
		}

		if (fmt === "agent") {
			const sanitized = this.sanitize(memories);
			const envelope = this.buildEnvelope({ data: sanitized, count });
			console.log(JSON.stringify(envelope, null, 2));
			return;
		}

		if (fmt === "quiet") {
			for (const m of memories) {
				console.log((m.id as string) ?? "");
			}
			return;
		}

		if (fmt === "table") {
			formatMemoriesTable(memories, { showScore: opts.showScore });
		} else {
			formatMemoriesText(memories, opts.title);
		}

		printResultSummary({
			count,
			durationSecs: this.durationMs !== null ? this.durationMs / 1000 : undefined,
			page: opts.page,
			scopeIds: this.scope ?? undefined,
		});
	}

	singleMemory(mem: Record<string, unknown>): void {
		const fmt = this.outputFormat;

		if (fmt === "json") {
			const envelope = this.buildEnvelope({ data: mem });
			console.log(JSON.stringify(envelope, null, 2));
			return;
		}

		if (fmt === "agent") {
			const sanitized = this.sanitize(mem);
			const envelope = this.buildEnvelope({ data: sanitized });
			console.log(JSON.stringify(envelope, null, 2));
			return;
		}

		if (fmt === "quiet") {
			console.log((mem.id as string) ?? "");
			return;
		}

		formatSingleMemory(mem, fmt);
	}

	addResult(results: Record<string, unknown>[] | Record<string, unknown>): void {
		const fmt = this.outputFormat;
		const resultList = Array.isArray(results) ? results : [results];
		const count = resultList.length;

		if (fmt === "json") {
			const envelope = this.buildEnvelope({ data: results, count });
			console.log(JSON.stringify(envelope, null, 2));
			return;
		}

		if (fmt === "agent") {
			const sanitized = this.sanitize(results);
			const envelope = this.buildEnvelope({ data: sanitized, count });
			console.log(JSON.stringify(envelope, null, 2));
			return;
		}

		if (fmt === "quiet") return;

		this.renderAddText(resultList);
	}

	private renderAddText(results: Record<string, unknown>[]): void {
		const addConfig = batchStatus.add as Record<string, unknown> || {};
		const statuses = addConfig.statuses as Record<string, Record<string, string>> || {};

		console.log();

		const seenIds = new Set<string>();

		for (const r of results) {
			const status = r.status as string | undefined;
			const event = (r.event as string) ?? "ADD";

			if (status === "PENDING") {
				const eventId = (r.event_id as string) ?? "";
				if (eventId && seenIds.has(eventId)) continue;
				if (eventId) seenIds.add(eventId);

				const statusInfo = statuses.PENDING || {};
				const iconChar = statusInfo.icon || "⧗";
				const label = statusInfo.label || "Queued";

				const icon = accent(sym(iconChar, "..."));
				const parts = [
					`  ${icon} ${dim(label.padEnd(10))}`,
					"Processing in background",
				];
				console.log(parts.join("  "));
				if (eventId) {
					console.log(`  ${dim(`  event_id: ${eventId}`)}`);
					console.log(
						`  ${dim(`  → Check status: mem0 event status ${eventId}`)}`,
					);
				}
				continue;
			}

			const statusInfo = statuses[event] || {};
			const iconChar = statusInfo.icon || "?";
			const label = statusInfo.label || event;
			const color = statusInfo.color || "dim";

			const colorMap: Record<string, (s: string) => string> = {
				success,
				accent,
				error: errorColor,
				dim,
			};
			const iconStyle = colorMap[color] || dim;

			const memory = (r.memory ?? r.text ?? r.content ?? r.data ?? "") as string;
			const memId = ((r.id as string) ?? (r.memory_id as string) ?? "").slice(0, 8);

			const parts = [`  ${iconStyle(iconChar)} ${dim(label.padEnd(10))}`];
			if (memory) parts.push(memory);
			if (memId) parts.push(dim(`(${memId})`));
			console.log(parts.join("  "));
		}

		console.log();
	}

	data(data: unknown, opts: { count?: number } = {}): void {
		const fmt = this.outputFormat;

		if (fmt === "json") {
			const envelope = this.buildEnvelope({ data, count: opts.count });
			console.log(JSON.stringify(envelope, null, 2));
			return;
		}

		if (fmt === "agent") {
			const sanitized = this.sanitize(data);
			const envelope = this.buildEnvelope({ data: sanitized, count: opts.count });
			console.log(JSON.stringify(envelope, null, 2));
			return;
		}

		if (fmt === "quiet") {
			if (data && typeof data === "object") {
				console.log(JSON.stringify(data));
			} else {
				console.log(String(data));
			}
			return;
		}

		if (data && typeof data === "object") {
			formatJson(data);
		} else {
			console.log(String(data));
		}
	}

	error(message: string, opts: { errorCode?: string } = {}): void {
		const fmt = this.outputFormat;

		if (fmt === "json" || fmt === "agent") {
			const envelope: Record<string, unknown> = {
				status: "error",
				command: this.command,
				error: message,
				data: null,
			};
			if (opts.errorCode) envelope.error_code = opts.errorCode;
			console.log(JSON.stringify(envelope, null, 2));
			return;
		}

		console.error(`${errorColor("✗ Error:")} ${message}`);
	}
}
