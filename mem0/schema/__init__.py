"""Shared schema contract for memory operations across all layers.

This package is the single source of truth (SSOT) for ALL memory-related
field definitions, data models, validation rules, and response formatting.

Consumers:
- Server Pydantic schemas (server/main.py)
- Python SDK option types (mem0/client/types.py)
- Python SDK memory response formatting (mem0/memory/main.py)
- Python CLI backend (cli/python/src/mem0_cli/backend/)
- Node CLI backend (cli/node/src/backend/)  [auto-generated from Python]

Field drift is eliminated by having every layer reference the same
field names, defaults, mappings, and response formatting logic defined here.

TypeScript side is generated from this package via scripts/generate_ts_schema.py.
"""

from mem0.schema.fields import (
    ADD_API_FIELD_MAP as ADD_API_FIELD_MAP,
    ADD_FIELD_SPECS as ADD_FIELD_SPECS,
    API_TO_CLI_MAP as API_TO_CLI_MAP,
    CLI_TO_API_MAP as CLI_TO_API_MAP,
    CORE_AND_PROMOTED_KEY_SET as CORE_AND_PROMOTED_KEY_SET,
    CORE_PAYLOAD_KEYS as CORE_PAYLOAD_KEYS,
    CREATE_EXPORT_FIELD_SPECS as CREATE_EXPORT_FIELD_SPECS,
    DELETE_ALL_FIELD_SPECS as DELETE_ALL_FIELD_SPECS,
    ENTITY_FIELD_SET as ENTITY_FIELD_SET,
    ENTITY_FIELD_SPECS as ENTITY_FIELD_SPECS,
    ENTITY_FIELDS as ENTITY_FIELDS,
    EXPIRES_FORMAT as EXPIRES_FORMAT,
    EXPIRES_FORMAT_DISPLAY as EXPIRES_FORMAT_DISPLAY,
    EXPORT_FIELDS as EXPORT_FIELDS,
    FEEDBACK_FIELD_SPECS as FEEDBACK_FIELD_SPECS,
    FEEDBACK_SET as FEEDBACK_SET,
    FEEDBACK_VALUES as FEEDBACK_VALUES,
    FIELD_DEFAULTS as FIELD_DEFAULTS,
    FIELD_VALIDATION as FIELD_VALIDATION,
    GET_ALL_FIELD_SPECS as GET_ALL_FIELD_SPECS,
    GET_EXPORT_FIELD_SPECS as GET_EXPORT_FIELD_SPECS,
    HISTORY_FIELD_SPECS as HISTORY_FIELD_SPECS,
    HISTORY_RESPONSE_FIELDS as HISTORY_RESPONSE_FIELDS,
    IMPORT_FIELDS as IMPORT_FIELDS,
    MEMORY_RESPONSE_FIELD_SPECS as MEMORY_RESPONSE_FIELD_SPECS,
    MEMORY_RESPONSE_FIELDS as MEMORY_RESPONSE_FIELDS,
    PAYLOAD_TO_RESPONSE_MAP as PAYLOAD_TO_RESPONSE_MAP,
    PROMOTED_PAYLOAD_KEYS as PROMOTED_PAYLOAD_KEYS,
    PROMOTED_PAYLOAD_KEY_SET as PROMOTED_PAYLOAD_KEY_SET,
    SCOPE_DISPLAY_NAMES as SCOPE_DISPLAY_NAMES,
    SEARCH_API_FIELD_MAP as SEARCH_API_FIELD_MAP,
    SEARCH_FIELD_SPECS as SEARCH_FIELD_SPECS,
    UPDATE_FIELD_SPECS as UPDATE_FIELD_SPECS,
    FieldSpec as FieldSpec,
    api_to_cli as api_to_cli,
    build_scope_dict as build_scope_dict,
    build_scope_display as build_scope_display,
    cli_to_api as cli_to_api,
    get_add_api_key as get_add_api_key,
    get_search_api_key as get_search_api_key,
    payload_to_response_key as payload_to_response_key,
    response_to_payload_key as response_to_payload_key,
    validate_entity_id as validate_entity_id,
    validate_expires as validate_expires,
    validate_feedback_value as validate_feedback_value,
    validate_field as validate_field,
    validate_filters_contain_entity as validate_filters_contain_entity,
)
from mem0.schema.models import (
    AddMemoryOptions as AddMemoryOptions,
    AddMemoryRequest as AddMemoryRequest,
    CreateMemoryExportOptions as CreateMemoryExportOptions,
    CreateMemoryExportRequest as CreateMemoryExportRequest,
    DeleteAllMemoryOptions as DeleteAllMemoryOptions,
    DeleteAllMemoryRequest as DeleteAllMemoryRequest,
    FeedbackOptions as FeedbackOptions,
    FeedbackRequest as FeedbackRequest,
    GetAllMemoryOptions as GetAllMemoryOptions,
    GetAllMemoryRequest as GetAllMemoryRequest,
    GetMemoryExportOptions as GetMemoryExportOptions,
    GetMemoryExportRequest as GetMemoryExportRequest,
    MemoryHistoryItem as MemoryHistoryItem,
    MemoryListResponse as MemoryListResponse,
    MemoryResponse as MemoryResponse,
    ProjectUpdateOptions as ProjectUpdateOptions,
    SearchMemoryOptions as SearchMemoryOptions,
    SearchMemoryRequest as SearchMemoryRequest,
    UpdateMemoryOptions as UpdateMemoryOptions,
    UpdateMemoryRequest as UpdateMemoryRequest,
)
from mem0.schema.response import (
    format_memory_item as format_memory_item,
    format_memory_list as format_memory_list,
    format_history_item as format_history_item,
)
from mem0.schema.generator import (
    generate_ts_schema as generate_ts_schema,
    export_json_schema as export_json_schema,
)
