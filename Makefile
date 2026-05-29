COMPOSE_FILE=infra/docker/docker-compose.dev.yml

.PHONY: dev-infra down-infra dev-backend dev-frontend test-backend test-frontend lint-backend lint-frontend format-backend format-frontend dev

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

dev: dev-infra
