# ═══════════════════════════════════════════════════════════════════════════
#  Mem0 monorepo — manifest-driven task runner
#  Single source of truth: monorepo-manifest.json
# ═══════════════════════════════════════════════════════════════════════════

# ── Location of the manifest and helper scripts ───────────────────────────
MANIFEST         := monorepo-manifest.json
MK_GENERATOR     := python3 scripts/generate_makefile_targets.py
CI_HELPER        := python3 scripts/ci_manifest.py

# ── Dynamic package lists (read from manifest) ──────────────────────────
# For core and integrations, use --release-only to respect the
# default_in_release flag (e.g. opencode-plugin is excluded by default).
# For infra, never use --release-only — the packages are opt-in via
# SKIP_INFRA=0 regardless of their default_in_release value.
CORE_PACKAGES         := $(shell $(MK_GENERATOR) --list-packages --group core --release-only)
INTEGRATION_PACKAGES  := $(shell $(MK_GENERATOR) --list-packages --group integrations --release-only)
INFRA_PACKAGES        := $(shell $(MK_GENERATOR) --list-packages --group infra)

# opencode-plugin requires bun and is excluded from INTEGRATION_PACKAGES by
# default. Set INCLUDE_OPENCODE=1 to include it.
ifdef INCLUDE_OPENCODE
INTEGRATION_PACKAGES += opencode-plugin
endif

# ── Skip strategy ─────────────────────────────────────────────────────────
# Space-separated list of package short names to exclude, e.g.
#   make check-all SKIP_PKGS="opencode-plugin openmemory"
SKIP_PKGS ?=

# Helper: filter out packages listed in SKIP_PKGS from a list
filter-skip = $(filter-out $(SKIP_PKGS),$(1))

# Resolve each group respecting SKIP_PKGS and optional opt-out flags
ACTIVE_CORE         := $(call filter-skip,$(CORE_PACKAGES))
ACTIVE_INTEGRATIONS := $(if $(SKIP_INTEGRATIONS),,$(call filter-skip,$(INTEGRATION_PACKAGES)))
# Infra is opt-in: only active when SKIP_INFRA is explicitly set to "0"
ACTIVE_INFRA        := $(if $(filter 0,$(SKIP_INFRA)),$(call filter-skip,$(INFRA_PACKAGES)),)

# ── Per-package targets (auto-generated from manifest) ───────────────────
# Generated targets are written to a temporary .mk file and included.
# Using `include` is more robust than $(eval $(shell ...)) for generated
# content containing semicolons and special characters.

# First, generate the targets file if it doesn't exist or manifest changed.
# We use an order-only prerequisite on the manifest file.
monorepo-targets.mk: $(MANIFEST) scripts/generate_makefile_targets.py
	@$(MK_GENERATOR) --print-phony > $@
	@echo "" >> $@
	@$(MK_GENERATOR) --print-targets >> $@

# Include the generated per-package targets
include monorepo-targets.mk

# ── Group aggregate targets (hand-written, uses variables for filtering) ─

# CORE
install-core:     $(addprefix install-,$(ACTIVE_CORE))
format-core:      $(addprefix format-,$(ACTIVE_CORE))
lint-core:        $(addprefix lint-,$(ACTIVE_CORE))
typecheck-core:   $(addprefix typecheck-,$(ACTIVE_CORE))
check-core:       $(addprefix check-,$(ACTIVE_CORE))
build-core:       $(addprefix build-,$(ACTIVE_CORE))
test-core:        $(addprefix test-,$(ACTIVE_CORE))
clean-core:       $(addprefix clean-,$(ACTIVE_CORE))

# INTEGRATIONS
install-integrations:     $(addprefix install-,$(ACTIVE_INTEGRATIONS))
format-integrations:      $(addprefix format-,$(ACTIVE_INTEGRATIONS))
lint-integrations:        $(addprefix lint-,$(ACTIVE_INTEGRATIONS))
typecheck-integrations:   $(addprefix typecheck-,$(ACTIVE_INTEGRATIONS))
check-integrations:       $(addprefix check-,$(ACTIVE_INTEGRATIONS))
build-integrations:       $(addprefix build-,$(ACTIVE_INTEGRATIONS))
test-integrations:        $(addprefix test-,$(ACTIVE_INTEGRATIONS))
clean-integrations:       $(addprefix clean-,$(ACTIVE_INTEGRATIONS))

# INFRA (opt-in)
install-infra:
	@echo "Infra packages (server, openmemory) use Docker — no install step."
	@echo "Use 'make build-server' or 'make build-openmemory' directly."

build-infra:   $(addprefix build-,$(ACTIVE_INFRA))
clean-infra:
	@echo "Infra packages use docker compose down -v — run from their own directories."

# ── ALL (core + integrations; infra always opt-in) ───────────────────────
install-all:     install-core install-integrations
format-all:      format-core format-integrations
lint-all:        lint-core lint-integrations
typecheck-all:   typecheck-core typecheck-integrations
check-all:       check-core check-integrations
build-all:       build-core build-integrations
test-all:        test-core test-integrations
clean-all:       clean-core clean-integrations clean-opencode-plugin

# ── Legacy aliases ───────────────────────────────────────────────────────
# Keep default targets pointing at python-sdk for backward compatibility
# with contributors who only touch the core Python SDK.
.PHONY: all help install format sort lint docs build publish clean test \
        install-core format-core lint-core typecheck-core check-core build-core test-core clean-core \
        install-integrations format-integrations lint-integrations typecheck-integrations check-integrations build-integrations test-integrations clean-integrations \
        install-infra build-infra clean-infra \
        install-all format-all lint-all typecheck-all check-all build-all test-all clean-all \
        release-check-core release-check-integrations release-check-all release-check \
        contract-check

ISORT_OPTIONS = --profile black
PROJECT_NAME  := mem0ai

all: format lint

# ── Default target ────────────────────────────────────────────────────────

help:
	@echo "Mem0 monorepo — manifest-driven task entry points"
	@echo ""
	@echo "Single source of truth: $(MANIFEST)"
	@echo ""
	@echo "Package groups (from manifest):"
	@echo "  core           $(CORE_PACKAGES)"
	@echo "  integrations   $(INTEGRATION_PACKAGES)"
	@echo "                   (+ opencode-plugin if INCLUDE_OPENCODE=1)"
	@echo "  infra          $(INFRA_PACKAGES)  (Docker — opt-in only)"
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
	@echo "Release preflight (layered):"
	@echo "  make release-check-core        Core only — must pass before cutting any release"
	@echo "  make release-check-integrations  Integration plugins only"
	@echo "  make release-check             Core + integrations (DEFAULT local preflight)"
	@echo "  make release-check-all         Core + integrations + infra (CI full gate)"
	@echo ""
	@echo "Contract / cross-cutting:"
	@echo "  make contract-check            Verify CLI payload contract files are in sync"

# ── Additional python-sdk only targets (not in manifest, backward compat) ─
sort:
	hatch run isort mem0/

install_all:
	pip install ruff==0.6.9 groq together boto3 litellm ollama chromadb weaviate weaviate-client sentence_transformers vertexai \
	            google-generativeai elasticsearch opensearch-py vecs "pinecone<7.0.0" pinecone-text faiss-cpu langchain-community \
							upstash-vector azure-search-documents langchain-memgraph langchain-neo4j langchain-aws rank-bm25 pymochow pymongo psycopg kuzu databricks-sdk valkey

publish:
	hatch publish

# ── Contract / release gates (layered) ───────────────────────────────────

# Cross-cutting contract check — Python + Node CLI payload consistency
contract-check:
	@echo "Checking CLI payload contract consistency..."
	@$(CI_HELPER) validate-contract

# Layer 1 — core packages + cross-cutting contract
release-check-core: check-core build-core contract-check
	@echo ""
	@echo "══════════════════════════════════════════════════════════════"
	@echo "  Core release preflight passed ✓"
	@echo "  Packages: $(ACTIVE_CORE)"
	@echo "══════════════════════════════════════════════════════════════"

# Layer 2 — integration plugins only
release-check-integrations: check-integrations build-integrations
	@echo ""
	@echo "══════════════════════════════════════════════════════════════"
	@echo "  Integrations release preflight passed ✓"
	@echo "  Packages: $(ACTIVE_INTEGRATIONS)"
	@echo "══════════════════════════════════════════════════════════════"

# Default local release check — core + integrations (no infra)
release-check: release-check-core release-check-integrations
	@echo ""
	@echo "All release checks passed ✓"

# Full CI gate — everything including infra Docker builds
release-check-all:
	@$(MAKE) --no-print-directory release-check-core SKIP_PKGS="$(SKIP_PKGS)" SKIP_INFRA=0
	@$(MAKE) --no-print-directory release-check-integrations SKIP_PKGS="$(SKIP_PKGS)" SKIP_INFRA=0
	@$(MAKE) --no-print-directory build-infra SKIP_PKGS="$(SKIP_PKGS)" SKIP_INFRA=0
	@echo ""
	@echo "Full release preflight passed ✓"

# ── Docs ─────────────────────────────────────────────────────────────────
docs:
	cd docs && mintlify dev
