/**
 * Abstract backend interface and factory.
 */

import type { Mem0Config } from "../config.js";
import type {
	AddOptions,
	DeleteOptions,
	EntityIds,
	Backend as IBackend,
	ListOptions,
	SearchOptions,
} from "../schema/index.js";
import { PlatformBackend } from "./platform.js";

export type {
	AddOptions,
	SearchOptions,
	ListOptions,
	DeleteOptions,
	EntityIds,
};
export type Backend = IBackend;

export class AuthError extends Error {
	constructor(
		message = "Authentication failed. Your API key may be invalid or expired.",
	) {
		super(message);
		this.name = "AuthError";
	}
}

export class NotFoundError extends Error {
	constructor(path: string) {
		super(`Resource not found: ${path}`);
		this.name = "NotFoundError";
	}
}

export class APIError extends Error {
	constructor(path: string, detail: string) {
		super(`Bad request to ${path}: ${detail}`);
		this.name = "APIError";
	}
}

export function getBackend(config: Mem0Config): Backend {
	return new PlatformBackend(config.platform);
}
