.PHONY: up down full incremental advance logs

up:
	docker compose build mock-api etl dashboard
	docker compose up -d db mock-api dashboard

down:
	docker compose down

full:
	docker compose run --rm etl python -m etl.cli full

incremental:
	docker compose run --rm etl python -m etl.cli incremental

advance:
	curl -X POST "http://localhost:8000/admin/advance?new_count=100&update_count=20"

logs:
	docker compose logs -f --tail=100
