import {
  HybridWeights,
  SearchFilters,
  SearchProfile,
  SearchRerankConfig,
  ScoreWeights,
} from "../types";

export interface Entity {
  userId?: string;
  agentId?: string;
  runId?: string;
}

export interface AddMemoryOptions extends Entity {
  metadata?: Record<string, any>;
  filters?: SearchFilters;
  infer?: boolean;
  timestamp?: number | string | Date | null;
}

export interface SearchMemoryOptions {
  profile?: string | SearchProfile;
  categories?: string | string[];
  topK?: number;
  filters?: SearchFilters;
  threshold?: number;
  explain?: boolean;
  referenceDate?: number | string | Date | null;
  scoreWeights?: ScoreWeights;
  hybridWeights?: HybridWeights;
  rerank?: boolean | SearchRerankConfig;
}

export interface GetAllMemoryOptions {
  topK?: number;
  filters?: SearchFilters;
  categories?: string | string[];
}

export interface DeleteAllMemoryOptions extends Entity {}

export interface UpdateProjectOptions {
  decay?: boolean;
  [key: string]: any;
}
