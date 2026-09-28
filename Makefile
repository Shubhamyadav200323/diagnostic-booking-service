.PHONY: up down test logs shell

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f web

test:
	docker compose run --rm web pytest

shell:
	docker compose run --rm web python manage.py shell
