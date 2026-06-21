/**
 * API response normalization helpers.
 *
 * This module normalizes inconsistent API response shapes into a canonical
 * form used by the output renderer and downstream code.
 *
 * Normalization rules follow the shared CLI contract in `cli/cli-spec.json`.
 */

import contract from './contract/payload_contract.json' with { type: 'json' };

const mapping = contract.fieldMapping || {};
const searchListKeys: string[] = contract.searchListKeys || ['results', 'memories'];
const addResultKey: string = contract.addResultKey || 'results';
const pendingConfig = contract.pendingDedup || {};

export function pickFields<T extends Record<string, unknown>>(
  data: T,
  fields: string[] | null | undefined,
): Partial<T> {
  if (!fields || fields.length === 0) return data;
  const result: Partial<T> = {};
  for (const field of fields) {
    if (field in data) {
      (result as Record<string, unknown>)[field] = data[field];
    }
  }
  return result;
}

export function extractList(data: unknown): unknown[] {
  if (Array.isArray(data)) return data;
  if (data && typeof data === 'object') {
    for (const key of searchListKeys) {
      const value = (data as Record<string, unknown>)[key];
      if (Array.isArray(value)) return value;
    }
  }
  return [];
}

export function extractAddResults(data: unknown): unknown[] {
  if (Array.isArray(data)) return data;
  if (data && typeof data === 'object') {
    const results = (data as Record<string, unknown>)[addResultKey];
    if (Array.isArray(results)) return results;
  }
  return [];
}

export function dedupPending(results: Record<string, unknown>[]): Record<string, unknown>[] {
  const statusKey = pendingConfig.statusKey || 'status';
  const pendingValue = pendingConfig.pendingValue || 'PENDING';
  const dedupKey = pendingConfig.dedupKey || 'event_id';

  const seenIds = new Set<string>();
  const result: Record<string, unknown>[] = [];

  for (const item of results) {
    if (!item || typeof item !== 'object') {
      result.push(item);
      continue;
    }
    const status = item[statusKey];
    if (status === pendingValue) {
      const eventId = item[dedupKey];
      if (eventId !== undefined && eventId !== null) {
        const idStr = String(eventId);
        if (seenIds.has(idStr)) continue;
        seenIds.add(idStr);
      }
    }
    result.push(item);
  }

  return result;
}

export interface BuildFiltersOptions {
  entityIds?: Record<string, string | undefined>;
  extra?: Record<string, unknown>;
}

export function buildFilters(options: BuildFiltersOptions = {}): Record<string, unknown> | null {
  const { entityIds = {}, extra = {} } = options;

  const filterBuilding = contract.filterBuilding || {};
  const entityOrder: string[] = filterBuilding.entityOrder || ['user_id', 'agent_id', 'app_id', 'run_id'];
  const combineOp = filterBuilding.combineOperator || 'AND';

  const filters: Record<string, unknown> = {};

  for (const field of entityOrder) {
    const value = entityIds[field];
    if (value !== undefined && value !== null && value !== '') {
      filters[field] = value;
    }
  }

  const listExtra = filterBuilding.listExtra || {};
  for (const [key, config] of Object.entries(listExtra)) {
    if (extra[key] !== undefined && extra[key] !== null) {
      const field = (config as Record<string, string>).field || key;
      const op = (config as Record<string, string>).op || 'eq';
      if (op === 'eq') {
        filters[field] = extra[key];
      } else {
        filters[field] = { [op]: extra[key] };
      }
    }
  }

  if (extra.filter !== undefined && extra.filter !== null) {
    const userFilter = extra.filter as Record<string, unknown>;
    if (Object.keys(filters).length > 0) {
      return { [combineOp]: [filters, userFilter] };
    }
    return userFilter;
  }

  return Object.keys(filters).length > 0 ? filters : null;
}

export function normalizeMemory(memory: Record<string, unknown>): Record<string, unknown> {
  if (!memory || typeof memory !== 'object') return memory;

  const result = { ...memory };
  for (const [canonName, apiName] of Object.entries(mapping)) {
    if (!(canonName in result) && apiName in result) {
      result[canonName] = result[apiName as string];
    }
  }
  return result;
}

export function normalizeMemoryList(
  memories: Record<string, unknown>[],
): Record<string, unknown>[] {
  return memories.map(normalizeMemory);
}

export function hasPending(results: Record<string, unknown>[]): boolean {
  const statusKey = pendingConfig.statusKey || 'status';
  const pendingValue = pendingConfig.pendingValue || 'PENDING';
  return results.some(
    (r) => r && typeof r === 'object' && r[statusKey] === pendingValue,
  );
}

export function countByStatus(results: Record<string, unknown>[]): Record<string, number> {
  const statusKey = pendingConfig.statusKey || 'status';
  const counts: Record<string, number> = {};
  for (const item of results) {
    if (item && typeof item === 'object') {
      const status = String(item[statusKey] ?? '');
      counts[status] = (counts[status] || 0) + 1;
    }
  }
  return counts;
}
