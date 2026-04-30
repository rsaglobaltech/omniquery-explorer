.PHONY: help db-up db-down db-logs import-local

COMPOSE_FILE := docker-compose.local-db.yml
IMPORT_SCRIPT := scripts/aws_import/import_all_local_docker.sh

help:
	@echo "Targets disponibles:"
	@echo "  make db-up         # Levanta MySQL y PostgreSQL locales"
	@echo "  make db-down       # Baja contenedores locales"
	@echo "  make db-logs       # Muestra logs de MySQL y PostgreSQL"
	@echo "  make import-local  # Importa todos los datasets MySQL + PostgreSQL"

db-up:
	docker compose -f $(COMPOSE_FILE) up -d

db-down:
	docker compose -f $(COMPOSE_FILE) down

db-logs:
	docker compose -f $(COMPOSE_FILE) logs --tail=150 mysql postgres

import-local:
	./$(IMPORT_SCRIPT)
