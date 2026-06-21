#!/usr/bin/env python3
"""Generate payload_contract.json for Python and Node CLI from the shared cli-spec.json.

This script is the single source of truth for all CLI contract data.
It reads ``cli/cli-spec.json`` and extracts the relevant sections into
``cli/python/src/mem0_cli/contract/payload_contract.json`` and
``cli/node/src/contract/payload_contract.json``.

Generated files include a ``_meta`` section with DO-NOT-edit markers and
a content hash so tests can detect manual edits.

Run this whenever ``cli-spec.json`` changes to keep both CLIs in sync.

Usage:
    python cli/generate_contracts.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


SPEC_PATH = Path(__file__).parent / "cli-spec.json"
PYTHON_OUT = Path(__file__).parent / "python" / "src" / "mem0_cli" / "contract" / "payload_contract.json"
NODE_OUT = Path(__file__).parent / "node" / "src" / "contract" / "payload_contract.json"


CONTRACT_SECTIONS = [
    "defaults",
    "fieldMapping",
    "pendingDedup",
    "searchListKeys",
    "addResultKey",
    "jsonEnvelope",
    "agentSanitization",
    "batchStatus",
    "notice",
    "traceEpilogue",
    "filterBuilding",
    "responseNormalization",
    "validation",
    "exitCodes",
    "parameterNaming",
    "outputFormats",
    "progressEvents",
    "timedStatus",
    "agentPickFields",
]


META_KEY = "_meta"


def compute_source_hash(spec_json: str, spec_path: Path) -> str:
    """Compute a SHA-256 hash of the source spec content + relative path.

    The hash covers the raw spec file bytes so that any manual edit of
    cli-spec.json produces a different digest.
    """
    hasher = hashlib.sha256()
    hasher.update(spec_json.encode("utf-8"))
    hasher.update(str(spec_path).encode("utf-8"))
    return hasher.hexdigest()


def build_payload_contract(spec: dict, spec_json: str, spec_path: Path) -> dict:
    """Build the payload contract dict from the full cli-spec.json.

    Only includes sections that are runtime-relevant for both CLIs.
    Includes a ``_meta`` section with provenance info and a content hash.
    """
    payload: dict = {}

    config_defaults = spec.get("config", {}).get("defaults", {}).get("fields", {})
    payload["defaults"] = {
        k: v.get("default") for k, v in config_defaults.items()
    }

    field_mapping = {
        "memory": "text",
        "score": "similarity",
        "created_at": "created",
        "updated_at": "updated",
        "categories": "tags",
    }
    payload["fieldMapping"] = field_mapping

    agent_pick_fields = {
        "add": spec.get("agentSanitization", {}).get("add", {}),
        "search": spec.get("agentSanitization", {}).get("search", []),
        "list": spec.get("agentSanitization", {}).get("list", []),
        "get": spec.get("agentSanitization", {}).get("get", []),
        "update": spec.get("agentSanitization", {}).get("update", []),
        "event_list": spec.get("agentSanitization", {}).get("event list", []),
        "event_status": spec.get("agentSanitization", {}).get("event status", []),
    }
    payload["agentPickFields"] = agent_pick_fields

    for section in [
        "pendingDedup",
        "searchListKeys",
        "addResultKey",
        "jsonEnvelope",
        "agentSanitization",
        "batchStatus",
        "notice",
        "traceEpilogue",
        "filterBuilding",
        "responseNormalization",
        "validation",
        "exitCodes",
        "parameterNaming",
        "outputFormats",
        "progressEvents",
        "timedStatus",
    ]:
        if section in spec:
            payload[section] = spec[section]

    payload["searchListKeys"] = spec.get("responseNormalization", {}).get("searchListKeys", ["results", "memories"])
    payload["addResultKey"] = spec.get("responseNormalization", {}).get("addResultKey", "results")

    source_hash = compute_source_hash(spec_json, spec_path)
    generated_at = datetime.now(timezone.utc).isoformat()

    payload[META_KEY] = {
        "generated": True,
        "source": "cli/cli-spec.json",
        "generator": "cli/generate_contracts.py",
        "generated_at": generated_at,
        "source_hash": source_hash,
        "do_not_edit": "DO NOT EDIT — generated from cli/cli-spec.json. Run `python cli/generate_contracts.py` to regenerate.",
    }

    return payload


def write_json(path: Path, data: dict) -> None:
    """Write dict to file as formatted JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate CLI payload contracts from cli-spec.json")
    parser.add_argument("--check", action="store_true", help="Check if generated files are up-to-date")
    args = parser.parse_args()

    if not SPEC_PATH.exists():
        print(f"ERROR: cli-spec.json not found at {SPEC_PATH}", file=sys.stderr)
        return 1

    with open(SPEC_PATH, encoding="utf-8") as f:
        spec_json = f.read()
    spec = json.loads(spec_json)

    payload = build_payload_contract(spec, spec_json, SPEC_PATH)

    if args.check:
        all_ok = True
        for path in [PYTHON_OUT, NODE_OUT]:
            if not path.exists():
                print(f"FAIL: {path} does not exist", file=sys.stderr)
                all_ok = False
                continue
            with open(path, encoding="utf-8") as f:
                existing_raw = f.read()
            existing = json.loads(existing_raw)

            existing_meta = existing.get(META_KEY, {})
            if not existing_meta.get("generated"):
                print(f"FAIL: {path} is not a generated contract (missing _meta.generated)", file=sys.stderr)
                all_ok = False
                continue

            expected_hash = payload[META_KEY]["source_hash"]
            actual_hash = existing_meta.get("source_hash")
            if actual_hash != expected_hash:
                print(f"FAIL: {path} source hash does not match cli-spec.json", file=sys.stderr)
                print(f"  Expected: {expected_hash}", file=sys.stderr)
                print(f"  Actual:   {actual_hash}", file=sys.stderr)
                all_ok = False
                continue

            existing_without_meta = {k: v for k, v in existing.items() if k != META_KEY}
            payload_without_meta = {k: v for k, v in payload.items() if k != META_KEY}
            if existing_without_meta != payload_without_meta:
                print(f"FAIL: {path} content is out of sync with cli-spec.json", file=sys.stderr)
                print("  Run: python cli/generate_contracts.py", file=sys.stderr)
                all_ok = False
                continue

        if not all_ok:
            return 1
        print("OK: All payload contracts are in sync with cli-spec.json")
        return 0

    write_json(PYTHON_OUT, payload)
    write_json(NODE_OUT, payload)

    print(f"Generated {PYTHON_OUT.relative_to(Path.cwd())}")
    print(f"Generated {NODE_OUT.relative_to(Path.cwd())}")
    print()
    print("Payload contracts are now in sync with cli-spec.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
