.PHONY: install lint test security check cases demo demo-all docker-up clean

install:
	pip install -e ".[dev]"

lint:
	ruff check . && ruff format --check . && python -m mypy

test:
	pytest --cov=src/gauntlet --cov-report=term-missing

security:
	bandit -r src && pip-audit

check: lint test security

# Regenerate the synthetic case set (deterministic; output is committed).
cases:
	python scripts/make_synthetic_cases.py

# Gate releases/trialbridge/candidate.yaml against the baseline, locally.
demo:
	scripts/gate_demo.sh

# Gate every example release and show each verdict.
demo-all:
	@for f in releases/trialbridge/examples/*.yaml; do \
	  echo "=== $$f"; OUT_DIR=out/$$(basename $$f .yaml) scripts/gate_demo.sh $$f >/dev/null \
	    && echo "PASS" || echo "FAIL (see out/$$(basename $$f .yaml)/gate-report.md)"; \
	done

docker-up:
	docker compose up --build --abort-on-container-exit --exit-code-from gate

clean:
	rm -rf out .coverage coverage.xml .pytest_cache .mypy_cache .ruff_cache
