"""TypeScript schema code generator and contract verifier.

Generates TypeScript type definitions, runtime constants, and JSON schema
contracts from the Python schema definitions in ``mem0.schema.fields`` and
``mem0.schema.models``. This ensures the TypeScript side (Node CLI, TypeScript
SDK), JSON contracts, and Python side stay in sync with a single source of
truth.

Generated files are tagged with a ``SOURCE_HASH`` derived from the canonical
Python source (fields.py + models.py + response.py). The companion
``verify_schema()`` function can re-derive the expected hash and reject
stale / hand-edited output before typecheck/lint runs.

Usage:
    # Generate (or regenerate) TypeScript files
    python -m mem0.schema.generator --output cli/node/src/schema/

    # Verify generated files are up-to-date (CI / pre-commit / pretypecheck)
    python -m mem0.schema.generator --check --output cli/node/src/schema/

    # Also emit payload_contract.json (equivalent to the old hand-written file)
    python -m mem0.schema.generator --output cli/node/src/schema/ --emit-json

    # Export full JSON contract to stdout
    python -m mem0.schema.generator --export-json
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
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


# ─── Source files that define the canonical contract ─────────────────────────

_SCHEMA_DIR = Path(__file__).resolve().parent
_CANONICAL_SOURCE_FILES: Tuple[Path, ...] = (
    _SCHEMA_DIR / "fields.py",
    _SCHEMA_DIR / "models.py",
    _SCHEMA_DIR / "response.py",
    _SCHEMA_DIR / "__init__.py",
    _SCHEMA_DIR / "generator.py",
)

_HASH_ALGO = "sha256"
_HASH_PREFIX = "SOURCE_HASH:"
_MANIFEST_FILENAME = "MANIFEST.json"


# ─── Source hash ─────────────────────────────────────────────────────────────


def compute_source_hash() -> str:
    """Derive a stable hash of the Python canonical schema sources.

    The hash covers all files that contribute to the contract definition.
    It is intentionally content-based (not mtime-based) so that it yields
    identical values across machines when the schema is identical.
    """
    hasher = hashlib.new(_HASH_ALGO)
    for path in sorted(_CANONICAL_SOURCE_FILES):
        hasher.update(path.name.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(path.read_bytes())
        hasher.update(b"\x00")
    return hasher.hexdigest()[:16]


# ─── Public API ──────────────────────────────────────────────────────────────


def generate_ts_schema(
    output_dir: str,
    *,
    emit_json_contract: bool = False,
) -> Dict[str, str]:
    """Generate TypeScript schema files (and optional JSON contract) from Python definitions.

    Args:
        output_dir: Directory to write generated files to.
        emit_json_contract: If True, also emit ``payload_contract.json``.

    Returns:
        Dict mapping filename -> file contents.
    """
    source_hash = compute_source_hash()

    fields_ts = _generate_fields_ts(source_hash)
    index_ts = _generate_index_ts(source_hash)

    files: Dict[str, str] = {
        "fields.ts": fields_ts,
        "index.ts": index_ts,
    }

    manifest = _build_manifest(source_hash, list(files.keys()))
    files[_MANIFEST_FILENAME] = json.dumps(manifest, indent=2) + "\n"

    if emit_json_contract:
        files["payload_contract.json"] = json.dumps(export_payload_contract(), indent=2) + "\n"

    return files


def export_json_schema() -> Dict[str, Any]:
    """Export the full schema contract as a JSON-serializable dict.

    This can be used for validation, documentation, or generating code
    in other languages. Covers *all* contract dimensions — not just the
    fields that the old payload_contract.json captured.
    """
    return {
        "$version": 2,
        "$sourceHash": compute_source_hash(),
        "description": "Canonical schema contract for Mem0 memory operations. Generated from Python Pydantic models — DO NOT EDIT by hand.",
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
        "fieldSpecs": {
            "entity": [s.model_dump() for s in ENTITY_FIELD_SPECS],
            "add": [s.model_dump() for s in ADD_FIELD_SPECS],
            "search": [s.model_dump() for s in SEARCH_FIELD_SPECS],
            "getAll": [s.model_dump() for s in GET_ALL_FIELD_SPECS],
            "deleteAll": [s.model_dump() for s in DELETE_ALL_FIELD_SPECS],
        },
    }


def export_payload_contract() -> Dict[str, Any]:
    """Export the CLI payload contract — equivalent to the old hand-written
    ``payload_contract.json``, but derived from the Python SSOT.

    This is a compatibility shim. New code should consume ``export_json_schema()``
    which is richer and versioned.
    """
    return {
        "$version": 2,
        "$sourceHash": compute_source_hash(),
        "description": (
            "Canonical payload contract for Mem0 CLI operations. "
            "AUTO-GENERATED from mem0/schema/*.py — DO NOT EDIT by hand. "
            "Regenerate with `python -m mem0.schema.generator --emit-json`."
        ),
        "source": "CLI",
        "defaults": {
            "top_k": FIELD_DEFAULTS["top_k"],
            "threshold": FIELD_DEFAULTS["threshold"],
            "infer": FIELD_DEFAULTS["infer"],
            "immutable": False,
            "rerank": False,
            "keyword": False,
        },
        "fieldMapping": dict(ADD_API_FIELD_MAP) | dict(SEARCH_API_FIELD_MAP),
        "payloadRules": {
            "immutable": "includeWhenTrue",
            "infer": "includeWhenFalse",
            "source": "always",
        },
        "addFields": [
            {"api": "messages", "from": "messages", "type": "messages_or_content"},
            *[{"api": f, "from": f} for f in list(ENTITY_FIELDS)],
            {"api": "metadata", "from": "metadata"},
            {"api": "immutable", "from": "immutable", "rule": "includeWhenTrue"},
            {"api": "infer", "from": "infer", "rule": "includeWhenFalse"},
            {"api": "expiration_date", "from": "expires", "mapped": True},
            {"api": "categories", "from": "categories"},
            {"api": "source", "literal": "CLI"},
        ],
        "searchFields": [
            {"api": "query", "from": "query", "required": True},
            {"api": "top_k", "from": "top_k", "hasDefault": True},
            {"api": "threshold", "from": "threshold", "hasDefault": True},
            {"api": "filters", "from": "filters", "built": True},
            {"api": "rerank", "from": "rerank", "rule": "includeWhenTrue"},
            {"api": "keyword_search", "from": "keyword", "mapped": True, "rule": "includeWhenTrue"},
            {"api": "fields", "from": "fields"},
            {"api": "source", "literal": "CLI"},
        ],
        "listFields": [
            {"api": "filters", "from": "filters", "built": True},
            {"api": "source", "literal": "CLI"},
        ],
        "addMessageRole": "user",
        "validation": {
            "categories": {"arrayError": "--categories JSON must be an array."},
            "expires": {
                "pattern": EXPIRES_FORMAT,
                "formatError": f"Invalid date format for --expires. Use {EXPIRES_FORMAT_DISPLAY}.",
                "futureError": "--expires date must be in the future.",
            },
            "filters": {
                "objectError": "--filter must be a JSON object.",
                "jsonError": "Invalid JSON in --filter: {error}",
            },
            **{
                k: {"min": v.get("min"), "max": v.get("max"), "error": v.get("error")}
                for k, v in FIELD_VALIDATION.items()
            },
        },
        "filterBuilding": {
            "entityOrder": list(ENTITY_FIELDS),
            "passthroughKeys": ["AND", "OR"],
            "combineOperator": "AND",
            "listExtra": {
                "category": {"field": "categories", "op": "contains"},
                "after": {"field": "created_at", "op": "gte"},
                "before": {"field": "created_at", "op": "lte"},
            },
        },
        "pendingDedup": {
            "statusKey": "status",
            "pendingValue": "PENDING",
            "dedupKey": "event_id",
        },
        "agentPickFields": {
            "add": {
                "pending": ["status", "event_id"],
                "normal": ["id", "memory", "event"],
            },
            "search": ["id", "memory", "score", "created_at", "categories"],
            "list": ["id", "memory", "created_at", "categories"],
            "get": ["id", "memory", "created_at", "updated_at", "categories", "metadata"],
            "update": ["id", "memory"],
            "event_list": ["id", "event_type", "status", "latency", "created_at"],
            "event_status": ["id", "event_type", "status", "latency", "created_at", "updated_at"],
        },
    }


# ─── Verification ────────────────────────────────────────────────────────────


class VerificationError(Exception):
    """Raised when generated schema files fail verification."""


def verify_schema(output_dir: str) -> Tuple[bool, List[str]]:
    """Verify that generated schema files match the current Python source.

    Checks performed:
      1. MANIFEST.json exists and contains a ``SOURCE_HASH``.
      2. Expected hash (re-derived from Python) matches manifest hash.
      3. Every generated file listed in the manifest:
         - exists on disk
         - contains the same ``SOURCE_HASH`` marker in its header
      4. Files were NOT hand-edited after generation (detected via content
         hash inside MANIFEST.json).

    Args:
        output_dir: Directory containing generated schema files.

    Returns:
        Tuple of ``(ok, errors)`` where ``ok`` is True when everything
        matches and ``errors`` is a list of human-readable problem
        descriptions (empty when ``ok``).
    """
    errors: List[str] = []
    out_path = Path(output_dir)

    expected_hash = compute_source_hash()

    manifest_path = out_path / _MANIFEST_FILENAME
    if not manifest_path.is_file():
        errors.append(
            f"Missing {_MANIFEST_FILENAME} — schema was never generated. "
            "Run `python -m mem0.schema.generator --output {output_dir}`."
        )
        return False, errors

    try:
        manifest: Dict[str, Any] = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        errors.append(f"{_MANIFEST_FILENAME} is not valid JSON: {exc}")
        return False, errors

    manifest_hash = manifest.get("sourceHash")
    if not manifest_hash:
        errors.append(f"{_MANIFEST_FILENAME} is missing the 'sourceHash' field.")
        return False, errors

    if manifest_hash != expected_hash:
        errors.append(
            "Source hash mismatch. Python schema changed but generated files are stale.\n"
            f"  Expected (from Python SSOT): {expected_hash}\n"
            f"  Found (in MANIFEST):       {manifest_hash}\n"
            f"  Fix: re-run `python -m mem0.schema.generator --output {output_dir}`."
        )
        return False, errors

    for filename, file_meta in manifest.get("files", {}).items():
        file_path = out_path / filename
        if not file_path.is_file():
            errors.append(f"Missing generated file listed in MANIFEST: {filename}")
            continue

        content = file_path.read_text()

        marker = f"{_HASH_PREFIX}{manifest_hash}"
        if marker not in content:
            errors.append(
                f"File {filename} does not contain the expected {_HASH_PREFIX} marker.\n"
                "This usually means the file was hand-edited after generation or is out of date.\n"
                f"Expected marker: {marker}\n"
                f"Fix: re-run `python -m mem0.schema.generator --output {output_dir}`."
            )
            continue

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        expected_content_hash = file_meta.get("contentHash") if isinstance(file_meta, dict) else None
        if expected_content_hash and content_hash != expected_content_hash:
            errors.append(
                f"File {filename} was modified after generation (content hash mismatch).\n"
                f"  Expected: {expected_content_hash}\n"
                f"  Actual:   {content_hash}\n"
                f"Fix: re-run `python -m mem0.schema.generator --output {output_dir}`."
            )

    return len(errors) == 0, errors


def _build_manifest(source_hash: str, filenames: List[str]) -> Dict[str, Any]:
    """Build the MANIFEST structure (does not write to disk)."""
    return {
        "generatedBy": "mem0.schema.generator",
        "sourceHash": source_hash,
        "hashAlgorithm": _HASH_ALGO,
        "canonicalSources": [str(p.relative_to(_SCHEMA_DIR.parent.parent)) for p in _CANONICAL_SOURCE_FILES],
        "regenerateCommand": "python -m mem0.schema.generator --output cli/node/src/schema/",
        "files": {f: None for f in filenames},
    }


def _finalize_manifest_with_content_hashes(manifest: Dict[str, Any], contents: Dict[str, str]) -> Dict[str, Any]:
    """Fill in per-file content hashes in the manifest so later edits are detectable."""
    new_manifest = dict(manifest)
    file_meta: Dict[str, Any] = {}
    for filename, content in contents.items():
        if filename == _MANIFEST_FILENAME:
            continue
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        file_meta[filename] = {"contentHash": content_hash}
    new_manifest["files"] = file_meta
    return new_manifest


# ─── TypeScript generation helpers ───────────────────────────────────────────


_TS_TYPE_MAP = {
    "str": "string",
    "int": "number",
    "float": "number",
    "bool": "boolean",
    "Dict[str, Any]": "Record<string, unknown>",
    "Dict[str, str]": "Record<string, string>",
    "List[str]": "string[]",
    "List[Dict[str, Any]]": "Record<string, unknown>[]",
    "List[Any]": "unknown[]",
    "Any": "unknown",
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


# ─── fields.ts generation ────────────────────────────────────────────────────


def _generate_fields_ts(source_hash: str) -> str:
    """Generate the complete fields.ts file."""
    sections: List[str] = []
    sections.append(_header(source_hash, "fields.ts"))

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


def _generate_index_ts(source_hash: str) -> str:
    """Generate the index.ts barrel file."""
    return _header(source_hash, "index.ts") + """
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


def _header(source_hash: str, filename: str) -> str:
    """Generate the auto-generated file header with hash marker and loud warnings.

    Marker format (picked up by :func:`verify_schema`):

        // SOURCE_HASH:<16-char-hex>
    """
    return (
        "// ================================================================\n"
        "// 🔒 AUTO-GENERATED FILE — DO NOT EDIT DIRECTLY UNDER ANY CIRCUMSTANCES\n"
        f"// 📄 Source:   mem0/schema/*.py (Python single source of truth for {filename})\n"
        f"// 🔑 {_HASH_PREFIX}{source_hash}\n"
        "// 🛠️  Regenerate: python -m mem0.schema.generator --output cli/node/src/schema/\n"
        "// 🧪  Verify:     python -m mem0.schema.generator --check --output cli/node/src/schema/\n"
        "//\n"
        "// Hand-edits will be REJECTED by the CI / pretypecheck / prelint\n"
        "// pipeline (MANIFEST.json + content hashes). If something here is\n"
        "// wrong, fix the Python schema in mem0/schema/ and regenerate.\n"
        "// ================================================================\n"
        "// biome-ignore format: auto-generated file, formatting is controlled by Python generator\n"
        "// biome-ignore lint/suspicious/noExplicitAny: any/unknown types come from Python's flexible dict types\n"
        "// biome-ignore lint/style/useNamingConvention: const names follow Python convention\n"
        "\n"
    )


# ─── CLI entry point ─────────────────────────────────────────────────────────


def main() -> None:
    """CLI entry point for generating and verifying schema files."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate / verify TypeScript schema from Python definitions (SSOT)"
    )
    parser.add_argument(
        "--output",
        "-o",
        default="cli/node/src/schema",
        help="Output directory for generated files (default: cli/node/src/schema)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify generated files match the Python source instead of writing them.",
    )
    parser.add_argument(
        "--export-json",
        action="store_true",
        help="Print the full JSON schema contract to stdout and exit.",
    )
    parser.add_argument(
        "--emit-json",
        action="store_true",
        help="Also emit payload_contract.json into the output directory.",
    )
    parser.add_argument(
        "--hash",
        action="store_true",
        help="Print the current source hash and exit.",
    )
    args = parser.parse_args()

    if args.hash:
        print(compute_source_hash())
        return

    if args.export_json:
        json.dump(export_json_schema(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    output_dir = args.output

    if args.check:
        ok, errors = verify_schema(output_dir)
        if ok:
            source_hash = compute_source_hash()
            print(f"✅ Schema verification passed. Source hash: {source_hash}")
            sys.exit(0)
        else:
            print("❌ Schema verification FAILED — generated files are stale or hand-edited:\n", file=sys.stderr)
            for i, err in enumerate(errors, 1):
                print(f"  {i}. {err}\n", file=sys.stderr)
            print(
                f"👉  Fix: re-run `python -m mem0.schema.generator --output {output_dir}`\n",
                file=sys.stderr,
            )
            sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    files = generate_ts_schema(output_dir, emit_json_contract=args.emit_json)

    # Compute content hashes AFTER we know the final file contents
    manifest = json.loads(files[_MANIFEST_FILENAME])
    manifest = _finalize_manifest_with_content_hashes(manifest, files)
    files[_MANIFEST_FILENAME] = json.dumps(manifest, indent=2) + "\n"

    written_paths: List[str] = []
    for filename, content in files.items():
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w") as f:
            f.write(content)
        written_paths.append(filepath)
        print(f"Generated {filepath}")

    print(
        f"\nDone. Generated {len(files)} files in {output_dir}/ "
        f"(source hash: {compute_source_hash()})"
    )
    if args.emit_json:
        print("Included payload_contract.json (auto-derived, not hand-written).")


if __name__ == "__main__":
    main()
