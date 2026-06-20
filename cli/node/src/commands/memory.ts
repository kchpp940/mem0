/**
 * Memory CRUD commands: add, search, get, list, update, delete.
 */

import fs from "node:fs";
import type { Backend } from "../backend/base.js";
import { PlatformBackend } from "../backend/platform.js";
import {
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

const TRACE_META_KEYS = [
	"count",
	"operation",
	"memories_added",
	"memories_updated",
	"memories_skipped",
	"duplicates_skipped",
	"entities_extracted",
	"entities_linked",
	"candidates_ranked",
	"candidates_passed_threshold",
	"semantic_candidates",
	"keyword_candidates",
	"entity_matches",
	"results_returned",
	"results_filtered",
	"has_bm25",
	"has_entity_boost",
	"threshold",
	"mode",
	"last_messages_count",
	"existing_memories",
] as const;

function formatCompactTrace(
	operationId: string | null | undefined,
	trace: Record<string, unknown> | null | undefined,
): string {
	const opIdShort = operationId ? operationId.slice(0, 8) : "?";

	if (!trace) {
		return `\x1b[2m[trace] op=\x1b[0m\x1b[1m\x1b[36m${opIdShort}\x1b[0m\x1b[2m \u00b7 stages=0 \u00b7 no_trace_data\x1b[0m`;
	}

	const stages = (trace.stages ?? []) as Record<string, unknown>[];
	const totalMs = (trace.total_duration_ms ?? 0) as number;

	let out = `\x1b[2m[trace] op=\x1b[0m\x1b[1m\x1b[36m${opIdShort}\x1b[0m\x1b[2m \u00b7 total=${Math.round(totalMs)}ms \u00b7 stages=${stages.length}\x1b[0m`;

	for (const s of stages) {
		const name = (s.name ?? "?") as string;
		const dur = (s.duration_ms ?? 0) as number;
		const status = (s.status ?? "ok") as string;
		const meta = (s.metadata ?? {}) as Record<string, unknown>;

		out += `\x1b[2m | \x1b[0m\x1b[34m${name}\x1b[36m:${Math.round(dur)}ms\x1b[0m`;
		if (status !== "ok") {
			out += `\x1b[31m\x1b[1m:${status}\x1b[0m`;
		}

		const picked: string[] = [];
		for (const key of TRACE_META_KEYS) {
			const val = meta[key];
			if (val !== undefined && val !== "" && val !== null) {
				if (typeof val === "boolean") {
					picked.push(`${key.slice(0, 6)}=${val ? "t" : "f"}`);
				} else if (typeof val !== "object") {
					picked.push(`${key.slice(0, 6)}=${val}`);
				}
			}
		}
		if (picked.length > 0) {
			out += `\x1b[96m(${picked.slice(0, 4).join(",")})\x1b[0m`;
		}
	}

	return out;
}

function printTraceEpilogue(
	backend: Backend,
	operationId: string | null | undefined,
	trace: Record<string, unknown> | null | undefined,
): void {
	let opId = operationId;
	if (!opId && backend instanceof PlatformBackend) {
		opId = backend.lastOperationId;
	}
	process.stderr.write("\n");
	process.stderr.write(formatCompactTrace(opId, trace));
	process.stderr.write("\n");
}

function extractTraceWrapper(data: Record<string, unknown>): {
	operationId: string | null;
	traceData: Record<string, unknown> | null;
	clean: Record<string, unknown>;
} {
	const operationId = (data.operation_id ?? null) as string | null;
	const traceData = (data.trace ?? data.trace_summary ?? null) as Record<
		string,
		unknown
	> | null;
	const clean: Record<string, unknown> = {};
	for (const [k, v] of Object.entries(data)) {
		if (k !== "trace" && k !== "trace_summary" && k !== "operation_id") {
			clean[k] = v;
		}
	}
	return { operationId, traceData, clean };
}

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
		trace?: boolean;
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
				traceEnabled: opts.trace,
			});
		});
	} catch (e) {
		printError(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}

	const {
		operationId,
		traceData,
		clean: cleanResult,
	} = extractTraceWrapper(result);
	result = cleanResult;

	if (opts.output === "quiet") {
		if (opts.trace) printTraceEpilogue(backend, operationId, traceData);
		return;
	}

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
		let agentData: unknown = deduped;
		if (opts.trace && operationId) {
			agentData = { results: deduped, operation_id: operationId };
			if (traceData) (agentData as Record<string, unknown>).trace = traceData;
		}
		formatAgentEnvelope({
			command: "add",
			data: agentData,
			scope,
			count: deduped.length,
		});
		if (opts.trace) printTraceEpilogue(backend, operationId, traceData);
		return;
	}

	if (opts.output === "json") {
		let jsonPayload: unknown = dedupedResult;
		if (opts.trace && operationId) {
			if (
				typeof jsonPayload === "object" &&
				jsonPayload !== null &&
				!Array.isArray(jsonPayload)
			) {
				(jsonPayload as Record<string, unknown>).operation_id = operationId;
				if (traceData)
					(jsonPayload as Record<string, unknown>).trace = traceData;
			} else {
				jsonPayload = { results: jsonPayload, operation_id: operationId };
				if (traceData)
					(jsonPayload as Record<string, unknown>).trace = traceData;
			}
		}
		formatJson(jsonPayload);
		if (opts.trace) printTraceEpilogue(backend, operationId, traceData);
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

	if (opts.trace) printTraceEpilogue(backend, operationId, traceData);
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
		trace?: boolean;
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
				traceEnabled: opts.trace,
			});
		});
	} catch (e) {
		printError(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}
	const elapsed = (performance.now() - start) / 1000;

	let operationId: string | null = null;
	let traceData: Record<string, unknown> | null = null;
	if (opts.trace && results.length === 1 && !Array.isArray(results[0]?.id)) {
		const wrapper = results[0] as Record<string, unknown>;
		operationId = (wrapper.operation_id ?? null) as string | null;
		traceData = (wrapper.trace ?? wrapper.trace_summary ?? null) as Record<
			string,
			unknown
		> | null;
		const extracted = (wrapper.results ?? wrapper.memories ?? []) as Record<
			string,
			unknown
		>[];
		if (extracted.length > 0) results = extracted;
	}

	if (opts.output === "quiet") {
		if (opts.trace) printTraceEpilogue(backend, operationId, traceData);
		return;
	}

	if (opts.output === "agent") {
		const scope: Record<string, string | undefined> = {
			user_id: opts.userId,
			agent_id: opts.agentId,
			app_id: opts.appId,
			run_id: opts.runId,
		};
		let agentData: unknown = results;
		if (opts.trace && operationId) {
			agentData = { results, operation_id: operationId };
			if (traceData) (agentData as Record<string, unknown>).trace = traceData;
		}
		formatAgentEnvelope({
			command: "search",
			data: agentData,
			scope,
			count: results.length,
			durationMs: Math.round(elapsed * 1000),
		});
		if (opts.trace) printTraceEpilogue(backend, operationId, traceData);
		return;
	}

	if (opts.output === "json") {
		let jsonPayload: unknown = results;
		if (opts.trace && operationId) {
			jsonPayload = { results, operation_id: operationId };
			if (traceData) (jsonPayload as Record<string, unknown>).trace = traceData;
		}
		formatJson(jsonPayload);
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

	if (opts.trace) printTraceEpilogue(backend, operationId, traceData);
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
		trace?: boolean;
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
				traceEnabled: opts.trace,
			});
		});
	} catch (e) {
		printError(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}
	const elapsed = (performance.now() - start) / 1000;

	let operationId: string | null = null;
	let traceData: Record<string, unknown> | null = null;
	if (opts.trace && results.length === 1 && !Array.isArray(results[0]?.id)) {
		const wrapper = results[0] as Record<string, unknown>;
		operationId = (wrapper.operation_id ?? null) as string | null;
		traceData = (wrapper.trace ?? wrapper.trace_summary ?? null) as Record<
			string,
			unknown
		> | null;
		const extracted = (wrapper.results ?? wrapper.memories ?? []) as Record<
			string,
			unknown
		>[];
		if (extracted.length > 0) results = extracted;
	}

	if (opts.output === "quiet") {
		if (opts.trace) printTraceEpilogue(backend, operationId, traceData);
		return;
	}

	if (opts.output === "agent" || opts.output === "json") {
		const scope: Record<string, string | undefined> = {
			user_id: opts.userId,
			agent_id: opts.agentId,
			app_id: opts.appId,
			run_id: opts.runId,
		};
		let outData: unknown = results;
		if (opts.trace && operationId) {
			outData = { results, operation_id: operationId };
			if (traceData) (outData as Record<string, unknown>).trace = traceData;
		}
		formatAgentEnvelope({
			command: "list",
			data: outData,
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

	if (opts.trace) printTraceEpilogue(backend, operationId, traceData);
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
