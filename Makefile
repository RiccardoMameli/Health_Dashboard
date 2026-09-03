.PHONY: install dev migrate revision test lint seed backfill

install:
	pip install -e ".[dev]"

dev:
	uvicorn app.main:app --reload --port 8000

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(m)"

test:
	pytest -q

lint:
	ruff check app tests && ruff format --check app tests

seed:
	python -m app.seed.run

backfill:
	python scripts/backfill.py --source all
