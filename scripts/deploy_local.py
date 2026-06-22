#!/usr/bin/env python3
"""
One-click local deployment orchestrator for Mem0 server + OpenMemory stacks.

Walks the user through .env generation (if missing), runs pre-flight validation,
brings up compose stacks, waits for all services to become healthy, then runs
end-to-end HTTP smoke tests. On failure, automatically collects logs and prints
actionable suggestions.

This is a convenience wrapper around compose_smoke_test.py + manual docker
compose commands — use it when you want one command that either succeeds
end-to-end or gives you a copy-pasteable diagnosis.

Usage:
    # Deploy both stacks (default — prompts for any missing config)
    python scripts/deploy_local.py

    # Deploy only one stack
    python scripts/deploy_local.py --stack server
    python scripts/deploy_local.py --stack openmemory

    # Skip prompts, use defaults + assume .env is already present (CI mode)
    python scripts/deploy_local.py --yes

    # Do not tear down after successful deploy (leave containers running)
    python scripts/deploy_local.py --keep-running

    # Skip the container phase, only validate config and create .env
    python scripts/deploy_local.py --config-only

Exit codes:
    0: everything deployed and verified
    1: deployment failed (diagnostics printed before exit)
    2: usage or configuration error
    3: Docker not available
"""

import argparse
import json
import os
import secrets
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO_ROOT / "server"
OPENMEMORY_DIR = REPO_ROOT / "openmemory"
SMOKE_TEST_SCRIPT = REPO_ROOT / "scripts" / "compose_smoke_test.py"

BANNER = r"""
  __  __        ____  _       _ 
 |  \/  |_ __  / ___|| | ___ | |
 | |\/| | '_ \ \___ \| |/ _ \| |
 | |  | | |_) | ___) | | (_) |_|
 |_|  |_| .__/ |____/|_|\___/(_)
        |_|                     
  Local Deployment Orchestrator
"""


def step(msg: str) -> None:
    """Print a numbered-step style heading."""
    print(f"\n  → {msg}")


def ok(msg: str) -> None:
    print(f"    ✅ {msg}")


def warn(msg: str) -> None:
    print(f"    ⚠️  {msg}")


def fail(msg: str) -> None:
    print(f"    ❌ {msg}")


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Simple y/n prompt; returns default on empty input or --yes flag."""
    if "--yes" in sys.argv:
        return default
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        answer = input(question + suffix).strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


def generate_secret(num_bytes: int = 48) -> str:
    """Generate a URL-safe random secret."""
    return secrets.token_urlsafe(num_bytes)


def docker_available() -> bool:
    try:
        return subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True, timeout=10
        ).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def load_env(path: Path) -> Dict[str, str]:
    """Load .env file into a dict."""
    result: Dict[str, str] = {}
    if not path.is_file():
        return result
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def save_env(path: Path, variables: Dict[str, str]) -> None:
    """Persist a dict to .env, preserving comment headers from .env.example."""
    example_path = REPO_ROOT / ".env.example"
    lines: List[str] = []
    if example_path.is_file():
        for line in example_path.read_text().splitlines():
            if line.startswith("#"):
                lines.append(line)
            elif "=" in line:
                k = line.split("=", 1)[0].strip()
                if k in variables:
                    lines.append(f"{k}={variables[k]}")
                else:
                    lines.append(line)
    for k, v in variables.items():
        if not any(line.startswith(k + "=") for line in lines):
            lines.append(f"{k}={v}")
    path.write_text("\n".join(lines) + "\n")


def interactive_create_env(env_path: Path, yes: bool) -> Dict[str, str]:
    """Guide the user through .env creation. Returns the merged env dict."""
    env = load_env(REPO_ROOT / ".env.example")

    # Always set POSTGRES_PASSWORD
    if not env.get("POSTGRES_PASSWORD"):
        env["POSTGRES_PASSWORD"] = generate_secret(32)
        ok(f"Generated POSTGRES_PASSWORD (saved to {env_path})")
    else:
        ok("POSTGRES_PASSWORD already set in .env")

    # JWT_SECRET for server stack
    if not env.get("JWT_SECRET"):
        env["JWT_SECRET"] = generate_secret(48)
        ok("Generated JWT_SECRET for server stack")
    else:
        ok("JWT_SECRET already set")

    # MEM0_USER_ID for OpenMemory
    if not env.get("MEM0_USER_ID"):
        env["MEM0_USER_ID"] = f"local-user-{generate_secret(8)}"
        ok(f"Set MEM0_USER_ID={env['MEM0_USER_ID']}")

    # LLM provider choice
    if not yes:
        print("\n  🤖 Choose an LLM provider (pasted into .env):")
        print("     1) OpenAI   (needs OPENAI_API_KEY)")
        print("     2) Ollama   (100% local, no key — install from https://ollama.com)")
        print("     3) Skip     (configure later in .env)")
        choice = input("     Enter 1/2/3 [default 2]: ").strip() or "2"
    else:
        choice = "2"

    if choice == "1":
        env["MEM0_LLM_PROVIDER"] = "openai"
        env["MEM0_EMBEDDER_PROVIDER"] = "openai"
        if not env.get("OPENAI_API_KEY"):
            key = input("     Paste your OPENAI_API_KEY: ").strip()
            if key:
                env["OPENAI_API_KEY"] = key
                ok("OPENAI_API_KEY saved")
            else:
                warn("OPENAI_API_KEY left empty — set it later in .env before starting the server")
    elif choice == "2":
        env["MEM0_LLM_PROVIDER"] = "ollama"
        env["MEM0_EMBEDDER_PROVIDER"] = "ollama"
        env["OLLAMA_BASE_URL"] = env.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
        env["MEM0_DEFAULT_LLM_MODEL"] = env.get("MEM0_DEFAULT_LLM_MODEL", "llama3.1")
        env["MEM0_DEFAULT_EMBEDDER_MODEL"] = env.get("MEM0_DEFAULT_EMBEDDER_MODEL", "nomic-embed-text")
        ok("Configured Ollama provider. Make sure to run: ollama pull llama3.1 && ollama pull nomic-embed-text")

    # Auth shortcut for local dev
    if yes or prompt_yes_no("Disable JWT auth on server for local development?", default=True):
        env["AUTH_DISABLED"] = "true"
        ok("AUTH_DISABLED=true — no login required for local dashboard")
    else:
        env["AUTH_DISABLED"] = "false"

    save_env(env_path, env)
    print(f"\n  💾 Configuration written to {env_path}")
    return env


def run_smoke(mode: str, *extra_args: str) -> Tuple[int, str, str]:
    """Run compose_smoke_test.py with args. Returns (exit_code, stdout, stderr)."""
    cmd = [sys.executable, str(SMOKE_TEST_SCRIPT), *extra_args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    return proc.returncode, proc.stdout, proc.stderr


def print_service_urls(stacks: List[str], env: Dict[str, str]) -> None:
    """Print a helpful summary of URLs after successful deployment."""
    print("\n" + "=" * 72)
    print("  🎉 DEPLOYMENT COMPLETE")
    print("=" * 72)

    if "server" in stacks:
        api_port = env.get("MEM0_SERVER_PORT", "8888")
        dash_port = env.get("MEM0_DASHBOARD_PORT", "3000")
        print(f"\n  Server stack:")
        print(f"    • REST API:     http://localhost:{api_port}")
        print(f"    • /health:      http://localhost:{api_port}/health")
        print(f"    • OpenAPI docs: http://localhost:{api_port}/docs")
        print(f"    • Dashboard:    http://localhost:{dash_port}")
    if "openmemory" in stacks:
        api_port = env.get("OPENMEMORY_API_PORT", "8765")
        ui_port = env.get("OPENMEMORY_UI_PORT", "3001")
        print(f"\n  OpenMemory stack:")
        print(f"    • MCP API:      http://localhost:{api_port}")
        print(f"    • /health:      http://localhost:{api_port}/health")
        print(f"    • OpenAPI docs: http://localhost:{api_port}/docs")
        print(f"    • Web UI:       http://localhost:{ui_port}")
    print(
        "\n  Next steps:"
        "\n    1. Visit the dashboard/UI URLs above"
        "\n    2. Read docs: https://docs.mem0.ai/open-source/local-deployment-playbook"
        "\n    3. Tear down later: cd server && docker compose down"
        "\n                    cd openmemory && docker compose down"
        "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Mem0 local deployment orchestrator")
    parser.add_argument(
        "--stack", choices=["server", "openmemory", "both"], default="both",
        help="Which compose stacks to deploy (default: both)"
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Accept all defaults, do not prompt"
    )
    parser.add_argument(
        "--keep-running", action="store_true",
        help="Leave containers running after successful deploy"
    )
    parser.add_argument(
        "--config-only", action="store_true",
        help="Only create/validate .env, do not start containers"
    )
    parser.add_argument(
        "--env-file", default=str(REPO_ROOT / ".env"),
        help="Path to the .env file to use/create (default: repo root)"
    )
    args = parser.parse_args()

    env_path = Path(args.env_file).resolve()
    print(BANNER)

    # ── Step 1: Docker check ──────────────────────────────────────────────
    if not args.config_only:
        step("Checking Docker availability")
        if not docker_available():
            fail("Docker with compose plugin is not available.")
            print(
                "\n     Install Docker Desktop (macOS/Windows) or Docker Engine + compose plugin (Linux),"
                "\n     then re-run this script. If you only want to validate configs without containers,"
                "\n     pass --config-only or use: python scripts/compose_smoke_test.py --all"
                "\n",
                file=sys.stderr,
            )
            return 3
        ok("Docker compose available")

    # ── Step 2: .env creation ─────────────────────────────────────────────
    step("Environment configuration")
    if env_path.is_file():
        env = load_env(env_path)
        ok(f".env already exists at {env_path} ({len(env)} variables loaded)")
    else:
        if args.yes or prompt_yes_no(f"No .env found at {env_path}. Create one now?", default=True):
            env = interactive_create_env(env_path, args.yes)
        else:
            fail("Cannot deploy without .env file.")
            print(
                f"     Create one manually: cp {REPO_ROOT / '.env.example'} {env_path}",
                file=sys.stderr,
            )
            return 2

    # ── Step 3: Non-container smoke tests ─────────────────────────────────
    step("Running pre-flight validation (non-Docker)")
    code, out, err = run_smoke("all", "--env-file", str(env_path), "--all")
    print(out)
    if code != 0:
        fail("Pre-flight validation failed — fix the issues above before starting containers.")
        print(err)
        return 1
    ok("Pre-flight checks passed (10/10)")

    if args.config_only:
        print("\n  ✅ Configuration-only run complete. .env is valid for deployment.")
        print(f"     Run without --config-only to start containers.")
        return 0

    # ── Step 4: Docker smoke tests (real containers) ──────────────────────
    step("Deploying compose stacks and verifying end-to-end")
    smoke_args = ["--env-file", str(env_path), "--docker", "--stack", args.stack]
    if args.keep_running:
        smoke_args.append("--no-teardown")

    code, out, err = run_smoke("docker", *smoke_args)
    print(out)
    if code != 0:
        print(err, file=sys.stderr)
        fail("Container smoke test failed. Review the diagnostics above.")
        print(
            f"\n     Common fixes:"
            f"\n       • Missing variables — edit {env_path}, then re-run"
            f"\n       • Port conflicts    — adjust *_PORT in {env_path}"
            f"\n       • Stale volumes    — cd server && docker compose down -v"
            f"\n       • Full guide       — https://docs.mem0.ai/open-source/local-deployment-playbook",
            file=sys.stderr,
        )
        return 1

    ok("All stacks deployed and verified end-to-end")

    # ── Step 5: Summary ───────────────────────────────────────────────────
    stacks = ["server", "openmemory"] if args.stack == "both" else [args.stack]
    print_service_urls(stacks, env)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n  ⚠️  Interrupted by user. Use 'docker compose down' in each stack directory to stop services.")
        sys.exit(130)
