# NadiSaathi task runner. Cloud targets wrap scripts/deploy/*.sh (see docs/DEPLOY.md).
SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: help smoke deploy destroy status logs setup test test-backend test-frontend eval eval-quick bench bench-cloud check-numbers count-tests docs dev traces mcp ops-report

help: ## List targets
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

# ---------------------------------------------------------------- cloud (AWS)
deploy: ## Build PWA, bundle, create/update the AWS stack, roll out, verify
	scripts/deploy/deploy.sh

destroy: ## Empty the bucket and delete the AWS stack (asks first; YES=1 skips)
	scripts/deploy/destroy.sh $(if $(YES),-y,)

status: ## Stack outputs, instance, alarms and endpoint latency
	scripts/deploy/status.sh

logs: ## Recent app logs from CloudWatch (SINCE=2h, FOLLOW=1)
	scripts/deploy/logs.sh

# ------------------------------------------------------------- local work
setup: ## Install backend (uv) and frontend (npm) dependencies
	cd backend && uv sync
	cd frontend && npm ci --legacy-peer-deps

test: test-backend test-frontend ## All tests + lint + build

test-backend: ## Backend pytest (original + agent + eval code)
	cd backend && uv run python -m pytest -q

test-frontend: ## Frontend vitest, ESLint and production build
	cd frontend && npm test && npm run lint && npm run build

eval: ## Every evaluation -> eval/results/*.json, then regenerate the docs
	cd backend && uv run python ../eval/run_stage.py
	cd backend && uv run python ../eval/run_real_physical.py
	cd backend && uv run python ../eval/run_real.py
	cd backend && uv run python ../eval/run_leadtime.py
	cd backend && uv run python ../eval/run_agent_suite.py
	cd backend && uv run python ../eval/run_real_replay.py
	cd backend && uv run python ../eval/run_guard_eval.py
	python3 scripts/soak_report.py || true
	$(MAKE) docs

eval-quick: ## The fast evaluations only (real cameras, real replay, guard, agent suite), then docs
	cd backend && uv run python ../eval/run_real_physical.py
	cd backend && uv run python ../eval/run_real_replay.py
	cd backend && uv run python ../eval/run_guard_eval.py
	cd backend && uv run python ../eval/run_agent_suite.py
	$(MAKE) docs

bench: ## Benchmark on this machine -> bench/results/local.json
	cd backend && uv run python ../bench/cool_bench.py --label local --out ../bench/results/local.json

bench-cloud: ## Benchmark configs on temporary EC2 instances (CFG=A|B|C, default B and C)
	@for c in $(or $(CFG),B C); do scripts/bench/cloud_bench.sh $$c; done
	$(MAKE) docs

docs: ## Regenerate README, report (and its PDF), Devpost text, video script and COOL page from the JSON
	python3 scripts/make_headline.py
	python3 scripts/report_pdf.py

count-tests: ## Run both test suites and record their counts -> eval/results/tests.json, then the docs
	python3 scripts/count_tests.py
	$(MAKE) docs

check-numbers: ## Fail if any document disagrees with eval/bench JSON
	python3 scripts/make_headline.py --check

traces: ## Export the demo traces to docs/traces/ (runs the three scenario replays)
	cd backend && uv run python ../scripts/export_traces.py

smoke: ## Every original and new API route against URL (default: the deployed stack); PIN=... adds protected writes
	python3 scripts/smoke_routes.py $(or $(URL),$$(aws cloudformation describe-stacks --stack-name nadisaathi --query "Stacks[0].Outputs[?OutputKey=='PublicUrl'].OutputValue" --output text)) $(if $(PIN),--pin $(PIN),)

dev: ## API on :8000 and PWA on :5173
	scripts/dev.sh

mcp: ## NadiSaathi tools over MCP (stdio), pointed at the AWS deployment; NADISAATHI_API overrides
	cd backend && uv run python -m jalrekha.mcp_server

ops-report: ## Production numbers from CloudWatch Logs Insights -> eval/results/cloud_ops.json
	cd backend && uv run python ../scripts/cloud_ops_report.py --days 7
