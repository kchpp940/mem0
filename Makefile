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
        install-all format-all lint-all typecheck-all check-all build-all test-all clean-all \
        contract-check

# ── Variables ─────────────────────────────────────────────────────────────

ISORT_OPTIONS = --profile black
PROJECT_NAME := mem0ai

# Python versions for matrix testing (used by CI)
PYTHON_VERSIONS ?= 3.10 3.11 3.12
NODE_VERSIONS ?= 20 22

# ── Default target ────────────────────────────────────────────────────────

all: format lint

help:
	@echo "Mem0 monorepo — unified task entry points"
	@echo ""
	@echo "Meta targets (run across all sub-projects):"
	@echo "  make install          Install dependencies for all packages"
	@echo "  make format           Format code in all packages"
	@echo "  make lint             Lint all packages"
	@echo "  make typecheck        Type-check all TypeScript packages"
	@echo "  make check            Full quality gate (format-check + lint + typecheck)"
	@echo "  make build            Build all packages"
	@echo "  make test             Run all tests"
	@echo "  make clean            Remove build artifacts everywhere"
	@echo ""
	@echo "Per-package targets (replace <pkg> with the package name):"
	@echo "  make install-<pkg>    Install deps for one package"
	@echo "  make format-<pkg>     Format one package"
	@echo "  make lint-<pkg>       Lint one package"
	@echo "  make typecheck-<pkg>  Type-check one package (TS only)"
	@echo "  make check-<pkg>      Full check on one package"
	@echo "  make build-<pkg>      Build one package"
	@echo "  make test-<pkg>       Test one package"
	@echo "  make clean-<pkg>      Clean one package"
	@echo ""
	@echo "Available packages:"
	@echo "  python-sdk, python-cli, node-cli, ts-sdk,"
	@echo "  openclaw, vercel-ai-sdk, pi-agent-plugin, opencode-plugin,"
	@echo "  server, openmemory"
	@echo ""
	@echo "Contract / release targets:"
	@echo "  make contract-check   Verify CLI payload contract files are in sync"
	@echo "  make release-check    Pre-release quality gate (check + build + contract-check)"

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

# Legacy aliases (keep backward-compat with the old root Makefile)
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
#  Server  (server/)
# ═══════════════════════════════════════════════════════════════════════════

build-server:
	cd server && make build

# ═══════════════════════════════════════════════════════════════════════════
#  OpenMemory  (openmemory/)
# ═══════════════════════════════════════════════════════════════════════════

build-openmemory:
	cd openmemory && make build

# ═══════════════════════════════════════════════════════════════════════════
#  Aggregate meta-targets
# ═══════════════════════════════════════════════════════════════════════════

# Note: opencode-plugin uses bun and is excluded from the default meta-targets
# to avoid requiring bun on every dev machine. Use make install-opencode-plugin
# explicitly if you need it.

TS_PACKAGES = ts-sdk node-cli openclaw vercel-ai-sdk pi-agent-plugin
PY_PACKAGES = python-sdk python-cli
ALL_PACKAGES = $(PY_PACKAGES) $(TS_PACKAGES)

install-all: install-python-sdk install-python-cli install-ts-sdk install-node-cli \
             install-openclaw install-vercel-ai-sdk install-pi-agent-plugin

format-all: format-python-sdk format-python-cli format-ts-sdk format-node-cli \
            format-openclaw format-vercel-ai-sdk format-pi-agent-plugin

lint-all: lint-python-sdk lint-python-cli lint-ts-sdk lint-node-cli \
          lint-openclaw lint-vercel-ai-sdk

typecheck-all: typecheck-ts-sdk typecheck-node-cli typecheck-openclaw \
               typecheck-vercel-ai-sdk typecheck-pi-agent-plugin

check-all: check-python-sdk check-python-cli check-ts-sdk check-node-cli \
           check-openclaw check-vercel-ai-sdk check-pi-agent-plugin

build-all: build-python-sdk build-python-cli build-ts-sdk build-node-cli \
           build-openclaw build-vercel-ai-sdk build-pi-agent-plugin

test-all: test-python-sdk test-python-cli test-ts-sdk test-node-cli \
          test-openclaw test-vercel-ai-sdk test-pi-agent-plugin

clean-all: clean-python-sdk clean-python-cli clean-ts-sdk clean-node-cli \
           clean-openclaw clean-vercel-ai-sdk clean-pi-agent-plugin clean-opencode-plugin

# ═══════════════════════════════════════════════════════════════════════════
#  Contract / release gates
# ═══════════════════════════════════════════════════════════════════════════

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

# Pre-release quality gate — everything that should be green before cutting a release.
release-check: check-all build-all contract-check
	@echo ""
	@echo "All release checks passed ✓"

# ═══════════════════════════════════════════════════════════════════════════
#  Docs
# ═══════════════════════════════════════════════════════════════════════════

docs:
	cd docs && mintlify dev
