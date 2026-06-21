.PHONY: all help install format sort lint docs build publish clean test \
        install-python-sdk format-python-sdk lint-python-sdk check-python-sdk build-python-sdk test-python-sdk clean-python-sdk \
        install-python-cli format-python-cli lint-python-cli check-python-cli build-python-cli test-python-cli clean-python-cli \
        install-node-cli format-node-cli lint-node-cli typecheck-node-cli check-node-cli build-node-cli test-node-cli clean-node-cli \
        install-ts-sdk format-ts-sdk lint-ts-sdk typecheck-ts-sdk check-ts-sdk build-ts-sdk test-ts-sdk clean-ts-sdk \
        install-openclaw format-openclaw lint-openclaw typecheck-openclaw check-openclaw build-openclaw test-openclaw clean-openclaw \
        install-vercel-ai-sdk format-vercel-ai-sdk lint-vercel-ai-sdk typecheck-vercel-ai-sdk check-vercel-ai-sdk build-vercel-ai-sdk test-vercel-ai-sdk clean-vercel-ai-sdk \
        install-pi-agent-plugin format-pi-agent-plugin lint-pi-agent-plugin typecheck-pi-agent-plugin check-pi-agent-plugin build-pi-agent-plugin test-pi-agent-plugin clean-pi-agent-plugin \
        install-opencode-plugin typecheck-opencode-plugin check-opencode-plugin build-opencode-plugin clean-opencode-plugin \
        build-server build-openmemory \
        install-core format-core lint-core typecheck-core check-core build-core test-core clean-core \
        install-integrations format-integrations lint-integrations typecheck-integrations check-integrations build-integrations test-integrations clean-integrations \
        install-infra build-infra clean-infra \
        install-all format-all lint-all typecheck-all check-all build-all test-all clean-all \
        release-check-core release-check-integrations release-check-all release-check \
        contract-check

# ═══════════════════════════════════════════════════════════════════════════
#  Package groups & skip strategy
# ═══════════════════════════════════════════════════════════════════════════
#
# Packages are divided into three groups so that local preflight checks can
# skip heavy dependencies. Use the SKIP_* variables or SKIP_PKGS to opt out:
#
#   make release-check SKIP_PKGS="opencode-plugin"
#   make check-all SKIP_INFRA=1
#
# ── Group 1: CORE ─────────────────────────────────────────────────────────
# Libraries and CLIs that every developer touches. Always run in CI and by
# default in local release checks.
CORE_PACKAGES = python-sdk python-cli node-cli ts-sdk
#
# ── Group 2: INTEGRATIONS ─────────────────────────────────────────────────
# IDE and framework plugins. Run in CI but can be skipped locally with
# SKIP_INTEGRATIONS=1 or by listing packages in SKIP_PKGS.
INTEGRATION_PACKAGES = openclaw vercel-ai-sdk pi-agent-plugin
# opencode-plugin requires bun and is excluded from INTEGRATION_PACKAGES by
# default. Add it explicitly or set INCLUDE_OPENCODE=1.
ifdef INCLUDE_OPENCODE
INTEGRATION_PACKAGES += opencode-plugin
endif
#
# ── Group 3: INFRASTRUCTURE ──────────────────────────────────────────────
# Docker-based services (server, openmemory). Never run by default — opt in
# with SKIP_INFRA=0 or make build-server / make build-openmemory directly.
INFRA_PACKAGES = server openmemory
#
# ── Skip handling ─────────────────────────────────────────────────────────
# Space-separated list of package short names to exclude, e.g.
#   make check-all SKIP_PKGS="opencode-plugin openmemory"
SKIP_PKGS ?=

# Helper: filter out packages listed in SKIP_PKGS from a list
filter-skip = $(filter-out $(SKIP_PKGS),$(1))

# Resolve each group respecting SKIP_PKGS and optional opt-out flags
ACTIVE_CORE         = $(call filter-skip,$(CORE_PACKAGES))
ACTIVE_INTEGRATIONS = $(if $(SKIP_INTEGRATIONS),,$(call filter-skip,$(INTEGRATION_PACKAGES)))
# Infra is opt-in: only active when SKIP_INFRA is explicitly set to "0"
ACTIVE_INFRA        = $(if $(filter 0,$(SKIP_INFRA)),$(call filter-skip,$(INFRA_PACKAGES)),)

# Convenience: all active non-infra packages (used by the default *-all)
ALL_PACKAGES = $(ACTIVE_CORE) $(ACTIVE_INTEGRATIONS)

# ── Variables ─────────────────────────────────────────────────────────────

ISORT_OPTIONS = --profile black
PROJECT_NAME := mem0ai

# Python / Node versions (informational, used by CI matrix configs)
PYTHON_VERSIONS ?= 3.10 3.11 3.12
NODE_VERSIONS ?= 20 22

# ── Default target ────────────────────────────────────────────────────────

all: format lint

help:
	@echo "Mem0 monorepo — unified task entry points"
	@echo ""
	@echo "Package groups:"
	@echo "  core           python-sdk, python-cli, node-cli, ts-sdk"
	@echo "  integrations   openclaw, vercel-ai-sdk, pi-agent-plugin"
	@echo "                   (+ opencode-plugin if INCLUDE_OPENCODE=1)"
	@echo "  infra          server, openmemory  (Docker — opt-in only)"
	@echo ""
	@echo "Skip-control variables:"
	@echo "  SKIP_PKGS=\"a b\"        Exclude specific packages by short name"
	@echo "  SKIP_INTEGRATIONS=1     Skip all integrations"
	@echo "  SKIP_INFRA=0            Enable infra targets (default: skipped)"
	@echo "  INCLUDE_OPENCODE=1      Add opencode-plugin to integrations"
	@echo ""
	@echo "Meta targets — aggregate across groups:"
	@echo "  make install-core / format-core / lint-core / typecheck-core"
	@echo "  make check-core / build-core / test-core / clean-core"
	@echo "  make install-integrations / check-integrations / build-integrations / ..."
	@echo "  make install-all / format-all / lint-all / typecheck-all"
	@echo "  make check-all / build-all / test-all / clean-all"
	@echo ""
	@echo "Per-package targets (replace <pkg>):"
	@echo "  make install-<pkg> / format-<pkg> / lint-<pkg> / typecheck-<pkg>"
	@echo "  make check-<pkg> / build-<pkg> / test-<pkg> / clean-<pkg>"
	@echo ""
	@echo "Available packages:"
	@echo "  python-sdk, python-cli, node-cli, ts-sdk,"
	@echo "  openclaw, vercel-ai-sdk, pi-agent-plugin, opencode-plugin,"
	@echo "  server, openmemory"
	@echo ""
	@echo "Release preflight (layered):"
	@echo "  make release-check-core        Core only — must pass before cutting any release"
	@echo "  make release-check-integrations  Integration plugins only"
	@echo "  make release-check             Core + integrations (DEFAULT local preflight)"
	@echo "  make release-check-all         Core + integrations + infra (CI full gate)"
	@echo ""
	@echo "Contract / cross-cutting:"
	@echo "  make contract-check            Verify CLI payload contract files are in sync"

# ═══════════════════════════════════════════════════════════════════════════
#  Python SDK  (mem0/)
# ═══════════════════════════════════════════════════════════════════════════

install-python-sdk:
	hatch env create

format-python-sdk:
	hatch run format

sort:
	hatch run isort mem0/

lint-python-sdk:
	hatch run lint

check-python-sdk: format-python-sdk lint-python-sdk

build-python-sdk:
	hatch build

test-python-sdk:
	hatch run test

clean-python-sdk:
	rm -rf dist

# Legacy aliases — keep default targets pointing at python-sdk for backward
# compatibility with contributors who only touch the core Python SDK.
install: install-python-sdk
format: format-python-sdk
lint: lint-python-sdk
build: build-python-sdk
test: test-python-sdk
clean: clean-python-sdk
install_all:
	pip install ruff==0.6.9 groq together boto3 litellm ollama chromadb weaviate weaviate-client sentence_transformers vertexai \
	            google-generativeai elasticsearch opensearch-py vecs "pinecone<7.0.0" pinecone-text faiss-cpu langchain-community \
							upstash-vector azure-search-documents langchain-memgraph langchain-neo4j langchain-aws rank-bm25 pymochow pymongo psycopg kuzu databricks-sdk valkey

publish:
	hatch publish

# ═══════════════════════════════════════════════════════════════════════════
#  Python CLI  (cli/python/)
# ═══════════════════════════════════════════════════════════════════════════

install-python-cli:
	cd cli/python && pip install -e ".[dev]"

format-python-cli:
	cd cli/python && ruff format .

lint-python-cli:
	cd cli/python && ruff check .

check-python-cli: format-python-cli lint-python-cli

build-python-cli:
	cd cli/python && hatch build --clean

test-python-cli:
	cd cli/python && pytest

clean-python-cli:
	rm -rf cli/python/dist

# ═══════════════════════════════════════════════════════════════════════════
#  Node CLI  (cli/node/)
# ═══════════════════════════════════════════════════════════════════════════

install-node-cli:
	cd cli/node && pnpm install

format-node-cli:
	cd cli/node && pnpm run lint:fix

lint-node-cli:
	cd cli/node && pnpm run lint

typecheck-node-cli:
	cd cli/node && pnpm run typecheck

check-node-cli: lint-node-cli typecheck-node-cli

build-node-cli:
	cd cli/node && pnpm run build

test-node-cli:
	cd cli/node && pnpm run test

clean-node-cli:
	rm -rf cli/node/dist

# ═══════════════════════════════════════════════════════════════════════════
#  TypeScript SDK  (mem0-ts/)
# ═══════════════════════════════════════════════════════════════════════════

install-ts-sdk:
	cd mem0-ts && pnpm install

format-ts-sdk:
	cd mem0-ts && pnpm run format

lint-ts-sdk:
	cd mem0-ts && npx prettier --check .

typecheck-ts-sdk:
	cd mem0-ts && npx tsc --noEmit

check-ts-sdk: lint-ts-sdk typecheck-ts-sdk

build-ts-sdk:
	cd mem0-ts && pnpm run build

test-ts-sdk:
	cd mem0-ts && pnpm run test:unit

clean-ts-sdk:
	rm -rf mem0-ts/dist

# ═══════════════════════════════════════════════════════════════════════════
#  OpenClaw plugin  (integrations/openclaw/)
# ═══════════════════════════════════════════════════════════════════════════

install-openclaw:
	cd integrations/openclaw && pnpm install

format-openclaw:
	cd integrations/openclaw && pnpm exec prettier --write .

lint-openclaw:
	@echo "openclaw: no lint step configured (relies on tsc + vitest)"

typecheck-openclaw:
	cd integrations/openclaw && pnpm exec tsc --noEmit

check-openclaw: typecheck-openclaw

build-openclaw:
	cd integrations/openclaw && pnpm build

test-openclaw:
	cd integrations/openclaw && pnpm test

clean-openclaw:
	rm -rf integrations/openclaw/dist

# ═══════════════════════════════════════════════════════════════════════════
#  Vercel AI SDK provider  (integrations/vercel-ai-sdk/)
# ═══════════════════════════════════════════════════════════════════════════

install-vercel-ai-sdk:
	cd integrations/vercel-ai-sdk && pnpm install

format-vercel-ai-sdk:
	cd integrations/vercel-ai-sdk && pnpm exec prettier --write .

lint-vercel-ai-sdk:
	cd integrations/vercel-ai-sdk && pnpm run lint

typecheck-vercel-ai-sdk:
	cd integrations/vercel-ai-sdk && pnpm run type-check

check-vercel-ai-sdk: lint-vercel-ai-sdk typecheck-vercel-ai-sdk

build-vercel-ai-sdk:
	cd integrations/vercel-ai-sdk && pnpm run build

test-vercel-ai-sdk:
	cd integrations/vercel-ai-sdk && pnpm run test

clean-vercel-ai-sdk:
	rm -rf integrations/vercel-ai-sdk/dist

# ═══════════════════════════════════════════════════════════════════════════
#  Pi Agent plugin  (integrations/pi-agent-plugin/)
# ═══════════════════════════════════════════════════════════════════════════

install-pi-agent-plugin:
	cd integrations/pi-agent-plugin && pnpm install

format-pi-agent-plugin:
	cd integrations/pi-agent-plugin && pnpm exec prettier --write .

lint-pi-agent-plugin:
	@echo "pi-agent-plugin: no lint step configured (relies on tsc + vitest)"

typecheck-pi-agent-plugin:
	cd integrations/pi-agent-plugin && pnpm run typecheck

check-pi-agent-plugin: typecheck-pi-agent-plugin

build-pi-agent-plugin:
	cd integrations/pi-agent-plugin && pnpm run build

test-pi-agent-plugin:
	cd integrations/pi-agent-plugin && pnpm test

clean-pi-agent-plugin:
	rm -rf integrations/pi-agent-plugin/dist

# ═══════════════════════════════════════════════════════════════════════════
#  OpenCode plugin  (integrations/mem0-plugin/.opencode-plugin/)
#  Requires bun — excluded from default integrations; set INCLUDE_OPENCODE=1
# ═══════════════════════════════════════════════════════════════════════════

install-opencode-plugin:
	cd integrations/mem0-plugin/.opencode-plugin && bun install

typecheck-opencode-plugin:
	cd integrations/mem0-plugin/.opencode-plugin && bun run type-check

check-opencode-plugin: typecheck-opencode-plugin

build-opencode-plugin:
	cd integrations/mem0-plugin/.opencode-plugin && bun run build

clean-opencode-plugin:
	rm -rf integrations/mem0-plugin/.opencode-plugin/dist

# ═══════════════════════════════════════════════════════════════════════════
#  Server  (server/)  — Docker build only; opt-in via SKIP_INFRA=0
# ═══════════════════════════════════════════════════════════════════════════

build-server:
	cd server && make build

# ═══════════════════════════════════════════════════════════════════════════
#  OpenMemory  (openmemory/)  — Docker build only; opt-in via SKIP_INFRA=0
# ═══════════════════════════════════════════════════════════════════════════

build-openmemory:
	cd openmemory && make build

# ═══════════════════════════════════════════════════════════════════════════
#  Group aggregates
# ═══════════════════════════════════════════════════════════════════════════
#
# Each verb (install / format / lint / typecheck / check / build / test /
# clean) has a group-level target (e.g. check-core, check-integrations) and
# a package-level target (e.g. check-python-sdk). The group targets expand
# to their per-package counterparts filtered through the skip strategy.

# ── CORE ───────────────────────────────────────────────────────────────────
install-core:     $(addprefix install-,$(ACTIVE_CORE))
format-core:      $(addprefix format-,$(ACTIVE_CORE))
lint-core:        $(addprefix lint-,$(ACTIVE_CORE))
typecheck-core:   $(addprefix typecheck-,$(ACTIVE_CORE))
check-core:       $(addprefix check-,$(ACTIVE_CORE))
build-core:       $(addprefix build-,$(ACTIVE_CORE))
test-core:        $(addprefix test-,$(ACTIVE_CORE))
clean-core:       $(addprefix clean-,$(ACTIVE_CORE))

# ── INTEGRATIONS ──────────────────────────────────────────────────────────
install-integrations:     $(addprefix install-,$(ACTIVE_INTEGRATIONS))
format-integrations:      $(addprefix format-,$(ACTIVE_INTEGRATIONS))
lint-integrations:        $(addprefix lint-,$(ACTIVE_INTEGRATIONS))
typecheck-integrations:   $(addprefix typecheck-,$(ACTIVE_INTEGRATIONS))
check-integrations:       $(addprefix check-,$(ACTIVE_INTEGRATIONS))
build-integrations:       $(addprefix build-,$(ACTIVE_INTEGRATIONS))
test-integrations:        $(addprefix test-,$(ACTIVE_INTEGRATIONS))
clean-integrations:       $(addprefix clean-,$(ACTIVE_INTEGRATIONS))

# ── INFRA (opt-in) ────────────────────────────────────────────────────────
install-infra:
	@echo "Infra packages (server, openmemory) use Docker — no install step."
	@echo "Use 'make build-server' or 'make build-openmemory' directly."

build-infra:   $(addprefix build-,$(ACTIVE_INFRA))
clean-infra:
	@echo "Infra packages use docker compose down -v — run from their own directories."

# ── ALL (core + integrations; infra always opt-in) ────────────────────────
install-all:     install-core install-integrations
format-all:      format-core format-integrations
lint-all:        lint-core lint-integrations
typecheck-all:   typecheck-core typecheck-integrations
check-all:       check-core check-integrations
build-all:       build-core build-integrations
test-all:        test-core test-integrations
clean-all:       clean-core clean-integrations clean-opencode-plugin

# ═══════════════════════════════════════════════════════════════════════════
#  Contract / release gates (layered)
# ═══════════════════════════════════════════════════════════════════════════
#
# Release preflight is split into three layers so a developer can run just
# what's relevant to the change they're about to ship:
#
#   release-check-core          Always required — core quality gate + contract
#   release-check-integrations  Integration plugin quality gate
#   release-check               Core + integrations (DEFAULT local preflight)
#   release-check-all           Everything including infra Docker builds (CI)

# Verify that the two CLI payload contract files are semantically identical.
# Both Python and Node CLIs derive their payload builders from this file;
# drift between the two copies is a bug. We compare parsed JSON, not bytes,
# so formatting/indentation differences don't cause false failures.
contract-check:
	@echo "Checking CLI payload contract consistency..."
	@python3 -c "import json,sys; py=json.load(open('cli/python/src/mem0_cli/contract/payload_contract.json')); node=json.load(open('cli/node/src/contract/payload_contract.json')); sys.exit(0 if py==node else 1)" || ( \
	  echo "ERROR: CLI payload contract files are out of sync."; \
	  echo "       cli/python/src/mem0_cli/contract/payload_contract.json"; \
	  echo "       cli/node/src/contract/payload_contract.json"; \
	  echo "       Both files must be semantically identical — copy the canonical one to the other."; \
	  exit 1)
	@echo "Contract check passed ✓"

# Layer 1 — core packages + cross-cutting contract. This is the minimum
# bar every release must clear regardless of scope.
release-check-core: check-core build-core contract-check
	@echo ""
	@echo "══════════════════════════════════════════════════════════════"
	@echo "  Core release preflight passed ✓"
	@echo "  Packages: $(ACTIVE_CORE)"
	@echo "══════════════════════════════════════════════════════════════"

# Layer 2 — integration plugins only. Used when cutting a plugin release
# or when a core change might affect plugin behaviour.
release-check-integrations: check-integrations build-integrations
	@echo ""
	@echo "══════════════════════════════════════════════════════════════"
	@echo "  Integrations release preflight passed ✓"
	@echo "  Packages: $(ACTIVE_INTEGRATIONS)"
	@echo "══════════════════════════════════════════════════════════════"

# Default local release check — core + integrations (infra excluded to
# avoid pulling Docker dependencies on developer laptops).
release-check: release-check-core release-check-integrations
	@echo ""
	@echo "All release checks passed ✓"

# Full CI gate — everything including infra Docker builds.
# Explicitly sets SKIP_INFRA=0 so infra targets participate.
release-check-all:
	@$(MAKE) --no-print-directory release-check-core SKIP_PKGS="$(SKIP_PKGS)" SKIP_INFRA=0
	@$(MAKE) --no-print-directory release-check-integrations SKIP_PKGS="$(SKIP_PKGS)" SKIP_INFRA=0
	@$(MAKE) --no-print-directory build-infra SKIP_PKGS="$(SKIP_PKGS)" SKIP_INFRA=0
	@echo ""
	@echo "Full release preflight passed ✓"

# ═══════════════════════════════════════════════════════════════════════════
#  Docs
# ═══════════════════════════════════════════════════════════════════════════

docs:
	cd docs && mintlify dev
