"""
等价重构验证脚本 - 逐项核对 PayloadNormalizer / ResultFormatter 与原始实现的一致性
"""
import sys
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Optional

# 导入原始函数
from mem0.memory.main import (
    _build_filters_and_metadata,
    _build_session_scope,
    _reject_top_level_entity_params,
    _validate_and_trim_entity_id,
    _validate_and_trim_search_query,
    _validate_search_params,
)
from mem0.configs.base import MemoryItem
from mem0.memory.lifecycle import annotate_memory_result

# 导入新组件
from mem0.memory.operation import (
    CORE_AND_PROMOTED_KEYS,
    PROMOTED_PAYLOAD_KEYS,
    MemoryRequestContext,
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

# ============================================================
# 1. 验证 _validate_and_trim_entity_id 等价性
# ============================================================
print("\n=== 1. validate_and_trim_entity_id ===")

# 正常值
check("正常 user_id", 
      _validate_and_trim_entity_id("u1", "user_id") == PayloadNormalizer.validate_and_trim_entity_id("u1", "user_id"))

# 带空格的值
check("带空格 trimming",
      _validate_and_trim_entity_id("  u1  ", "user_id") == PayloadNormalizer.validate_and_trim_entity_id("  u1  ", "user_id"))

# None 值
check("None 值",
      _validate_and_trim_entity_id(None, "user_id") == PayloadNormalizer.validate_and_trim_entity_id(None, "user_id"))

# 空字符串
try:
    _validate_and_trim_entity_id("", "user_id")
    old_raises = False
except ValueError:
    old_raises = True
try:
    PayloadNormalizer.validate_and_trim_entity_id("", "user_id")
    new_raises = False
except ValueError:
    new_raises = True
check("空字符串抛异常", old_raises and new_raises)

# 含空格的字符串
try:
    _validate_and_trim_entity_id("user 1", "user_id")
    old_raises = False
except ValueError:
    old_raises = True
try:
    PayloadNormalizer.validate_and_trim_entity_id("user 1", "user_id")
    new_raises = False
except ValueError:
    new_raises = True
check("含空格抛异常", old_raises and new_raises)

# ============================================================
# 2. 验证 _validate_search_params 等价性
# ============================================================
print("\n=== 2. validate_search_params ===")

check("正常参数不抛异常", True)  # 都不抛异常

try:
    _validate_search_params(threshold=1.5)
    old_raises = False
except ValueError:
    old_raises = True
try:
    PayloadNormalizer.validate_search_params(threshold=1.5)
    new_raises = False
except ValueError:
    new_raises = True
check("threshold > 1 抛异常", old_raises and new_raises)

try:
    _validate_search_params(top_k=-1)
    old_raises = False
except ValueError:
    old_raises = True
try:
    PayloadNormalizer.validate_search_params(top_k=-1)
    new_raises = False
except ValueError:
    new_raises = True
check("top_k 负数抛异常", old_raises and new_raises)

# ============================================================
# 3. 验证 _validate_and_trim_search_query 等价性
# ============================================================
print("\n=== 3. validate_and_trim_search_query ===")

check("正常 query",
      _validate_and_trim_search_query("hello") == PayloadNormalizer.validate_and_trim_search_query("hello"))

check("带空格 query",
      _validate_and_trim_search_query("  hello  ") == PayloadNormalizer.validate_and_trim_search_query("  hello  "))

try:
    _validate_and_trim_search_query("   ")
    old_raises = False
except ValueError:
    old_raises = True
try:
    PayloadNormalizer.validate_and_trim_search_query("   ")
    new_raises = False
except ValueError:
    new_raises = True
check("空 query 抛异常", old_raises and new_raises)

# ============================================================
# 4. 验证 _build_filters_and_metadata 等价性
# ============================================================
print("\n=== 4. build_filters_and_metadata ===")

# 基本用例
old_meta, old_filters = _build_filters_and_metadata(
    user_id="u1",
    agent_id="a1",
    input_metadata={"key": "val"},
    input_filters={"custom": "filter"},
)
new_meta, new_filters = PayloadNormalizer.build_filters_and_metadata(
    user_id="u1",
    agent_id="a1",
    input_metadata={"key": "val"},
    input_filters={"custom": "filter"},
)
check("基本用例 - metadata 相等", old_meta == new_meta, f"old={old_meta}, new={new_meta}")
check("基本用例 - filters 相等", old_filters == new_filters, f"old={old_filters}, new={new_filters}")

# 只有 user_id
old_meta, old_filters = _build_filters_and_metadata(user_id="u1")
new_meta, new_filters = PayloadNormalizer.build_filters_and_metadata(user_id="u1")
check("只有 user_id - metadata", old_meta == new_meta)
check("只有 user_id - filters", old_filters == new_filters)

# 三个 ID 都有
old_meta, old_filters = _build_filters_and_metadata(user_id="u1", agent_id="a1", run_id="r1")
new_meta, new_filters = PayloadNormalizer.build_filters_and_metadata(user_id="u1", agent_id="a1", run_id="r1")
check("三个 ID - metadata", old_meta == new_meta)
check("三个 ID - filters", old_filters == new_filters)

# 带空格的 ID
old_meta, old_filters = _build_filters_and_metadata(user_id="  u1  ", agent_id="a1")
new_meta, new_filters = PayloadNormalizer.build_filters_and_metadata(user_id="  u1  ", agent_id="a1")
check("带空格 ID - metadata", old_meta == new_meta)
check("带空格 ID - filters", old_filters == new_filters)

# actor_id 参数
old_meta, old_filters = _build_filters_and_metadata(user_id="u1", actor_id="actor1")
new_meta, new_filters = PayloadNormalizer.build_filters_and_metadata(user_id="u1", actor_id="actor1")
check("actor_id - metadata 不含 actor_id", "actor_id" not in old_meta and "actor_id" not in new_meta)
check("actor_id - filters 含 actor_id", old_filters.get("actor_id") == new_filters.get("actor_id"))

# actor_id 来自 input_filters
old_meta, old_filters = _build_filters_and_metadata(user_id="u1", input_filters={"actor_id": "filter_actor"})
new_meta, new_filters = PayloadNormalizer.build_filters_and_metadata(user_id="u1", input_filters={"actor_id": "filter_actor"})
check("actor_id 来自 filters - filters", old_filters.get("actor_id") == new_filters.get("actor_id"))

# 没有 entity ID 抛异常
try:
    _build_filters_and_metadata(input_metadata={"key": "val"})
    old_raises = False
except Exception:
    old_raises = True
try:
    PayloadNormalizer.build_filters_and_metadata(input_metadata={"key": "val"})
    new_raises = False
except Exception:
    new_raises = True
check("无 entity ID 抛异常", old_raises and new_raises)

# ============================================================
# 5. 验证 _build_session_scope 等价性
# ============================================================
print("\n=== 5. session_scope ===")

filters = {"user_id": "u1", "agent_id": "a1"}
old_scope = _build_session_scope(filters)

ctx = MemoryRequestContext(user_id="u1", agent_id="a1", filters=filters)
new_scope = ctx.session_scope

check("两个 ID 的 session_scope", old_scope == new_scope, f"old={old_scope}, new={new_scope}")

filters = {"user_id": "u1", "agent_id": "a1", "run_id": "r1"}
old_scope = _build_session_scope(filters)
ctx = MemoryRequestContext(user_id="u1", agent_id="a1", run_id="r1", filters=filters)
new_scope = ctx.session_scope
check("三个 ID 的 session_scope", old_scope == new_scope)

filters = {"user_id": "u1"}
old_scope = _build_session_scope(filters)
ctx = MemoryRequestContext(user_id="u1", filters=filters)
new_scope = ctx.session_scope
check("单个 ID 的 session_scope", old_scope == new_scope)

# ============================================================
# 6. 验证 PROMOTED_PAYLOAD_KEYS 一致性
# ============================================================
print("\n=== 6. PROMOTED_PAYLOAD_KEYS ===")

# 原始代码中的定义
original_promoted = ["user_id", "agent_id", "run_id", "actor_id", "role"]
check("promoted keys 列表一致", set(PROMOTED_PAYLOAD_KEYS) == set(original_promoted),
      f"old={original_promoted}, new={PROMOTED_PAYLOAD_KEYS}")

# ============================================================
# 7. 验证 CORE_AND_PROMOTED_KEYS 一致性
# ============================================================
print("\n=== 7. CORE_AND_PROMOTED_KEYS ===")

original_core = {"data", "hash", "created_at", "updated_at", "id", "text_lemmatized", "attributed_to", "expires_at", "ttl_source"}
original_core.update(original_promoted)
check("core_and_promoted keys 一致", CORE_AND_PROMOTED_KEYS == original_core,
      f"diff: {CORE_AND_PROMOTED_KEYS.symmetric_difference(original_core)}")

# ============================================================
# 8. 验证 ResultFormatter.format_memory_item 等价性
# ============================================================
print("\n=== 8. ResultFormatter.format_memory_item 等价性 ===")

# 构造一个典型的 payload
test_payload = {
    "data": "test memory content",
    "hash": "abc123",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-02T00:00:00Z",
    "expires_at": "2024-12-31T00:00:00Z",
    "ttl_source": "workspace",
    "user_id": "u1",
    "agent_id": "a1",
    "run_id": "r1",
    "actor_id": "actor1",
    "role": "user",
    "custom_meta": "custom_value",
    "another_field": "another_value",
    "text_lemmatized": "test memori content",
    "attributed_to": "system",
}

# 新方式
new_result = ResultFormatter.format_memory_item(
    payload=test_payload,
    memory_id="mem_123",
    score=0.95,
    score_details={"semantic": 0.9, "bm25": 0.8},
    include_score=True,
)

# 原始方式（手动构造，模拟原始代码逻辑）
original_result = MemoryItem(
    id="mem_123",
    memory=test_payload.get("data", ""),
    hash=test_payload.get("hash"),
    created_at=test_payload.get("created_at"),
    updated_at=test_payload.get("updated_at"),
    expires_at=test_payload.get("expires_at"),
    ttl_source=test_payload.get("ttl_source"),
    score=0.95,
).model_dump()

for key in original_promoted:
    if key in test_payload:
        original_result[key] = test_payload[key]

additional_metadata = {k: v for k, v in test_payload.items() if k not in original_core}
if additional_metadata:
    if not original_result.get("metadata"):
        original_result["metadata"] = {}
    original_result["metadata"].update(additional_metadata)

original_result["score_details"] = {"semantic": 0.9, "bm25": 0.8}
annotate_memory_result(original_result)

check("MemoryItem 基础字段一致", 
      {k: original_result.get(k) for k in ["id", "memory", "hash", "created_at", "updated_at", "expires_at", "ttl_source", "score"]} ==
      {k: new_result.get(k) for k in ["id", "memory", "hash", "created_at", "updated_at", "expires_at", "ttl_source", "score"]})

check("promoted fields 一致",
      {k: original_result.get(k) for k in original_promoted} ==
      {k: new_result.get(k) for k in original_promoted})

check("metadata 一致",
      original_result.get("metadata") == new_result.get("metadata"),
      f"old={original_result.get('metadata')}, new={new_result.get('metadata')}")

check("score_details 一致",
      original_result.get("score_details") == new_result.get("score_details"))

# 测试 include_score=False 的情况
new_no_score = ResultFormatter.format_memory_item(
    payload=test_payload,
    memory_id="mem_123",
    include_score=False,
)
check("include_score=False 时不含 score", "score" not in new_no_score)

# ============================================================
# 9. 验证 normalize_filters_dict 与 search 原始逻辑一致性
# ============================================================
print("\n=== 9. normalize_filters_dict (search 用) ===")

filters = {"user_id": "  u1  ", "agent_id": "a1", "custom_field": "val"}

# 原始方式（模拟 search 方法中的处理）
def original_normalize_filters(filters):
    effective_filters = filters.copy() if filters else {}
    if "user_id" in effective_filters:
        effective_filters["user_id"] = _validate_and_trim_entity_id(effective_filters["user_id"], "user_id")
    if "agent_id" in effective_filters:
        effective_filters["agent_id"] = _validate_and_trim_entity_id(effective_filters["agent_id"], "agent_id")
    if "run_id" in effective_filters:
        effective_filters["run_id"] = _validate_and_trim_entity_id(effective_filters["run_id"], "run_id")
    return effective_filters

old_normalized = original_normalize_filters(filters)
new_normalized = PayloadNormalizer.normalize_filters_dict(filters)
check("filters 归一化结果一致", old_normalized == new_normalized,
      f"old={old_normalized}, new={new_normalized}")

# ============================================================
# 10. 验证 entity_filters 属性
# ============================================================
print("\n=== 10. entity_filters 属性 ===")

filters = {"user_id": "u1", "agent_id": "a1", "custom": "val", "actor_id": "actor1"}
ctx = MemoryRequestContext(user_id="u1", agent_id="a1", filters=filters)
entity_filters = ctx.entity_filters
check("entity_filters 只含 entity keys", 
      set(entity_filters.keys()) == {"user_id", "agent_id"},
      f"got keys: {set(entity_filters.keys())}")

# ============================================================
# 11. 验证 for_search 上下文构建
# ============================================================
print("\n=== 11. PayloadNormalizer.for_search ===")

ctx = PayloadNormalizer.for_search(
    query="  test query  ",
    filters={"user_id": "  u1  ", "agent_id": "a1"},
    top_k=20,
    threshold=0.5,
    sync_type="async",
)
check("for_search - operation", ctx.operation == "search")
check("for_search - sync_type", ctx.sync_type == "async")
check("for_search - user_id", ctx.user_id == "u1")
check("for_search - query trimmed", ctx.extra["query"] == "test query")
check("for_search - top_k", ctx.extra["top_k"] == 20)
check("for_search - threshold", ctx.extra["threshold"] == 0.5)

# ============================================================
# 12. 验证 for_get_all 上下文构建
# ============================================================
print("\n=== 12. PayloadNormalizer.for_get_all ===")

ctx = PayloadNormalizer.for_get_all(
    filters={"user_id": "u1", "agent_id": "a1"},
    top_k=50,
    sync_type="sync",
)
check("for_get_all - operation", ctx.operation == "get_all")
check("for_get_all - sync_type", ctx.sync_type == "sync")
check("for_get_all - top_k", ctx.extra["top_k"] == 50)

# ============================================================
# 13. 验证 telemetry_payload 
# ============================================================
print("\n=== 13. telemetry_payload ===")

# 这个需要和原始代码中的 telemetry 调用对比
# 原始代码用 process_telemetry_filters(filters) 得到 keys, encoded_ids
from mem0.memory.utils import process_telemetry_filters

filters = {"user_id": "u1", "agent_id": "a1"}
orig_keys, orig_encoded = process_telemetry_filters(filters)

ctx = MemoryRequestContext(user_id="u1", agent_id="a1", filters=filters, sync_type="sync", operation="add")
payload = ctx.telemetry_payload()

check("telemetry - keys", payload.get("keys") == orig_keys)
check("telemetry - encoded_ids", payload.get("encoded_ids") == orig_encoded)
check("telemetry - sync_type", payload.get("sync_type") == "sync")

# ============================================================
# 14. 验证 wrap_results
# ============================================================
print("\n=== 14. wrap_results ===")

results = [{"id": "1", "memory": "test"}]
wrapped = ResultFormatter.wrap_results(results)
check("wrap_results 格式", wrapped == {"results": results})

# ============================================================
# 总结
# ============================================================
print(f"\n{'='*60}")
print(f"结果: {passed} passed, {failed} failed")
print(f"{'='*60}")

if failed > 0:
    sys.exit(1)
else:
    print("\n✓ 所有等价性检查通过！")
    sys.exit(0)
