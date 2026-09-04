# Porchlight — local development entry points.
# Everything runs without AWS credentials when PORCHLIGHT_MODEL_PROVIDER=mock.

PY := .venv/bin/python
VENV := . .venv/bin/activate;

.DEFAULT_GOAL := help
.PHONY: help install test lint fmt seed api demo demo-mock clean

help: ## Show the available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install the package and dev dependencies into .venv
	$(VENV) uv pip install -e ".[dev]"

test: ## Run the test suite
	$(VENV) pytest -q

lint: ## Lint with ruff
	$(VENV) ruff check .

fmt: ## Autofix and format with ruff
	$(VENV) ruff check --fix . && ruff format .

seed: ## Load the Maple Street fixtures into the local store
	$(VENV) python scripts/seed.py

api: ## Run the FastAPI app on http://localhost:8000
	$(VENV) uvicorn api.main:app --reload --port 8000

demo: ## Run a day of requests end-to-end (uses the configured model provider)
	$(VENV) python scripts/run_day.py

demo-mock: ## Run six requests end-to-end with the mock model (no AWS needed)
	$(VENV) PORCHLIGHT_MODEL_PROVIDER=mock python scripts/run_day.py --count 6

clean: ## Remove local databases, sessions, and caches
	rm -rf data/local data/sessions .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
