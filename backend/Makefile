# Agent Hub Backend

.PHONY: install dev test lint format migrate

PYTHON ?= python3

install:
	$(PYTHON) -m pip install -r requirements.txt

dev:
	$(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	$(PYTHON) -m pytest tests/ -v

test-unit:
	$(PYTHON) -m pytest tests/unit/ -v

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff check . --fix && $(PYTHON) -m ruff format .

migrate:
	$(PYTHON) -m alembic upgrade head
