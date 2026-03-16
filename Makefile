IMAGE := cc-spend:latest
PYTHON := .venv/bin/python
PYLINT := .venv/bin/pylint
FLAKE8 := .venv/bin/flake8

# Source files — exclude the test file and the thin parser.py redirect shim
SRC := $(filter-out test_cc_spend.py parser.py, $(wildcard *.py))

.PHONY: all lint flake8 test build

all: lint flake8 test build

lint:
	$(PYLINT) $(SRC) \
		--disable=disallowed-name \
		--disable=broad-exception-caught \
		--disable=trailing-newlines

flake8:
	$(FLAKE8) $(SRC)

test:
	$(PYTHON) -m pytest test_cc_spend.py -v

build:
	docker build -t $(IMAGE) .
