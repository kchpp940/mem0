/**
 * Memory CRUD commands: add, search, get, list, update, delete.
 */

import fs from "node:fs";
import type { Backend } from "../backend/base.js";
import {
	printError,
	printInfo,
	printScope,
	printSuccess,
	timedStatus,
} from "../branding.js";
import { OutputRenderer } from "../output.js";
import { buildScope, parseCategories, parseJsonOption, validateTopK, validateThreshold, validatePage, validatePageSize } from "../option-builder.js";
import { dedupPending, extractAddResults } from "../result-normalizer.js";
import { isAgentMode, setCurrentCommand } from "../state.js";

function _stdinIsPiped(): boolean {
	if (isAgentMode()) return false;
	try {
		const stat = fs.fstatSync(0);
		return stat.isFIFO() || stat.isFile();
	} catch {
		return false;
	}
}

function _resolveOutput(output: string): string {
	if (isAgentMode()) return "agent";
	return output;
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
	const output = _resolveOutput(opts.output);
	const scope = buildScope({
		userId: opts.userId,
		agentId: opts.agentId,
		appId: opts.appId,
		runId: opts.runId,
	});
	const renderer = new OutputRenderer({ outputFormat: output, command: "add", scope });

	let msgs: Record<string, unknown>[] | undefined;
	let content = text;

	if (opts.file) {
		try {
			const raw = fs.readFileSync(opts.file, "utf-8");
			msgs = JSON.parse(raw);
		} catch (e) {
			renderer.error(`Failed to read file: ${e instanceof Error ? e.message : e}`, { errorCode: "file_error" });
			process.exit(1);
		}
	} else if (opts.messages) {
		try {
			msgs = JSON.parse(opts.messages);
		} catch (e) {
			renderer.error(`Invalid JSON in --messages: ${e instanceof Error ? e.message : e}`, { errorCode: "validation" });
			process.exit(1);
		}
	} else if (!content && _stdinIsPiped()) {
		content = fs.readFileSync(0, "utf-8").trim();
	}

	if (content !== undefined && content.trim() === "") {
		renderer.error("Content cannot be empty.", { errorCode: "validation" });
		process.exit(1);
	}
	if (!content && !msgs) {
		renderer.error("No content provided. Pass text, --messages, --file, or pipe via stdin.", { errorCode: "validation" });
		process.exit(1);
	}

	if (opts.expires) {
		if (!/^\d{4}-\d{2}-\d{2}$/.test(opts.expires)) {
			renderer.error("Invalid date format for --expires. Use YYYY-MM-DD (e.g. 2025-12-31).", { errorCode: "validation" });
			process.exit(1);
		}
		if (new Date(opts.expires) <= new Date()) {
			renderer.error("--expires date must be in the future.", { errorCode: "validation" });
			process.exit(1);
		}
	}

	let meta: Record<string, unknown> | undefined;
	if (opts.metadata) {
		try {
			meta = JSON.parse(opts.metadata);
		} catch {
			renderer.error("Invalid JSON in --metadata.", { errorCode: "validation" });
			process.exit(1);
		}
	}

	const cats = parseCategories(opts.categories);

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
				categories: cats ?? undefined,
			});
		});
	} catch (e) {
		renderer.error(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}

	if (output === "quiet") return;

	const rawResults = extractAddResults(result);
	const deduped = dedupPending(rawResults as Record<string, unknown>[]);

	if (output === "json" || output === "agent") {
		renderer.addResult(deduped);
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
		printSuccess(`Memory queued — ${count} event${count !== 1 ? "s" : ""} pending`);
	} else {
		printSuccess(`Memory processed — ${count} memor${count === 1 ? "y" : "ies"} extracted`);
	}
	renderer.addResult(deduped);
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
	const output = _resolveOutput(opts.output);
	const scope = buildScope({
		userId: opts.userId,
		agentId: opts.agentId,
		appId: opts.appId,
		runId: opts.runId,
	});
	const renderer = new OutputRenderer({ outputFormat: output, command: "search", scope });

	if (!query) {
		renderer.error("No query provided. Pass a query argument or pipe via stdin.", { errorCode: "validation" });
		process.exit(1);
	}

	let filters: Record<string, unknown> | undefined;
	try {
		filters = parseJsonOption(opts.filterJson, "--filter") as Record<string, unknown> | undefined;
	} catch (e) {
		renderer.error(e instanceof Error ? e.message : String(e), { errorCode: "validation" });
		process.exit(1);
	}

	const fieldList = opts.fields
		? opts.fields.split(",").map((f) => f.trim())
		: undefined;

	try {
		validateTopK(opts.topK);
	} catch (e) {
		renderer.error(e instanceof Error ? e.message : String(e), { errorCode: "validation" });
		process.exit(1);
	}
	try {
		validateThreshold(opts.threshold);
	} catch (e) {
		renderer.error(e instanceof Error ? e.message : String(e), { errorCode: "validation" });
		process.exit(1);
	}

	const start = performance.now();
	let results: Record<string, unknown>[];
	try {
		results = await timedStatus("Searching memories...", async () => {
			return backend.search(query, {
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
		renderer.error(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}
	const elapsed = (performance.now() - start) / 1000;

	if (output === "quiet") return;

	renderer.setDuration({ seconds: elapsed });

	if (output === "json" || output === "agent") {
		renderer.memoryList(results, { showScore: true });
		return;
	}

	if (results.length > 0) {
		renderer.memoryList(results, { showScore: true });
	} else {
		console.log();
		printInfo("No memories found matching your query.");
		console.log();
	}
}

export async function cmdGet(
	backend: Backend,
	memoryId: string,
	opts: { output: string },
): Promise<void> {
	setCurrentCommand("get");
	const output = _resolveOutput(opts.output);
	const renderer = new OutputRenderer({ outputFormat: output, command: "get" });

	let result: Record<string, unknown>;
	try {
		result = await timedStatus("Fetching memory...", async () => {
			return backend.get(memoryId);
		});
	} catch (e) {
		renderer.error(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}

	renderer.singleMemory(result);
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
	const output = _resolveOutput(opts.output);
	const scope = buildScope({
		userId: opts.userId,
		agentId: opts.agentId,
		appId: opts.appId,
		runId: opts.runId,
	});
	const renderer = new OutputRenderer({ outputFormat: output, command: "list", scope });

	try {
		validatePageSize(opts.pageSize);
	} catch (e) {
		renderer.error(e instanceof Error ? e.message : String(e), { errorCode: "validation" });
		process.exit(1);
	}
	try {
		validatePage(opts.page);
	} catch (e) {
		renderer.error(e instanceof Error ? e.message : String(e), { errorCode: "validation" });
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
		renderer.error(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}
	const elapsed = (performance.now() - start) / 1000;

	if (output === "quiet") return;

	renderer.setDuration({ seconds: elapsed });

	if (output === "json" || output === "agent") {
		renderer.memoryList(results, { page: opts.page });
		return;
	}

	if (results.length > 0) {
		renderer.memoryList(results, { page: opts.page });
	} else {
		console.log();
		printInfo("No memories found.");
		console.log();
	}
}

export async function cmdUpdate(
	backend: Backend,
	memoryId: string,
	text: string | undefined,
	opts: { metadata?: string; output: string },
): Promise<void> {
	setCurrentCommand("update");
	const output = _resolveOutput(opts.output);
	const renderer = new OutputRenderer({ outputFormat: output, command: "update" });

	let meta: Record<string, unknown> | undefined;
	if (opts.metadata) {
		try {
			meta = JSON.parse(opts.metadata);
		} catch {
			renderer.error("Invalid JSON in --metadata.", { errorCode: "validation" });
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
		renderer.error(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}
	const elapsed = (performance.now() - start) / 1000;

	renderer.setDuration({ seconds: elapsed });

	if (output === "json" || output === "agent") {
		renderer.singleMemory(result);
	} else if (output !== "quiet") {
		printSuccess(`Memory ${memoryId.slice(0, 8)} updated (${elapsed.toFixed(2)}s)`);
	}
}

export async function cmdDelete(
	backend: Backend,
	memoryId: string,
	opts: { output: string; dryRun?: boolean; force?: boolean },
): Promise<void> {
	setCurrentCommand("delete");
	const output = _resolveOutput(opts.output);
	const renderer = new OutputRenderer({ outputFormat: output, command: "delete" });

	if (opts.dryRun) {
		let mem: Record<string, unknown>;
		try {
			mem = await backend.get(memoryId);
		} catch (e) {
			renderer.error(e instanceof Error ? e.message : String(e));
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
		renderer.error(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}
	const elapsed = (performance.now() - start) / 1000;

	renderer.setDuration({ seconds: elapsed });

	if (output === "json" || output === "agent") {
		renderer.data({ id: memoryId, deleted: true });
	} else if (output !== "quiet") {
		printSuccess(`Memory ${memoryId.slice(0, 8)} deleted (${elapsed.toFixed(2)}s)`);
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
	const output = _resolveOutput(opts.output);
	const scope = buildScope({
		userId: opts.userId,
		agentId: opts.agentId,
		appId: opts.appId,
		runId: opts.runId,
	});
	const renderer = new OutputRenderer({ outputFormat: output, command: "delete-all", scope });

	if (isAgentMode() && !opts.force) {
		renderer.error("Destructive operation requires --force in agent mode.", { errorCode: "auth" });
		process.exit(1);
	}

	if (opts.all) {
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
			renderer.error(e instanceof Error ? e.message : String(e));
			process.exit(1);
		}
		const elapsed = (performance.now() - start) / 1000;

		renderer.setDuration({ seconds: elapsed });

		if (output === "json" || output === "agent") {
			renderer.data({ deleted: true, scope: "project" });
		} else if (output !== "quiet") {
			if (result.message) {
				printInfo("Deletion started. Memories will be removed in the background.");
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
			renderer.error(e instanceof Error ? e.message : String(e));
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
		const scopeStr =
			scopeParts.length > 0 ? scopeParts.join(", ") : "ALL entities";

		const readline = await import("node:readline");
		const rl = readline.createInterface({
			input: process.stdin,
			output: process.stdout,
		});
		const answer = await new Promise<string>((resolve) => {
			rl.question(
				`\n  \u26a0  Delete ALL memories for ${scopeStr}? This cannot be undone. [y/N] `,
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
		renderer.error(e instanceof Error ? e.message : String(e));
		process.exit(1);
	}
	const elapsed = (performance.now() - start) / 1000;

	renderer.setDuration({ seconds: elapsed });

	if (output === "json" || output === "agent") {
		renderer.data({ deleted: true });
	} else if (output !== "quiet") {
		if (result.message) {
			printInfo("Deletion started. Memories will be removed in the background.");
		} else {
			printSuccess(`All matching memories deleted (${elapsed.toFixed(2)}s)`);
		}
	}
}
