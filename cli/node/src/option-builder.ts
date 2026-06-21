/**
 * Reusable CLI option builders derived from the shared CLI contract.
 *
 * This module centralizes option definitions, validation rules, and default
 * values so that every command uses consistent parameter names, help text,
 * and defaults.
 *
 * All option builders follow the contract defined in `cli/cli-spec.json`
 * and `src/contract/payload_contract.json`.
 */

import { Command, Option } from 'commander';
import { VALIDATION_RULES, validateField } from './schema/fields.js';
import contract from './contract/payload_contract.json' with { type: 'json' };

interface ContractDefaults {
  top_k?: number;
  threshold?: number;
  rerank?: boolean;
  keyword?: boolean;
  immutable?: boolean;
  [key: string]: unknown;
}

const defaults = (contract.defaults || {}) as ContractDefaults;

export interface OptionSpec {
  flags: string;
  description: string;
  defaultValue?: unknown;
  choices?: string[];
  required?: boolean;
  argParser?: (value: string) => unknown;
  helpGroup?: string;
}

export type OptionGroup = Record<string, OptionSpec>;

export function scopeOptions(helpGroup = 'Scope'): OptionGroup {
  return {
    userId: {
      flags: '--user-id <id>',
      description: 'Scope to user.',
      helpGroup,
    },
    agentId: {
      flags: '--agent-id <id>',
      description: 'Scope to agent.',
      helpGroup,
    },
    appId: {
      flags: '--app-id <id>',
      description: 'Scope to app.',
      helpGroup,
    },
    runId: {
      flags: '--run-id <id>',
      description: 'Scope to run.',
      helpGroup,
    },
  };
}

export function outputOption(
  defaultFormat = 'text',
  choices = ['text', 'json', 'table', 'quiet'],
  helpGroup = 'Output',
): OptionSpec {
  const choicesStr = choices.join(', ');
  return {
    flags: '--output <format>',
    description: `Output format: ${choicesStr}.`,
    defaultValue: defaultFormat,
    choices,
    helpGroup,
  };
}

export function connectionOptions(helpGroup = 'Connection'): OptionGroup {
  return {
    apiKey: {
      flags: '--api-key <key>',
      description: 'Override API key.',
      helpGroup,
    },
    baseUrl: {
      flags: '--base-url <url>',
      description: 'Override API base URL.',
      helpGroup,
    },
  };
}

export function searchOptions(helpGroup = 'Search'): OptionGroup {
  return {
    topK: {
      flags: '--top-k <n>',
      description: 'Number of results.',
      defaultValue: defaults.top_k ?? 10,
      argParser: parseInt,
      helpGroup,
    },
    threshold: {
      flags: '--threshold <n>',
      description: 'Minimum similarity score.',
      defaultValue: defaults.threshold ?? 0.3,
      argParser: parseFloat,
      helpGroup,
    },
    rerank: {
      flags: '--rerank',
      description: 'Enable reranking (Platform only).',
      defaultValue: defaults.rerank ?? false,
      helpGroup,
    },
    keyword: {
      flags: '--keyword',
      description: 'Use keyword search.',
      defaultValue: defaults.keyword ?? false,
      helpGroup,
    },
    filter: {
      flags: '--filter <json>',
      description: 'Advanced filter expression (JSON).',
      helpGroup,
    },
    fields: {
      flags: '--fields <fields>',
      description: 'Specific fields to return (comma-separated).',
      helpGroup,
    },
  };
}

export function paginationOptions(helpGroup = 'Pagination'): OptionGroup {
  return {
    page: {
      flags: '--page <n>',
      description: 'Page number.',
      defaultValue: 1,
      argParser: parseInt,
      helpGroup,
    },
    pageSize: {
      flags: '--page-size <n>',
      description: 'Results per page.',
      defaultValue: 100,
      argParser: parseInt,
      helpGroup,
    },
  };
}

export function filterOptions(helpGroup = 'Filters'): OptionGroup {
  return {
    category: {
      flags: '--category <name>',
      description: 'Filter by category.',
      helpGroup,
    },
    after: {
      flags: '--after <date>',
      description: 'Created after (YYYY-MM-DD).',
      helpGroup,
    },
    before: {
      flags: '--before <date>',
      description: 'Created before (YYYY-MM-DD).',
      helpGroup,
    },
  };
}

export function addOptions(): OptionGroup {
  return {
    messages: {
      flags: '--messages <json>',
      description: 'Conversation messages as JSON.',
    },
    file: {
      flags: '-f, --file <path>',
      description: 'Read messages from JSON file.',
    },
    metadata: {
      flags: '-m, --metadata <json>',
      description: 'Custom metadata as JSON.',
    },
    immutable: {
      flags: '--immutable',
      description: 'Prevent future updates.',
      defaultValue: defaults.immutable ?? false,
    },
    noInfer: {
      flags: '--no-infer',
      description: 'Skip inference, store raw.',
      defaultValue: false,
    },
    expires: {
      flags: '--expires <date>',
      description: 'Expiration date (YYYY-MM-DD).',
    },
    categories: {
      flags: '--categories <list>',
      description: 'Categories (JSON array or comma-separated).',
    },
  };
}

export function applyOptions(cmd: Command, options: OptionGroup): Command {
  for (const [_name, spec] of Object.entries(options)) {
    const opt = new Option(spec.flags, spec.description);

    if (spec.defaultValue !== undefined) {
      opt.default(spec.defaultValue);
    }
    if (spec.choices?.length) {
      opt.choices(spec.choices);
    }
    const optAny = opt as unknown as Record<string, unknown>;
    if (spec.helpGroup && typeof optAny.helpGroup === 'function') {
      (optAny.helpGroup as (name: string) => Option)(spec.helpGroup);
    }
    if (spec.argParser) {
      opt.argParser(spec.argParser as (value: string, previous: unknown) => unknown);
    }

    cmd.addOption(opt);
  }
  return cmd;
}

export function validateTopK(topK: number): void {
  validateField('top_k', topK);
}

export function validateThreshold(threshold: number): void {
  validateField('threshold', threshold);
}

export function validatePage(page: number): void {
  validateField('page', page);
}

export function validatePageSize(pageSize: number): void {
  validateField('pageSize', pageSize);
}

export function parseJsonOption(value: string | undefined, name: string): unknown {
  if (value === undefined || value === null) return null;
  try {
    return JSON.parse(value);
  } catch (e) {
    throw new Error(`Invalid JSON in ${name}: ${e instanceof Error ? e.message : String(e)}`);
  }
}

export function parseCategories(value: string | undefined): string[] | null {
  if (value === undefined || value === null) return null;
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) {
      throw new Error('--categories JSON must be an array.');
    }
    return parsed.map(String);
  } catch {
    return value.split(',').map((c) => c.trim()).filter(Boolean);
  }
}

export function parseFields(value: string | undefined): string[] | null {
  if (value === undefined || value === null) return null;
  return value.split(',').map((f) => f.trim()).filter(Boolean);
}

export function buildScope(params: {
  userId?: string;
  agentId?: string;
  appId?: string;
  runId?: string;
}): Record<string, string> | null {
  const scope: Record<string, string> = {};
  if (params.userId) scope.user_id = params.userId;
  if (params.agentId) scope.agent_id = params.agentId;
  if (params.appId) scope.app_id = params.appId;
  if (params.runId) scope.run_id = params.runId;
  return Object.keys(scope).length ? scope : null;
}
