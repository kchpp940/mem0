/**
 * Utility commands: status, version, import.
 */

import fs from "node:fs";
import boxen from "boxen";
import type { Backend } from "../backend/base.js";
import { colors, printError, printSuccess, timedStatus } from "../branding.js";
import { OutputRenderer } from "../output.js";
import { buildScope } from "../option-builder.js";
import { setCurrentCommand, isAgentMode } from "../state.js";
import { CLI_VERSION } from "../version.js";

const { brand, dim, success, error: errorColor } = colors;

function _resolveOutput(output: string): string {
	if (isAgentMode()) return "agent";
	return output;
}

export async function cmdStatus(
	backend: Backend,
	opts: { userId?: string; agentId?: string; output?: string } = {},
): Promise<void> {
	setCurrentCommand("status");
	const output = _resolveOutput(opts.output ?? "text");
	const renderer = new OutputRenderer({ outputFormat: output, command: "status" });

	const start = performance.now();
	let result: Record<string, unknown>;
	try {
		result = await timedStatus("Checking connection...", async () => {
			return backend.status({ userId: opts.userId, agentId: opts.agentId });
		});
	} catch (e) {
		result = {
			connected: false,
			error: e instanceof Error ? e.message : String(e),
		};
	}
	const elapsed = (performance.now() - start) / 1000;

	renderer.setDuration({ seconds: elapsed });

	if (output === "agent" || output === "json") {
		renderer.data({
			connected: result.connected,
			backend: result.backend ?? null,
			base_url: result.base_url ?? null,
		});
		return;
	}

	const lines: string[] = [];
	if (result.connected) {
		lines.push(`  ${success("\u25cf")} Connected`);
	} else {
		lines.push(`  ${errorColor("\u25cf")} Disconnected`);
	}

	lines.push(`  ${dim("Backend:")}  ${result.backend ?? "?"}`);
	if (result.base_url) {
		lines.push(`  ${dim("API URL:")}  ${result.base_url}`);
	}
	if (result.error) {
		lines.push(`  ${errorColor("Error:")}    ${result.error}`);
		if (String(result.error).includes("Authentication failed")) {
			lines.push("");
			lines.push(
				`  ${dim("Run")} ${brand("mem0 init")} ${dim("to reconfigure your API key")}`,
			);
			lines.push(
				`  ${dim("Get a key at")} ${brand("https://app.mem0.ai/dashboard/api-keys?utm_source=oss&utm_medium=cli-node")}`,
			);
		}
	}
	lines.push(`  ${dim("Latency:")}  ${elapsed.toFixed(2)}s`);

	const content = lines.join("\n");
	console.log();
	console.log(
		boxen(content, {
			title: brand("Connection Status"),
			titleAlignment: "left",
			borderColor: "magenta",
			padding: 1,
		}),
	);
	console.log();
}

export function cmdVersion(): void {
	console.log(`  ${brand("◆ Mem0")} CLI v${CLI_VERSION}`);
}

export async function cmdImport(
	backend: Backend,
	filePath: string,
	opts: { userId?: string; agentId?: string; output?: string },
): Promise<void> {
	setCurrentCommand("import");
	const output = _resolveOutput(opts.output ?? "text");
	const scope = buildScope({ userId: opts.userId, agentId: opts.agentId });
	const renderer = new OutputRenderer({ outputFormat: output, command: "import", scope });

	let data: Record<string, unknown>[];
	try {
		const raw = fs.readFileSync(filePath, "utf-8");
		const parsed = JSON.parse(raw);
		data = Array.isArray(parsed) ? parsed : [parsed];
	} catch (e) {
		renderer.error(`Failed to read file: ${e instanceof Error ? e.message : e}`, { errorCode: "file_error" });
		process.exit(1);
	}

	let added = 0;
	let failed = 0;
	const start = performance.now();

	for (let i = 0; i < data.length; i++) {
		const item = data[i];
		const content = (item.memory ?? item.text ?? item.content ?? "") as string;
		if (!content) {
			failed++;
			continue;
		}

		try {
			await backend.add(content, undefined, {
				userId: opts.userId ?? (item.user_id as string | undefined),
				agentId: opts.agentId ?? (item.agent_id as string | undefined),
				metadata: item.metadata as Record<string, unknown> | undefined,
			});
			added++;
		} catch {
			failed++;
		}

		if ((i + 1) % 10 === 0 || i === data.length - 1) {
			process.stdout.write(
				`\r  ${dim(`Importing memories... ${i + 1}/${data.length}`)}`,
			);
		}
	}

	const elapsed = (performance.now() - start) / 1000;
	console.log();

	renderer.setDuration({ seconds: elapsed });

	if (output === "agent" || output === "json") {
		renderer.data({ added, failed });
		return;
	}

	printSuccess(`Imported ${added} memories (${elapsed.toFixed(2)}s)`);
	if (failed > 0) {
		printError(`${failed} memories failed to import.`);
	}
}
