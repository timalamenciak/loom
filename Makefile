.PHONY: dev stop build migrate migrations superuser lint fmt test clean

MANAGE = docker compose exec web python manage.py

# First-time setup:
#   cp .env.example .env        # edit SECRET_KEY + DB creds
#   make build
#   docker compose up -d
#   make migrate superuser

dev:
	docker compose up

stop:
	docker compose down

build:
	docker compose build

migrate:
	$(MANAGE) migrate

migrations:
	$(MANAGE) makemigrations

superuser:
	$(MANAGE) createsuperuser

lint:
	ruff check . && black --check .

fmt:
	ruff check --fix . && black .

test:
	pytest

clean:
	docker compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
