"""Shared fixtures for mem0 CLI tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mem0_cli.backend.base import Backend
from mem0_cli.config import Mem0Config

CLI_ROOT = Path(__file__).parent.parent.parent
SPEC_PATH = CLI_ROOT / "cli-spec.json"
CONTRACT_PATH = Path(__file__).parent.parent / "src" / "mem0_cli" / "contract" / "payload_contract.json"


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """Redirect config to a temp directory so tests don't touch real config."""
    fake_config_dir = tmp_path / ".mem0"
    fake_config_file = fake_config_dir / "config.json"
    monkeypatch.setattr("mem0_cli.config.CONFIG_DIR", fake_config_dir)
    monkeypatch.setattr("mem0_cli.config.CONFIG_FILE", fake_config_file)
    # Also patch the commands that import config
    monkeypatch.setattr("mem0_cli.commands.config_cmd.CONFIG_DIR", fake_config_dir, raising=False)
    # Clear any MEM0 env vars
    for key in list(os.environ.keys()):
        if key.startswith("MEM0_"):
            monkeypatch.delenv(key, raising=False)
    return fake_config_dir


@pytest.fixture
def mock_backend():
    """Return a mock backend with all methods stubbed."""
    backend = MagicMock(spec=Backend)

    # Default return values
    backend.add.return_value = {
        "results": [
            {
                "id": "abc-123-def-456",
                "memory": "User prefers dark mode",
                "event": "ADD",
            }
        ]
    }

    backend.search.return_value = [
        {
            "id": "abc-123-def-456",
            "memory": "User prefers dark mode",
            "score": 0.92,
            "created_at": "2026-02-15T10:30:00Z",
            "categories": ["preferences"],
        },
        {
            "id": "ghi-789-jkl-012",
            "memory": "User uses vim keybindings",
            "score": 0.78,
            "created_at": "2026-03-01T14:00:00Z",
            "categories": ["tools"],
        },
    ]

    backend.get.return_value = {
        "id": "abc-123-def-456",
        "memory": "User prefers dark mode",
        "created_at": "2026-02-15T10:30:00Z",
        "updated_at": "2026-02-20T08:00:00Z",
        "metadata": {"source": "onboarding"},
        "categories": ["preferences"],
    }

    backend.list_memories.return_value = [
        {
            "id": "abc-123-def-456",
            "memory": "User prefers dark mode",
            "created_at": "2026-02-15T10:30:00Z",
            "categories": ["preferences"],
        },
        {
            "id": "ghi-789-jkl-012",
            "memory": "User uses vim keybindings",
            "created_at": "2026-03-01T14:00:00Z",
            "categories": ["tools"],
        },
    ]

    backend.update.return_value = {"id": "abc-123-def-456", "memory": "Updated memory"}
    backend.delete.return_value = {"status": "deleted"}
    backend.status.return_value = {
        "connected": True,
        "backend": "platform",
        "base_url": "https://api.mem0.ai",
    }
    backend.delete_entities.return_value = {"message": "Entity deleted"}
    backend.entities.return_value = [
        {"name": "alice", "count": 5},
        {"name": "bob", "count": 3},
    ]
    backend.list_events.return_value = [
        {
            "id": "evt-abc-123-def-456",
            "event_type": "ADD",
            "status": "SUCCEEDED",
            "graph_status": None,
            "latency": 1234.5,
            "created_at": "2026-04-01T10:00:00Z",
            "updated_at": "2026-04-01T10:00:01Z",
        },
        {
            "id": "evt-def-456-ghi-789",
            "event_type": "SEARCH",
            "status": "PENDING",
            "graph_status": None,
            "latency": None,
            "created_at": "2026-04-01T10:01:00Z",
            "updated_at": "2026-04-01T10:01:00Z",
        },
    ]
    backend.get_event.return_value = {
        "id": "evt-abc-123-def-456",
        "event_type": "ADD",
        "status": "SUCCEEDED",
        "graph_status": "SUCCEEDED",
        "latency": 1234.5,
        "created_at": "2026-04-01T10:00:00Z",
        "updated_at": "2026-04-01T10:00:01Z",
        "results": [
            {
                "id": "mem-abc-123",
                "event": "ADD",
                "user_id": "alice",
                "data": {"memory": "User prefers dark mode"},
            }
        ],
    }

    return backend


@pytest.fixture
def sample_config():
    """Return a sample config object."""
    config = Mem0Config()
    config.platform.api_key = "m0-test-key-12345678"
    config.platform.base_url = "https://api.mem0.ai"
    return config


def pytest_configure(config: pytest.Config) -> None:
    """Validate the payload contract before running any tests.

    Ensures the generated payload_contract.json is in sync with cli-spec.json
    and has not be manually edited.
    """
    if not SPEC_PATH.exists():
        print(f"[contract-warn] cli-spec.json not found at {SPEC_PATH}; skipping contract validation")
        sys.stdout.flush()
        return

    if not CONTRACT_PATH.exists():
        pytest.exit(
            f"ERROR: payload_contract.json not found at {CONTRACT_PATH}\n"
            f"  Run: python cli/generate_contracts.py",
            returncode=1,
        )

    with open(SPEC_PATH, encoding="utf-8") as f:
        spec_json = f.read()

    with open(CONTRACT_PATH, encoding="utf-8") as f:
        contract = json.load(f)

    meta = contract.get("_meta", {})
    if not meta.get("generated"):
        pytest.exit(
            f"ERROR: {CONTRACT_PATH} is not a generated contract (missing _meta.generated)\n"
            f"  Do not edit payload_contract.json manually.\n"
            f"  Run: python cli/generate_contracts.py",
            returncode=1,
        )

    script_path = CLI_ROOT / "generate_contracts.py"
    if script_path.exists():
        import importlib.util

        spec_module = importlib.util.spec_from_file_location("generate_contracts", script_path)
        module = importlib.util.module_from_spec(spec_module)
        spec_module.loader.exec_module(module)

        expected_hash = module.compute_source_hash(spec_json, SPEC_PATH)
        actual_hash = meta.get("source_hash")

        if actual_hash != expected_hash:
            pytest.exit(
                f"ERROR: payload_contract.json source hash does not match cli-spec.json\n"
                f"  Expected: {expected_hash}\n"
                f"  Actual:   {actual_hash}\n"
                f"  The contract may have been manually edited.\n"
                f"  Run: python cli/generate_contracts.py",
                returncode=1,
            )

    print(f"[contract-ok] payload_contract.json is in sync with cli-spec.json")
    sys.stdout.flush()
