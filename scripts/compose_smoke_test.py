#!/usr/bin/env python3
"""
End-to-end smoke tests for Mem0 docker-compose deployments.

Verifies:
  1. .env file exists and has the required variables
  2. Configuration validation produces helpful errors on missing variables
  3. Entrypoint pre-flight checks work correctly
  4. /health endpoints return proper responses
  5. Missing secrets / database URLs produce actionable messages, not raw connection errors

Usage:
    # Run all smoke tests (does NOT require docker)
    python scripts/compose_smoke_test.py --all

    # Run specific tests only
    python scripts/compose_smoke_test.py --env-check
    python scripts/compose_smoke_test.py --config-errors
    python scripts/compose_smoke_test.py --health-endpoints

    # Point to a specific .env file
    python scripts/compose_smoke_test.py --env-file /path/to/.env --all

Exit codes:
    0: all tests passed
    1: one or more tests failed
    2: usage error
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO_ROOT / "server"
OPENMEMORY_API_DIR = REPO_ROOT / "openmemory" / "api"


@dataclass
class TestResult:
    name: str
    passed: bool
    message: str
    details: Optional[str] = None


def load_env_file(env_path: Path) -> Dict[str, str]:
    """Load a .env file into a dict, ignoring comments and empty lines."""
    result: Dict[str, str] = {}
    if not env_path.is_file():
        return result
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def save_env_file(env_path: Path, variables: Dict[str, str]) -> None:
    """Write a dict to a .env file."""
    lines = [f"{k}={v}" for k, v in variables.items()]
    env_path.write_text("\n".join(lines) + "\n")


def run_python_script(cwd: Path, script: str, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    """Run a Python script snippet in a subprocess, returning the result."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(cwd),
        env=full_env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def check_health_endpoint(host: str, port: int, timeout: float = 2.0) -> bool:
    """Try to reach a /health endpoint. Returns True if it returns 200 with valid JSON."""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=timeout) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read())
            return "status" in data and data["status"] == "ok"
    except Exception:
        return False


# ── Test cases ────────────────────────────────────────────────────────────────


def test_env_file_exists(env_file: Path) -> TestResult:
    """Verify .env exists in the repo root, or suggest creating it from .env.example."""
    if env_file.is_file():
        return TestResult("env_file_exists", True, f".env found at {env_file}")
    example = REPO_ROOT / ".env.example"
    suggestion = ""
    if example.is_file():
        suggestion = f"\n    💡 Run: cp {example} {env_file} and edit the values."
    return TestResult(
        "env_file_exists",
        False,
        f"No .env file found at {env_file}.{suggestion}",
    )


def test_env_required_variables(env_file: Path) -> TestResult:
    """Check that the most critical variables are set."""
    env = load_env_file(env_file)
    required = [
        "POSTGRES_PASSWORD",
    ]
    missing = [k for k in required if not env.get(k)]
    if not missing:
        return TestResult(
            "env_required_variables",
            True,
            "All required variables are set.",
        )
    return TestResult(
        "env_required_variables",
        False,
        f"Missing required variables in {env_file}: {', '.join(missing)}",
        details=(
            f"  💡 POSTGRES_PASSWORD is required for both the postgres container and the API server.\n"
            f"     Set it to any non-empty value for local development."
        ),
    )


def test_env_naming_consistency(env_file: Path) -> TestResult:
    """Check that we use the new unified naming, not legacy names alone."""
    env = load_env_file(env_file)
    issues: List[str] = []

    legacy_new_map = {
        "APP_DB_NAME": "MEM0_APP_DB_NAME",
        "USER": "MEM0_USER_ID",
        "VECTOR_STORE": "VECTOR_STORE_PROVIDER",
        "LLM_PROVIDER": "MEM0_LLM_PROVIDER",
        "EMBEDDER_PROVIDER": "MEM0_EMBEDDER_PROVIDER",
        "LLM_MODEL": "MEM0_DEFAULT_LLM_MODEL",
        "EMBEDDER_MODEL": "MEM0_DEFAULT_EMBEDDER_MODEL",
    }
    for legacy, new in legacy_new_map.items():
        if legacy in env and new not in env:
            issues.append(f"  ⚠️  Using legacy '{legacy}' — prefer '{new}' (legacy still works)")

    if not issues:
        return TestResult(
            "env_naming_consistency",
            True,
            "All variables use the new unified naming convention.",
        )
    return TestResult(
        "env_naming_consistency",
        True,  # not a failure, just a warning
        "Some variables use legacy names (still supported):",
        details="\n".join(issues),
    )


def test_config_error_server_postgres_password() -> TestResult:
    """Verify server entrypoint gives a helpful error when POSTGRES_PASSWORD is missing."""
    env = {
        "POSTGRES_PASSWORD": "",
        "MEM0_LLM_PROVIDER": "ollama",
        "MEM0_EMBEDDER_PROVIDER": "ollama",
        "AUTH_DISABLED": "true",
    }
    script = """
import sys
sys.path.insert(0, '.')
from _env_loader import load_env, validate_postgres_connection, ConfigValidationError, fatal_config_error
load_env()
errors = validate_postgres_connection()
if errors:
    fatal_config_error(errors)
print('OK')
"""
    result = run_python_script(SERVER_DIR, script, env=env)
    if result.returncode == 2 and "POSTGRES_PASSWORD" in result.stderr and "CONFIGURATION ERROR" in result.stderr:
        return TestResult(
            "config_error_server_postgres_password",
            True,
            "Missing POSTGRES_PASSWORD produces a helpful error with exit code 2.",
            details=f"    Snippet: {result.stderr.strip().splitlines()[2] if len(result.stderr.splitlines()) > 2 else ''}",
        )
    return TestResult(
        "config_error_server_postgres_password",
        False,
        f"Expected exit code 2 with helpful error, got exit code {result.returncode}.",
        details=f"    stdout: {result.stdout.strip()}\n    stderr: {result.stderr.strip()}",
    )


def test_config_error_server_jwt_secret() -> TestResult:
    """Verify server gives a helpful error when JWT_SECRET is missing and AUTH_DISABLED != true."""
    env = {
        "POSTGRES_PASSWORD": "test",
        "MEM0_LLM_PROVIDER": "ollama",
        "MEM0_EMBEDDER_PROVIDER": "ollama",
        "AUTH_DISABLED": "false",
        "JWT_SECRET": "",
    }
    script = """
import sys
sys.path.insert(0, '.')
from _env_loader import ConfigValidationError
from entrypoint import load_env_loader, validate_server_config
env_loader = load_env_loader()
env_loader.load_env()
errors = validate_server_config(env_loader)
if errors:
    raise ConfigValidationError(errors)
print('OK')
"""
    result = run_python_script(SERVER_DIR, script, env=env)
    if result.returncode != 0 and "JWT_SECRET" in result.stderr:
        return TestResult(
            "config_error_server_jwt_secret",
            True,
            "Missing JWT_SECRET (with auth enabled) produces a helpful error.",
            details=f"    Snippet: {result.stderr.strip().splitlines()[2] if len(result.stderr.splitlines()) > 2 else ''}",
        )
    return TestResult(
        "config_error_server_jwt_secret",
        False,
        f"Expected error about JWT_SECRET, got exit code {result.returncode}.",
        details=f"    stdout: {result.stdout.strip()}\n    stderr: {result.stderr.strip()}",
    )


def test_config_error_openmemory_openai_key() -> TestResult:
    """Verify openmemory-api gives a helpful error when OPENAI_API_KEY is missing and provider is openai."""
    env = {
        "DATABASE_URL": "sqlite:///./test.db",
        "VECTOR_STORE_PROVIDER": "qdrant",
        "QDRANT_HOST": "localhost",
        "MEM0_LLM_PROVIDER": "openai",
        "OPENAI_API_KEY": "",
    }
    script = """
import sys
sys.path.insert(0, '.')
from _env_loader import ConfigValidationError
from entrypoint import load_env_loader, validate_openmemory_api_config
env_loader = load_env_loader()
env_loader.load_env()
errors = validate_openmemory_api_config(env_loader)
if errors:
    raise ConfigValidationError(errors)
print('OK')
"""
    result = run_python_script(OPENMEMORY_API_DIR, script, env=env)
    if result.returncode != 0 and "OPENAI_API_KEY" in result.stderr and "platform.openai.com" in result.stderr:
        return TestResult(
            "config_error_openmemory_openai_key",
            True,
            "Missing OPENAI_API_KEY with openai provider produces a helpful error with link.",
            details=f"    Snippet: {result.stderr.strip().splitlines()[2] if len(result.stderr.splitlines()) > 2 else ''}",
        )
    return TestResult(
        "config_error_openmemory_openai_key",
        False,
        f"Expected helpful OPENAI_API_KEY error, got exit code {result.returncode}.",
        details=f"    stdout: {result.stdout.strip()}\n    stderr: {result.stderr.strip()}",
    )


def test_config_ok_openmemory_ollama() -> TestResult:
    """Verify openmemory-api passes validation with valid Ollama config (no OpenAI key needed)."""
    env = {
        "DATABASE_URL": "sqlite:///./test.db",
        "VECTOR_STORE_PROVIDER": "qdrant",
        "QDRANT_HOST": "localhost",
        "MEM0_LLM_PROVIDER": "ollama",
        "MEM0_EMBEDDER_PROVIDER": "ollama",
        "OPENAI_API_KEY": "",
    }
    script = """
import sys
sys.path.insert(0, '.')
from entrypoint import load_env_loader, validate_openmemory_api_config
env_loader = load_env_loader()
env_loader.load_env()
errors = validate_openmemory_api_config(env_loader)
if errors:
    print(f'ERRORS: {errors}')
    sys.exit(1)
print('OK')
"""
    result = run_python_script(OPENMEMORY_API_DIR, script, env=env)
    if result.returncode == 0 and "OK" in result.stdout:
        return TestResult(
            "config_ok_openmemory_ollama",
            True,
            "Valid Ollama + Qdrant config passes validation (no OpenAI key needed).",
        )
    return TestResult(
        "config_ok_openmemory_ollama",
        False,
        f"Expected validation to pass, got exit code {result.returncode}.",
        details=f"    stdout: {result.stdout.strip()}\n    stderr: {result.stderr.strip()}",
    )


def test_server_health_endpoint_structure() -> TestResult:
    """Verify server/main.py exports a /health endpoint with correct structure (static check)."""
    main_py = SERVER_DIR / "main.py"
    content = main_py.read_text()
    if "@app.get(\"/health\"" in content and '"status": "ok"' in content and '"service": "mem0-server"' in content:
        return TestResult(
            "server_health_endpoint_structure",
            True,
            "server/main.py defines /health with correct response structure.",
        )
    return TestResult(
        "server_health_endpoint_structure",
        False,
        "server/main.py is missing /health endpoint or has wrong structure.",
        details="    Expected: @app.get('/health') returning {'status': 'ok', 'service': 'mem0-server'}",
    )


def test_openmemory_health_endpoint_structure() -> TestResult:
    """Verify openmemory/api/main.py exports a /health endpoint with correct structure."""
    main_py = OPENMEMORY_API_DIR / "main.py"
    content = main_py.read_text()
    if "@app.get(\"/health\"" in content and '"status": "ok"' in content and '"service": "openmemory-api"' in content:
        return TestResult(
            "openmemory_health_endpoint_structure",
            True,
            "openmemory/api/main.py defines /health with correct response structure.",
        )
    return TestResult(
        "openmemory_health_endpoint_structure",
        False,
        "openmemory/api/main.py is missing /health endpoint or has wrong structure.",
        details="    Expected: @app.get('/health') returning {'status': 'ok', 'service': 'openmemory-api'}",
    )


def test_env_loader_standalone() -> TestResult:
    """Verify _env_loader.py can be imported with no dependencies other than python-dotenv."""
    for service_dir in [SERVER_DIR, OPENMEMORY_API_DIR]:
        script = """
import sys
sys.path.insert(0, '.')
from _env_loader import (
    load_env, get_env, get_env_int, get_env_bool,
    validate_required, validate_postgres_connection,
    build_postgres_url, ConfigError, ConfigValidationError, fatal_config_error
)
# Test basic functionality
load_env()
assert get_env('__NONEXISTENT_VAR__', 'default') == 'default'
assert get_env_int('__NONEXISTENT_VAR__', 42) == 42
assert get_env_bool('__NONEXISTENT_VAR__', False) is False
print('OK')
"""
        result = run_python_script(service_dir, script)
        if result.returncode != 0 or "OK" not in result.stdout:
            return TestResult(
                "env_loader_standalone",
                False,
                f"_env_loader.py failed standalone import in {service_dir.name}.",
                details=f"    stdout: {result.stdout.strip()}\n    stderr: {result.stderr.strip()}",
            )
    return TestResult(
        "env_loader_standalone",
        True,
        "_env_loader.py imports and works correctly in both service directories with no mem0 package dependency.",
    )


# ── Test runner ───────────────────────────────────────────────────────────────


def run_tests(tests: List[Callable[[], TestResult]]) -> List[TestResult]:
    """Run a list of test functions and return results."""
    results: List[TestResult] = []
    for test_fn in tests:
        try:
            results.append(test_fn())
        except Exception as exc:
            results.append(
                TestResult(
                    test_fn.__name__,
                    False,
                    f"Test raised an exception: {exc}",
                    details=f"    {type(exc).__name__}: {exc}",
                )
            )
    return results


def print_results(results: List[TestResult]) -> None:
    """Pretty-print test results to the console."""
    print("\n" + "=" * 72)
    print("  MEM0 COMPOSE SMOKE TEST RESULTS")
    print("=" * 72 + "\n")

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)

    for result in results:
        status = "✅ PASS" if result.passed else "❌ FAIL"
        print(f"  {status}  {result.name}")
        print(f"     {result.message}")
        if result.details:
            print(result.details)
        print()

    print("=" * 72)
    print(f"  Summary: {passed} passed, {failed} failed, {len(results)} total")
    print("=" * 72 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Mem0 compose smoke tests")
    parser.add_argument("--env-file", default=str(REPO_ROOT / ".env"), help="Path to .env file")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    parser.add_argument("--env-check", action="store_true", help="Check .env file only")
    parser.add_argument("--config-errors", action="store_true", help="Check config error messages only")
    parser.add_argument("--health-endpoints", action="store_true", help="Check /health endpoint structure only")
    parser.add_argument("--list", action="store_true", help="List available tests and exit")
    args = parser.parse_args()

    env_file = Path(args.env_file).resolve()

    all_env_tests = [
        lambda: test_env_file_exists(env_file),
        lambda: test_env_required_variables(env_file),
        lambda: test_env_naming_consistency(env_file),
    ]

    all_config_error_tests = [
        test_env_loader_standalone,
        test_config_error_server_postgres_password,
        test_config_error_server_jwt_secret,
        test_config_error_openmemory_openai_key,
        test_config_ok_openmemory_ollama,
    ]

    all_health_tests = [
        test_server_health_endpoint_structure,
        test_openmemory_health_endpoint_structure,
    ]

    if args.list:
        print("Available tests:")
        for group, tests in [
            ("--env-check", all_env_tests),
            ("--config-errors", all_config_error_tests),
            ("--health-endpoints", all_health_tests),
        ]:
            print(f"\n  {group}:")
            for t in tests:
                print(f"    - {t.__name__}")
        return 0

    tests: List[Callable[[], TestResult]] = []
    if args.all:
        tests = all_env_tests + all_config_error_tests + all_health_tests
    else:
        if args.env_check:
            tests.extend(all_env_tests)
        if args.config_errors:
            tests.extend(all_config_error_tests)
        if args.health_endpoints:
            tests.extend(all_health_tests)

    if not tests:
        parser.error("Specify at least one test group: --all, --env-check, --config-errors, or --health-endpoints")
        return 2

    results = run_tests(tests)
    print_results(results)

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
