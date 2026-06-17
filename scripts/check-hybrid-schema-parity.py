#!/usr/bin/env python3
"""Cross-language schema parity checker for hybrid search.

The single source of truth (SSOT) for hybrid search field contracts is the
Python module ``mem0/utils/hybrid_search_schema.py``.  This script parses
it with :mod:`ast` (**no runtime import, zero package side effects**) and
compares the TypedDicts found there against the TypeScript interfaces in
``mem0-ts/src/oss/src/types/index.ts``.

The checker also enforces that ``SCHEMA_VERSION`` — bumped on every
intentional schema change — is identical on both sides.

Checked dimensions
------------------
* which schemas exist (name mapping is configurable)
* field names per schema (snake_case, exact match)
* field optionality (``Optional[X]`` / ``X | None`` ↔ ``name?: T`` / ``T | null | undefined``)
* ``SCHEMA_VERSION`` integer constant

The checker is intentionally stdlib-only so it can run in any Python 3.9+
environment without installing extra dependencies.

Modes
-----
default      read-only; exits 1 if any drift is found.
--generate   (reserved for future) emit a .ts sidecar file derived from
             the Python SSOT instead of checking parity.

Exit codes
----------
0  schemas are in sync
1  drift detected
2  invocation / environment error (e.g. schema file missing / unparsable)
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import re
import sys
from typing import Any, Dict, List, Set, Tuple


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PY_SCHEMA_PATH = REPO_ROOT / "mem0" / "utils" / "hybrid_search_schema.py"
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
# Python side — AST-based static parse (no imports, no side effects)
# ---------------------------------------------------------------------------


def _annotation_is_optional(node: ast.expr) -> Tuple[bool, str]:
    """Return (is_optional, human_readable_type_name) for an AST annotation.

    Handles:
    * ``Optional[X]``      → (True, "X")
    * ``X | None``         → (True, "X")
    * ``Union[X, None]``   → (True, "X")
    * plain names / subscripts → (False, rendered name)
    """
    # typing.Optional[X]  →  ast.Subscript(value=ast.Name(id='Optional'), slice=X)
    # typing.Union[X, None]  →  ast.Subscript(value=ast.Name(id='Union'), slice=Tuple)
    # X | None  →  ast.BinOp(left=X, op=ast.BitOr(), right=ast.Constant(value=None))
    # X | None | Y  →  ast.BinOp with nested BinOp left

    none_names = {"None", "NoneType"}

    def _name(n: ast.expr) -> str:
        if isinstance(n, ast.Name):
            return n.id
        if isinstance(n, ast.Constant) and n.value is None:
            return "None"
        if isinstance(n, ast.Subscript):
            base = _name(n.value)
            if isinstance(n.slice, ast.Tuple):
                inner = ", ".join(_name(e) for e in n.slice.elts)
            else:
                inner = _name(n.slice)
            return f"{base}[{inner}]"
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr):
            return f"{_name(n.left)} | {_name(n.right)}"
        if isinstance(n, ast.Constant):
            return repr(n.value)
        return ast.unparse(n) if hasattr(ast, "unparse") else "<annotation>"

    def _collect_union_parts(n: ast.expr, *, inside_optional: bool = False) -> List[str]:
        """Flatten ``Union[X, Y]`` / ``X | Y | Z`` / ``Optional[X]`` into a list of names.

        ``Optional[X]`` is treated as ``Union[X, None]`` even though its AST
        does not literally contain a ``None`` element.
        """
        parts: List[str] = []
        if (
            isinstance(n, ast.Subscript)
            and isinstance(n.value, ast.Name)
            and n.value.id
            in {
                "Union",
                "Optional",
            }
        ):
            inner_is_optional = n.value.id == "Optional"
            if isinstance(n.slice, ast.Tuple):
                for e in n.slice.elts:
                    parts.extend(_collect_union_parts(e, inside_optional=inner_is_optional))
            else:
                parts.extend(_collect_union_parts(n.slice, inside_optional=inner_is_optional))
            if inner_is_optional:
                parts.append("None")
        elif isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr):
            parts.extend(_collect_union_parts(n.left, inside_optional=inside_optional))
            parts.extend(_collect_union_parts(n.right, inside_optional=inside_optional))
        else:
            parts.append(_name(n))
        return parts

    parts = _collect_union_parts(node)
    has_none = any(p in none_names for p in parts)
    non_none = [p for p in parts if p not in none_names]
    if has_none:
        return True, " | ".join(non_none) if non_none else "None"
    return False, _name(node)


def _class_has_total_false(cls: ast.ClassDef) -> bool:
    """Detect ``class Foo(TypedDict, total=False): ...``."""
    for kw in getattr(cls, "keywords", []) or []:
        if kw.arg == "total" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
            return True
    # Also handle positional total=False in TypedDict subclass bases
    for base in cls.bases:
        if isinstance(base, ast.Subscript):
            continue  # generic base, not a keyword arg
    return False


def extract_python_schemas() -> Tuple[Dict[str, Dict[str, Dict[str, Any]]], int | None]:
    """Parse the SSOT file with ast and return ``(schemas, schema_version)``.

    ``schemas`` has the form ``{ts_iface_name: {field: {optional, type}}}``.
    ``schema_version`` is the integer SCHEMA_VERSION constant or ``None``
    if not found.
    """
    if not PY_SCHEMA_PATH.exists():
        print(
            f"ERROR: Python schema file not found at {PY_SCHEMA_PATH}",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        source = PY_SCHEMA_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(PY_SCHEMA_PATH))
    except SyntaxError as exc:
        print(f"ERROR: cannot parse {PY_SCHEMA_PATH}: {exc}", file=sys.stderr)
        sys.exit(2)

    result: Dict[str, Dict[str, Dict[str, Any]]] = {}
    schema_version: int | None = None

    for node in tree.body:
        # Pull SCHEMA_VERSION out of module-level assignments.
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "SCHEMA_VERSION"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, int)
        ):
            schema_version = node.value.value
            continue
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "SCHEMA_VERSION"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, int)
        ):
            schema_version = node.value.value
            continue

        if not isinstance(node, ast.ClassDef):
            continue
        if node.name not in SCHEMA_NAME_MAP:
            continue
        ts_iface_name = SCHEMA_NAME_MAP[node.name]
        cls_total_default = not _class_has_total_false(node)  # total=True → required by default

        fields: Dict[str, Dict[str, Any]] = {}
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                continue  # skip docstrings, methods, etc.
            field = stmt.target.id
            if ts_iface_name == "MemoryItem" and field not in HYBRID_SNAKE_CASE_FIELDS:
                continue
            hint_optional, hint_type = _annotation_is_optional(stmt.annotation)
            optional = (not cls_total_default) or hint_optional
            fields[field] = {"optional": optional, "type": hint_type}
        result[ts_iface_name] = fields

    return result, schema_version


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
_TS_SCHEMA_VERSION_RE = re.compile(r"export\s+const\s+SCHEMA_VERSION\s*=\s*(?P<ver>\d+)\s*;")


def extract_ts_schemas() -> Tuple[Dict[str, Dict[str, Dict[str, Any]]], int | None]:
    """Return ``(schemas, schema_version)`` from the TS types file."""
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
            continue
        fields: Dict[str, Dict[str, Any]] = {}
        for fm in _TS_FIELD_RE.finditer(m.group("body")):
            fname = fm.group("name")
            if iface_name == "MemoryItem" and fname not in HYBRID_SNAKE_CASE_FIELDS:
                continue
            optional = fm.group("opt") is not None
            ftype = fm.group("type").strip()
            # Collapse TS unions with null / undefined to "optional" in our view
            if re.search(r"\|\s*(?:null|undefined)", ftype) or ftype.endswith(" | undefined"):
                optional = True
                ftype = re.sub(r"\s*\|\s*(?:null|undefined)\s*", "", ftype).strip()
            fields[fname] = {"optional": optional, "type": ftype}
        result[iface_name] = fields

    schema_version: int | None = None
    m = _TS_SCHEMA_VERSION_RE.search(source)
    if m:
        schema_version = int(m.group("ver"))

    return result, schema_version


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _py_cls_name(ts_name: str) -> str:
    """Reverse-lookup SCHEMA_NAME_MAP for error messages."""
    for py, ts in SCHEMA_NAME_MAP.items():
        if ts == ts_name:
            return py
    return ts_name


def compare_schemas(
    py: Dict[str, Dict[str, Dict[str, Any]]],
    ts: Dict[str, Dict[str, Dict[str, Any]]],
    py_version: int | None,
    ts_version: int | None,
) -> List[str]:
    """Return a list of human-readable drift descriptions (empty = in sync)."""
    errors: List[str] = []

    # SCHEMA_VERSION parity
    if py_version is None:
        errors.append(f"SCHEMA_VERSION not found in Python SSOT {PY_SCHEMA_PATH.name}")
    if ts_version is None:
        errors.append(f"SCHEMA_VERSION not found in TypeScript {TS_SCHEMA_PATH.name}")
    if py_version is not None and ts_version is not None and py_version != ts_version:
        errors.append(f"SCHEMA_VERSION mismatch: Python={py_version}, TypeScript={ts_version}")

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

            if pf["optional"] != tf["optional"]:
                errors.append(
                    f"[{name}.{field}] optionality mismatch: "
                    f"Python={'optional' if pf['optional'] else 'required'}, "
                    f"TS={'optional' if tf['optional'] else 'required'}"
                )

    return errors


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

    py_schemas, py_version = extract_python_schemas()
    ts_schemas, ts_version = extract_ts_schemas()
    errors = compare_schemas(py_schemas, ts_schemas, py_version, ts_version)

    if not errors:
        schemas = ", ".join(sorted(py_schemas))
        print(f"OK: hybrid search schemas in sync (SCHEMA_VERSION={py_version}, schemas={schemas})")
        return 0

    print("DRIFT DETECTED between Python SSOT and TypeScript interfaces:", file=sys.stderr)
    print(file=sys.stderr)
    for e in errors:
        print(f"  - {e}", file=sys.stderr)
    print(file=sys.stderr)
    print(
        f"Python SSOT: {PY_SCHEMA_PATH}",
        file=sys.stderr,
    )
    print(f"TypeScript:  {TS_SCHEMA_PATH}", file=sys.stderr)
    print(
        "Update the TypeScript interfaces to match the Python TypedDicts "
        "(or vice-versa after confirming the change is intentional) and "
        "ensure SCHEMA_VERSION is identical on both sides.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
