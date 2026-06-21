/**
 * Agent mode state — set by the root program option handler,
 * read by commands and branding functions.
 */

import contract from "./contract/payload_contract.json" with { type: "json" };

let _agentMode = false;
let _currentCommand = "";
let _pendingNotice = "";
let _traceEnabled = true;
let _traceEventId = "";

export interface TraceStep {
	label: string;
	durationMs?: number;
	status?: string;
	metadata?: Record<string, unknown>;
	_startTime?: number;
}

const _traces: TraceStep[] = [];
let _traceContract: Record<string, unknown> | null = null;

function loadTraceContract(): Record<string, unknown> {
	if (!_traceContract) {
		_traceContract = (contract as Record<string, unknown>).traceEpilogue as Record<string, unknown> || {};
	}
	return _traceContract;
}

export function isAgentMode(): boolean {
	return _agentMode;
}

export function setAgentMode(val: boolean): void {
	_agentMode = val;
}

export function getCurrentCommand(): string {
	return _currentCommand;
}

export function setCurrentCommand(name: string): void {
	_currentCommand = name;
}

/**
 * Stash a Mem0 backend notice (Agent Mode unclaimed reminder) for end-of-
 * command surfacing. Called from the platform backend after each response so
 * the notice prints once per command regardless of how many sub-requests
 * fired. Last-write-wins is fine — the message text is identical.
 */
export function captureNotice(notice: string | null | undefined): void {
	if (notice) _pendingNotice = notice;
}

export function takeNotice(): string {
	const msg = _pendingNotice;
	_pendingNotice = "";
	return msg;
}

// ---------------------------------------------------------------------------
// Trace epilogue
// ---------------------------------------------------------------------------

export function setTraceEnabled(enabled: boolean): void {
	_traceEnabled = enabled;
}

export function isTraceEnabled(): boolean {
	return _traceEnabled && !isAgentMode();
}

export function setTraceEventId(eventId: string): void {
	_traceEventId = eventId;
}

export function getTraceEventId(): string {
	return _traceEventId;
}

export function addTraceStep(label: string, { start = false }: { start?: boolean } = {}): TraceStep {
	const step: TraceStep = { label };
	if (start && isTraceEnabled()) {
		step._startTime = performance.now();
	}
	if (isTraceEnabled()) {
		_traces.push(step);
	}
	return step;
}

export function finishTraceStep(step: TraceStep, status?: string): void {
	if (step._startTime !== undefined) {
		step.durationMs = Math.round(performance.now() - step._startTime);
	}
	if (status !== undefined) {
		step.status = status;
	}
}

export function getTraceSteps(): TraceStep[] {
	return [..._traces];
}

export function clearTraceSteps(): void {
	_traces.length = 0;
	_traceEventId = "";
}

export function formatTraceEpilogue(): string | null {
	if (!isTraceEnabled()) return null;

	const contract = loadTraceContract();
	const steps = getTraceSteps();
	if (steps.length === 0) return null;

	const minDuration = (contract.minDurationMs as number) ?? 5;
	const filtered = steps.filter((s) => s.durationMs === undefined || s.durationMs >= minDuration);
	if (filtered.length === 0) return null;

	const headerLabel = (contract.headerLabel as string) ?? "STEP";
	const headerDuration = (contract.headerDuration as string) ?? "DURATION";
	const headerStatus = (contract.headerStatus as string) ?? "STATUS";

	const labelWidth = (contract.labelWidth as number) ?? 18;
	const durationWidth = (contract.durationWidth as number) ?? 10;
	const statusWidth = (contract.statusWidth as number) ?? 10;

	const statusColors: Record<string, string> = (contract.statusColors as Record<string, string>) ?? {
		success: "green",
		failed: "red",
		skipped: "yellow",
		pending: "dim",
	};
	const defaultStatus = (contract.defaultStatus as string) ?? "success";
	const totalLabel = (contract.totalLabel as string) ?? "Total";

	const colorMap: Record<string, (s: string) => string> = {
		green: (s: string) => `\x1b[32m${s}\x1b[0m`,
		red: (s: string) => `\x1b[31m${s}\x1b[0m`,
		yellow: (s: string) => `\x1b[33m${s}\x1b[0m`,
		dim: (s: string) => `\x1b[2m${s}\x1b[0m`,
	};

	const reset = "\x1b[0m";
	const accent = "\x1b[35m";
	const dim = "\x1b[2m";

	const lines: string[] = [];
	lines.push(
		`  ${accent}${headerLabel.padEnd(labelWidth)}${" "}${headerDuration.padStart(
			durationWidth,
		)}${" "}${headerStatus.padStart(statusWidth)}${reset}`,
	);

	let totalMs = 0;
	for (const step of filtered) {
		const status = step.status ?? defaultStatus;
		const colorName = statusColors[status] ?? "dim";
		const colorFn = colorMap[colorName] ?? colorMap.dim;

		let durationStr: string;
		if (step.durationMs !== undefined) {
			durationStr = `${step.durationMs.toString().padStart(6)} ms`;
			totalMs += step.durationMs;
		} else {
			durationStr = "     —";
		}

		const statusText = colorFn(status.toUpperCase().padStart(statusWidth));
		lines.push(
			`  ${dim}${step.label.padEnd(labelWidth)}${reset}${" "}${durationStr.padStart(
				durationWidth,
			)}${" "}${statusText}`,
		);
	}

	lines.push(
		`  ${accent}${totalLabel.padEnd(labelWidth)}${" "}${accent}${totalMs
			.toString()
			.padStart(6)} ms${reset}${" "}${"".padStart(statusWidth)}`,
	);

	const traceEventId = getTraceEventId();
	if (traceEventId) {
		const traceCommand = ((contract.traceCommand as string) ?? "mem0 trace {event_id}").replace(
			"{event_id}",
			traceEventId,
		);
		lines.push("");
		lines.push(`  ${dim}  For full trace: ${traceCommand}${reset}`);
	}

	return lines.join("\n") + "\n";
}

export function emitTraceEpilogue(): void {
	const epilogue = formatTraceEpilogue();
	if (epilogue) {
		process.stderr.write("\n" + epilogue);
	}
}
