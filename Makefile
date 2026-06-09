# Simplified Makefile for GeoDjango
# No complex abstractions, just clear commands

.PHONY: help build up down restart logs shell pg-shell migrate collectstatic clean test

# Default target
.DEFAULT_GOAL := help

# Docker Compose command
DC := docker compose

help:  ## Show this help message
	@echo "GeoDjango Simple Template - Available Commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

build:  ## Build all Docker images
	$(DC) build

up:  ## Start all services
	$(DC) up -d
	@echo "✅ Services started!"
	@echo "   Django:  http://localhost:8000"
	@echo "   Nginx:   http://localhost:1337"
	@echo "   PostGIS: localhost:54321"

down:  ## Stop all services
	$(DC) down

restart:  ## Restart all services
	$(DC) restart

logs:  ## Show logs (use 'make logs SERVICE=webserver' for specific service)
	$(DC) logs -f $(SERVICE)

shell:  ## Open shell in webserver container
	$(DC) exec webserver /bin/bash

pg-shell:  ## Open PostgreSQL shell
	$(DC) exec postgis psql -U dheerajchand -d geodjango_database

migrate:  ## Run Django migrations
	$(DC) exec webserver python3 ellington_web/manage.py migrate

makemigrations:  ## Create Django migrations
	$(DC) exec webserver python3 ellington_web/manage.py makemigrations

collectstatic:  ## Collect static files
	$(DC) exec webserver python3 ellington_web/manage.py collectstatic --no-input

createsuperuser:  ## Create Django superuser
	$(DC) exec webserver python3 ellington_web/manage.py createsuperuser

test:  ## Run Django tests
	$(DC) exec webserver python3 ellington_web/manage.py test

clean:  ## Remove containers and volumes
	$(DC) down -v
	@echo "✅ Cleaned up containers and volumes"

rebuild:  ## Rebuild images without cache
	$(DC) build --no-cache

status:  ## Show container status
	$(DC) ps

# Data loading commands
load-spatial:  ## Load standard spatial data (GADM, timezones)
	$(DC) exec webserver python3 ellington_web/manage.py fetch_and_load_standard_spatial_data

load-census:  ## Load US Census TIGER data
	$(DC) exec webserver python3 ellington_web/manage.py fetch_and_load_census_tiger_data

create-places:  ## Create sample places
	$(DC) exec webserver python3 ellington_web/manage.py create_sample_places

create-addresses:  ## Create sample addresses
	$(DC) exec webserver python3 ellington_web/manage.py create_sample_addresses

