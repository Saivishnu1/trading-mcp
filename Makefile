.PHONY: install test test-cov lint fmt typecheck check migrate run clean

install:    ## Install dependencies
	uv sync

test:       ## Run the test suite
	uv run pytest -q

test-cov:   ## Run tests with coverage report
	uv run pytest --cov --cov-report=term-missing --cov-report=html

lint:       ## Check lint rules (ruff)
	uv run ruff check src tests

fmt:        ## Auto-fix lint violations
	uv run ruff check --fix src tests

typecheck:  ## Static type check (mypy)
	uv run mypy src

check: lint typecheck test   ## Everything CI runs

migrate:    ## Apply pending Alembic migrations
	uv run alembic upgrade head

run:        ## Run the MCP server locally
	uv run zerodha-mcp

clean:      ## Remove test/coverage artifacts
	rm -rf htmlcov .coverage .pytest_cache
