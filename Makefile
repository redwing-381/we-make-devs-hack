.PHONY: help install db db-down api ui test test-unit lint fmt smoke docs

help:            ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

install:         ## install backend + UI deps
	uv sync
	cd ui && npm install

db:              ## start FalkorDB (6379) + Browser (http://localhost:3000)
	docker compose up -d falkordb

db-down:         ## stop FalkorDB
	docker compose down

api:             ## run the API with reload on :8000
	uv run uvicorn whygraph.api.main:app --reload --port 8000

ui:              ## run the UI dev server on :5173 (proxies /api to :8000)
	cd ui && npm run dev

test:            ## all tests (DB tests skip if FalkorDB is down)
	uv run pytest -q

test-unit:       ## tests that need no database
	uv run pytest -q -m "not db"

lint:            ## ruff + UI typecheck
	uv run ruff check .
	uv run ruff format --check .
	cd ui && npm run typecheck

fmt:             ## auto-format python
	uv run ruff check --fix .
	uv run ruff format .

smoke:           ## check every FalkorDB feature we depend on
	uv run python scripts/smoke_falkordb.py

docs:            ## regenerate docs/queries.md from the query catalog
	uv run python scripts/gen_query_docs.py
