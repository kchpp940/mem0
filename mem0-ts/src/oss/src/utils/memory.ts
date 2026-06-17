import { OpenAILLM } from "../llms/openai";
import { Message } from "../types";
import type { PoolStatus } from "../types";

const get_image_description = async (image_url: string) => {
  const llm = new OpenAILLM({
    apiKey: process.env.OPENAI_API_KEY,
  });
  const response = await llm.generateResponse([
    {
      role: "user",
      content:
        "Provide a description of the image and do not include any additional text.",
    },
    {
      role: "user",
      content: { type: "image_url", image_url: { url: image_url } },
    },
  ]);
  return response;
};

const parse_vision_messages = async (messages: Message[]) => {
  const parsed_messages = [];
  for (const message of messages) {
    let new_message = {
      role: message.role,
      content: "",
    };
    if (message.role !== "system") {
      if (
        typeof message.content === "object" &&
        message.content.type === "image_url"
      ) {
        const description = await get_image_description(
          message.content.image_url.url,
        );
        new_message.content =
          typeof description === "string"
            ? description
            : JSON.stringify(description);
        parsed_messages.push(new_message);
      } else parsed_messages.push(message);
    }
  }
  return parsed_messages;
};

function _getPayload(mem: any): Record<string, any> {
  if (mem && typeof mem === "object" && "payload" in mem) {
    return mem.payload || {};
  }
  if (mem && typeof mem === "object" && "get" in mem) {
    return mem.payload || {};
  }
  return {};
}

function _getId(mem: any): string | null {
  if (mem == null) return null;
  if (typeof mem.id === "string" || typeof mem.id === "number") {
    return String(mem.id);
  }
  return null;
}

function _getScore(mem: any): number {
  if (mem == null) return 0.0;
  const s = mem.score;
  if (typeof s === "number") return s;
  return 0.0;
}

export interface Candidate {
  id: string;
  score: number;
  payload: Record<string, any>;
  sources: string[];
}

export function buildCandidatePool(
  semanticResults: Array<any> | null,
  keywordCandidates: Record<string, Record<string, any>>,
  entityBoosts: Record<string, number>,
  vectorStoreGet: ((id: string) => any) | null,
  precomputedEntityPayloads?: Record<string, Record<string, any>>,
): [Candidate[], PoolStatus] {
  const poolStatus: PoolStatus = {
    semantic_ok: semanticResults !== null,
    keyword_ok: Object.keys(keywordCandidates).length > 0,
    entity_ok: Object.keys(entityBoosts).length > 0,
    degraded: false,
  };

  const seen = new Map<string, Candidate>();

  if (semanticResults !== null) {
    for (const mem of semanticResults) {
      const memId = _getId(mem);
      if (memId == null) continue;
      seen.set(memId, {
        id: memId,
        score: _getScore(mem),
        payload: _getPayload(mem),
        sources: ["semantic"],
      });
    }
  }

  for (const [memId, payload] of Object.entries(keywordCandidates)) {
    const existing = seen.get(memId);
    if (existing) {
      existing.sources.push("keyword");
    } else {
      seen.set(memId, {
        id: memId,
        score: 0.0,
        payload,
        sources: ["keyword"],
      });
    }
  }

  const entityOnlyIds: string[] = [];
  for (const memId of Object.keys(entityBoosts)) {
    const existing = seen.get(memId);
    if (existing) {
      if (!existing.sources.includes("entity")) {
        existing.sources.push("entity");
      }
    } else {
      entityOnlyIds.push(memId);
    }
  }

  if (entityOnlyIds.length > 0) {
    if (precomputedEntityPayloads) {
      for (const memId of entityOnlyIds) {
        const payload = precomputedEntityPayloads[memId];
        if (payload) {
          seen.set(memId, {
            id: memId,
            score: 0.0,
            payload,
            sources: ["entity"],
          });
        }
      }
    } else if (vectorStoreGet) {
      try {
        for (const memId of entityOnlyIds) {
          const result = vectorStoreGet(memId);
          if (result != null) {
            let payload = _getPayload(result);
            if (
              Object.keys(payload).length === 0 &&
              typeof result === "object" &&
              result !== null
            ) {
              payload = result as Record<string, any>;
            }
            seen.set(memId, {
              id: memId,
              score: 0.0,
              payload,
              sources: ["entity"],
            });
          }
        }
      } catch (e) {
        console.warn("Failed to fetch payloads for entity-only candidates:", e);
      }
    }
  }

  if (
    !poolStatus.semantic_ok &&
    (poolStatus.keyword_ok || poolStatus.entity_ok)
  ) {
    poolStatus.degraded = true;
    poolStatus.degradation_reason =
      "Semantic search failed; results from keyword/entity lanes only";
  }

  return [Array.from(seen.values()), poolStatus];
}

export { parse_vision_messages };
