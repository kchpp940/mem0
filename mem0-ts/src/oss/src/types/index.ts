import { z } from "zod";

export interface ScoreWeights {
  semanticWeight?: number;
  bm25Weight?: number;
  entityBoostWeight?: number;
}

export interface SearchProfile {
  name?: string;
  filters?: SearchFilters;
  categories?: string[];
  topK?: number;
  threshold?: number;
  explain?: boolean;
  scoreWeights?: ScoreWeights;
  rerank?: boolean;
  description?: string;
}

export interface SearchProfileStore {
  [name: string]: SearchProfile;
}

export interface SearchExplainInfo {
  profile?: {
    name: string | null;
    appliedConfig: Omit<SearchProfile, "name" | "description">;
  };
  overriddenFields?: string[];
  scoring?: {
    semanticCount: number;
    bm25Count: number;
    entityCount: number;
    threshold: number;
    topK: number;
    weights?: Required<ScoreWeights>;
  };
  rerank?: {
    enabled: boolean;
    provider?: string;
    inputCount?: number;
    outputCount?: number;
  };
  filters?: {
    normalized: Record<string, any>;
    categories?: string[];
  };
}

export interface MultiModalMessages {
  type: "image_url";
  image_url: {
    url: string;
  };
}

export interface Message {
  role: string;
  content: string | MultiModalMessages;
}

export interface EmbeddingConfig {
  apiKey?: string;
  model?: string | any;
  baseURL?: string;
  url?: string;
  embeddingDims?: number;
  modelProperties?: Record<string, any>;
}

export interface VectorStoreConfig {
  collectionName?: string;
  dimension?: number;
  dbPath?: string;
  client?: any;
  instance?: any;
  [key: string]: any;
}

export interface HistoryStoreConfig {
  provider: string;
  config: {
    historyDbPath?: string;
    supabaseUrl?: string;
    supabaseKey?: string;
    tableName?: string;
  };
}

export interface LLMConfig {
  provider?: string;
  baseURL?: string;
  url?: string;
  config?: Record<string, any>;
  apiKey?: string;
  model?: string | any;
  modelProperties?: Record<string, any>;
  timeout?: number;
  temperature?: number;
  topP?: number;
  maxTokens?: number;
}

export interface MemoryConfig {
  version?: string;
  embedder: {
    provider: string;
    config: EmbeddingConfig;
  };
  vectorStore: {
    provider: string;
    config: VectorStoreConfig;
  };
  llm: {
    provider: string;
    config: LLMConfig;
  };
  historyStore?: HistoryStoreConfig;
  reranker?: {
    provider: string;
    config?: Record<string, any>;
  };
  disableHistory?: boolean;
  historyDbPath?: string;
  customInstructions?: string;
  searchProfiles?: SearchProfileStore;
}

export interface MemoryItem {
  id: string;
  memory: string;
  hash?: string;
  createdAt?: string;
  updatedAt?: string;
  score?: number;
  metadata?: Record<string, any>;
}

export interface SearchFilters {
  user_id?: string;
  agent_id?: string;
  run_id?: string;
  [key: string]: any;
}

export interface SearchResult {
  results: MemoryItem[];
}

export interface VectorStoreResult {
  id: string;
  payload: Record<string, any>;
  score?: number;
}

const ScoreWeightsSchema = z.object({
  semanticWeight: z.number().min(0).max(1).optional(),
  bm25Weight: z.number().min(0).max(1).optional(),
  entityBoostWeight: z.number().min(0).max(1).optional(),
});

const SearchProfileSchema = z.object({
  name: z.string().optional(),
  filters: z.record(z.string(), z.any()).optional(),
  categories: z.array(z.string()).optional(),
  topK: z.number().int().min(0).optional(),
  threshold: z.number().min(0).max(1).optional(),
  explain: z.boolean().optional(),
  scoreWeights: ScoreWeightsSchema.optional(),
  rerank: z.boolean().optional(),
  description: z.string().optional(),
});

const SearchProfileStoreSchema = z.record(z.string(), SearchProfileSchema);

export const MemoryConfigSchema = z.object({
  version: z.string().optional(),
  embedder: z.object({
    provider: z.string(),
    config: z.object({
      modelProperties: z.record(z.string(), z.any()).optional(),
      apiKey: z.string().optional(),
      model: z.union([z.string(), z.any()]).optional(),
      baseURL: z.string().optional(),
      embeddingDims: z.number().optional(),
      url: z.string().optional(),
    }),
  }),
  vectorStore: z.object({
    provider: z.string(),
    config: z
      .object({
        collectionName: z.string().optional(),
        dimension: z.number().optional(),
        dbPath: z.string().optional(),
        client: z.any().optional(),
      })
      .passthrough(),
  }),
  llm: z.object({
    provider: z.string(),
    config: z.object({
      apiKey: z.string().optional(),
      model: z.union([z.string(), z.any()]).optional(),
      modelProperties: z.record(z.string(), z.any()).optional(),
      baseURL: z.string().optional(),
      url: z.string().optional(),
      timeout: z.number().optional(),
      temperature: z.number().optional(),
      topP: z.number().optional(),
      maxTokens: z.number().optional(),
    }),
  }),
  historyDbPath: z.string().optional(),
  customInstructions: z.string().optional(),
  historyStore: z
    .object({
      provider: z.string(),
      config: z.record(z.string(), z.any()),
    })
    .optional(),
  disableHistory: z.boolean().optional(),
  searchProfiles: SearchProfileStoreSchema.optional(),
  reranker: z
    .object({
      provider: z.string(),
      config: z.record(z.string(), z.any()).optional(),
    })
    .optional(),
});
