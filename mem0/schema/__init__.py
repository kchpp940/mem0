"""Shared schema contract for memory operations across all layers.

This package provides the canonical field definitions, name mappings,
default values, and validation rules that are consumed by:
- Server Pydantic schemas (server/main.py)
- Python SDK option types (mem0/client/types.py)
- Python CLI backend (cli/python/src/mem0_cli/backend/)
- Node CLI backend (cli/node/src/backend/)

Field drift is eliminated by having every layer reference the same
field names, defaults, and mappings defined here.
"""

from mem0.schema.fields import (
    ADD_API_FIELD_MAP as ADD_API_FIELD_MAP,
    ADD_FIELD_SPECS as ADD_FIELD_SPECS,
    API_TO_CLI_MAP as API_TO_CLI_MAP,
    CLI_TO_API_MAP as CLI_TO_API_MAP,
    DELETE_ALL_FIELD_SPECS as DELETE_ALL_FIELD_SPECS,
    ENTITY_FIELD_SET as ENTITY_FIELD_SET,
    ENTITY_FIELD_SPECS as ENTITY_FIELD_SPECS,
    ENTITY_FIELDS as ENTITY_FIELDS,
    EXPIRES_FORMAT as EXPIRES_FORMAT,
    EXPIRES_FORMAT_DISPLAY as EXPIRES_FORMAT_DISPLAY,
    FIELD_DEFAULTS as FIELD_DEFAULTS,
    FIELD_VALIDATION as FIELD_VALIDATION,
    GET_ALL_FIELD_SPECS as GET_ALL_FIELD_SPECS,
    SCOPE_DISPLAY_NAMES as SCOPE_DISPLAY_NAMES,
    SEARCH_FIELD_SPECS as SEARCH_FIELD_SPECS,
    UPDATE_FIELD_SPECS as UPDATE_FIELD_SPECS,
    FieldSpec as FieldSpec,
    api_to_cli as api_to_cli,
    build_scope_dict as build_scope_dict,
    build_scope_display as build_scope_display,
    cli_to_api as cli_to_api,
    get_add_api_key as get_add_api_key,
    get_search_api_key as get_search_api_key,
    validate_entity_id as validate_entity_id,
    validate_expires as validate_expires,
    validate_field as validate_field,
    validate_filters_contain_entity as validate_filters_contain_entity,
)
from mem0.schema.models import (
    AddMemoryOptions as AddMemoryOptions,
    AddMemoryRequest as AddMemoryRequest,
    DeleteAllMemoryOptions as DeleteAllMemoryOptions,
    DeleteAllMemoryRequest as DeleteAllMemoryRequest,
    GetAllMemoryOptions as GetAllMemoryOptions,
    GetAllMemoryRequest as GetAllMemoryRequest,
    ProjectUpdateOptions as ProjectUpdateOptions,
    SearchMemoryOptions as SearchMemoryOptions,
    SearchMemoryRequest as SearchMemoryRequest,
    UpdateMemoryOptions as UpdateMemoryOptions,
    UpdateMemoryRequest as UpdateMemoryRequest,
)
