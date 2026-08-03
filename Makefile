# Automated BI Pipeline with AI Enrichment — developer commands.
# Works on macOS/Linux/Git-Bash. Python deps are installed via venv (local)
# or inside Docker (recommended).

PYTHON ?= python
VENV   ?= .venv
PIP    := $(VENV)/bin/pip

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Local dev environment ──────────────────────────────────────
.PHONY: venv
venv: ## Create a local virtualenv
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

.PHONY: dev-install
dev-install: ## Install dev dependencies into existing venv
	$(PIP) install -e ".[dev]"

# ── Quality gates ──────────────────────────────────────────────
.PHONY: lint
lint: ## Run ruff
	$(VENV)/bin/ruff check pipeline tests

.PHONY: format
format: ## Auto-format with ruff
	$(VENV)/bin/ruff format pipeline tests
	$(VENV)/bin/ruff check --fix pipeline tests

.PHONY: typecheck
typecheck: ## Run mypy
	$(VENV)/bin/mypy pipeline

.PHONY: test
test: ## Run unit tests
	$(VENV)/bin/pytest

.PHONY: check
check: lint typecheck test ## Run all automated checks

# ── Docker stack ───────────────────────────────────────────────
.PHONY: up
up: ## Build & start the full Docker stack (Airflow + Postgres + Streamlit)
	docker compose up -d --build

.PHONY: down
down: ## Stop the Docker stack (keep volumes)
	docker compose down

.PHONY: clean
clean: ## Stop stack AND remove volumes (deletes all data)
	docker compose down -v

.PHONY: logs
logs: ## Tail stack logs
	docker compose logs -f --tail=100

.PHONY: ps
ps: ## Show running containers
	docker compose ps

# ── DAG helpers ────────────────────────────────────────────────
.PHONY: dags-list
dags-list: ## List Airflow DAGs
	docker compose exec airflow airflow dags list

.PHONY: dags-test
dags-test: ## Run the bi_pipeline DAG end-to-end (one logical run)
	docker compose exec airflow airflow dags test bi_pipeline

.PHONY: trigger
trigger: ## Trigger a DAG run now
	docker compose exec airflow airflow dags trigger bi_pipeline
