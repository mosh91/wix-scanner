COMPOSE_FILE=infra/wix_scanner/docker-compose.dev.yml

.PHONY: dev-infra down-infra dev-backend dev-frontend test-backend test-frontend lint-backend lint-frontend format-backend format-frontend dev db-upgrade db-downgrade db-revision db-history db-stamp

dev-infra:
	docker compose -f $(COMPOSE_FILE) up -d --build

down-infra:
	docker compose -f $(COMPOSE_FILE) down

dev-backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev -- --host 0.0.0.0 --port 5173

test-backend:
	cd backend && pytest

test-frontend:
	cd frontend && npm run test

lint-backend:
	cd backend && ruff check .

lint-frontend:
	cd frontend && npm run lint

format-backend:
	cd backend && ruff format .

format-frontend:
	cd frontend && npm run format

# ---------------------------------------------------------------------------
# Database migrations (Alembic)
# ---------------------------------------------------------------------------
# Apply all pending migrations
db-upgrade:
	docker compose -f $(COMPOSE_FILE) exec backend alembic upgrade head

# Roll back one step
db-downgrade:
	docker compose -f $(COMPOSE_FILE) exec backend alembic downgrade -1

# Generate a new migration: make db-revision MSG="describe the change"
db-revision:
	docker compose -f $(COMPOSE_FILE) exec backend alembic revision --autogenerate -m "$(MSG)"

# Print current revision history
db-history:
	docker compose -f $(COMPOSE_FILE) exec backend alembic history --verbose

# Stamp the DB at a specific revision without running migrations (e.g. baseline)
# Usage: make db-stamp REV=0001
db-stamp:
	docker compose -f $(COMPOSE_FILE) exec backend alembic stamp $(REV)

dev: dev-infra
