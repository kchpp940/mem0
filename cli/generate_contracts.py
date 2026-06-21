#!/usr/bin/env python3
"""Generate payload_contract.json for Python and Node CLI from the shared cli-spec.json.

This script is the single source of truth for all CLI contract data.
It reads ``cli/cli-spec.json`` and extracts the relevant sections into
``cli/python/src/mem0_cli/contract/payload_contract.json`` and
``cli/node/src/contract/payload_contract.json``.

Run this whenever ``cli-spec.json`` changes to keep both CLIs in sync.

Usage:
    python cli/generate_contracts.py
"""

from __future__ import annotations

import argparse
import json
import sys
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


def build_payload_contract(spec: dict) -> dict:
    """Build the payload contract dict from the full cli-spec.json.

    Only includes sections that are runtime-relevant for both CLIs.
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
        spec = json.load(f)

    payload = build_payload_contract(spec)

    if args.check:
        for path in [PYTHON_OUT, NODE_OUT]:
            if not path.exists():
                print(f"FAIL: {path} does not exist", file=sys.stderr)
                return 1
            with open(path, encoding="utf-8") as f:
                existing = json.load(f)
            if existing != payload:
                print(f"FAIL: {path} is out of sync with cli-spec.json", file=sys.stderr)
                print("  Run: python cli/generate_contracts.py", file=sys.stderr)
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
