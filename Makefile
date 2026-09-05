# Porchlight — local development entry points.
# Everything runs without AWS credentials when PORCHLIGHT_MODEL_PROVIDER=mock.

PY := .venv/bin/python
VENV := . .venv/bin/activate;

# AgentCore Runtime (see docs/DEPLOY.md § AgentCore Runtime).
AC_TARGET ?= default
AC_RUNTIME := runtime
AC_STATE := $(PY) agentcore/deployed_state.py --target $(AC_TARGET)
# The stack name the CLI's vended CDK app derives: AgentCore-<project>-<target>.
AC_STACK := AgentCore-porchlight-$(AC_TARGET)
# Shared with the app-stack section below; ?= so either half works on its own.
ENV_DEPLOY ?= .env.deploy
RUNTIME_ARN_PARAM ?= /porchlight/runtime_arn
MEMORY_ID_PARAM ?= /porchlight/memory_id

.DEFAULT_GOAL := help
.PHONY: help install test lint fmt seed api demo demo-mock clean \
        sync-runtime package-runtime deploy-runtime runtime-local runtime-arn

help: ## Show the available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install the package and dev dependencies into .venv
	$(VENV) uv pip install -e ".[dev]"

test: ## Run the test suite
	$(VENV) pytest -q

lint: ## Lint with ruff
	$(VENV) ruff check .

fmt: ## Autofix and format with ruff
	$(VENV) ruff check --fix . && ruff format .

seed: ## Load the Maple Street fixtures into the local store
	$(VENV) python scripts/seed.py

api: ## Run the FastAPI app on http://localhost:8000
	$(VENV) uvicorn api.main:app --reload --port 8000

demo: ## Run a day of requests end-to-end (uses the configured model provider)
	$(VENV) python scripts/run_day.py

demo-mock: ## Run six requests end-to-end with the mock model (no AWS needed)
	$(VENV) PORCHLIGHT_MODEL_PROVIDER=mock python scripts/run_day.py --count 6

# --- AgentCore Runtime ----------------------------------------------------------------
# porchlight/ is not on PyPI, so the CodeZip build gets it by copy: everything under
# runtime/ goes into the zip verbatim, and runtime/porchlight/ is a gitignored mirror of
# the real package that is re-synced before every package and every deploy.

sync-runtime: ## Mirror porchlight/ into runtime/porchlight/ for the CodeZip build
	@rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' porchlight/ $(AC_RUNTIME)/porchlight/
	@echo "synced porchlight/ -> $(AC_RUNTIME)/porchlight/"

package-runtime: sync-runtime ## Build the AgentCore CodeZip artifact (no AWS credentials needed)
	agentcore package --runtime Porchlight

runtime-local: sync-runtime ## Serve the runtime locally on :8080 with the mock model
	PORCHLIGHT_MODEL_PROVIDER=mock PORCHLIGHT_STORE=sqlite $(PY) $(AC_RUNTIME)/main.py

deploy-runtime: sync-runtime ## Deploy the AgentCore Runtime + Memory (needs AWS credentials)
	@test -d agentcore/cdk/node_modules || (cd agentcore/cdk && npm ci --no-audit --no-fund)
	agentcore validate
	agentcore deploy --target $(AC_TARGET) -y
	@$(AC_STATE) --write $(ENV_DEPLOY)
	@set -e; \
	ARN="$$($(AC_STATE) --key PORCHLIGHT_AGENT_RUNTIME_ARN)"; \
	aws ssm put-parameter --name $(RUNTIME_ARN_PARAM) --type String --overwrite \
	  --value "$$ARN" --description 'Porchlight AgentCore Runtime ARN' >/dev/null; \
	MEM="$$($(AC_STATE) --key PORCHLIGHT_MEMORY_ID 2>/dev/null || true)"; \
	if [ -n "$$MEM" ]; then aws ssm put-parameter --name $(MEMORY_ID_PARAM) --type String \
	  --overwrite --value "$$MEM" --description 'Porchlight AgentCore Memory id' >/dev/null; fi; \
	echo "  runtime : $$ARN"; echo "  memory  : $$MEM"
	@echo "Pass these to the app stack with: make deploy"

runtime-arn: ## Print the deployed runtime ARN and memory id (from agentcore/.cli)
	@$(AC_STATE)

clean: ## Remove local databases, sessions, and caches
	rm -rf data/local data/sessions .pytest_cache .ruff_cache
	rm -rf $(AC_RUNTIME)/porchlight agentcore/Porchlight agentcore/Porchlight.zip agentcore/.cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# ------------------------------------------------------------------------------------------
# Deploy — see docs/DEPLOY.md. Everything below needs AWS credentials.
# ------------------------------------------------------------------------------------------

# ENV_DEPLOY, RUNTIME_ARN_PARAM and MEMORY_ID_PARAM are defined at the top of this file —
# both halves of the deploy read them, and the AgentCore half writes them.
INFRA := infra
STACK := PorchlightAppStack
CDK_OUTPUTS := build/cdk-outputs.json

.PHONY: build-lambda build-web infra-install synth deploy-infra deploy smoke-bedrock destroy

build-lambda: ## Build the arm64 Lambda bundle into build/lambda (no Docker)
	bash scripts/build_lambda.sh

build-web: ## Build the React UI into web/dist
	cd web && npm ci && npm run build

infra-install: ## Install the CDK app's dependencies
	cd $(INFRA) && npm install --no-audit --no-fund

synth: infra-install ## Synthesize the app stack (works with no AWS credentials)
	cd $(INFRA) && npx cdk synth --quiet

deploy-infra: infra-install ## Deploy the app stack; writes its outputs to .env.deploy
	@set -e; \
	if [ -f $(ENV_DEPLOY) ]; then set -a; . ./$(ENV_DEPLOY); set +a; fi; \
	RUNTIME_ARN="$${PORCHLIGHT_AGENT_RUNTIME_ARN:-}"; \
	MEMORY_ID="$${PORCHLIGHT_MEMORY_ID:-}"; \
	if [ -z "$$RUNTIME_ARN" ]; then \
	  RUNTIME_ARN="$$(aws ssm get-parameter --name $(RUNTIME_ARN_PARAM) \
	    --query Parameter.Value --output text 2>/dev/null || true)"; fi; \
	if [ -z "$$MEMORY_ID" ]; then \
	  MEMORY_ID="$$(aws ssm get-parameter --name $(MEMORY_ID_PARAM) \
	    --query Parameter.Value --output text 2>/dev/null || true)"; fi; \
	if [ "$$RUNTIME_ARN" = "None" ]; then RUNTIME_ARN=""; fi; \
	if [ "$$MEMORY_ID" = "None" ]; then MEMORY_ID=""; fi; \
	if [ -z "$$RUNTIME_ARN" ]; then \
	  echo "no AgentCore runtime ARN — the API will run the graph in-process"; \
	else echo "runtime : $$RUNTIME_ARN"; fi; \
	if [ ! -f build/lambda/run.sh ]; then \
	  echo "build/lambda is missing; run 'make build-lambda' first" >&2; exit 1; fi; \
	if [ -z "$${PORCHLIGHT_FROM_ADDR:-}" ]; then \
	  echo "no PORCHLIGHT_FROM_ADDR — email will be logged, not sent (see docs/DEPLOY.md)"; fi; \
	mkdir -p build; \
	cd $(INFRA) && npx cdk deploy --require-approval never \
	  -c runtimeArn="$$RUNTIME_ARN" -c memoryId="$$MEMORY_ID" \
	  -c fromAddr="$${PORCHLIGHT_FROM_ADDR:-}" \
	  --outputs-file ../$(CDK_OUTPUTS)
	@set -e; \
	get() { $(PY) -c "import json,sys;print(json.load(open('$(CDK_OUTPUTS)'))['$(STACK)'].get(sys.argv[1],''))" "$$1"; }; \
	CF="$$(get CloudFrontUrl)"; FN="$$(get FunctionUrl)"; TB="$$(get TableName)"; \
	SB="$$(get SessionBucketName)"; DI="$$(get DistributionId)"; \
	{ \
	  if [ -f $(ENV_DEPLOY) ]; then grep -v '^PORCHLIGHT_CLOUDFRONT_URL=' $(ENV_DEPLOY) \
	    | grep -v '^PORCHLIGHT_FUNCTION_URL=' | grep -v '^PORCHLIGHT_DYNAMO_TABLE=' \
	    | grep -v '^PORCHLIGHT_SESSION_BUCKET=' | grep -v '^PORCHLIGHT_DISTRIBUTION_ID=' || true; fi; \
	  printf 'PORCHLIGHT_CLOUDFRONT_URL=%s\n' "$$CF"; \
	  printf 'PORCHLIGHT_FUNCTION_URL=%s\n' "$$FN"; \
	  printf 'PORCHLIGHT_DYNAMO_TABLE=%s\n' "$$TB"; \
	  printf 'PORCHLIGHT_SESSION_BUCKET=%s\n' "$$SB"; \
	  printf 'PORCHLIGHT_DISTRIBUTION_ID=%s\n' "$$DI"; \
	} > $(ENV_DEPLOY).tmp && mv $(ENV_DEPLOY).tmp $(ENV_DEPLOY); \
	echo; echo "  The Porch : $$CF"; echo "  API       : $$FN"; \
	echo "  outputs   : $(ENV_DEPLOY)"

deploy: ## Deploy everything: AgentCore runtime first, then the app stack
	$(MAKE) deploy-runtime
	$(MAKE) build-lambda build-web deploy-infra
	@echo; echo "Both halves are up. Check them with: make smoke-bedrock"

smoke-bedrock: ## Check Bedrock model access and run two samples through the real graph
	$(VENV) python scripts/smoke_bedrock.py

destroy: ## Tear both halves down: the app stack, then the AgentCore runtime and memory
	cd $(INFRA) && npx cdk destroy $(STACK) --force
	cd agentcore/cdk && npm run build --silent && npx cdk destroy $(AC_STACK) --force
	-@aws ssm delete-parameter --name $(RUNTIME_ARN_PARAM) >/dev/null 2>&1 || true
	-@aws ssm delete-parameter --name $(MEMORY_ID_PARAM) >/dev/null 2>&1 || true
	rm -f $(ENV_DEPLOY) $(CDK_OUTPUTS)
	@echo "torn down — the table, both buckets, and the memory went with their stacks"

# ------------------------------------------------------------------------------------------
# Demo video — see docs/VIDEO.md. Runs entirely against the local mock stack; no AWS.
# ------------------------------------------------------------------------------------------

MEDIA_API_PORT ?= 8000
MEDIA_WEB_PORT ?= 5173
# Why the quiet hours are moved: after 21:00 the group's real policy holds outreach until
# morning. That is a lovely feature and a terrible forty-second story — the narration says
# "someone says yes" over a screen that would say "held until 8am", and which of the two you
# filmed would depend on what time you pressed make. The recording group is configured awake
# so the film is the same film at any hour. Everything else is stock.
MEDIA_ENV := PORCHLIGHT_MODEL_PROVIDER=mock PORCHLIGHT_QUIET_HOURS=[3,4]
MEDIA_BASE := http://localhost:$(MEDIA_WEB_PORT)
MEDIA_API := http://localhost:$(MEDIA_API_PORT)/api

.PHONY: video

video: ## Record and cut the demo video into media/out/porchlight-demo.mp4
	@test -x /opt/homebrew/bin/ffmpeg || command -v ffmpeg >/dev/null || \
	  { echo "ffmpeg is not installed — brew install ffmpeg" >&2; exit 1; }
	@test -d web/node_modules || (cd web && npm ci --no-audit --no-fund)
	@set -e; \
	for port in $(MEDIA_API_PORT) $(MEDIA_WEB_PORT); do \
	  pids="$$(lsof -ti:$$port 2>/dev/null || true)"; \
	  if [ -n "$$pids" ]; then echo "  freeing port $$port"; kill $$pids 2>/dev/null || true; sleep 1; fi; \
	done; \
	mkdir -p media/out; \
	trap 'lsof -ti:$(MEDIA_API_PORT) -ti:$(MEDIA_WEB_PORT) 2>/dev/null | xargs kill 2>/dev/null || true' \
	  EXIT INT TERM; \
	echo "  api   :$(MEDIA_API_PORT)  (mock model, no AWS)"; \
	$(MEDIA_ENV) $(PY) -m uvicorn api.main:app --port $(MEDIA_API_PORT) \
	  > media/out/api.log 2>&1 & \
	echo "  web   :$(MEDIA_WEB_PORT)"; \
	(cd web && npm run dev -- --port $(MEDIA_WEB_PORT) > ../media/out/web.log 2>&1) & \
	for i in $$(seq 1 60); do curl -sf $(MEDIA_API)/porch >/dev/null 2>&1 && break || sleep 1; done; \
	for i in $$(seq 1 60); do curl -sf $(MEDIA_BASE)/ >/dev/null 2>&1 && break || sleep 1; done; \
	curl -sf $(MEDIA_API)/porch >/dev/null || { echo "the API never came up (media/out/api.log)" >&2; exit 1; }; \
	curl -sf $(MEDIA_BASE)/ >/dev/null || { echo "the UI never came up (media/out/web.log)" >&2; exit 1; }; \
	curl -sf -X POST $(MEDIA_API)/demo/reset >/dev/null; \
	echo; \
	$(PY) media/tts.py; \
	BASE=$(MEDIA_BASE) API=$(MEDIA_API) node media/record.mjs; \
	node media/render-cards.mjs; \
	node media/code-cards.mjs; \
	$(PY) media/assemble.py
