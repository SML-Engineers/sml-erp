COMPOSE = docker compose -f deploy/docker-compose.dev.yml --env-file .env

.PHONY: help env up down restart logs ps migrate makemigrations superuser shell test test-backend \
        test-frontend lint

help:  ## Show the available commands
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-16s %s\n", $$1, $$2}'

env:
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")

up: env  ## Build and start everything; open http://localhost:8080
	$(COMPOSE) up -d --build

down:  ## Stop everything (data is kept)
	$(COMPOSE) down

restart: down up  ## Stop and start again

logs:  ## Follow the logs of all services
	$(COMPOSE) logs -f --tail=100

ps:  ## List running services
	$(COMPOSE) ps

migrate: env  ## Apply database migrations
	$(COMPOSE) run --rm backend python manage.py migrate

makemigrations: env  ## Create migrations after changing models
	$(COMPOSE) run --rm backend python manage.py makemigrations

superuser: env  ## Create the first administrator account (asks for email and password)
	$(COMPOSE) run --rm backend python manage.py createsuperuser

shell: env  ## Open a Django shell
	$(COMPOSE) run --rm backend python manage.py shell

test: test-backend test-frontend  ## Run all tests

test-backend: env  ## Run backend tests
	$(COMPOSE) run --rm backend pytest

test-frontend: env  ## Run frontend tests and type check
	$(COMPOSE) run --rm --no-deps frontend sh -c "npm run typecheck && npm test"

lint: env  ## Check backend code style
	$(COMPOSE) run --rm --no-deps backend ruff check .
