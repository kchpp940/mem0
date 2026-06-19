import { createClient, SupabaseClient } from "@supabase/supabase-js";
import { VectorStore } from "./base";
import { SearchFilters, VectorStoreConfig, VectorStoreResult } from "../types";
import { buildSupabaseFilters } from "../utils/filter_normalizer";

interface VectorData {
  id: string;
  embedding: number[];
  metadata: Record<string, any>;
  [key: string]: any;
}

interface VectorQueryParams {
  query_embedding: number[];
  match_count: number;
  filter?: SearchFilters;
}

interface VectorSearchResult {
  id: string;
  similarity: number;
  metadata: Record<string, any>;
  [key: string]: any;
}

interface SupabaseConfig extends VectorStoreConfig {
  supabaseUrl: string;
  supabaseKey: string;
  tableName: string;
  embeddingColumnName?: string;
  metadataColumnName?: string;
}

/*
SQL Migration to run in Supabase SQL Editor:

-- Enable the vector extension
create extension if not exists vector;

-- Create the memories table
create table if not exists memories (
  id text primary key,
  embedding vector(1536),
  metadata jsonb,
  created_at timestamp with time zone default timezone('utc', now()),
  updated_at timestamp with time zone default timezone('utc', now())
);

-- Create the memory migrations table
create table if not exists memory_migrations (
  user_id text primary key,
  created_at timestamp with time zone default timezone('utc', now())
);

-- Create the vector similarity search function
create or replace function match_vectors(
  query_embedding vector(1536),
  match_count int,
  filter jsonb default '{}'::jsonb
)
returns table (
  id text,
  similarity float,
  metadata jsonb
)
language plpgsql
as $$
declare
  categories_arr text[];
  categories_nin_arr text[];
  scalar_filter jsonb;
begin
  -- Extract categories overlap filter (sent by SDK)
  categories_arr := ARRAY(SELECT jsonb_array_elements_text(filter->'$categoriesOverlap'));
  categories_nin_arr := ARRAY(SELECT jsonb_array_elements_text(filter->'$categoriesNin'));
  -- Remove sentinel keys to get the scalar @> filter
  scalar_filter := filter - '$categoriesOverlap' - '$categoriesNin';

  return query
  select
    t.id::text,
    1 - (t.embedding <=> query_embedding) as similarity,
    t.metadata
  from memories t
  where case
    when scalar_filter::text = '{}'::text then true
    else t.metadata @> scalar_filter
  end
  and case
    when array_length(categories_arr, 1) is null then true
    else t.metadata->'categories' ?| categories_arr
  end
  and case
    when array_length(categories_nin_arr, 1) is null then true
    else NOT (t.metadata->'categories' ?| categories_nin_arr)
  end
  order by t.embedding <=> query_embedding
  limit match_count;
end;
$$;
*/

export class SupabaseDB implements VectorStore {
  private client: SupabaseClient;
  private readonly tableName: string;
  private readonly embeddingColumnName: string;
  private readonly metadataColumnName: string;
  private _initPromise?: Promise<void>;

  constructor(config: SupabaseConfig) {
    this.client = createClient(config.supabaseUrl, config.supabaseKey);
    this.tableName = config.tableName;
    this.embeddingColumnName = config.embeddingColumnName || "embedding";
    this.metadataColumnName = config.metadataColumnName || "metadata";

    this.initialize().catch((err) => {
      console.error("Failed to initialize Supabase:", err);
      throw err;
    });
  }

  async initialize(): Promise<void> {
    if (!this._initPromise) {
      this._initPromise = this._doInitialize();
    }
    return this._initPromise;
  }

  private async _doInitialize(): Promise<void> {
    try {
      // Verify table exists and vector operations work by attempting a test insert
      const testVector = Array(1536).fill(0);

      // First try to delete any existing test vector
      try {
        await this.client.from(this.tableName).delete().eq("id", "test_vector");
      } catch {
        // Ignore delete errors - table might not exist yet
      }

      // Try to insert the test vector
      const { error: insertError } = await this.client
        .from(this.tableName)
        .insert({
          id: "test_vector",
          [this.embeddingColumnName]: testVector,
          [this.metadataColumnName]: {},
        })
        .select();

      // If we get a duplicate key error, that's actually fine - it means the table exists
      if (insertError && insertError.code !== "23505") {
        console.error("Test insert error:", insertError);
        throw new Error(
          `Vector operations failed. Please ensure:
1. The vector extension is enabled
2. The table "${this.tableName}" exists with correct schema
3. The match_vectors function is created

RUN THE FOLLOWING SQL IN YOUR SUPABASE SQL EDITOR:

-- Enable the vector extension
create extension if not exists vector;

-- Create the memories table
create table if not exists memories (
  id text primary key,
  embedding vector(1536),
  metadata jsonb,
  created_at timestamp with time zone default timezone('utc', now()),
  updated_at timestamp with time zone default timezone('utc', now())
);

-- Create the memory migrations table
create table if not exists memory_migrations (
  user_id text primary key,
  created_at timestamp with time zone default timezone('utc', now())
);

-- Create the vector similarity search function
create or replace function match_vectors(
  query_embedding vector(1536),
  match_count int,
  filter jsonb default '{}'::jsonb
)
returns table (
  id text,
  similarity float,
  metadata jsonb
)
language plpgsql
as $$
declare
  categories_arr text[];
  categories_nin_arr text[];
  scalar_filter jsonb;
begin
  -- Extract categories overlap filter (sent by SDK)
  categories_arr := ARRAY(SELECT jsonb_array_elements_text(filter->'$categoriesOverlap'));
  categories_nin_arr := ARRAY(SELECT jsonb_array_elements_text(filter->'$categoriesNin'));
  -- Remove sentinel keys to get the scalar @> filter
  scalar_filter := filter - '$categoriesOverlap' - '$categoriesNin';

  return query
  select
    t.id::text,
    1 - (t.embedding <=> query_embedding) as similarity,
    t.metadata
  from memories t
  where case
    when scalar_filter::text = '{}'::text then true
    else t.metadata @> scalar_filter
  end
  and case
    when array_length(categories_arr, 1) is null then true
    else t.metadata->'categories' ?| categories_arr
  end
  and case
    when array_length(categories_nin_arr, 1) is null then true
    else NOT (t.metadata->'categories' ?| categories_nin_arr)
  end
  order by t.embedding <=> query_embedding
  limit match_count;
end;
$$;

See the SQL migration instructions in the code comments.`,
        );
      }

      // Clean up test vector - ignore errors here too
      try {
        await this.client.from(this.tableName).delete().eq("id", "test_vector");
      } catch {
        // Ignore delete errors
      }

      console.log("Connected to Supabase successfully");
    } catch (error) {
      console.error("Error during Supabase initialization:", error);
      throw error;
    }
  }

  async insert(
    vectors: number[][],
    ids: string[],
    payloads: Record<string, any>[],
  ): Promise<void> {
    try {
      const data = vectors.map((vector, idx) => ({
        id: ids[idx],
        [this.embeddingColumnName]: vector,
        [this.metadataColumnName]: {
          ...payloads[idx],
          created_at: new Date().toISOString(),
        },
      }));

      const { error } = await this.client.from(this.tableName).insert(data);

      if (error) throw error;
    } catch (error) {
      console.error("Error during vector insert:", error);
      throw error;
    }
  }

  async keywordSearch(): Promise<null> {
    return null;
  }

  async search(
    query: number[],
    topK: number = 5,
    filters?: SearchFilters,
  ): Promise<VectorStoreResult[]> {
    try {
      const built = buildSupabaseFilters(filters);
      const rpcQuery: VectorQueryParams = {
        query_embedding: query,
        match_count: topK,
      };

      if (filters && Object.keys(built.rpcFilter).length > 0) {
        rpcQuery.filter = built.rpcFilter;
      }

      const { data, error } = await this.client.rpc("match_vectors", rpcQuery);

      if (error) throw error;
      if (!data) return [];

      const results = data as VectorSearchResult[];
      return results.map((result) => ({
        id: result.id,
        payload: result.metadata,
        score: result.similarity,
      }));
    } catch (error) {
      console.error("Error during vector search:", error);
      throw error;
    }
  }

  async get(vectorId: string): Promise<VectorStoreResult | null> {
    try {
      const { data, error } = await this.client
        .from(this.tableName)
        .select("*")
        .eq("id", vectorId)
        .maybeSingle();

      if (error) throw error;
      if (!data) return null;

      return {
        id: data.id,
        payload: data[this.metadataColumnName],
      };
    } catch (error) {
      console.error("Error getting vector:", error);
      throw error;
    }
  }

  async update(
    vectorId: string,
    vector: number[],
    payload: Record<string, any>,
  ): Promise<void> {
    try {
      const { error } = await this.client
        .from(this.tableName)
        .update({
          [this.embeddingColumnName]: vector,
          [this.metadataColumnName]: {
            ...payload,
            updated_at: new Date().toISOString(),
          },
        })
        .eq("id", vectorId);

      if (error) throw error;
    } catch (error) {
      console.error("Error during vector update:", error);
      throw error;
    }
  }

  async delete(vectorId: string): Promise<void> {
    try {
      const { error } = await this.client
        .from(this.tableName)
        .delete()
        .eq("id", vectorId);

      if (error) throw error;
    } catch (error) {
      console.error("Error deleting vector:", error);
      throw error;
    }
  }

  async deleteCol(): Promise<void> {
    try {
      const { error } = await this.client
        .from(this.tableName)
        .delete()
        .neq("id", ""); // Delete all rows

      if (error) throw error;
    } catch (error) {
      console.error("Error deleting collection:", error);
      throw error;
    }
  }

  async list(
    filters?: SearchFilters,
    topK: number = 100,
  ): Promise<[VectorStoreResult[], number]> {
    try {
      const built = buildSupabaseFilters(filters);
      let query = this.client
        .from(this.tableName)
        .select("*", { count: "exact" })
        .limit(topK);

      if (filters && built.clientConditions.length > 0) {
        // Use raw SQL via .or/.filter or .sql() for complex conditions
        const condition = built.clientConditions.join(" AND ");
        query = query.or(condition, { foreignTable: undefined } as any) as any;
        // Note: Supabase JS client doesn't easily support arbitrary
        // parameterized SQL with ?| operators, so we use .gte("id", "")
        // trick + .sql() or raw rpc. For simple categories filters the
        // RPC path is preferred. For list() we use best-effort.
      }

      // Fallback: for simple filters that aren't categories, still apply them
      // via the standard eq() builder (skips categories which are handled above)
      if (filters) {
        const normalized = buildSupabaseFilters(filters);
        for (const [key, value] of Object.entries(normalized.rpcFilter)) {
          if (key.startsWith("$")) continue; // skip sentinels
          if (typeof value === "object" && value !== null) continue; // skip op-style
          query = query.eq(`${this.metadataColumnName}->>${key}`, value);
        }
      }

      const { data, error, count } = await query;

      if (error) throw error;

      const results = data.map((item: VectorData) => ({
        id: item.id,
        payload: item[this.metadataColumnName],
      }));

      return [results, count || 0];
    } catch (error) {
      console.error("Error listing vectors:", error);
      throw error;
    }
  }

  async getUserId(): Promise<string> {
    try {
      // First check if the table exists
      const { data: tableExists } = await this.client
        .from("memory_migrations")
        .select("user_id")
        .limit(1);

      if (!tableExists || tableExists.length === 0) {
        // Generate a random user_id
        const randomUserId =
          Math.random().toString(36).substring(2, 15) +
          Math.random().toString(36).substring(2, 15);

        // Insert the new user_id
        const { error: insertError } = await this.client
          .from("memory_migrations")
          .insert({ user_id: randomUserId });

        if (insertError) throw insertError;
        return randomUserId;
      }

      // Get the first user_id
      const { data, error } = await this.client
        .from("memory_migrations")
        .select("user_id")
        .limit(1);

      if (error) throw error;
      if (!data || data.length === 0) {
        // Generate a random user_id if no data found
        const randomUserId =
          Math.random().toString(36).substring(2, 15) +
          Math.random().toString(36).substring(2, 15);

        const { error: insertError } = await this.client
          .from("memory_migrations")
          .insert({ user_id: randomUserId });

        if (insertError) throw insertError;
        return randomUserId;
      }

      return data[0].user_id;
    } catch (error) {
      console.error("Error getting user ID:", error);
      return "anonymous-supabase";
    }
  }

  async setUserId(userId: string): Promise<void> {
    try {
      const { error: deleteError } = await this.client
        .from("memory_migrations")
        .delete()
        .neq("user_id", "");

      if (deleteError) throw deleteError;

      const { error: insertError } = await this.client
        .from("memory_migrations")
        .insert({ user_id: userId });

      if (insertError) throw insertError;
    } catch (error) {
      console.error("Error setting user ID:", error);
    }
  }
}
