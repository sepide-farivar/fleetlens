.PHONY: install data lint test coverage serve docker smoke client-test

install:
	pip install -e ".[dev]"

data:
	fleetlens all

lint:
	ruff check .
	ruff format --check .

test:
	pytest

coverage:
	pytest --cov --cov-report=term-missing --cov-fail-under=90

serve:
	fleetlens serve

docker:
	docker build -t fleetlens .

smoke:
	python scripts/smoke_test.py http://localhost:8000

client-test:
	cd clients/typescript && npm ci && npm test
