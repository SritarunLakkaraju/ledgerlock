.PHONY: demo install install-ui generate test test-ui api ui clean

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
SEED ?= 42

install:
	python3 -m venv $(VENV)
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e ".[dev]"

install-ui:
	cd ui && npm install

generate:
	$(PY) -m generator.generate --config config.yaml --out runs/demo --seed $(SEED)

test:
	$(PY) -m pytest tests/ -q

api:
	$(PY) -m uvicorn api.app:app --port 8000 --host 127.0.0.1

ui:
	cd ui && npm run dev -- --port 5173

# generate -> reconcile -> serve: prints the honest headline numbers to the
# terminal, then brings up the API + UI dev servers for interactive use.
# Ctrl+C stops both.
demo:
	@test -x $(PY) || $(MAKE) install
	@test -d ui/node_modules || $(MAKE) install-ui
	@$(PY) scripts/run_demo_metrics.py $(SEED)
	@trap 'kill %1 2>/dev/null' EXIT; \
	$(PY) -m uvicorn api.app:app --port 8000 --host 127.0.0.1 & \
	sleep 1; \
	cd ui && npm run dev -- --port 5173

clean:
	rm -rf runs/* $(VENV) ui/node_modules ui/dist .pytest_cache
