#!/usr/bin/env python3
"""Generate GitHub Actions workflow configuration from monorepo-manifest.json.

Usage:
  python3 scripts/ci_manifest.py matrix --group core --task test
  python3 scripts/ci_manifest.py paths-filter --package python-sdk
  python3 scripts/ci_manifest.py package-info --package node-cli --field path
  python3 scripts/ci_manifest.py validate-contract  (JSON semantic comparison)

Outputs GitHub Actions compatible JSON (for fromJSON) or plain text values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

MANIFEST_PATH = Path(__file__).parent.parent / "monorepo-manifest.json"


def load_manifest() -> dict:
    with open(MANIFEST_PATH, "r") as f:
        return json.load(f)


def cmd_matrix(manifest: dict, group: str | None, task: str, include_all: bool,
               release_only: bool) -> None:
    """Generate a GitHub Actions matrix JSON for packages in a group."""
    packages = manifest["packages"]

    if group:
        packages = [p for p in packages if p["group"] == group]

    if release_only:
        packages = [
            p for p in packages
            if p.get("default_in_release", manifest["groups"][p["group"]].get("default_in_release", False))
        ]

    if not include_all:
        # Filter to packages that actually have this task
        packages = [p for p in packages if p["commands"].get(task)]

    # For Python, include matrix versions if specified
    matrix_include = []
    for pkg in packages:
        if pkg["runtime"] == "python":
            for py_ver in ["3.10", "3.11", "3.12"]:
                matrix_include.append({
                    "package": pkg["name"],
                    "runtime": pkg["runtime"],
                    "python-version": py_ver,
                    "node-version": "",
                })
        elif pkg["runtime"] in ("node", "bun"):
            for node_ver in ["20", "22"]:
                matrix_include.append({
                    "package": pkg["name"],
                    "runtime": pkg["runtime"],
                    "python-version": "",
                    "node-version": node_ver,
                })
        else:  # docker
            matrix_include.append({
                "package": pkg["name"],
                "runtime": pkg["runtime"],
                "python-version": "",
                "node-version": "",
            })

    output = {
        "include": matrix_include,
        "package_names": [p["name"] for p in packages],
    }
    print(json.dumps(output))


def cmd_paths_filter(manifest: dict, package: str | None, all_packages: bool,
                     ci_gate_file: str | None, extras: list[str] | None) -> None:
    """Print YAML-style path filters for dorny/paths-filter.

    If --all is specified, generates filters for all packages. Each filter
    automatically includes ci-gate.yml if --ci-gate-file is provided.
    Use --extra name=path1,path2 to add non-package filters (e.g. docs).
    """
    lines = []

    if all_packages:
        packages = manifest["packages"]
    elif package:
        packages = [p for p in manifest["packages"] if p["name"] == package]
        if not packages:
            print(f"Package '{package}' not found", file=sys.stderr)
            sys.exit(1)
    else:
        print("Must specify either --package or --all", file=sys.stderr)
        sys.exit(1)

    for pkg in packages:
        ci_name = pkg["name"].replace("-", "_")
        paths = list(pkg.get("ci_paths", [f"{pkg['path']}/**"]))
        if ci_gate_file:
            paths.append(ci_gate_file)
        lines.append(f"  {ci_name}:")
        for p in paths:
            lines.append(f"    - '{p}'")

    if extras:
        for extra in extras:
            name, paths_str = extra.split("=", 1)
            paths = paths_str.split(",")
            if ci_gate_file:
                paths.append(ci_gate_file)
            lines.append(f"  {name}:")
            for p in paths:
                lines.append(f"    - '{p}'")

    print("\n".join(lines))


def cmd_package_info(manifest: dict, package: str, field: str) -> None:
    """Print a single field value for a package."""
    for pkg in manifest["packages"]:
        if pkg["name"] == package:
            if field == "path":
                print(pkg["path"])
            elif field == "group":
                print(pkg["group"])
            elif field == "runtime":
                print(pkg["runtime"])
            elif field == "command":
                # Field format: command:build  or  command:lint
                cmd = pkg["commands"].get(field.split(":", 1)[1], "")
                print(cmd)
            else:
                print(pkg.get(field, ""), end="")
            return
    print(f"Package '{package}' not found", file=sys.stderr)
    sys.exit(1)


def cmd_validate_contract(manifest: dict) -> None:
    """Run the cross-cutting contract check."""
    cmd = manifest["cross_cutting"]["contract_check"]["command"]
    result = os.WEXITSTATUS(os.system(cmd))
    if result != 0:
        print("ERROR: Contract check failed", file=sys.stderr)
        sys.exit(1)
    print("Contract check passed ✓")


def cmd_list(manifest: dict, group: str | None, release_only: bool) -> None:
    """List package names with optional filters."""
    packages = manifest["packages"]
    if group:
        packages = [p for p in packages if p["group"] == group]
    if release_only:
        packages = [
            p for p in packages
            if p.get("default_in_release", manifest["groups"][p["group"]].get("default_in_release", False))
        ]
    print("\n".join(f"{p['name']}: {p['description']}" for p in packages))


def main() -> int:
    parser = argparse.ArgumentParser(description="CI helpers reading from monorepo-manifest.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_matrix = subparsers.add_parser("matrix", help="Generate GitHub Actions matrix JSON")
    p_matrix.add_argument("--group", type=str, help="Filter by group (core/integrations/infra)")
    p_matrix.add_argument("--task", type=str, default="test", help="Task to filter by (default: test)")
    p_matrix.add_argument("--include-all", action="store_true", help="Include packages even if task is null")
    p_matrix.add_argument("--release-only", action="store_true", help="Only default_in_release=true packages")

    p_paths = subparsers.add_parser("paths-filter", help="Generate paths-filter YAML")
    p_paths.add_argument("--package", type=str, help="Generate for a single package")
    p_paths.add_argument("--all", action="store_true", help="Generate for all packages")
    p_paths.add_argument("--ci-gate-file", type=str,
                        help="Additional path to append to every filter (e.g. the gate workflow file)")
    p_paths.add_argument("--extra", type=str, action="append",
                        help="Extra filter entries, format: name=path1,path2 (repeatable)")

    p_info = subparsers.add_parser("package-info", help="Get a field value for a package")
    p_info.add_argument("--package", type=str, required=True)
    p_info.add_argument("--field", type=str, required=True,
                       help="e.g. path, group, runtime, command:build")

    subparsers.add_parser("validate-contract", help="Run the CLI payload contract check")

    p_list = subparsers.add_parser("list", help="List packages with optional filters")
    p_list.add_argument("--group", type=str, help="Filter by group")
    p_list.add_argument("--release-only", action="store_true", help="Only default_in_release=true packages")

    args = parser.parse_args()
    manifest = load_manifest()

    if args.command == "matrix":
        cmd_matrix(manifest, args.group, args.task, args.include_all, args.release_only)
    elif args.command == "paths-filter":
        cmd_paths_filter(manifest, args.package, args.all, args.ci_gate_file, args.extra)
    elif args.command == "package-info":
        cmd_package_info(manifest, args.package, args.field)
    elif args.command == "validate-contract":
        cmd_validate_contract(manifest)
    elif args.command == "list":
        cmd_list(manifest, args.group, args.release_only)

    return 0


if __name__ == "__main__":
    sys.exit(main())
