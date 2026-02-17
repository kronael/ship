.PHONY: build test smoke clean run right image install

build:
	uv sync

install:
	uv tool install --editable .

run:
	uv run python -m ship

test:
	uv run pytest -v

smoke:
	uv run pytest -v

right:
	uv run pyright ship/

image:
	docker build -t ship .

clean:
	rm -rf __pycache__ ship/__pycache__
	rm -rf .pytest_cache
	rm -rf .ship/
