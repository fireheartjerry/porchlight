# `runtime/` — the AgentCore CodeZip build

This directory *is* the `codeLocation` in
[`../agentcore/agentcore.json`](../agentcore/agentcore.json). Everything in it (minus
`.git`, `.venv`, `__pycache__`, `.pytest_cache`, `.DS_Store`, `node_modules`, which the
packager always skips) ends up in the zip that Amazon Bedrock AgentCore Runtime unpacks.

| File | What it is |
|---|---|
| `main.py` | The entry point AgentCore executes (`opentelemetry-instrument main.py`). Imports `porchlight.runtime.app`. |
| `pyproject.toml` | The dependency manifest `uv` resolves for `aarch64-manylinux`, Python 3.14. |
| `iam-policy.json` | Extra permissions for the runtime's execution role, attached via `additionalPolicies`. |
| `porchlight/` | **Build artifact.** `make package-runtime` rsyncs `/porchlight` here; gitignored. |

Never edit `runtime/porchlight/` — it is overwritten (`rsync --delete`) on every package or
deploy. The source of truth is `/porchlight`.

See [`../docs/DEPLOY.md`](../docs/DEPLOY.md) § AgentCore Runtime for the deploy commands and
the environment contract with `infra/`.
