.PHONY: install lint format test run notebook

install:
	pip install -e ".[dev,analysis]"
	pre-commit install

lint:
	ruff check src tests

format:
	ruff format src tests
	ruff check --fix src tests

test:
	pytest

run:
	python -m data_platform

notebook:
	jupyter lab
