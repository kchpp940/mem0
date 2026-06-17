/// <reference types="jest" />

import { scoreAndRank } from "../src/utils/scoring";

describe("scoreAndRank", () => {
  const results = [
    { id: "a", score: 0.8, payload: { data: "mem a" } },
    { id: "b", score: 0.5, payload: { data: "mem b" } },
  ];

  it("omits score_details by default", () => {
    const scored = scoreAndRank(results, {}, {}, 0.1, 10);
    expect(scored[0].score_details).toBeUndefined();
    expect(scored[1].score_details).toBeUndefined();
  });

  it("omits score_details when explain is false", () => {
    const scored = scoreAndRank(results, {}, {}, 0.1, 10, false);
    expect(scored[0].score_details).toBeUndefined();
  });

  it("includes score_details when explain is true", () => {
    const bm25 = { a: 0.6 };
    const entity = { a: 0.3 };
    const scored = scoreAndRank(results, bm25, entity, 0.1, 10, true);

    const details = scored[0].score_details!;
    expect(details).toBeDefined();
    expect(details.semantic_score).toBe(0.8);
    expect(details.bm25_score).toBe(0.6);
    expect(details.entity_boost).toBe(0.3);
    expect(details.raw_score).toBeCloseTo(1.7);
    expect(details.max_possible_score).toBe(2.5);
    expect(details.final_score).toBeCloseTo(0.68);
    expect(details.threshold).toBe(0.1);
  });

  it("includes score_details for results without bm25/entity signals", () => {
    const scored = scoreAndRank(results, {}, {}, 0.1, 10, true);

    const details = scored[0].score_details!;
    expect(details.semantic_score).toBe(0.8);
    expect(details.bm25_score).toBe(0);
    expect(details.entity_boost).toBe(0);
    expect(details.raw_score).toBe(0.8);
    expect(details.max_possible_score).toBe(1.0);
    expect(details.final_score).toBe(0.8);
  });

  it("marks degraded_from_hybrid when pool status is degraded", () => {
    const poolStatus = {
      semantic_ok: false,
      keyword_ok: true,
      entity_ok: false,
      degraded: true,
      degradation_reason: "Semantic search failed",
    };
    const keywordResults = [
      { id: "k1", score: 0, payload: { data: "mem k1" } },
    ];
    const bm25 = { k1: 0.7 };
    const scored = scoreAndRank(
      keywordResults,
      bm25,
      {},
      0.1,
      10,
      true,
      poolStatus,
    );

    expect(scored[0].degraded_from_hybrid).toBe(true);
    expect(scored[0].score_details!.pool_status).toEqual(poolStatus);
  });
});
