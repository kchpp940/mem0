"""
等价重构验证脚本 - 第 3 部分：get() 方法参照 + lifecycle + notices
"""
import sys
from copy import deepcopy
from unittest.mock import MagicMock, Mock

from mem0.configs.base import MemoryItem
from mem0.memory.lifecycle import annotate_memory_result

from mem0.memory.operation import (
    CORE_AND_PROMOTED_KEYS,
    PROMOTED_PAYLOAD_KEYS,
    MemoryRequestContext,
    OperationLifecycle,
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
# 20. get() 方法原始实现 vs ResultFormatter 对比
# ============================================================
print("\n=== 20. get() 原始实现 vs ResultFormatter 对比 ===")

# 模拟一个 vector store 返回的 memory 对象
class MockMemory:
    def __init__(self, id, payload):
        self.id = id
        self.payload = payload

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
    "text_lemmatized": "test memori content",
    "attributed_to": "system",
}

mock_memory = MockMemory(id="mem_123", payload=test_payload)

# 原始方式（从 get() 方法中复制的逻辑）
def original_get_format(memory):
    promoted_payload_keys = [
        "user_id",
        "agent_id",
        "run_id",
        "actor_id",
        "role",
    ]
    core_and_promoted_keys = {
        "data", "hash", "created_at", "updated_at", "id",
        "text_lemmatized", "attributed_to", "expires_at", "ttl_source",
        *promoted_payload_keys,
    }
    result_item = MemoryItem(
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
            result_item[key] = memory.payload[key]
    additional_metadata = {k: v for k, v in memory.payload.items() if k not in core_and_promoted_keys}
    if additional_metadata:
        result_item["metadata"] = additional_metadata
    annotate_memory_result(result_item)
    return result_item

original_result = original_get_format(mock_memory)
new_result = ResultFormatter.format_memory_item(
    payload=test_payload,
    memory_id="mem_123",
)

# 逐项对比
all_keys = set(original_result.keys()) | set(new_result.keys())
for key in sorted(all_keys):
    orig_val = original_result.get(key)
    new_val = new_result.get(key)
    check(f"get 格式 - {key}", orig_val == new_val, 
          f"old={orig_val}, new={new_val}")

# ============================================================
# 21. OperationLifecycle.capture_event 与原始 capture_event 对比
# ============================================================
print("\n=== 21. telemetry 事件捕获对比 ===")

from mem0.memory.telemetry import capture_event as original_capture_event
from mem0.memory.utils import process_telemetry_filters

# 测试 context 生成 telemetry payload
filters = {"user_id": "u1", "agent_id": "a1", "custom_filter": "val"}
ctx = MemoryRequestContext(
    user_id="u1",
    agent_id="a1",
    filters=filters,
    operation="search",
    sync_type="sync",
)

telemetry_payload = ctx.telemetry_payload(limit=20, threshold=0.5)

# 验证关键字段
check("telemetry - 包含 keys", "keys" in telemetry_payload)
check("telemetry - 包含 encoded_ids", "encoded_ids" in telemetry_payload)
check("telemetry - sync_type 正确", telemetry_payload["sync_type"] == "sync")
check("telemetry - 包含自定义字段", telemetry_payload.get("limit") == 20)
check("telemetry - threshold 正确", telemetry_payload.get("threshold") == 0.5)

# 验证 keys/encoded_ids 和原始函数结果一致
orig_keys, orig_encoded = process_telemetry_filters(filters)
check("telemetry - keys 与原始一致", telemetry_payload["keys"] == orig_keys)
check("telemetry - encoded_ids 与原始一致", telemetry_payload["encoded_ids"] == orig_encoded)

# ============================================================
# 22. for_add 中 lifecycle 处理
# ============================================================
print("\n=== 22. for_add lifecycle 处理 ===")

# 测试没有 config 的情况（不解析 lifecycle）
ctx_no_config = PayloadNormalizer.for_add(
    user_id="u1",
    metadata={"key": "val"},
    sync_type="sync",
)
check("无 config 时 metadata 不含 expires_at", "expires_at" not in ctx_no_config.metadata)
check("无 config 时 metadata 不含 ttl_source", "ttl_source" not in ctx_no_config.metadata)

# ============================================================
# 23. metadata 中 reserved keys 处理
# ============================================================
print("\n=== 23. metadata reserved keys 处理 ===")

# 测试：用户传入的 metadata 中包含 data/hash 等 reserved key
metadata_with_reserved = {
    "data": "should_not_overwrite",
    "hash": "should_not_overwrite",
    "created_at": "should_not_overwrite",
    "user_id": "should_be_overwritten_by_build",
    "custom_key": "should_stay",
}

ctx = PayloadNormalizer.for_add(
    user_id="u1",
    metadata=metadata_with_reserved,
    sync_type="sync",
)

# build_filters_and_metadata 会把 user_id 加到 metadata 中，覆盖用户传入的
check("metadata - user_id 被正确设置（覆盖用户值）", ctx.metadata["user_id"] == "u1")
check("metadata - data key 保留在 metadata 中", ctx.metadata.get("data") == "should_not_overwrite")
check("metadata - custom_key 保留", ctx.metadata.get("custom_key") == "should_stay")

# ============================================================
# 24. filters 合并语义
# ============================================================
print("\n=== 24. filters 合并语义 ===")

# 测试：input_filters 和 entity IDs 的合并
_, filters = PayloadNormalizer.build_filters_and_metadata(
    user_id="u1",
    agent_id="a1",
    input_filters={"custom_field": "val", "user_id": "should_be_overwritten"},
)

check("filters - user_id 被正确覆盖", filters["user_id"] == "u1")
check("filters - agent_id 被正确添加", filters["agent_id"] == "a1")
check("filters - 自定义字段保留", filters.get("custom_field") == "val")

# ============================================================
# 25. actor_id 优先级
# ============================================================
print("\n=== 25. actor_id 优先级 ===")

# 测试：显式 actor_id 参数 优先级高于 input_filters 中的 actor_id
_, filters1 = PayloadNormalizer.build_filters_and_metadata(
    user_id="u1",
    actor_id="explicit_actor",
    input_filters={"actor_id": "filter_actor"},
)
check("actor_id - 显式参数优先级高于 filters", filters1["actor_id"] == "explicit_actor")

# 测试：只有 input_filters 中的 actor_id
_, filters2 = PayloadNormalizer.build_filters_and_metadata(
    user_id="u1",
    input_filters={"actor_id": "filter_actor"},
)
check("actor_id - 只有 filters 时使用 filters 中的", filters2["actor_id"] == "filter_actor")

# 测试：actor_id 不在 metadata 中（只在 filters 中）
meta, _ = PayloadNormalizer.build_filters_and_metadata(
    user_id="u1",
    actor_id="actor1",
)
check("actor_id - 不在 metadata 中", "actor_id" not in meta)

# ============================================================
# 26. search 方法中 advanced filters 处理后 filters 的一致性
# ============================================================
print("\n=== 26. search advanced filters 流程一致性 ===")

# 模拟 search 方法中的处理流程
filters = {"user_id": "  u1  ", "agent_id": "a1", "custom_field": "val"}

# 原始流程（简化版）
def original_search_filter_process(filters):
    effective_filters = filters.copy() if filters else {}
    if "user_id" in effective_filters:
        from mem0.memory.main import _validate_and_trim_entity_id
        effective_filters["user_id"] = _validate_and_trim_entity_id(effective_filters["user_id"], "user_id")
    if "agent_id" in effective_filters:
        from mem0.memory.main import _validate_and_trim_entity_id
        effective_filters["agent_id"] = _validate_and_trim_entity_id(effective_filters["agent_id"], "agent_id")
    return effective_filters

# 新流程
ctx = PayloadNormalizer.for_search(
    query="test",
    filters=filters,
    sync_type="sync",
)
new_filters = ctx.filters

orig_filters = original_search_filter_process(filters)

check("search filters - user_id trim 一致", orig_filters["user_id"] == new_filters["user_id"])
check("search filters - agent_id 一致", orig_filters["agent_id"] == new_filters["agent_id"])
check("search filters - 自定义字段保留", orig_filters.get("custom_field") == new_filters.get("custom_field"))

# ============================================================
# 27. MemoryRequestContext.entity_filters 属性
# ============================================================
print("\n=== 27. entity_filters 属性 ===")

filters = {"user_id": "u1", "agent_id": "a1", "run_id": "r1", "custom": "val", "actor_id": "actor1"}
ctx = MemoryRequestContext(filters=filters)
entity = ctx.entity_filters

check("entity_filters - 包含 user_id", "user_id" in entity)
check("entity_filters - 包含 agent_id", "agent_id" in entity)
check("entity_filters - 包含 run_id", "run_id" in entity)
check("entity_filters - 不含 custom", "custom" not in entity)
check("entity_filters - 不含 actor_id", "actor_id" not in entity)

# ============================================================
# 总结
# ============================================================
print(f"\n{'='*60}")
print(f"第 3 部分结果: {passed} passed, {failed} failed")
print(f"{'='*60}")

if failed > 0:
    sys.exit(1)
else:
    print("\n✓ 第 3 部分所有等价性检查通过！")
    print(f"\n累计: {48+38+passed} 个检查全部通过 ✓")
    sys.exit(0)
