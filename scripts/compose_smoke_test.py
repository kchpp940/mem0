#!/usr/bin/env python3
"""
End-to-end smoke tests for Mem0 docker-compose deployments.

Verifies:
  1. .env file exists and has the required variables
  2. Configuration validation produces helpful errors on missing variables
  3. Entrypoint pre-flight checks work correctly
  4. /health endpoints return proper responses
  5. Missing secrets / database URLs produce actionable messages, not raw connection errors
  6. (Optional, --docker) Real containers: compose build/up, wait for healthchecks,
     verify API/UI/server reachability, diagnose failures with service logs

Usage:
    # Run all non-Docker smoke tests (fast, no containers needed)
    python scripts/compose_smoke_test.py --all

    # Run specific non-Docker tests only
    python scripts/compose_smoke_test.py --env-check
    python scripts/compose_smoke_test.py --config-errors
    python scripts/compose_smoke_test.py --health-endpoints

    # Run REAL container smoke tests (requires Docker)
    python scripts/compose_smoke_test.py --docker                    # both server + openmemory
    python scripts/compose_smoke_test.py --docker --stack server     # server stack only
    python scripts/compose_smoke_test.py --docker --stack openmemory # openmemory stack only
    python scripts/compose_smoke_test.py --docker --no-teardown      # leave containers running after test

    # Point to a specific .env file
    python scripts/compose_smoke_test.py --env-file /path/to/.env --all
    python scripts/compose_smoke_test.py --env-file /path/to/.env --docker

Exit codes:
    0: all tests passed
    1: one or more tests failed
    2: usage error
    3: docker not available or compose failed to start
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


# ── Docker compose helpers ────────────────────────────────────────────────────


@dataclass
class StackConfig:
    """Configuration for a docker-compose stack under test."""

    name: str
    cwd: Path
    services: List[str]
    health_endpoints: Dict[str, str]  # service name -> http://host:port/path


@dataclass
class ServiceDiagnostic:
    service: str
    log_tail: str
    status: str
    suggestion: str


OPENMEMORY_DIR = REPO_ROOT / "openmemory"


def docker_available() -> bool:
    """Return True if `docker compose` is usable."""
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def compose_cmd(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """Run `docker compose` with the given arguments in cwd, returning the result."""
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=600,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )


def wait_for_service_health(
    cwd: Path, service: str, timeout_sec: int = 180, interval_sec: int = 5
) -> bool:
    """Wait for a docker compose service to report 'healthy'.

    Polls `docker compose ps --format json` until the service's State is 'healthy',
    or until timeout_sec have elapsed.
    """
    import time

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "ps",
                    "--format",
                    "json",
                    "--status",
                    "running",
                    service,
                ],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                # docker compose ps --format json returns either a single JSON object
                # or a JSON array depending on the version
                raw = result.stdout.strip()
                if raw.startswith("["):
                    containers = json.loads(raw)
                else:
                    containers = [json.loads(raw)] if raw else []
                for c in containers:
                    if c.get("Service") == service or c.get("Name", "").endswith(service):
                        state = c.get("State", "")
                        health = c.get("Health", state)
                        if health == "healthy" or state == "running" and "healthy" in str(c):
                            # Some compose versions put the detailed status in State
                            if "healthy" in state.lower() or "healthy" in str(c).lower():
                                return True
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        time.sleep(interval_sec)
    return False


def wait_for_http(
    url: str, timeout_sec: int = 60, interval_sec: int = 2, expected_status: int = 200
) -> tuple[bool, Optional[int], Optional[str]]:
    """Poll an HTTP endpoint until it returns expected_status or timeout.

    Returns (ok, status_code, error_message).
    """
    import time

    deadline = time.time() + timeout_sec
    last_error: Optional[str] = None
    last_status: Optional[int] = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                last_status = resp.status
                if resp.status == expected_status:
                    return True, last_status, None
                last_error = f"HTTP {resp.status}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(interval_sec)
    return False, last_status, last_error


def get_service_logs(cwd: Path, service: str, tail: int = 50) -> str:
    """Fetch the last N lines of logs for a compose service."""
    result = compose_cmd(cwd, "logs", "--tail", str(tail), service)
    return result.stderr + result.stdout


def diagnose_failed_service(
    cwd: Path, service: str, env: Dict[str, str]
) -> ServiceDiagnostic:
    """Collect logs and produce a human-readable suggestion for a failed service."""
    logs = get_service_logs(cwd, service, tail=80)
    status = "unknown"

    try:
        ps = subprocess.run(
            ["docker", "compose", "ps", service],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=10,
        )
        status = (ps.stdout + ps.stderr).strip()
    except Exception:  # noqa: BLE001
        pass

    suggestion = _suggest_fix(service, logs, env)
    return ServiceDiagnostic(service=service, log_tail=logs, status=status, suggestion=suggestion)


def _suggest_fix(service: str, logs: str, env: Dict[str, str]) -> str:
    """Heuristically match error patterns to actionable suggestions."""
    llogs = logs.lower()
    suggestions: List[str] = []

    if "postgres" in service.lower() or "connection refused" in llogs or "password authentication" in llogs:
        if not env.get("POSTGRES_PASSWORD"):
            suggestions.append("💡 POSTGRES_PASSWORD is not set in your .env. Both the postgres container and the API need it.")
        if "password authentication failed" in llogs:
            suggestions.append("💡 POSTGRES_PASSWORD in .env does not match what the postgres container was initialized with. Try removing the postgres volume: docker compose down -v")
        suggestions.append("💡 Check POSTGRES_HOST (should be the compose service name 'postgres' inside the docker network).")

    if "qdrant" in service.lower() or "mem0_store" in service:
        suggestions.append("💡 Check that QDRANT_HOST is set to 'mem0_store' (the compose service name) inside containers.")
        suggestions.append("💡 Verify qdrant is listening on port 6333: docker compose exec mem0_store wget -qO- http://localhost:6333/readyz")

    if "jwt" in llogs or "jwt_secret" in llogs:
        suggestions.append("💡 JWT_SECRET missing or empty. Generate one with: openssl rand -base64 48 and set it in .env, or set AUTH_DISABLED=true for local development.")

    if "openai_api_key" in llogs or "api key" in llogs:
        suggestions.append("💡 OPENAI_API_KEY not set. Get one from https://platform.openai.com/api-keys or change MEM0_LLM_PROVIDER to ollama/anthropic/gemini.")

    if "alembic" in llogs or "migration" in llogs:
        suggestions.append("💡 Alembic migration failed. Verify POSTGRES_HOST/PORT/USER/PASSWORD and that the mem0_app database exists (see server/init-db.sh).")

    if "configuration error" in llogs or "exit code 2" in llogs:
        suggestions.append("💡 The entrypoint detected a missing configuration variable. Look above in the logs for the detailed CONFIGURATION ERROR block.")

    if not suggestions:
        suggestions.append("💡 Review the full log output above. Search for 'CONFIGURATION ERROR' or 'Traceback' to pinpoint the issue.")

    return "\n".join(suggestions)


def run_docker_stack(stack: StackConfig, env: Dict[str, str], teardown: bool = True) -> List[TestResult]:
    """Bring up a compose stack, verify health endpoints, optionally tear it down.

    Returns a list of TestResult objects — one per service + an overall result.
    """
    results: List[TestResult] = []

    # ── 1. build ──────────────────────────────────────────────────────────
    print(f"\n  🐳 [{stack.name}] Building images...")
    build = compose_cmd(stack.cwd, "build", "--quiet")
    if build.returncode != 0:
        return [
            TestResult(
                f"docker_{stack.name}_build",
                False,
                f"`docker compose build` failed for stack '{stack.name}'.",
                details=f"    stdout:\n{build.stdout[-1000:]}\n    stderr:\n{build.stderr[-1000:]}",
            )
        ]
    results.append(TestResult(f"docker_{stack.name}_build", True, f"[{stack.name}] Images built successfully."))

    # ── 2. up (detached) ──────────────────────────────────────────────────
    print(f"  🐳 [{stack.name}] Starting services: {', '.join(stack.services)}...")
    up = compose_cmd(stack.cwd, "up", "-d", "--remove-orphans")
    if up.returncode != 0:
        return results + [
            TestResult(
                f"docker_{stack.name}_up",
                False,
                f"`docker compose up -d` failed for stack '{stack.name}'.",
                details=f"    stdout:\n{up.stdout[-1000:]}\n    stderr:\n{up.stderr[-1000:]}",
            )
        ]
    results.append(TestResult(f"docker_{stack.name}_up", True, f"[{stack.name}] Containers started."))

    try:
        # ── 3. wait for health ───────────────────────────────────────────
        for service in stack.services:
            print(f"  ⏳ [{stack.name}] Waiting for '{service}' to become healthy...")
            healthy = wait_for_service_health(stack.cwd, service, timeout_sec=240)
            if healthy:
                results.append(
                    TestResult(
                        f"docker_{stack.name}_{service}_health",
                        True,
                        f"[{stack.name}] Service '{service}' is healthy.",
                    )
                )
            else:
                diag = diagnose_failed_service(stack.cwd, service, env)
                results.append(
                    TestResult(
                        f"docker_{stack.name}_{service}_health",
                        False,
                        f"[{stack.name}] Service '{service}' did not become healthy within timeout.",
                        details=(
                            f"    Compose ps:\n{diag.status}\n\n"
                            f"    Logs (last 80 lines):\n{diag.log_tail[-3000:]}\n\n"
                            f"    Suggestions:\n{diag.suggestion}"
                        ),
                    )
                )

        # ── 4. verify HTTP endpoints are reachable from host ──────────────
        for service, url in stack.health_endpoints.items():
            print(f"  🌐 [{stack.name}] Checking endpoint {url}...")
            ok, status, err = wait_for_http(url, timeout_sec=60)
            if ok:
                results.append(
                    TestResult(
                        f"docker_{stack.name}_{service}_http",
                        True,
                        f"[{stack.name}] Endpoint {url} reachable from host (HTTP {status}).",
                    )
                )
            else:
                diag = diagnose_failed_service(stack.cwd, service, env)
                results.append(
                    TestResult(
                        f"docker_{stack.name}_{service}_http",
                        False,
                        f"[{stack.name}] Endpoint {url} not reachable from host (last error: {err}).",
                        details=(
                            f"    Suggestions:\n{diag.suggestion}\n\n"
                            f"    Logs:\n{diag.log_tail[-2000:]}"
                        ),
                    )
                )
    finally:
        # ── 5. teardown ───────────────────────────────────────────────────
        if teardown:
            print(f"  🧹 [{stack.name}] Tearing down...")
            compose_cmd(stack.cwd, "down", "--remove-orphans")
            results.append(
                TestResult(f"docker_{stack.name}_teardown", True, f"[{stack.name}] Stack torn down.")
            )
        else:
            results.append(
                TestResult(
                    f"docker_{stack.name}_teardown",
                    True,
                    f"[{stack.name}] Containers left running (--no-teardown). Access them via docker compose in {stack.cwd}.",
                )
            )

    return results


def get_server_stack(env_file_path: Path, env: Dict[str, str]) -> StackConfig:
    """Build the StackConfig for server/docker-compose.yaml."""
    server_port = env.get("MEM0_SERVER_PORT", "8888")
    dashboard_port = env.get("MEM0_DASHBOARD_PORT", "3000")
    return StackConfig(
        name="server",
        cwd=SERVER_DIR,
        services=["postgres", "mem0", "mem0-dashboard"],
        health_endpoints={
            "mem0": f"http://localhost:{server_port}/health",
            "mem0-dashboard": f"http://localhost:{dashboard_port}",
        },
    )


def get_openmemory_stack(env_file_path: Path, env: Dict[str, str]) -> StackConfig:
    """Build the StackConfig for openmemory/docker-compose.yml."""
    api_port = env.get("OPENMEMORY_API_PORT", "8765")
    ui_port = env.get("OPENMEMORY_UI_PORT", "3001")
    return StackConfig(
        name="openmemory",
        cwd=OPENMEMORY_DIR,
        services=["mem0_store", "openmemory-mcp", "openmemory-ui"],
        health_endpoints={
            "openmemory-mcp": f"http://localhost:{api_port}/health",
            "openmemory-ui": f"http://localhost:{ui_port}",
        },
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
    parser.add_argument("--all", action="store_true", help="Run all non-Docker tests")
    parser.add_argument("--env-check", action="store_true", help="Check .env file only")
    parser.add_argument("--config-errors", action="store_true", help="Check config error messages only")
    parser.add_argument("--health-endpoints", action="store_true", help="Check /health endpoint structure only")
    parser.add_argument("--list", action="store_true", help="List available tests and exit")
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Run REAL container smoke tests (requires Docker). Use with --stack to pick a stack.",
    )
    parser.add_argument(
        "--stack",
        choices=["server", "openmemory", "both"],
        default="both",
        help="Which docker-compose stack to test (default: both). Only used with --docker.",
    )
    parser.add_argument(
        "--no-teardown",
        action="store_true",
        help="Leave containers running after the docker smoke test (for manual debugging).",
    )
    args = parser.parse_args()

    env_file = Path(args.env_file).resolve()
    env = load_env_file(env_file)

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
        print("Available test groups:")
        env_test_names = [
            "test_env_file_exists",
            "test_env_required_variables",
            "test_env_naming_consistency",
        ]
        for group, test_names in [
            ("--env-check", env_test_names),
            ("--config-errors", [t.__name__ for t in all_config_error_tests]),
            ("--health-endpoints", [t.__name__ for t in all_health_tests]),
        ]:
            print(f"\n  {group}:")
            for name in test_names:
                print(f"    - {name}")
        print(
            "\n  --docker (requires Docker):\n"
            "    --stack server     : postgres + mem0 API + dashboard\n"
            "    --stack openmemory : qdrant + openmemory API + UI\n"
            "    --stack both       : both stacks (default)\n"
            "    --no-teardown      : leave containers running after test\n"
        )
        return 0

    # ── Docker mode ────────────────────────────────────────────────────────
    if args.docker:
        if not docker_available():
            print(
                "\n" + "=" * 72
                + "\n  ❌ Docker is not available. `docker compose version` did not succeed.\n"
                + "  💡 Install Docker Desktop / Docker Engine, or use the non-Docker test groups:\n"
                + "     python scripts/compose_smoke_test.py --all\n"
                + "=" * 72
                + "\n",
                file=sys.stderr,
            )
            return 3

        # Always run env check first — without .env, docker tests can't start
        env_results = run_tests(all_env_tests)
        env_pass = all(r.passed for r in env_results)
        if not env_pass:
            print_results(env_results)
            print(
                "  ⚠️  .env file issues detected — docker smoke tests may fail.\n"
                "     Fix the issues above, or pass --env-file <path> to point to a valid .env.\n",
                file=sys.stderr,
            )

        stacks: List[StackConfig] = []
        if args.stack in ("server", "both"):
            stacks.append(get_server_stack(env_file, env))
        if args.stack in ("openmemory", "both"):
            stacks.append(get_openmemory_stack(env_file, env))

        all_results: List[TestResult] = env_results
        for stack in stacks:
            print(f"\n{'=' * 72}")
            print(f"  🐳 DOCKER SMOKE TEST — stack: {stack.name}")
            print(f"{'=' * 72}")
            all_results.extend(
                run_docker_stack(stack, env, teardown=not args.no_teardown)
            )

        print_results(all_results)

        if not args.no_teardown:
            print(
                "  💡 To leave containers running after the test, re-run with --no-teardown\n"
            )
        else:
            for stack in stacks:
                print(f"  💡 Debug {stack.name}: cd {stack.cwd} && docker compose logs -f")

        return 0 if all(r.passed for r in all_results) else 1

    # ── Non-Docker mode ───────────────────────────────────────────────────
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
        parser.error(
            "Specify at least one test group: --all, --env-check, --config-errors, --health-endpoints, or --docker"
        )
        return 2

    results = run_tests(tests)
    print_results(results)

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
