# Agent Hub Backend

.PHONY: install dev test test-relay lint format migrate

PYTHON ?= python3

install:
	$(PYTHON) -m pip install -e ../packages/agent-hub-pipeline && $(PYTHON) -m pip install -r requirements.txt

dev:
	$(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	$(PYTHON) -m pytest tests/ -v

test-relay:
	AGENTHUB_TEST_MINIMAL_LIFESPAN=1 $(PYTHON) -m pytest tests/integration/test_relay_gateway.py -v --tb=short

test-unit:
	$(PYTHON) -m pytest tests/unit/ -v

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff check . --fix && $(PYTHON) -m ruff format .

migrate:
	$(PYTHON) -m alembic upgrade head
