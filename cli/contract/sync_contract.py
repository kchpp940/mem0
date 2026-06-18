#!/usr/bin/env python3
"""Sync the canonical payload contract to both CLI packages.

Usage:
    python cli/contract/sync_contract.py          # copy + verify
    python cli/contract/sync_contract.py --verify  # verify only, no copy
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANONICAL = ROOT / "contract" / "payload_contract.json"
TARGETS = [
    ROOT / "python" / "src" / "mem0_cli" / "contract" / "payload_contract.json",
    ROOT / "node" / "src" / "contract" / "payload_contract.json",
]


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    verify_only = "--verify" in sys.argv

    canonical_hash = _sha256(CANONICAL)
    all_ok = True

    for target in TARGETS:
        if not verify_only:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(CANONICAL, target)
            print(f"  synced → {target.relative_to(ROOT)}")

        if target.exists():
            target_hash = _sha256(target)
            if target_hash != canonical_hash:
                print(f"  MISMATCH: {target.relative_to(ROOT)}", file=sys.stderr)
                all_ok = False
            else:
                status = "OK" if verify_only else "verified"
                print(f"  {status}: {target.relative_to(ROOT)}")
        else:
            print(f"  MISSING: {target.relative_to(ROOT)}", file=sys.stderr)
            all_ok = False

    if not all_ok:
        print("\nContract out of sync! Run: python cli/contract/sync_contract.py", file=sys.stderr)
        sys.exit(1)
    print("\nAll copies match the canonical contract.")


if __name__ == "__main__":
    main()
