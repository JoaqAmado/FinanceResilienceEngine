# Shortcuts around docker compose. `make all` rebuilds everything from the raw CSVs.
.PHONY: build pipeline test findings notebook engine app all clean

build:
	docker compose build

pipeline:
	docker compose run --rm pipeline

test:
	docker compose run --rm test

findings:
	docker compose run --rm findings

notebook:
	docker compose up notebook

engine:            # make engine ID=20111 SHOCK=furnace_1_month
	docker compose run --rm engine $(or $(ID),20111) --shock $(or $(SHOCK),job_loss_ei55)

app:               # web app on http://localhost:8000
	docker compose up app

all: build pipeline test findings

clean:
	rm -f warehouse/tangerine.duckdb warehouse/tangerine.duckdb.wal
