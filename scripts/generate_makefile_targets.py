#!/usr/bin/env python3
"""Generate GNU Make targets from monorepo-manifest.json.

Usage: python3 scripts/generate_makefile_targets.py [--print-phony] [--print-targets]

Produces Makefile syntax that can be evaluated by GNU Make. Each package
gets per-task targets (e.g. install-python-sdk, lint-node-cli) and each
group gets aggregate targets (e.g. install-core, check-integrations).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

MANIFEST_PATH = Path(__file__).parent.parent / "monorepo-manifest.json"

TASKS = ["install", "format", "lint", "typecheck", "build", "test", "clean"]

# Tasks that are used in aggregate group targets (e.g. check-core = format-core + lint-core + typecheck-core)
GROUP_TASKS = {
    "check": ["format", "lint", "typecheck"],
}


def load_manifest() -> dict:
    with open(MANIFEST_PATH, "r") as f:
        return json.load(f)


def pkg_has_task(pkg: dict, task: str) -> bool:
    cmd = pkg["commands"].get(task)
    return cmd is not None and cmd.strip() != ""


def print_phony(manifest: dict) -> None:
    """Print the .PHONY line listing only per-package targets.

    Group aggregate targets are defined in the Makefile itself and listed
    there in its own .PHONY declaration.
    """
    targets = []
    for pkg in manifest["packages"]:
        for task in TASKS:
            if pkg_has_task(pkg, task):
                targets.append(f"{task}-{pkg['name']}")
        if pkg_has_task(pkg, "format") or pkg_has_task(pkg, "lint") or pkg_has_task(pkg, "typecheck"):
            targets.append(f"check-{pkg['name']}")

    print(".PHONY: " + " ".join(targets))


def print_targets(manifest: dict) -> None:
    """Print all per-package target definitions in Makefile syntax.

    Does NOT generate group aggregate targets — those live in the Makefile
    itself so they can use Make variables (SKIP_PKGS, etc.) for filtering.
    """
    lines = []
    packages = manifest["packages"]

    # ── Per-package targets only ───────────────────────────────────────
    for pkg in packages:
        name = pkg["name"]

        # Individual task targets
        for task in TASKS:
            if not pkg_has_task(pkg, task):
                continue
            cmd = pkg["commands"][task]
            lines.append(f"{task}-{name}:")
            lines.append(f"\t@{cmd}")
            lines.append("")

        # check-<pkg> = format + lint + typecheck
        check_deps = []
        for sub_task in GROUP_TASKS["check"]:
            if pkg_has_task(pkg, sub_task):
                check_deps.append(f"{sub_task}-{name}")
        if check_deps:
            lines.append(f"check-{name}: {' '.join(check_deps)}")
            lines.append(f"\t@echo \"✓ check-{name} passed\"")
            lines.append("")

    print("\n".join(lines))


def print_package_list(manifest: dict, group: str | None = None, task: str | None = None,
                       release_only: bool = False) -> None:
    """Print a space-separated list of package names matching filters."""
    pkgs = manifest["packages"]
    if group:
        pkgs = [p for p in pkgs if p["group"] == group]
    if release_only:
        pkgs = [p for p in pkgs if p.get("default_in_release", manifest["groups"][p["group"]].get("default_in_release", False))]
    if task:
        pkgs = [p for p in pkgs if pkg_has_task(p, task)]
    print(" ".join(p["name"] for p in pkgs))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate GNU Make targets from monorepo manifest")
    parser.add_argument("--print-phony", action="store_true", help="Print .PHONY line")
    parser.add_argument("--print-targets", action="store_true", help="Print target definitions")
    parser.add_argument("--list-packages", action="store_true", help="List package names (optional filters)")
    parser.add_argument("--group", type=str, help="Filter packages by group (for --list-packages)")
    parser.add_argument("--task", type=str, help="Filter packages with task (for --list-packages)")
    parser.add_argument("--release-only", action="store_true", help="Only packages default_in_release=true (for --list-packages)")
    args = parser.parse_args()

    manifest = load_manifest()

    if args.print_phony:
        print_phony(manifest)
    elif args.print_targets:
        print_targets(manifest)
    elif args.list_packages:
        print_package_list(manifest, group=args.group, task=args.task, release_only=args.release_only)
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
