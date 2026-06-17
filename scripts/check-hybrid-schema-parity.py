#!/usr/bin/env python3
"""Cross-language schema parity checker for hybrid search.

The single source of truth (SSOT) for hybrid search field contracts is the
Python module ``mem0.utils.hybrid_search_schema``.  This script compares
the TypedDicts defined there against the TypeScript interfaces in
``mem0-ts/src/oss/src/types/index.ts`` and fails the build if any of the
following drift:

* field names (must match exactly, snake_case on both sides)
* optionality (``Optional[...]`` in Python ↔ ``?`` in TypeScript)
* which schemas are defined on each side (PoolStatus, ScoreDetails,
  SearchResultItem, Candidate)

The checker is intentionally stdlib-only so it can run in any Python 3.9+
environment without installing extra dependencies (the same constraint as
``scripts/check-llms-txt-coverage.py``).

Modes
-----
default      read-only; exits 1 if any drift is found.
--generate   (reserved for future) emit a .ts sidecar file derived from
             the Python SSOT instead of checking parity.

Exit codes
----------
0  schemas are in sync
1  drift detected
2  invocation / environment error (e.g. Python module not importable)
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import typing
from typing import Any, Dict, List, Set, Tuple


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PY_SCHEMA_MODULE = "mem0.utils.hybrid_search_schema"
TS_SCHEMA_PATH = REPO_ROOT / "mem0-ts" / "src" / "oss" / "src" / "types" / "index.ts"

# Map from the TypedDict class name in the SSOT to the TypeScript interface name
# in the TS source.  If a schema exists only on one side, that is drift too.
SCHEMA_NAME_MAP: Dict[str, str] = {
    "PoolStatusSchema": "PoolStatus",
    "ScoreDetailsSchema": "ScoreDetails",
    "CandidateSchema": "Candidate",
    "SearchResultItemSchema": "MemoryItem",
}

# For SearchResultItemSchema ↔ MemoryItem, the TS interface has legacy
# camelCase fields (createdAt, updatedAt) that predate the hybrid search
# schema and are serialized differently by each runtime.  The parity
# checker only validates the hybrid-specific snake_case fields listed
# below; anything else in MemoryItem is out of scope for this check.
HYBRID_SNAKE_CASE_FIELDS: Set[str] = {
    "score_details",
    "degraded_from_hybrid",
    "user_id",
    "agent_id",
    "run_id",
}


# ---------------------------------------------------------------------------
# Python side — extract via typing.get_type_hints
# ---------------------------------------------------------------------------


def _is_optional(hint: Any) -> Tuple[bool, str]:
    """Return (is_optional, bare_type_name) for a typing hint.

    We intentionally reduce complex types to a human-readable type name
    rather than deep-comparing them across languages, because the
    cross-language parity we care about is *field presence* and
    *optionality*, not the exact Python/TS type representation (which
    cannot map perfectly anyway).
    """
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    # Optional[X] ≡ Union[X, None]
    if origin is typing.Union and len(args) == 2 and type(None) in args:
        non_none = [a for a in args if a is not type(None)][0]
        return True, _type_name(non_none)
    # TypedDict with total=False → every field is optional; handled at class level.
    return False, _type_name(hint)


def _type_name(hint: Any) -> str:
    if hint is type(None):
        return "None"
    if hint is Any:
        return "Any"
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    if origin is not None and args:
        arg_names = ", ".join(_type_name(a) for a in args)
        return f"{origin.__name__}[{arg_names}]"
    if hasattr(hint, "__name__"):
        return hint.__name__
    return str(hint)


def extract_python_schemas() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Load the SSOT module and return ``{schema_name: {field: {optional, type}}}``.

    ``schema_name`` is the TypeScript-side interface name (e.g. ``PoolStatus``,
    not ``PoolStatusSchema``) so it lines up with the TS extractor output.
    """
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    try:
        module = __import__(PY_SCHEMA_MODULE, fromlist=["*"])
    except Exception as exc:  # noqa: BLE001 — surface import failure clearly
        print(
            f"ERROR: cannot import Python schema module {PY_SCHEMA_MODULE!r}: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)

    result: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for py_cls_name, ts_iface_name in SCHEMA_NAME_MAP.items():
        cls = getattr(module, py_cls_name, None)
        if cls is None:
            print(
                f"ERROR: Python schema class {py_cls_name!r} not found in {PY_SCHEMA_MODULE}",
                file=sys.stderr,
            )
            sys.exit(2)

        # TypedDict with total=False → every field is optional by default.
        # We additionally honour per-field Optional[] annotations.
        cls_total = cls.__dict__.get("__total__")
        if cls_total is None:
            # typing.TypedDict in 3.9+ stores it on the class directly
            cls_total = getattr(cls, "__total__", True)
        total_default = bool(cls_total)

        hints = typing.get_type_hints(cls)
        fields: Dict[str, Dict[str, Any]] = {}
        for field, hint in hints.items():
            # MemoryItem has legacy camelCase fields; only check the hybrid
            # snake_case subset so we don't flag non-hybrid drift.
            if ts_iface_name == "MemoryItem" and field not in HYBRID_SNAKE_CASE_FIELDS:
                continue
            hint_optional, hint_type = _is_optional(hint)
            optional = (not total_default) or hint_optional
            fields[field] = {"optional": optional, "type": hint_type}
        result[ts_iface_name] = fields

    return result


# ---------------------------------------------------------------------------
# TypeScript side — parse via AST-lite regex
# ---------------------------------------------------------------------------


_TS_IFACE_RE = re.compile(
    r"export\s+interface\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\{(?P<body>.*?)\n\}",
    re.DOTALL,
)
_TS_FIELD_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<opt>\?)?\s*:\s*(?P<type>[^;]+?)(?:;|$)",
    re.MULTILINE,
)


def extract_ts_schemas() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Return ``{iface_name: {field: {optional, type}}}`` from the TS types file."""
    if not TS_SCHEMA_PATH.exists():
        print(
            f"ERROR: TypeScript schema file not found at {TS_SCHEMA_PATH}",
            file=sys.stderr,
        )
        sys.exit(2)

    source = TS_SCHEMA_PATH.read_text(encoding="utf-8")
    result: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for m in _TS_IFACE_RE.finditer(source):
        iface_name = m.group("name")
        if iface_name not in set(SCHEMA_NAME_MAP.values()):
            continue  # only the schemas covered by SCHEMA_NAME_MAP matter here
        fields: Dict[str, Dict[str, Any]] = {}
        for fm in _TS_FIELD_RE.finditer(m.group("body")):
            fname = fm.group("name")
            # MemoryItem has legacy camelCase fields; only check the hybrid
            # snake_case subset so we don't flag non-hybrid drift.
            if iface_name == "MemoryItem" and fname not in HYBRID_SNAKE_CASE_FIELDS:
                continue
            optional = fm.group("opt") is not None
            ftype = fm.group("type").strip()
            # Collapse TS unions with null to "optional" in our schema view
            if (
                re.search(r"\|\s*(?:null|undefined)", ftype)
                or ftype.endswith(" | undefined")
                or ftype.endswith("| null")
            ):
                optional = True
                ftype = re.sub(r"\s*\|\s*(?:null|undefined)\s*", "", ftype).strip()
            fields[fname] = {"optional": optional, "type": ftype}
        result[iface_name] = fields

    return result


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def compare_schemas(
    py: Dict[str, Dict[str, Dict[str, Any]]],
    ts: Dict[str, Dict[str, Dict[str, Any]]],
) -> List[str]:
    """Return a list of human-readable drift descriptions (empty = in sync)."""
    errors: List[str] = []

    all_names: Set[str] = set(py) | set(ts)
    for name in sorted(all_names):
        py_fields = py.get(name)
        ts_fields = ts.get(name)

        if py_fields is None:
            errors.append(f"[{name}] present in TS but missing from Python SSOT")
            continue
        if ts_fields is None:
            errors.append(
                f"[{name}] present in Python SSOT ({_py_cls_name(name)}) but missing from TS {TS_SCHEMA_PATH.name}"
            )
            continue

        all_fields: Set[str] = set(py_fields) | set(ts_fields)
        for field in sorted(all_fields):
            pf = py_fields.get(field)
            tf = ts_fields.get(field)

            if pf is None:
                errors.append(f"[{name}.{field}] present in TS ({TS_SCHEMA_PATH.name}) but missing from Python SSOT")
                continue
            if tf is None:
                errors.append(f"[{name}.{field}] present in Python SSOT ({_py_cls_name(name)}) but missing from TS")
                continue

            # Optionality must match.  Types are compared loosely (just presence).
            if pf["optional"] != tf["optional"]:
                errors.append(
                    f"[{name}.{field}] optionality mismatch: "
                    f"Python={'optional' if pf['optional'] else 'required'}, "
                    f"TS={'optional' if tf['optional'] else 'required'}"
                )

    return errors


def _py_cls_name(ts_name: str) -> str:
    """Reverse-lookup SCHEMA_NAME_MAP for error messages."""
    for py, ts in SCHEMA_NAME_MAP.items():
        if ts == ts_name:
            return py
    return ts_name


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--generate",
        action="store_true",
        help="(reserved) emit TS sidecar from Python SSOT instead of checking",
    )
    args = parser.parse_args()

    if args.generate:
        print("--generate is reserved for future use; exiting", file=sys.stderr)
        return 2

    py_schemas = extract_python_schemas()
    ts_schemas = extract_ts_schemas()
    errors = compare_schemas(py_schemas, ts_schemas)

    if not errors:
        schemas = ", ".join(sorted(py_schemas))
        print(f"OK: hybrid search schemas in sync ({schemas})")
        return 0

    print("DRIFT DETECTED between Python SSOT and TypeScript interfaces:", file=sys.stderr)
    print(file=sys.stderr)
    for e in errors:
        print(f"  - {e}", file=sys.stderr)
    print(file=sys.stderr)
    print(
        f"Python SSOT: {PY_SCHEMA_MODULE}  (file: {REPO_ROOT / 'mem0' / 'utils' / 'hybrid_search_schema.py'})",
        file=sys.stderr,
    )
    print(f"TypeScript:  {TS_SCHEMA_PATH}", file=sys.stderr)
    print(
        "Update the TypeScript interfaces to match the Python TypedDicts, "
        "or vice-versa after confirming the change is intentional.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
