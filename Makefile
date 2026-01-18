.PHONY: build test smoke clean all run right image install

all: build

build:
	uv sync

install:
	uv tool install --editable .

run:
	uv run python -m demiurg

test:
	uv run pytest -v

smoke:
	uv run pytest -v

right:
	uv run pyright demiurg/
	uv run pytest -v

image:
	docker build -t demiurg .

clean:
	rm -rf __pycache__ demiurg/__pycache__
	rm -rf .pytest_cache
	rm -rf .demiurg/
