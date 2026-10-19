# MiniPay Makefile
# Usage: make <target>
# Requires: Docker, Python 3.12, a virtualenv activated.

COMPOSE = docker compose -f deploy/docker-compose.yml
PYTEST  = pytest --cov=src/minipay --cov-report=term-missing

.PHONY: up down restart logs test lint run-api seed help

## up       — Start postgres (and any other defined services) in the background
up:
	$(COMPOSE) up -d

## down     — Stop and remove containers
down:
	$(COMPOSE) down

## restart  — Restart all services
restart:
	$(COMPOSE) restart

## logs     — Tail logs from all running containers
logs:
	$(COMPOSE) logs -f

## test     — Run the full test suite with coverage
test:
	$(PYTEST) tests/

## lint     — Run ruff linter and formatter check
lint:
	ruff check src/ tests/ tools/
	ruff format --check src/ tests/ tools/

## format   — Auto-fix ruff issues
format:
	ruff check --fix src/ tests/ tools/
	ruff format src/ tests/ tools/

## run-api  — Start the FastAPI dev server (requires DB running)
run-api:
	uvicorn minipay.api.main:app --reload --host 0.0.0.0 --port 8000

## seed     — Seed demo merchants into the database
seed:
	python tools/seed.py

## help     — Show this help message
help:
	@grep -E '^##' Makefile | sed 's/## //'
