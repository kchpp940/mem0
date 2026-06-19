/**
 * Memory CRUD commands: add, search, get, list, update, delete, import, export.
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import Table from "cli-table3";
import ora from "ora";
import type { Backend, BatchImportResponse } from "../backend/base.js";
import {
	colors,
	printError,
	printInfo,
	printScope,
	printSuccess,
	timedStatus,
} from "../branding.js";
import {
	formatAddResult,
	formatAgentEnvelope,
	formatJson,
	formatJsonEnvelope,
	formatMemoriesTable,
	formatMemoriesText,
	formatSingleMemory,
	printResultSummary,
} from "../output.js";
import { isAgentMode, setCurrentCommand } from "../state.js";

const { brand, accent, success, error: errorColor, dim } = colors;

/** True only when stdin is an actual pipe or file redirect — never in agent mode. */
function _stdinIsPiped(): boolean {
	if (isAgentMode()) return false;
	try {
		const stat = fs.fstatSync(0);
		return stat.isFIFO() || stat.isFile();
	} catch {
		return false;
	}
}

export async function cmdAdd(
	backend: Backend,
	text: string | undefined,
	opts: {
		userId?: string;
		agentId?: string;
		appId?: string;
		runId?: string;
		messages?: string;
		file?: string;
		metadata?: string;
		immutable: boolean;
		infer?: boolean;
		expires?: string;
		categories?: string;
		output: string;
	},
): Promise<void> {
	setCurrentCommand("add");
	let msgs: Record<string, unknown>[] | undefined;
	let content = text;

	// Read from file
	if (opts.file) {
		try {
			const raw = fs.readFileSync(opts.file, "utf-8");
			msgs = JSON.parse(raw);
		} catch (e) {
			printError(`Failed to read file: ${e instanceof Error ? e.message : e}`);
			process.exit(1);
		}
	}
	// Parse messages JSON
	else if (opts.messages) {
		try {
			msgs = JSON.parse(opts.messages);
		} catch (e) {
			printError(
				`Invalid JSON in --messages: ${e instanceof Error ? e.message : e}`,
			);
			process.exit(1);
		}
	}
	// Read from stdin only if stdin is an actual pipe or file redirect
	else if (!content && _stdinIsPiped()) {
		content = fs.readFileSync(0, "utf-8").trim();
	}

	if (content !== undefined && content.trim() === "") {
		printError("Content cannot be empty.");
		process.exit(1);
	}
	if (!content && !msgs) {
		printError(
			"No content provided. Pass text, --messages, --file, or pipe via stdin.",
		);
		process.exit(1);
	}

	// Validate --expires
	if (opts.expires) {
		if (!/^\d{4}-\d{2}-\d{2}$/.test(opts.expires)) {
			printError(
				"Invalid date format for --expires. Use YYYY-MM-DD (e.g. 2025-12-31).",
			);
			process.exit(1);
		}
		if (new Date(opts.expires) <= new Date()) {
			printError("--expires date must be in the future.");
			process.exit(1);
		}
	}

	let meta: Record<string, unknown> | undefined;
	if (opts.metadata) {
		try {
			meta = JSON.parse(opts.metadata);
		} catch {
			printError("Invalid JSON in --metadata.");
			process.exit(1);
		}
	}

	let cats: string[] | undefined;
	if (opts.categories) {
		try {
			cats = JSON.parse(opts.categories);
		} catch {
			cats = opts.categories.split(",").map((c) => c.trim());
		}
	}

	let result: Record<string, unknown>;
	try {
		result = await timedStatus("Adding memory...", async () => {
			return backend.add(content ?? undefined, msgs, {
				userId: opts.userId,
				agentId: opts.agentId,
				appId: opts.appId,
				runId: opts.runId,
				metadata: meta,
				immutable: opts.immutable,
				infer: opts.infer !== false,
				expires: opts.expires,
				categories: cats,
			});
		});
	} catch (e) {
		printError(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}

	if (opts.output === "quiet") return;

	// Deduplicate PENDING entries sharing the same event_id across all output modes
	const rawResults: Record<string, unknown>[] = Array.isArray(result)
		? result
		: ((result.results as Record<string, unknown>[]) ?? [result]);
	const seenEvents = new Set<string>();
	const deduped: Record<string, unknown>[] = [];
	for (const r of rawResults) {
		if (r.status === "PENDING") {
			const eid = (r.event_id as string) ?? "";
			if (eid && seenEvents.has(eid)) continue;
			if (eid) seenEvents.add(eid);
		}
		deduped.push(r);
	}
	// Write back so downstream formatters see deduplicated data
	const dedupedResult: Record<string, unknown> = Array.isArray(result)
		? (deduped as unknown as Record<string, unknown>)
		: { ...result, results: deduped };

	if (opts.output === "agent") {
		const scope: Record<string, string | undefined> = {
			user_id: opts.userId,
			agent_id: opts.agentId,
			app_id: opts.appId,
			run_id: opts.runId,
		};
		formatAgentEnvelope({
			command: "add",
			data: deduped,
			scope,
			count: deduped.length,
		});
		return;
	}

	if (opts.output === "json") {
		formatAddResult(dedupedResult, opts.output);
		return;
	}

	console.log();
	printScope({
		user_id: opts.userId,
		agent_id: opts.agentId,
		app_id: opts.appId,
		run_id: opts.runId,
	});
	const count = deduped.length;
	const allPending = count > 0 && deduped.every((r) => r.status === "PENDING");
	if (allPending) {
		printSuccess(
			`Memory queued — ${count} event${count !== 1 ? "s" : ""} pending`,
		);
	} else {
		printSuccess(
			`Memory processed — ${count} memor${count === 1 ? "y" : "ies"} extracted`,
		);
	}
	formatAddResult(dedupedResult, opts.output);
}

export async function cmdSearch(
	backend: Backend,
	query: string | undefined,
	opts: {
		userId?: string;
		agentId?: string;
		appId?: string;
		runId?: string;
		topK: number;
		threshold: number;
		rerank: boolean;
		keyword: boolean;
		filterJson?: string;
		fields?: string;
		output: string;
	},
): Promise<void> {
	setCurrentCommand("search");
	if (!query) {
		printError("No query provided. Pass a query argument or pipe via stdin.");
		process.exit(1);
	}

	let filters: Record<string, unknown> | undefined;
	if (opts.filterJson) {
		try {
			filters = JSON.parse(opts.filterJson);
		} catch {
			printError("Invalid JSON in --filter.");
			process.exit(1);
		}
	}

	const fieldList = opts.fields
		? opts.fields.split(",").map((f) => f.trim())
		: undefined;

	if (opts.topK < 1) {
		printError("--top-k must be >= 1.");
		process.exit(1);
	}
	if (opts.threshold < 0 || opts.threshold > 1) {
		printError("--threshold must be between 0.0 and 1.0.");
		process.exit(1);
	}

	const start = performance.now();
	let results: Record<string, unknown>[];
	try {
		results = await timedStatus("Searching memories...", async () => {
			// biome-ignore lint/style/noNonNullAssertion: guarded by process.exit above
			return backend.search(query!, {
				userId: opts.userId,
				agentId: opts.agentId,
				appId: opts.appId,
				runId: opts.runId,
				topK: opts.topK,
				threshold: opts.threshold,
				rerank: opts.rerank,
				keyword: opts.keyword,
				filters,
				fields: fieldList,
			});
		});
	} catch (e) {
		printError(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}
	const elapsed = (performance.now() - start) / 1000;

	if (opts.output === "quiet") return;

	if (opts.output === "agent") {
		const scope: Record<string, string | undefined> = {
			user_id: opts.userId,
			agent_id: opts.agentId,
			app_id: opts.appId,
			run_id: opts.runId,
		};
		formatAgentEnvelope({
			command: "search",
			data: results,
			scope,
			count: results.length,
			durationMs: Math.round(elapsed * 1000),
		});
		return;
	}

	if (opts.output === "json") {
		formatJson(results);
	} else if (opts.output === "table") {
		if (results.length > 0) {
			formatMemoriesTable(results, { showScore: true });
			printResultSummary({
				count: results.length,
				durationSecs: elapsed,
				scopeIds: { user_id: opts.userId, agent_id: opts.agentId },
			});
		} else {
			console.log();
			printInfo("No memories found matching your query.");
			console.log();
		}
	} else {
		if (results.length > 0) {
			formatMemoriesText(results);
			printResultSummary({
				count: results.length,
				durationSecs: elapsed,
				scopeIds: { user_id: opts.userId, agent_id: opts.agentId },
			});
		} else {
			console.log();
			printInfo("No memories found matching your query.");
			console.log();
		}
	}
}

export async function cmdGet(
	backend: Backend,
	memoryId: string,
	opts: { output: string },
): Promise<void> {
	setCurrentCommand("get");
	let result: Record<string, unknown>;
	try {
		result = await timedStatus("Fetching memory...", async () => {
			return backend.get(memoryId);
		});
	} catch (e) {
		printError(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}

	if (opts.output === "agent") {
		formatAgentEnvelope({ command: "get", data: result });
	} else {
		formatSingleMemory(result, opts.output);
	}
}

export async function cmdList(
	backend: Backend,
	opts: {
		userId?: string;
		agentId?: string;
		appId?: string;
		runId?: string;
		page: number;
		pageSize: number;
		category?: string;
		after?: string;
		before?: string;
		output: string;
	},
): Promise<void> {
	setCurrentCommand("list");
	if (opts.pageSize < 1) {
		printError("--page-size must be >= 1.");
		process.exit(1);
	}
	if (opts.page < 1) {
		printError("--page must be >= 1.");
		process.exit(1);
	}

	const start = performance.now();
	let results: Record<string, unknown>[];
	try {
		results = await timedStatus("Listing memories...", async () => {
			return backend.listMemories({
				userId: opts.userId,
				agentId: opts.agentId,
				appId: opts.appId,
				runId: opts.runId,
				page: opts.page,
				pageSize: opts.pageSize,
				category: opts.category,
				after: opts.after,
				before: opts.before,
			});
		});
	} catch (e) {
		printError(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}
	const elapsed = (performance.now() - start) / 1000;

	if (opts.output === "quiet") return;

	if (opts.output === "agent" || opts.output === "json") {
		const scope: Record<string, string | undefined> = {
			user_id: opts.userId,
			agent_id: opts.agentId,
			app_id: opts.appId,
			run_id: opts.runId,
		};
		formatAgentEnvelope({
			command: "list",
			data: results,
			scope,
			count: results.length,
			durationMs: Math.round(elapsed * 1000),
		});
	} else if (opts.output === "table") {
		if (results.length > 0) {
			formatMemoriesTable(results);
			printResultSummary({
				count: results.length,
				durationSecs: elapsed,
				page: opts.page,
				scopeIds: { user_id: opts.userId, agent_id: opts.agentId },
			});
		} else {
			console.log();
			printInfo("No memories found.");
			console.log();
		}
	} else {
		if (results.length > 0) {
			formatMemoriesText(results, "memories");
			printResultSummary({
				count: results.length,
				durationSecs: elapsed,
				page: opts.page,
				scopeIds: { user_id: opts.userId, agent_id: opts.agentId },
			});
		} else {
			console.log();
			printInfo("No memories found.");
			console.log();
		}
	}
}

export async function cmdUpdate(
	backend: Backend,
	memoryId: string,
	text: string | undefined,
	opts: { metadata?: string; output: string },
): Promise<void> {
	setCurrentCommand("update");
	let meta: Record<string, unknown> | undefined;
	if (opts.metadata) {
		try {
			meta = JSON.parse(opts.metadata);
		} catch {
			printError("Invalid JSON in --metadata.");
			process.exit(1);
		}
	}

	const start = performance.now();
	let result: Record<string, unknown>;
	try {
		result = await timedStatus("Updating memory...", async () => {
			return backend.update(memoryId, text, meta);
		});
	} catch (e) {
		printError(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}
	const elapsed = (performance.now() - start) / 1000;

	if (opts.output === "agent") {
		formatAgentEnvelope({
			command: "update",
			data: result,
			durationMs: Math.round(elapsed * 1000),
		});
	} else if (opts.output === "json") {
		formatJson(result);
	} else if (opts.output !== "quiet") {
		printSuccess(
			`Memory ${memoryId.slice(0, 8)} updated (${elapsed.toFixed(2)}s)`,
		);
	}
}

export async function cmdDelete(
	backend: Backend,
	memoryId: string,
	opts: { output: string; dryRun?: boolean; force?: boolean },
): Promise<void> {
	setCurrentCommand("delete");
	if (opts.dryRun) {
		let mem: Record<string, unknown>;
		try {
			mem = await backend.get(memoryId);
		} catch (e) {
			printError(e instanceof Error ? e.message : String(e));
			process.exit(1);
		}
		const text = (mem.memory ?? mem.text ?? "") as string;
		printInfo(`Would delete memory ${memoryId.slice(0, 8)}: ${text}`);
		printInfo("No changes made.");
		return;
	}

	const start = performance.now();
	let result: Record<string, unknown>;
	try {
		result = await timedStatus("Deleting...", async () => {
			return backend.delete(memoryId);
		});
	} catch (e) {
		printError(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}
	const elapsed = (performance.now() - start) / 1000;

	if (opts.output === "agent") {
		formatAgentEnvelope({
			command: "delete",
			data: { id: memoryId, deleted: true },
			durationMs: Math.round(elapsed * 1000),
		});
	} else if (opts.output === "json") {
		formatJson(result);
	} else if (opts.output !== "quiet") {
		printSuccess(
			`Memory ${memoryId.slice(0, 8)} deleted (${elapsed.toFixed(2)}s)`,
		);
	}
}

export async function cmdDeleteAll(
	backend: Backend,
	opts: {
		force: boolean;
		dryRun?: boolean;
		all?: boolean;
		userId?: string;
		agentId?: string;
		appId?: string;
		runId?: string;
		output: string;
	},
): Promise<void> {
	setCurrentCommand("delete-all");
	const { isAgentMode } = await import("../state.js");
	if (isAgentMode() && !opts.force) {
		printError("Destructive operation requires --force in agent mode.");
		process.exit(1);
	}
	if (opts.all) {
		// Project-wide wipe using wildcard entity IDs
		// Note: --dry-run is ignored here because the API has no count-before-delete endpoint.

		if (!opts.force) {
			const readline = await import("node:readline");
			const rl = readline.createInterface({
				input: process.stdin,
				output: process.stdout,
			});
			const answer = await new Promise<string>((resolve) => {
				rl.question(
					"\n  \u26a0  Delete ALL memories across the ENTIRE project? This cannot be undone. [y/N] ",
					resolve,
				);
			});
			rl.close();
			if (answer.toLowerCase() !== "y") {
				printInfo("Cancelled.");
				process.exit(0);
			}
		}

		const start = performance.now();
		let result: Record<string, unknown>;
		try {
			result = await timedStatus(
				"Deleting all memories project-wide...",
				async () => {
					return backend.delete(undefined, {
						all: true,
						userId: "*",
						agentId: "*",
						appId: "*",
						runId: "*",
					});
				},
			);
		} catch (e) {
			printError(e instanceof Error ? e.message : String(e));
			process.exit(1);
		}
		const elapsed = (performance.now() - start) / 1000;

		if (opts.output === "agent") {
			formatAgentEnvelope({
				command: "delete-all",
				data: result,
				durationMs: Math.round(elapsed * 1000),
			});
		} else if (opts.output === "json") {
			formatJson(result);
		} else if (opts.output !== "quiet") {
			if (result.message) {
				printInfo(
					"Deletion started. Memories will be removed in the background.",
				);
			} else {
				printSuccess(`All project memories deleted (${elapsed.toFixed(2)}s)`);
			}
		}
		return;
	}

	if (opts.dryRun) {
		let memories: Record<string, unknown>[];
		try {
			memories = await backend.listMemories({
				userId: opts.userId,
				agentId: opts.agentId,
				appId: opts.appId,
				runId: opts.runId,
			});
		} catch (e) {
			printError(e instanceof Error ? e.message : String(e));
			process.exit(1);
		}
		printInfo(`Would delete ${memories.length} memories.`);
		printInfo("No changes made.");
		return;
	}

	if (!opts.force) {
		const scopeParts: string[] = [];
		if (opts.userId) scopeParts.push(`user=${opts.userId}`);
		if (opts.agentId) scopeParts.push(`agent=${opts.agentId}`);
		if (opts.appId) scopeParts.push(`app=${opts.appId}`);
		if (opts.runId) scopeParts.push(`run=${opts.runId}`);
		const scope =
			scopeParts.length > 0 ? scopeParts.join(", ") : "ALL entities";

		const readline = await import("node:readline");
		const rl = readline.createInterface({
			input: process.stdin,
			output: process.stdout,
		});
		const answer = await new Promise<string>((resolve) => {
			rl.question(
				`\n  \u26a0  Delete ALL memories for ${scope}? This cannot be undone. [y/N] `,
				resolve,
			);
		});
		rl.close();
		if (answer.toLowerCase() !== "y") {
			printInfo("Cancelled.");
			process.exit(0);
		}
	}

	const start = performance.now();
	let result: Record<string, unknown>;
	try {
		result = await timedStatus("Deleting all memories...", async () => {
			return backend.delete(undefined, {
				all: true,
				userId: opts.userId,
				agentId: opts.agentId,
				appId: opts.appId,
				runId: opts.runId,
			});
		});
	} catch (e) {
		printError(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}
	const elapsed = (performance.now() - start) / 1000;

	if (opts.output === "agent") {
		formatAgentEnvelope({
			command: "delete-all",
			data: result,
			durationMs: Math.round(elapsed * 1000),
		});
	} else if (opts.output === "json") {
		formatJson(result);
	} else if (opts.output !== "quiet") {
		if (result.message) {
			printInfo(
				"Deletion started. Memories will be removed in the background.",
			);
		} else {
			printSuccess(`All matching memories deleted (${elapsed.toFixed(2)}s)`);
		}
	}
}

// ── Batch cache helpers ────────────────────────────────────────────────────

interface LastBatchCache {
	batch_id: string;
	cursor: number;
	total: number;
	file_path: string;
	user_id?: string;
	agent_id?: string;
	app_id?: string;
	run_id?: string;
	saved_at: string;
}

function _getBatchCacheDir(): string {
	return path.join(os.homedir(), ".mem0");
}

function _getLastBatchFile(): string {
	return path.join(_getBatchCacheDir(), "last_import_batch.json");
}

function _utcNowIso(): string {
	return new Date().toISOString();
}

function _saveLastBatch(cache: LastBatchCache): void {
	try {
		const dir = _getBatchCacheDir();
		if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
		fs.writeFileSync(_getLastBatchFile(), JSON.stringify(cache, null, 2), "utf-8");
	} catch {
		/* ignore write failures */
	}
}

function _loadLastBatch(): LastBatchCache | undefined {
	try {
		const file = _getLastBatchFile();
		if (!fs.existsSync(file)) return undefined;
		return JSON.parse(fs.readFileSync(file, "utf-8")) as LastBatchCache;
	} catch {
		return undefined;
	}
}

// ── Import / Export helpers ────────────────────────────────────────────────

function _parseFieldMap(fieldMapStr: string): Record<string, string> {
	const mapping: Record<string, string> = {};
	if (!fieldMapStr) return mapping;
	for (const pair of fieldMapStr.split(",")) {
		if (pair.includes("=")) {
			const [src, dst] = pair.split("=", 2);
			mapping[src.trim()] = dst.trim();
		}
	}
	return mapping;
}

function _applyFieldMap(
	item: Record<string, unknown>,
	fieldMap: Record<string, string>,
): Record<string, unknown> {
	if (!fieldMap || Object.keys(fieldMap).length === 0) return item;
	const mapped: Record<string, unknown> = { ...item };
	for (const [src, dst] of Object.entries(fieldMap)) {
		if (src in mapped && src !== dst) {
			mapped[dst] = mapped[src];
			delete mapped[src];
		}
	}
	return mapped;
}

function _readInputFile(
	filePath: string,
	formatHint?: string,
): Record<string, unknown>[] {
	const ext = formatHint
		? `.${formatHint.toLowerCase()}`
		: path.extname(filePath).toLowerCase();

	if (ext === ".jsonl") {
		const items: Record<string, unknown>[] = [];
		const lines = fs.readFileSync(filePath, "utf-8").split("\n");
		for (let i = 0; i < lines.length; i++) {
			const line = lines[i].trim();
			if (!line) continue;
			try {
				items.push(JSON.parse(line));
			} catch (e) {
				throw new Error(
					`Invalid JSONL at line ${i + 1}: ${e instanceof Error ? e.message : String(e)}`,
				);
			}
		}
		return items;
	}

	if (ext === ".csv") {
		const content = fs.readFileSync(filePath, "utf-8");
		const lines = content.split("\n").filter((l) => l.trim());
		if (lines.length === 0) return [];

		const headers = lines[0].split(",").map((h) => h.trim());
		const items: Record<string, unknown>[] = [];

		for (let i = 1; i < lines.length; i++) {
			const values = lines[i].split(",");
			const item: Record<string, unknown> = {};
			for (let j = 0; j < headers.length; j++) {
				item[headers[j]] = values[j]?.trim() ?? "";
			}
			items.push(item);
		}
		return items;
	}

	// Default: JSON
	try {
		const data = JSON.parse(fs.readFileSync(filePath, "utf-8"));
		return Array.isArray(data) ? data : [data];
	} catch (e) {
		throw new Error(
			`Invalid JSON: ${e instanceof Error ? e.message : String(e)}`,
		);
	}
}

function _normalizeImportItem(
	item: Record<string, unknown>,
	opts: {
		userId?: string;
		agentId?: string;
		appId?: string;
		runId?: string;
		category?: string;
		categories?: string[];
		metadata?: Record<string, unknown>;
	},
): Record<string, unknown> {
	const normalized: Record<string, unknown> = { ...item };

	if (opts.userId) normalized.user_id = opts.userId;
	if (opts.agentId) normalized.agent_id = opts.agentId;
	if (opts.appId) normalized.app_id = opts.appId;
	if (opts.runId) normalized.run_id = opts.runId;

	if (opts.category) {
		let cats: string[] = [];
		const existing = normalized.categories;
		if (typeof existing === "string") {
			cats = existing.split(",").map((c) => c.trim());
		} else if (Array.isArray(existing)) {
			cats = existing as string[];
		}
		if (!cats.includes(opts.category)) {
			cats.push(opts.category);
		}
		normalized.categories = cats;
	} else if (opts.categories) {
		normalized.categories = opts.categories;
	}

	if (opts.metadata) {
		let existingMeta: Record<string, unknown> = {};
		const em = normalized.metadata;
		if (em && typeof em === "object" && !Array.isArray(em)) {
			existingMeta = em as Record<string, unknown>;
		} else if (em !== undefined && em !== null) {
			existingMeta = { value: em };
		}
		normalized.metadata = { ...existingMeta, ...opts.metadata };
	}

	return normalized;
}

function _formatPreviewTable(
	items: Record<string, unknown>[],
	maxRows = 10,
): string {
	const table = new Table({
		head: [
			accent("#"),
			accent("Content"),
			accent("user_id"),
			accent("agent_id"),
			accent("categories"),
		],
		colWidths: [4, 50, 20, 20, 20],
		wordWrap: true,
		style: { head: [], border: [] },
	});

	for (let i = 0; i < Math.min(items.length, maxRows); i++) {
		const item = items[i];
		let content = (item.memory ?? item.text ?? item.content ?? "") as string;
		if (content.length > 47) content = `${content.slice(0, 47)}...`;
		const cats = item.categories;
		const catStr = Array.isArray(cats) ? cats.join(", ") : "";
		table.push([
			dim(String(i + 1)),
			content,
			String(item.user_id ?? ""),
			String(item.agent_id ?? ""),
			catStr,
		]);
	}

	if (items.length > maxRows) {
		table.push([
			"...",
			`... and ${items.length - maxRows} more rows`,
			"",
			"",
			"",
		]);
	}

	return table.toString();
}

// ── Import command ────────────────────────────────────────────────────────

export async function cmdImport(
	backend: Backend,
	filePath: string,
	opts: {
		userId?: string;
		agentId?: string;
		appId?: string;
		runId?: string;
		category?: string;
		categories?: string;
		fieldMap?: string;
		metadata?: string;
		format?: string;
		batchSize?: number;
		infer?: boolean;
		cursor?: number;
		batchId?: string;
		resume?: boolean;
		dryRun?: boolean;
		output: string;
	},
): Promise<void> {
	setCurrentCommand("import");

	if (!fs.existsSync(filePath)) {
		printError(`File not found: ${filePath}`);
		process.exit(1);
	}

	// Parse categories
	let catsList: string[] | undefined;
	if (opts.categories) {
		try {
			catsList = JSON.parse(opts.categories);
		} catch {
			catsList = opts.categories.split(",").map((c) => c.trim());
		}
	}

	// Parse metadata
	let metaDict: Record<string, unknown> | undefined;
	if (opts.metadata) {
		try {
			metaDict = JSON.parse(opts.metadata);
		} catch {
			printError("Invalid JSON in --metadata.");
			process.exit(1);
		}
	}

	// Parse field mapping
	const mapping = _parseFieldMap(opts.fieldMap ?? "");

	// Read input file
	let items: Record<string, unknown>[];
	try {
		items = _readInputFile(filePath, opts.format);
	} catch (e) {
		printError(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}

	const total = items.length;
	if (total === 0) {
		printInfo("No items to import.");
		return;
	}

	// Apply field mapping and normalization
	items = items.map((item) => _applyFieldMap(item, mapping));
	items = items.map((item) =>
		_normalizeImportItem(item, {
			userId: opts.userId,
			agentId: opts.agentId,
			appId: opts.appId,
			runId: opts.runId,
			category: opts.category,
			categories: catsList,
			metadata: metaDict,
		}),
	);

	// Dry-run preview
	if (opts.dryRun) {
		if (opts.output === "agent" || opts.output === "json") {
			const preview: Record<string, unknown> = {
				total,
				batch_size: opts.batchSize ?? 100,
				cursor: opts.cursor ?? 0,
				infer: opts.infer ?? true,
				field_map: mapping,
				items: items.slice(0, 10),
			};
			const scope: Record<string, string | undefined> = {
				user_id: opts.userId,
				agent_id: opts.agentId,
				app_id: opts.appId,
				run_id: opts.runId,
				category: opts.category,
			};
			formatAgentEnvelope({
				command: "import",
				data: preview,
				scope,
				count: total,
			});
			return;
		}

		console.log();
		console.log(brand("Import Preview (first 10 rows):"));
		console.log();
		console.log(_formatPreviewTable(items));
		console.log();
		printInfo(`Total items: ${total}`);
		printInfo(`Batch size: ${opts.batchSize ?? 100}`);
		if (Object.keys(mapping).length > 0) {
			printInfo(`Field mapping: ${JSON.stringify(mapping)}`);
		}
		printInfo("No changes made (dry run).");
		return;
	}

	// ── Resume logic: load from cache when --resume and no explicit cursor/batchId ──
	let effectiveCursor = opts.cursor ?? 0;
	let effectiveBatchId: string | undefined = opts.batchId;

	if (opts.resume) {
		const cached = _loadLastBatch();
		if (!opts.batchId && cached?.batch_id) {
			effectiveBatchId = cached.batch_id;
		}
		// Only fall back to cached cursor when user didn't pass --cursor explicitly
		if ((opts.cursor ?? 0) === 0 && cached) {
			effectiveCursor = cached.cursor ?? 0;
		}
		if (effectiveBatchId) {
			printInfo(`Resuming batch ${effectiveBatchId} from cursor ${effectiveCursor}`);
		} else if (effectiveCursor > 0) {
			printInfo(`Resuming from cursor: ${effectiveCursor}`);
		}
	}

	const start = performance.now();
	let totalSuccess = 0;
	let totalFailed = 0;
	const allSuccessful: BatchImportResponse["successful"] = [];
	const allFailed: BatchImportResponse["failed"] = [];
	let currentCursor = effectiveCursor;
	const batchSize = opts.batchSize ?? 100;
	let finalBatchId: string | undefined = effectiveBatchId;
	let lastResult: BatchImportResponse | undefined;

	const spinner = ora({
		text: dim(`Importing ${total} memories...`),
		color: "yellow",
		stream: process.stderr,
	}).start();

	try {
		while (currentCursor < total) {
			const batchEnd = Math.min(currentCursor + batchSize, total);
			const batchItems = items.slice(currentCursor, batchEnd);

			const result = await backend.batchImport(batchItems, {
				cursor: currentCursor,
				batchSize,
				infer: opts.infer,
				batchId: finalBatchId,
			});
			lastResult = result;
			if (!finalBatchId) finalBatchId = result.batchId;

			totalSuccess += result.successCount;
			totalFailed += result.failedCount;
			allSuccessful.push(...result.successful);
			allFailed.push(...result.failed);
			currentCursor = result.cursor;

			// Save cache after every successful batch for crash resumability
			_saveLastBatch({
				batch_id: finalBatchId,
				cursor: currentCursor,
				total,
				file_path: filePath,
				user_id: opts.userId,
				agent_id: opts.agentId,
				app_id: opts.appId,
				run_id: opts.runId,
				saved_at: _utcNowIso(),
			});

			const progress = Math.round((currentCursor / total) * 100);
			spinner.text = dim(
				`Importing... ${currentCursor}/${total} (${progress}%) · ${totalSuccess} ok · ${totalFailed} failed`,
			);
		}
	} catch (e) {
		spinner.stop();
		const msg = e instanceof Error ? e.message : String(e);
		printError(
			`Batch import failed at cursor ${currentCursor}${finalBatchId ? ` (batch ${finalBatchId})` : ""}: ${msg}`,
		);
		// Save cache so --resume can pick this up even after an exception
		if (finalBatchId) {
			_saveLastBatch({
				batch_id: finalBatchId,
				cursor: currentCursor,
				total,
				file_path: filePath,
				user_id: opts.userId,
				agent_id: opts.agentId,
				app_id: opts.appId,
				run_id: opts.runId,
				saved_at: _utcNowIso(),
			});
			printInfo(
				`To resume the SAME batch, run: mem0 import ${filePath} --resume --batch-id ${finalBatchId}`,
			);
		} else {
			printInfo(`To resume, run with --resume --cursor ${currentCursor}`);
		}
		process.exit(1);
	}

	spinner.stop();
	const elapsed = (performance.now() - start) / 1000;

	if (opts.output === "agent" || opts.output === "json") {
		const data: Record<string, unknown> = {
			batch_id: finalBatchId,
			total,
			processed: currentCursor,
			success_count: totalSuccess,
			failed_count: totalFailed,
			cursor: currentCursor,
			completed: currentCursor >= total,
			successful: allSuccessful,
			failed: allFailed,
		};
		const scope: Record<string, string | undefined> = {
			user_id: opts.userId,
			agent_id: opts.agentId,
			app_id: opts.appId,
			run_id: opts.runId,
		};
		formatAgentEnvelope({
			command: "import",
			data,
			scope,
			count: total,
			durationMs: Math.round(elapsed * 1000),
		});
		return;
	}

	console.log();
	printScope({
		user_id: opts.userId,
		agent_id: opts.agentId,
		app_id: opts.appId,
		run_id: opts.runId,
	});
	if (finalBatchId) printInfo(`Batch ID: ${finalBatchId}`);
	printSuccess(
		`Import complete — ${totalSuccess} succeeded, ${totalFailed} failed (${elapsed.toFixed(2)}s)`,
	);

	if (currentCursor < total) {
		if (finalBatchId) {
			printInfo(
				`To resume the SAME batch, run: mem0 import ${filePath} --resume --batch-id ${finalBatchId}`,
			);
		} else {
			printInfo(`To resume, run with --resume --cursor ${currentCursor}`);
		}
	}

	if (allFailed.length > 0) {
		console.log();
		console.log(`${errorColor("Failures:")}`);
		for (let i = 0; i < Math.min(allFailed.length, 10); i++) {
			const f = allFailed[i];
			const mem = (f.data?.memory ?? f.data?.text ?? "") as string;
			const memPreview = mem.slice(0, 50);
			console.log(`  ${dim(`#${f.index}:`)} ${f.error} — ${memPreview}...`);
		}
		if (allFailed.length > 10) {
			console.log(`  ${dim(`... and ${allFailed.length - 10} more`)}`);
		}
	}
}

// ── Export command ────────────────────────────────────────────────────────

export async function cmdExport(
	backend: Backend,
	outputFile: string,
	opts: {
		userId?: string;
		agentId?: string;
		appId?: string;
		runId?: string;
		category?: string;
		after?: string;
		before?: string;
		filterJson?: string;
		format?: string;
		output: string;
	},
): Promise<void> {
	setCurrentCommand("export");

	let filters: Record<string, unknown> | undefined;
	if (opts.filterJson) {
		try {
			filters = JSON.parse(opts.filterJson);
		} catch {
			printError("Invalid JSON in --filter.");
			process.exit(1);
		}
	}

	const start = performance.now();
	let exportData: string;
	try {
		exportData = await backend.exportMemories({
			userId: opts.userId,
			agentId: opts.agentId,
			appId: opts.appId,
			runId: opts.runId,
			category: opts.category,
			after: opts.after,
			before: opts.before,
			filters,
		});
	} catch (e) {
		printError(`Export failed: ${e instanceof Error ? e.message : String(e)}`);
		process.exit(1);
	}

	const elapsed = (performance.now() - start) / 1000;

	// Count exported items
	const count = exportData
		.trim()
		.split("\n")
		.filter((l) => l.trim()).length;

	// Write to file
	try {
		fs.writeFileSync(outputFile, exportData, "utf-8");
	} catch (e) {
		printError(
			`Failed to write output file: ${e instanceof Error ? e.message : String(e)}`,
		);
		process.exit(1);
	}

	if (opts.output === "agent" || opts.output === "json") {
		const data: Record<string, unknown> = {
			file: outputFile,
			count,
			format: opts.format ?? "jsonl",
		};
		const scope: Record<string, string | undefined> = {
			user_id: opts.userId,
			agent_id: opts.agentId,
			app_id: opts.appId,
			run_id: opts.runId,
			category: opts.category,
		};
		formatAgentEnvelope({
			command: "export",
			data,
			scope,
			count,
			durationMs: Math.round(elapsed * 1000),
		});
		return;
	}

	console.log();
	printScope({
		user_id: opts.userId,
		agent_id: opts.agentId,
		app_id: opts.appId,
		run_id: opts.runId,
	});
	printSuccess(
		`Exported ${count} memories to ${outputFile} (${elapsed.toFixed(2)}s)`,
	);
}

// ── Import status command ─────────────────────────────────────────────────

export async function cmdImportStatus(
	backend: Backend,
	batchIdArg: string | undefined,
	opts: { output: string },
): Promise<void> {
	setCurrentCommand("import-status");

	let effectiveBatchId = batchIdArg;
	if (!effectiveBatchId) {
		const cached = _loadLastBatch();
		if (cached?.batch_id) {
			effectiveBatchId = cached.batch_id;
		} else {
			printError(
				"No batch_id provided and no cached import found.",
				"Pass a batch_id as argument, or run a batch import first.",
			);
			process.exit(1);
		}
	}

	let status: BatchImportResponse;
	try {
		status = await timedStatus(`Fetching status for ${effectiveBatchId}...`, async () =>
			backend.getBatchStatus(effectiveBatchId!),
		);
	} catch (e) {
		printError(
			`Failed to fetch batch status: ${e instanceof Error ? e.message : String(e)}`,
		);
		process.exit(1);
	}

	if (opts.output === "agent" || opts.output === "json") {
		formatAgentEnvelope({
			command: "import-status",
			data: {
				batch_id: status.batchId,
				total: status.total,
				processed: status.processed,
				success_count: status.successCount,
				failed_count: status.failedCount,
				cursor: status.cursor,
				completed: status.completed,
				successful: status.successful,
				failed: status.failed,
			},
		});
		return;
	}

	const cached = _loadLastBatch();

	console.log();
	console.log(brand(`Batch Import Status: ${status.batchId}`));
	console.log();

	const statusTable = new Table({
		head: [accent("Field"), accent("Value")],
		style: { head: [], border: [] },
		wordWrap: true,
	});
	statusTable.push(["Batch ID", status.batchId]);
	statusTable.push(["Total", String(status.total)]);
	statusTable.push(["Processed", String(status.processed)]);
	statusTable.push([
		success("Succeeded"),
		success(String(status.successCount)),
	]);
	statusTable.push([
		errorColor("Failed"),
		errorColor(String(status.failedCount)),
	]);
	statusTable.push(["Cursor", String(status.cursor)]);
	const pct = status.total > 0 ? Math.round((status.processed / status.total) * 100) : 0;
	statusTable.push(["Progress", `${status.processed}/${status.total} (${pct}%)`]);
	statusTable.push([
		"Completed",
		status.completed ? success("Yes") : accent("No (in progress)"),
	]);
	if (cached?.saved_at) statusTable.push(["Cached at", cached.saved_at]);
	if (cached?.file_path) statusTable.push(["Source file", cached.file_path]);

	console.log(statusTable.toString());

	if (!status.completed) {
		const fileHint = cached?.file_path ? ` ${cached.file_path}` : "";
		console.log();
		printInfo(
			`To resume this batch: mem0 import${fileHint} --resume --batch-id ${status.batchId}`,
		);
	}

	if (status.failed.length > 0) {
		console.log();
		console.log(`${errorColor("Failed Items:")}`);
		console.log();
		const failTable = new Table({
			head: [accent("#"), accent("Error"), accent("Preview")],
			colWidths: [6, 40, 50],
			style: { head: [], border: [] },
			wordWrap: true,
		});
		for (let i = 0; i < Math.min(status.failed.length, 10); i++) {
			const f = status.failed[i];
			const mem = (f.data?.memory ?? f.data?.text ?? "") as string;
			const preview = mem.length > 47 ? `${mem.slice(0, 47)}...` : mem;
			failTable.push([dim(String(f.index)), f.error, preview]);
		}
		console.log(failTable.toString());
		if (status.failed.length > 10) {
			console.log(dim(`  ... and ${status.failed.length - 10} more failures`));
		}
	}
	console.log();
}
