"""
等价重构验证脚本 - 第 2 部分：深入核对 ResultFormatter 和 Lifecycle
"""
import sys
from copy import deepcopy

from mem0.configs.base import MemoryItem
from mem0.memory.lifecycle import annotate_memory_result

from mem0.memory.operation import (
    CORE_AND_PROMOTED_KEYS,
    PROMOTED_PAYLOAD_KEYS,
    PayloadNormalizer,
    ResultFormatter,
)

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name} - {detail}")

def original_format_search_result(scored_results, explain=False):
    """模拟原始 _search_vector_store 中的结果格式化逻辑"""
    promoted_payload_keys = [
        "user_id",
        "agent_id",
        "run_id",
        "actor_id",
        "role",
    ]
    core_and_promoted_keys = {"data", "hash", "created_at", "updated_at", "id", "text_lemmatized", "attributed_to", "expires_at", "ttl_source", *promoted_payload_keys}

    original_memories = []
    for scored in scored_results:
        payload = scored.get("payload") or {}
        if not payload.get("data"):
            continue

        memory_item_dict = MemoryItem(
            id=scored["id"],
            memory=payload.get("data", ""),
            hash=payload.get("hash"),
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
            expires_at=payload.get("expires_at"),
            ttl_source=payload.get("ttl_source"),
            score=scored["score"],
        ).model_dump()

        for key in promoted_payload_keys:
            if key in payload:
                memory_item_dict[key] = payload[key]

        additional_metadata = {k: v for k, v in payload.items() if k not in core_and_promoted_keys}
        if additional_metadata:
            if not memory_item_dict.get("metadata"):
                memory_item_dict["metadata"] = {}
            memory_item_dict["metadata"].update(additional_metadata)
        if explain and "score_details" in scored:
            memory_item_dict["score_details"] = scored["score_details"]

        annotate_memory_result(memory_item_dict)
        original_memories.append(memory_item_dict)

    return original_memories


# ============================================================
# 15. format_search_results 等价性
# ============================================================
print("\n=== 15. format_search_results 等价性 ===")

test_scored_results = [
    {
        "id": "mem_1",
        "score": 0.95,
        "payload": {
            "data": "test memory 1",
            "hash": "abc123",
            "created_at": "2024-01-01",
            "updated_at": "2024-01-02",
            "expires_at": "2024-12-31",
            "ttl_source": "workspace",
            "user_id": "u1",
            "agent_id": "a1",
            "run_id": "r1",
            "actor_id": "actor1",
            "role": "user",
            "custom_field": "custom_val",
            "text_lemmatized": "test memori 1",
            "attributed_to": "system",
        },
        "score_details": {"semantic": 0.9, "bm25": 0.8},
    },
    {
        "id": "mem_2",
        "score": 0.85,
        "payload": {
            "data": "test memory 2",
            "hash": "def456",
            "created_at": "2024-02-01",
            "updated_at": "2024-02-02",
            "user_id": "u2",
            "another_meta": "another_val",
        },
    },
    {
        "id": "mem_empty",
        "score": 0.5,
        "payload": {
            "data": "",  # 空 data 应该被跳过
            "user_id": "u3",
        },
    },
]

original = original_format_search_result(test_scored_results, explain=True)
new_result = ResultFormatter.format_search_results(test_scored_results, explain=True)

check("结果数量一致", len(original) == len(new_result), f"old={len(original)}, new={len(new_result)}")

for i, (o, n) in enumerate(zip(original, new_result)):
    check(f"结果 {i} - id 一致", o.get("id") == n.get("id"))
    check(f"结果 {i} - memory 一致", o.get("memory") == n.get("memory"))
    check(f"结果 {i} - score 一致", o.get("score") == n.get("score"))
    check(f"结果 {i} - promoted fields 一致", 
          {k: o.get(k) for k in PROMOTED_PAYLOAD_KEYS} == {k: n.get(k) for k in PROMOTED_PAYLOAD_KEYS})
    check(f"结果 {i} - metadata 一致", 
          o.get("metadata") == n.get("metadata"),
          f"old={o.get('metadata')}, new={n.get('metadata')}")
    check(f"结果 {i} - score_details 一致", 
          o.get("score_details") == n.get("score_details"))
    check(f"结果 {i} - expires_at/ttl_source 一致",
          o.get("expires_at") == n.get("expires_at") and o.get("ttl_source") == n.get("ttl_source"))

# 测试 explain=False
original_no_explain = original_format_search_result(test_scored_results, explain=False)
new_no_explain = ResultFormatter.format_search_results(test_scored_results, explain=False)
check("explain=False 时不含 score_details", 
      "score_details" not in original_no_explain[0] and "score_details" not in new_no_explain[0])

# ============================================================
# 16. format_list_results 等价性
# ============================================================
print("\n=== 16. format_list_results 等价性 ===")

class MockVectorPoint:
    def __init__(self, id, payload):
        self.id = id
        self.payload = payload

def original_format_list_result(memories):
    """模拟原始 _get_all_from_vector_store 中的结果格式化逻辑"""
    promoted_payload_keys = [
        "user_id",
        "agent_id",
        "run_id",
        "actor_id",
        "role",
    ]
    core_and_promoted_keys = {"data", "hash", "created_at", "updated_at", "id", "text_lemmatized", "attributed_to", "expires_at", "ttl_source", *promoted_payload_keys}

    formatted = []
    for memory in memories:
        memory_item_dict = MemoryItem(
            id=memory.id,
            memory=memory.payload.get("data", ""),
            hash=memory.payload.get("hash"),
            created_at=memory.payload.get("created_at"),
            updated_at=memory.payload.get("updated_at"),
            expires_at=memory.payload.get("expires_at"),
            ttl_source=memory.payload.get("ttl_source"),
        ).model_dump()

        for key in promoted_payload_keys:
            if key in memory.payload:
                memory_item_dict[key] = memory.payload[key]

        additional_metadata = {k: v for k, v in memory.payload.items() if k not in core_and_promoted_keys}
        if additional_metadata:
            if not memory_item_dict.get("metadata"):
                memory_item_dict["metadata"] = {}
            memory_item_dict["metadata"].update(additional_metadata)

        annotate_memory_result(memory_item_dict)
        formatted.append(memory_item_dict)

    return formatted

test_points = [
    MockVectorPoint(
        id="mem_1",
        payload={
            "data": "memory 1",
            "hash": "h1",
            "created_at": "2024-01-01",
            "updated_at": "2024-01-02",
            "expires_at": "2024-12-31",
            "ttl_source": "workspace",
            "user_id": "u1",
            "agent_id": "a1",
            "custom_meta": "val1",
        }
    ),
    MockVectorPoint(
        id="mem_2",
        payload={
            "data": "memory 2",
            "hash": "h2",
            "created_at": "2024-02-01",
            "updated_at": "2024-02-02",
            "user_id": "u2",
            "another_meta": "val2",
        }
    ),
]

original_list = original_format_list_result(test_points)
new_list = ResultFormatter.format_list_results(test_points)

check("list 结果数量一致", len(original_list) == len(new_list))

for i, (o, n) in enumerate(zip(original_list, new_list)):
    check(f"list 结果 {i} - id 一致", o.get("id") == n.get("id"))
    check(f"list 结果 {i} - memory 一致", o.get("memory") == n.get("memory"))
    check(f"list 结果 {i} - score 为 None", o.get("score") is None and n.get("score") is None)
    check(f"list 结果 {i} - promoted fields 一致",
          {k: o.get(k) for k in PROMOTED_PAYLOAD_KEYS} == {k: n.get(k) for k in PROMOTED_PAYLOAD_KEYS})
    check(f"list 结果 {i} - metadata 一致",
          o.get("metadata") == n.get("metadata"),
          f"old={o.get('metadata')}, new={n.get('metadata')}")

# 测试 tuple/list 包裹的情况（某些 vector store 返回 (list, ...) 格式）
wrapped_points = (test_points,)  # tuple 包裹
new_wrapped = ResultFormatter.format_list_results(wrapped_points)
check("tuple 包裹的结果能正确解包", len(new_wrapped) == len(test_points))

nested_list = [test_points]  # list 包裹
new_nested = ResultFormatter.format_list_results(nested_list)
check("list 包裹的结果能正确解包", len(new_nested) == len(test_points))

# ============================================================
# 17. for_add - user_id/agent_id/run_id 应该被 trim
# ============================================================
print("\n=== 17. for_add - entity ID 应该被 trim ===")

ctx = PayloadNormalizer.for_add(
    user_id="  u1  ",
    agent_id="  a1  ",
    run_id="  r1  ",
    metadata={"key": "val"},
    sync_type="sync",
)

check("for_add - user_id 已 trim", ctx.user_id == "u1", f"got: {repr(ctx.user_id)}")
check("for_add - agent_id 已 trim", ctx.agent_id == "a1", f"got: {repr(ctx.agent_id)}")
check("for_add - run_id 已 trim", ctx.run_id == "r1", f"got: {repr(ctx.run_id)}")
check("for_add - filters 中的 user_id 一致", ctx.filters["user_id"] == ctx.user_id)
check("for_add - metadata 中的 user_id 一致", ctx.metadata["user_id"] == ctx.user_id)

# ============================================================
# 18. session_scope 一致性
# ============================================================
print("\n=== 18. session_scope 一致性 ===")

from mem0.memory.main import _build_session_scope

filters = {"user_id": "u1", "agent_id": "a1", "run_id": "r1"}
old_scope = _build_session_scope(filters)

ctx = PayloadNormalizer.for_add(
    user_id="u1",
    agent_id="a1",
    run_id="r1",
    sync_type="sync",
)
check("for_add 的 session_scope 与原始一致", 
      ctx.session_scope == old_scope,
      f"old={old_scope}, new={ctx.session_scope}")

ctx2 = PayloadNormalizer.for_search(
    query="test",
    filters=filters,
    sync_type="sync",
)
check("for_search 的 session_scope 与原始一致",
      ctx2.session_scope == old_scope,
      f"old={old_scope}, new={ctx2.session_scope}")

# ============================================================
# 19. reject_top_level_entity_params 等价性
# ============================================================
print("\n=== 19. reject_top_level_entity_params 等价性 ===")

from mem0.memory.main import _reject_top_level_entity_params

try:
    _reject_top_level_entity_params({"user_id": "u1"}, "search")
    old_raises = False
except ValueError:
    old_raises = True

try:
    PayloadNormalizer.reject_top_level_entity_params({"user_id": "u1"}, "search")
    new_raises = False
except ValueError:
    new_raises = True

check("top-level user_id 抛异常", old_raises and new_raises)

try:
    _reject_top_level_entity_params({"custom": "val"}, "search")
    old_raises = False
except ValueError:
    old_raises = True

try:
    PayloadNormalizer.reject_top_level_entity_params({"custom": "val"}, "search")
    new_raises = False
except ValueError:
    new_raises = True

check("没有 top-level entity 不抛异常", not old_raises and not new_raises)

# ============================================================
# 总结
# ============================================================
print(f"\n{'='*60}")
print(f"第 2 部分结果: {passed} passed, {failed} failed")
print(f"{'='*60}")

if failed > 0:
    sys.exit(1)
else:
    print("\n✓ 第 2 部分所有等价性检查通过！")
    sys.exit(0)
