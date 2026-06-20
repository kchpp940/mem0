"""TypeScript schema code generator.

Generates TypeScript type definitions and runtime constants from the Python
schema definitions in ``mem0.schema.fields`` and ``mem0.schema.models``.

This ensures the TypeScript side (Node CLI, TypeScript SDK) stays in sync
with the Python single source of truth.

Usage:
    python -m mem0.schema.generator --output cli/node/src/schema/
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from mem0.schema.fields import (
    ADD_API_FIELD_MAP,
    ADD_FIELD_SPECS,
    CLI_TO_API_MAP,
    CORE_PAYLOAD_KEYS,
    DELETE_ALL_FIELD_SPECS,
    ENTITY_FIELD_SPECS,
    ENTITY_FIELDS,
    EXPIRES_FORMAT,
    EXPIRES_FORMAT_DISPLAY,
    EXPORT_FIELDS,
    FEEDBACK_VALUES,
    FIELD_DEFAULTS,
    FIELD_VALIDATION,
    GET_ALL_FIELD_SPECS,
    HISTORY_RESPONSE_FIELDS,
    IMPORT_FIELDS,
    MEMORY_RESPONSE_FIELDS,
    PROMOTED_PAYLOAD_KEYS,
    SCOPE_DISPLAY_NAMES,
    SEARCH_API_FIELD_MAP,
    SEARCH_FIELD_SPECS,
    FieldSpec,
)


# ─── Public API ───────────────────────────────────────────────────────────────


def generate_ts_schema(output_dir: str) -> Dict[str, str]:
    """Generate TypeScript schema files from Python definitions.

    Args:
        output_dir: Directory to write generated files to.

    Returns:
        Dict mapping filename -> file contents.
    """
    fields_ts = _generate_fields_ts()
    index_ts = _generate_index_ts()

    return {
        "fields.ts": fields_ts,
        "index.ts": index_ts,
    }


def export_json_schema() -> Dict[str, Any]:
    """Export the full schema contract as a JSON-serializable dict.

    This can be used for validation, documentation, or generating code
    in other languages.

    Returns:
        Dict with the complete schema contract.
    """
    return {
        "$version": 2,
        "description": "Canonical schema contract for Mem0 memory operations. Generated from Python Pydantic models.",
        "entityFields": list(ENTITY_FIELDS),
        "defaults": dict(FIELD_DEFAULTS),
        "cliToApiMap": dict(CLI_TO_API_MAP),
        "addApiFieldMap": dict(ADD_API_FIELD_MAP),
        "searchApiFieldMap": dict(SEARCH_API_FIELD_MAP),
        "scopeDisplayNames": dict(SCOPE_DISPLAY_NAMES),
        "expiresFormat": EXPIRES_FORMAT,
        "expiresFormatDisplay": EXPIRES_FORMAT_DISPLAY,
        "fieldValidation": dict(FIELD_VALIDATION),
        "corePayloadKeys": list(CORE_PAYLOAD_KEYS),
        "promotedPayloadKeys": list(PROMOTED_PAYLOAD_KEYS),
        "memoryResponseFields": list(MEMORY_RESPONSE_FIELDS),
        "historyResponseFields": list(HISTORY_RESPONSE_FIELDS),
        "feedbackValues": list(FEEDBACK_VALUES),
        "exportFields": list(EXPORT_FIELDS),
        "importFields": list(IMPORT_FIELDS),
    }


# ─── TypeScript generation helpers ───────────────────────────────────────────


_TS_TYPE_MAP = {
    "str": "string",
    "int": "number",
    "float": "number",
    "bool": "boolean",
    "Dict[str, Any]": "Record<string, any>",
    "Dict[str, str]": "Record<string, string>",
    "List[str]": "string[]",
    "List[Dict[str, Any]]": "Record<string, any>[]",
    "List[Any]": "any[]",
    "Any": "any",
}


def _py_type_to_ts(py_type: str) -> str:
    """Convert a Python type annotation string to TypeScript.

    Note: Optional[] wrapper is stripped — optionality is expressed via `?` in interfaces.
    """
    base = py_type
    if base.startswith("Optional[") and base.endswith("]"):
        base = base[9:-1]

    return _TS_TYPE_MAP.get(base, base)


def _tsdoc(lines: List[str]) -> str:
    """Format lines as a JSDoc comment."""
    if not lines:
        return ""
    if len(lines) == 1:
        return f"/** {lines[0]} */\n"
    body = "\n".join(f" * {line}" for line in lines)
    return f"/**\n{body}\n */\n"


def _generate_const_array(name: str, values: Tuple[str, ...], description: str) -> str:
    """Generate a TypeScript const array with JSDoc."""
    items = ", ".join(f'"{v}"' for v in values)
    return _tsdoc([description]) + f"export const {name}: readonly string[] = [{items}] as const;\n"


def _generate_const_dict(name: str, data: Dict[str, Any], description: str) -> str:
    """Generate a TypeScript const object with JSDoc."""
    items = ",\n".join(f"  {json.dumps(k)}: {json.dumps(v)}" for k, v in data.items())
    return _tsdoc([description]) + f"export const {name} = {{\n{items},\n}} as const;\n"


def _generate_spec_array(name: str, specs: List[FieldSpec], description: str) -> str:
    """Generate a TypeScript array of field spec objects."""
    items = []
    for spec in specs:
        obj = (
            f"  {{ apiName: {json.dumps(spec.api_name)}, "
            f"cliName: {json.dumps(spec.cli_name)}, "
            f"tsName: {json.dumps(spec.ts_name)}, "
            f"required: {str(spec.required).lower()}, "
            f"description: {json.dumps(spec.description)} }}"
        )
        items.append(obj)
    body = ",\n".join(items)
    return _tsdoc([description]) + f"export const {name} = [\n{body},\n] as const;\n"


def _generate_interface(name: str, specs: List[FieldSpec], description: str) -> str:
    """Generate a TypeScript interface from field specs."""
    lines = [description, ""]
    for spec in specs:
        ts_type = _py_type_to_ts(spec.py_type)
        q = "" if spec.required else "?"
        lines.append(f"@param {spec.ts_name} {spec.description}")
        lines.append(f"{spec.ts_name}{q}: {ts_type};")
    body = "\n  ".join(lines)
    return _tsdoc([description]) + f"export interface {name} {{\n  {body}\n}}\n"


# ─── fields.ts generation ────────────────────────────────────────────────────


def _generate_fields_ts() -> str:
    """Generate the complete fields.ts file."""
    sections: List[str] = []
    sections.append(_header())

    sections.append("// ─── Entity identifiers ───────────────────────────────────────────────")
    sections.append(
        _generate_const_array(
            "ENTITY_FIELDS",
            ENTITY_FIELDS,
            "Canonical entity identifier field names (snake_case, API format).",
        )
    )

    sections.append("// ─── CLI ↔ API name mappings ────────────────────────────────────────")
    sections.append(
        _generate_const_dict(
            "CLI_TO_API_MAP",
            dict(CLI_TO_API_MAP),
            "Map from TypeScript/CLI camelCase field names to API snake_case names.",
        )
    )
    api_to_cli = {v: k for k, v in CLI_TO_API_MAP.items()}
    sections.append(
        _generate_const_dict(
            "API_TO_CLI_MAP",
            api_to_cli,
            "Reverse map from API snake_case field names to TypeScript/CLI camelCase names.",
        )
    )

    sections.append("// ─── Default values ──────────────────────────────────────────────────")
    sections.append(
        _generate_const_dict(
            "FIELD_DEFAULTS",
            dict(FIELD_DEFAULTS),
            "Default values for optional memory operation parameters.",
        )
    )

    sections.append("// ─── Expires validation ──────────────────────────────────────────────")
    sections.append(
        _tsdoc(["Regular expression for validating expires date format (YYYY-MM-DD)."])
        + f'export const EXPIRES_PATTERN = /{EXPIRES_FORMAT[1:-1]}/;\n'
    )
    sections.append(
        _tsdoc(["Human-readable display format for expires date validation errors."])
        + f'export const EXPIRES_FORMAT_DISPLAY = "{EXPIRES_FORMAT_DISPLAY}";\n'
    )
    sections.append(
        _tsdoc(["Error message for invalid expires date format."])
        + 'export const EXPIRES_FORMAT_ERROR = '
        + '"Invalid date format for --expires. Use YYYY-MM-DD (e.g. 2025-12-31).";\n'
    )

    sections.append("// ─── Validation rules ───────────────────────────────────────────────")
    sections.append(_generate_validation_rules())

    sections.append("// ─── API field aliases ──────────────────────────────────────────────")
    sections.append(
        _generate_const_dict(
            "ADD_API_FIELD_MAP",
            ADD_API_FIELD_MAP,
            "Field name aliases for add-memory API payloads (logical name → payload key).",
        )
    )
    sections.append(
        _generate_const_dict(
            "SEARCH_API_FIELD_MAP",
            dict(SEARCH_API_FIELD_MAP),
            "Field name aliases for search API payloads (logical name → payload key).",
        )
    )

    sections.append("// ─── Scope display names ────────────────────────────────────────────")
    sections.append(
        _generate_const_dict(
            "SCOPE_DISPLAY_NAMES",
            dict(SCOPE_DISPLAY_NAMES),
            "Human-readable display names for entity scope fields.",
        )
    )

    sections.append("// ─── Response / payload field classification ────────────────────────")
    sections.append(
        _generate_const_array(
            "CORE_PAYLOAD_KEYS",
            CORE_PAYLOAD_KEYS,
            "Core payload keys that are always present and map to top-level response fields.",
        )
    )
    sections.append(
        _generate_const_array(
            "PROMOTED_PAYLOAD_KEYS",
            PROMOTED_PAYLOAD_KEYS,
            "Payload keys that should be promoted to top-level response fields (not nested under metadata).",
        )
    )

    sections.append("// ─── Memory response field order ────────────────────────────────────")
    sections.append(
        _generate_const_array(
            "MEMORY_RESPONSE_FIELDS",
            MEMORY_RESPONSE_FIELDS,
            "Canonical field ordering for memory response objects.",
        )
    )

    sections.append("// ─── History response fields ────────────────────────────────────────")
    sections.append(
        _generate_const_array(
            "HISTORY_RESPONSE_FIELDS",
            HISTORY_RESPONSE_FIELDS,
            "Canonical field ordering for history response objects.",
        )
    )

    sections.append("// ─── Feedback values ────────────────────────────────────────────────")
    sections.append(
        _generate_const_array(
            "FEEDBACK_VALUES",
            FEEDBACK_VALUES,
            "Allowed feedback values.",
        )
    )

    sections.append("// ─── Export / Import ───────────────────────────────────────────────")
    sections.append(
        _generate_const_array(
            "EXPORT_FIELDS",
            EXPORT_FIELDS,
            "Fields related to memory export operations.",
        )
    )
    sections.append(
        _generate_const_array(
            "IMPORT_FIELDS",
            IMPORT_FIELDS,
            "Fields related to memory import operations.",
        )
    )

    sections.append("// ─── CLI option interfaces ────────────────────────────────────────")
    sections.append(_generate_cli_interfaces())

    sections.append("// ─── Helper functions ──────────────────────────────────────────────")
    sections.append(_generate_helper_functions())

    return "\n".join(sections)


def _generate_validation_rules() -> str:
    """Generate TypeScript validation rules object."""
    rules = {}
    for name, spec in FIELD_VALIDATION.items():
        rule = {}
        if "min" in spec:
            rule["min"] = spec["min"]
        if "max" in spec:
            rule["max"] = spec["max"]
        if "error" in spec:
            rule["error"] = spec["error"]
        ts_name = _api_to_ts_name(name)
        rules[ts_name] = rule
    items = ",\n".join(f'  "{k}": {json.dumps(v)}' for k, v in rules.items())
    return (
        _tsdoc(["Validation rules for numeric fields (min/max and error messages). Keys are CLI option names (camelCase)."])
        + f"export const VALIDATION_RULES = {{\n{items},\n}} as const;\n"
    )


def _api_to_ts_name(api_name: str) -> str:
    """Convert a snake_case API name to camelCase TypeScript name."""
    parts = api_name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _specs_to_ts_interface(
    name: str, specs: List[FieldSpec], description: str
) -> str:
    """Generate a TypeScript interface from a list of FieldSpec objects.

    Field names are converted from snake_case (api_name) to camelCase (ts_name).
    """
    lines = []
    for spec in specs:
        ts_type = _py_type_to_ts(spec.py_type)
        q = "" if spec.required else "?"
        lines.append(_tsdoc([spec.description]))
        lines.append(f"{spec.ts_name}{q}: {ts_type};")
    body = "\n  ".join(lines)
    return _tsdoc([description]) + f"export interface {name} {{\n  {body}\n}}\n"


def _generate_cli_interfaces() -> str:
    """Generate TypeScript interfaces for CLI option types."""
    sections: List[str] = []

    sections.append(
        _specs_to_ts_interface(
            "EntityIds",
            ENTITY_FIELD_SPECS,
            "Entity identifier fields used for scoping operations.",
        )
    )

    sections.append(
        _specs_to_ts_interface(
            "AddOptions",
            ADD_FIELD_SPECS,
            "Options for the memory add command.",
        )
    )

    sections.append(
        _specs_to_ts_interface(
            "SearchOptions",
            SEARCH_FIELD_SPECS,
            "Options for the memory search command.",
        )
    )

    sections.append(
        _specs_to_ts_interface(
            "ListOptions",
            GET_ALL_FIELD_SPECS,
            "Options for the memory list command.",
        )
    )

    sections.append(
        _specs_to_ts_interface(
            "DeleteOptions",
            DELETE_ALL_FIELD_SPECS,
            "Options for the memory delete-all command.",
        )
    )

    return "\n".join(sections)


def _generate_helper_functions() -> str:
    """Generate TypeScript helper functions."""
    return '''
/**
 * Map a TypeScript/CLI camelCase field name to an API snake_case name.
 * @param cliName The camelCase field name
 * @returns The snake_case API field name
 */
export function cliToApi(cliName: string): string {
  return (CLI_TO_API_MAP as Record<string, string>)[cliName] ?? cliName;
}

/**
 * Map an API snake_case field name to a TypeScript/CLI camelCase name.
 * @param apiName The snake_case API field name
 * @returns The camelCase field name
 */
export function apiToCli(apiName: string): string {
  return (API_TO_CLI_MAP as Record<string, string>)[apiName] ?? apiName;
}

/**
 * Get the API payload key for an add-memory field (handles aliases like expires → expiration_date).
 * @param fieldName The logical field name
 * @returns The key to use in the API payload
 */
export function getAddApiKey(fieldName: string): string {
  return (ADD_API_FIELD_MAP as Record<string, string>)[fieldName] ?? fieldName;
}

/**
 * Get the API payload key for a search field (handles aliases like keyword → keyword_search).
 * @param fieldName The logical field name
 * @returns The key to use in the API payload
 */
export function getSearchApiKey(fieldName: string): string {
  return (SEARCH_API_FIELD_MAP as Record<string, string>)[fieldName] ?? fieldName;
}

/**
 * Build a scope display string from entity IDs (e.g. "user=alice, agent=bot").
 * @param entityIds Object with entity ID values
 * @returns Human-readable scope string
 */
export function buildScopeDisplay(entityIds: Record<string, string | null | undefined>): string {
  const parts: string[] = [];
  for (const field of ENTITY_FIELDS) {
    const value = entityIds[field];
    if (value) {
      const displayName = (SCOPE_DISPLAY_NAMES as Record<string, string>)[field] ?? field;
      parts.push(`${displayName}=${value}`);
    }
  }
  return parts.length > 0 ? parts.join(", ") : "ALL entities";
}

/**
 * Validate an expires date string (format and future check).
 * @param expires Date string in YYYY-MM-DD format
 * @returns The validated date string
 * @throws Error if the date is invalid or in the past
 */
export function validateExpires(expires: string): string {
  if (!EXPIRES_PATTERN.test(expires)) {
    throw new Error(EXPIRES_FORMAT_ERROR);
  }
  const date = new Date(expires);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  if (date <= today) {
    throw new Error("--expires date must be in the future.");
  }
  return expires;
}

/**
 * Validate that a feedback value is one of the allowed values.
 * @param feedback The feedback value to validate
 * @returns The uppercased feedback value if valid
 * @throws Error if the feedback value is not valid
 */
export function validateFeedbackValue(feedback: string): string {
  const upper = feedback.toUpperCase();
  if (!(FEEDBACK_VALUES as readonly string[]).includes(upper)) {
    throw new Error(
      `Invalid feedback value '${feedback}'. ` +
      `Must be one of: ${FEEDBACK_VALUES.join(", ")}.`
    );
  }
  return upper;
}
'''


# ─── index.ts generation ─────────────────────────────────────────────────────


def _generate_index_ts() -> str:
    """Generate the index.ts barrel file."""
    return _header() + """
export {
  ENTITY_FIELDS,
  CLI_TO_API_MAP,
  API_TO_CLI_MAP,
  FIELD_DEFAULTS,
  EXPIRES_PATTERN,
  EXPIRES_FORMAT_DISPLAY,
  EXPIRES_FORMAT_ERROR,
  VALIDATION_RULES,
  ADD_API_FIELD_MAP,
  SEARCH_API_FIELD_MAP,
  SCOPE_DISPLAY_NAMES,
  CORE_PAYLOAD_KEYS,
  PROMOTED_PAYLOAD_KEYS,
  MEMORY_RESPONSE_FIELDS,
  HISTORY_RESPONSE_FIELDS,
  FEEDBACK_VALUES,
  EXPORT_FIELDS,
  IMPORT_FIELDS,
  cliToApi,
  apiToCli,
  getAddApiKey,
  getSearchApiKey,
  buildScopeDisplay,
  validateExpires,
  validateFeedbackValue,
} from "./fields.js";

export type {
  EntityIds,
  AddOptions,
  SearchOptions,
  ListOptions,
  DeleteOptions,
} from "./fields.js";
"""


def _header() -> str:
    """Generate the auto-generated file header."""
    return (
        "// AUTO-GENERATED FILE — DO NOT EDIT DIRECTLY\n"
        "// Generated from mem0/schema/ (Python single source of truth)\n"
        "// Run `python -m mem0.schema.generator --output cli/node/src/schema/` to regenerate\n"
        "\n"
    )


# ─── CLI entry point ─────────────────────────────────────────────────────────


def main() -> None:
    """CLI entry point for generating TypeScript schema files."""
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Generate TypeScript schema from Python definitions")
    parser.add_argument(
        "--output",
        "-o",
        default="cli/node/src/schema",
        help="Output directory for generated TypeScript files (default: cli/node/src/schema)",
    )
    args = parser.parse_args()

    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    files = generate_ts_schema(output_dir)
    for filename, content in files.items():
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w") as f:
            f.write(content)
        print(f"Generated {filepath}")

    print(f"\nDone. Generated {len(files)} files in {output_dir}/")


if __name__ == "__main__":
    main()
