#!/usr/bin/env node
/**
 * Validate that the payload_contract.json was generated from cli-spec.json.
 *
 * Checks:
 *   1. Contract file exists
 *   2. Has _meta.generated = true (DO NOT EDIT marker)
 *   3. If Python is available, runs generate_contracts.py --check for full hash validation
 */

import { existsSync, readFileSync } from "node:fs";
import { execSync } from "node:child_process";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const REPO_ROOT = resolve(__dirname, "..", "..", "..");
const CLI_ROOT = resolve(REPO_ROOT, "cli");
const SPEC_PATH = resolve(CLI_ROOT, "cli-spec.json");
const CONTRACT_PATH = resolve(__dirname, "..", "src", "contract", "payload_contract.json");
const GENERATOR_PATH = resolve(CLI_ROOT, "generate_contracts.py");

function fail(message) {
	console.error(`[contract-fail] ${message}`);
	process.exit(1);
}

if (!existsSync(CONTRACT_PATH)) {
	fail(`payload_contract.json not found at ${CONTRACT_PATH}\n  Run: python cli/generate_contracts.py`);
}

let contract;
try {
	contract = JSON.parse(readFileSync(CONTRACT_PATH, "utf-8"));
} catch (err) {
	fail(`Failed to parse payload_contract.json: ${err.message}`);
}

const meta = contract._meta || {};
if (!meta.generated) {
	fail(
		`payload_contract.json is not a generated contract (missing _meta.generated)\n` +
			`  Do not edit payload_contract.json manually.\n` +
			`  Run: python cli/generate_contracts.py`,
	);
}

if (!meta.source_hash) {
	fail(
		`payload_contract.json is missing _meta.source_hash\n` +
			`  Run: python cli/generate_contracts.py`,
	);
}

let hasPython = false;
try {
	execSync("python3 --version", { stdio: "ignore" });
	hasPython = true;
} catch {
	try {
		execSync("python --version", { stdio: "ignore" });
		hasPython = true;
	} catch {
		hasPython = false;
	}
}

if (hasPython && existsSync(GENERATOR_PATH) && existsSync(SPEC_PATH)) {
	console.log("[contract-check] Running generate_contracts.py --check ...");
	try {
		const pythonCmd = process.platform === "win32" ? "python" : "python3";
		execSync(`${pythonCmd} ${GENERATOR_PATH} --check`, {
			stdio: "inherit",
			cwd: REPO_ROOT,
		});
		console.log("[contract-ok] Full hash validation passed.");
	} catch (err) {
		process.exit(err.status || 1);
	}
} else {
	console.log(
		"[contract-ok] Basic checks passed (_meta marker present). " +
			"Skipping full hash validation (Python not available or generator not found).",
	);
}
