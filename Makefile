.PHONY: install lint test security check

install:
	pip install -e ".[dev]"

lint:
	ruff check . && ruff format --check . && mypy

test:
	pytest --cov=src/gauntlet --cov-report=term-missing

security:
	bandit -r src && pip-audit

check: lint test security
