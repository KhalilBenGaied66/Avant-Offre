# Avant-Offre — every command runs in sample mode on a small VM (SPEC §4.7).
UV  ?= uv
RUN := $(UV) run
CLI := $(RUN) avant-offre

.PHONY: setup setup-full lint format test check-sources data-sample data-full quality \
        index-sample index-full eval-sample eval-full serve mcp mcp-http web web-build ci

setup:            ## install core + dev deps (no model runtime)
	$(UV) sync --extra llm

setup-full:       ## + embeddings/reranker runtime (torch, sentence-transformers)
	$(UV) sync --all-extras

lint:
	$(RUN) ruff check src tests scripts
	$(RUN) ruff format --check src tests scripts
	$(RUN) mypy

format:
	$(RUN) ruff format src tests scripts
	$(RUN) ruff check --fix src tests scripts

test:
	$(RUN) pytest

check-sources:
	$(RUN) python scripts/check_sources.py

data-sample:
	AVANT_OFFRE_MODE=sample $(CLI) data

data-full:
	AVANT_OFFRE_MODE=full $(CLI) data

quality:
	$(CLI) quality

index-sample:
	AVANT_OFFRE_MODE=sample $(CLI) index

index-full:
	AVANT_OFFRE_MODE=full $(CLI) index

eval-sample:
	AVANT_OFFRE_MODE=sample $(CLI) eval all

eval-full:
	AVANT_OFFRE_MODE=full $(CLI) eval all

serve:
	$(RUN) uvicorn avant_offre.api.app:app --host 0.0.0.0 --port 8000

mcp:
	$(CLI) mcp --transport stdio

mcp-http:
	$(CLI) mcp --transport http

web:
	cd web && npm run dev

web-build:
	cd web && npm ci && npm run build

ci: lint test
