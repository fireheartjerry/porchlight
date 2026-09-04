"""The two deployment projects have to agree, and only a test keeps them agreeing.

Porchlight deploys in two halves that are configured in different languages and deployed by
different tools:

* ``agentcore/agentcore.json`` — a static JSON file the AgentCore CLI turns into the Runtime
  and Memory resources. Its ``envVars`` are baked in at deploy time.
* ``infra/lib/porchlight-stack.ts`` — the CDK app for everything else. It computes the same
  names at synth time from the stack's account and region.

Nothing at runtime checks that the table the Lambda writes to is the table the agent reads
from, or that the bucket in the agent's environment is the bucket CDK created. A mismatch is
silent until a live invocation fails on a missing table. These tests read both files and
assert the overlap by hand.

They parse text rather than execute anything: no AWS, no ``cdk synth``, no node.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from porchlight.config import Settings

REPO = Path(__file__).resolve().parent.parent

AGENTCORE_JSON = REPO / "agentcore" / "agentcore.json"
AWS_TARGETS_JSON = REPO / "agentcore" / "aws-targets.json"
RUNTIME_IAM_POLICY = REPO / "runtime" / "iam-policy.json"
STACK_TS = REPO / "infra" / "lib" / "porchlight-stack.ts"
APP_TS = REPO / "infra" / "bin" / "porchlight.ts"

pytestmark = pytest.mark.skipif(
    not AGENTCORE_JSON.exists() or not STACK_TS.exists(),
    reason="deployment projects are not present in this checkout",
)


# --------------------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------------------


def _json(path: Path) -> Any:
    """Parse a JSON file from the repo."""
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def project() -> dict[str, Any]:
    """The parsed ``agentcore.json`` project."""
    return _json(AGENTCORE_JSON)


@pytest.fixture(scope="module")
def runtime(project: dict[str, Any]) -> dict[str, Any]:
    """The single ``Porchlight`` runtime definition."""
    runtimes = project["runtimes"]
    assert len(runtimes) == 1, "one runtime — the tests below assume it"
    return runtimes[0]


@pytest.fixture(scope="module")
def env_vars(runtime: dict[str, Any]) -> dict[str, str]:
    """The runtime's ``envVars`` as a plain mapping."""
    return {var["name"]: var["value"] for var in runtime["envVars"]}


@pytest.fixture(scope="module")
def target() -> dict[str, Any]:
    """The ``default`` deployment target from ``aws-targets.json``."""
    targets = {entry["name"]: entry for entry in _json(AWS_TARGETS_JSON)}
    return targets["default"]


@pytest.fixture(scope="module")
def stack_source() -> str:
    """The CDK stack's TypeScript source."""
    return STACK_TS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def app_source() -> str:
    """The CDK app entry point's TypeScript source."""
    return APP_TS.read_text(encoding="utf-8")


def _context_default(source: str, key: str) -> str:
    """The fallback in ``this.contextString('<key>', '<default>')``."""
    match = re.search(rf"contextString\(\s*'{key}'\s*,\s*'([^']+)'\s*\)", source)
    assert match, f"no contextString default for {key!r} in the stack"
    return match.group(1)


# --------------------------------------------------------------------------------------
# The names both halves have to agree on
# --------------------------------------------------------------------------------------


def test_the_agent_and_the_api_use_the_same_dynamodb_table(
    env_vars: dict[str, str], stack_source: str
) -> None:
    """One single table, named the same in the runtime's environment and in the stack."""
    assert env_vars["PORCHLIGHT_DYNAMO_TABLE"] == _context_default(stack_source, "tableName")


def test_the_agents_session_bucket_is_the_one_the_stack_creates(
    env_vars: dict[str, str], target: dict[str, Any], stack_source: str
) -> None:
    """``agentcore.json`` cannot interpolate, so its literal must match the CDK template."""
    assert "bucketName: `porchlight-sessions-${this.account}-${this.region}`" in stack_source
    expected = f"porchlight-sessions-{target['account']}-{target['region']}"
    assert env_vars["PORCHLIGHT_SESSION_BUCKET"] == expected, (
        "agentcore.json's PORCHLIGHT_SESSION_BUCKET is a literal; it has to be re-typed "
        "whenever aws-targets.json changes account or region"
    )


def test_both_halves_deploy_to_the_same_region(
    env_vars: dict[str, str], target: dict[str, Any], app_source: str
) -> None:
    """The runtime's region, the CLI target, and the CDK app's fallback are one region."""
    assert env_vars["PORCHLIGHT_AWS_REGION"] == target["region"]
    assert f"FALLBACK_REGION = '{target['region']}'" in app_source
    assert f"FALLBACK_ACCOUNT = '{target['account']}'" in app_source


def test_the_iam_policy_grants_the_table_the_runtime_actually_uses(env_vars: dict[str, str]) -> None:
    """``runtime/iam-policy.json`` is hand-written, so it drifts from the table name silently."""
    table = env_vars["PORCHLIGHT_DYNAMO_TABLE"]
    statements = _json(RUNTIME_IAM_POLICY)["Statement"]
    resources = [arn for statement in statements for arn in _as_list(statement["Resource"])]
    assert f"arn:aws:dynamodb:*:*:table/{table}" in resources
    assert f"arn:aws:dynamodb:*:*:table/{table}/index/*" in resources


def _as_list(value: Any) -> list[str]:
    """A policy ``Resource`` is either a string or a list of them."""
    return [value] if isinstance(value, str) else list(value)


# --------------------------------------------------------------------------------------
# Every configured variable has to be one Settings actually reads
# --------------------------------------------------------------------------------------


def _settings_env_names() -> set[str]:
    """Every environment variable name :class:`Settings` accepts."""
    names: set[str] = set()
    for name, field in Settings.model_fields.items():
        names.add(f"PORCHLIGHT_{name.upper()}")
        alias = field.validation_alias
        for choice in getattr(alias, "choices", []) or ([alias] if isinstance(alias, str) else []):
            if isinstance(choice, str):
                names.add(choice)
    return names


def test_every_porchlight_variable_on_the_runtime_is_one_settings_reads(
    env_vars: dict[str, str],
) -> None:
    """A typo'd env var is accepted by AgentCore and then silently ignored by pydantic."""
    known = _settings_env_names()
    configured = {name for name in env_vars if name.startswith("PORCHLIGHT_")}
    assert configured <= known, f"not read by Settings: {sorted(configured - known)}"


def test_every_porchlight_variable_in_the_stack_is_one_settings_reads(stack_source: str) -> None:
    """Same check for the Lambda environment, which the stack builds in TypeScript."""
    known = _settings_env_names()
    configured = set(re.findall(r"\bPORCHLIGHT_[A-Z0-9_]+\b", stack_source))
    assert configured <= known, f"not read by Settings: {sorted(configured - known)}"


def test_the_memory_id_alias_matches_the_memory_resource_name(project: dict[str, Any]) -> None:
    """The CLI's CDK injects ``MEMORY_<NAME upper-cased>_ID``; Settings has to accept it."""
    memories = project["memories"]
    assert len(memories) == 1
    injected = f"MEMORY_{memories[0]['name'].upper()}_ID"
    alias = Settings.model_fields["memory_id"].validation_alias
    assert injected in getattr(alias, "choices", [])


# --------------------------------------------------------------------------------------
# The runtime bundle
# --------------------------------------------------------------------------------------


def test_the_runtime_entrypoint_exists_where_agentcore_looks_for_it(runtime: dict[str, Any]) -> None:
    """``codeLocation`` + ``entrypoint`` is what gets zipped and started."""
    code_location = REPO / runtime["codeLocation"]
    assert (code_location / runtime["entrypoint"]).is_file()
    assert (code_location / "pyproject.toml").is_file()


def test_the_additional_iam_policy_is_resolved_relative_to_the_code_location(
    runtime: dict[str, Any],
) -> None:
    """``additionalPolicies`` paths are relative to ``codeLocation``, not the project root."""
    code_location = REPO / runtime["codeLocation"]
    for policy in runtime["additionalPolicies"]:
        assert (code_location / policy).is_file(), f"missing policy file {policy!r}"


def test_the_runtime_only_depends_on_packages_the_repo_already_pins() -> None:
    """The CodeZip manifest is a subset of the app's dependencies, plus the ADOT distro."""
    root = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    runtime_toml = (REPO / "runtime" / "pyproject.toml").read_text(encoding="utf-8")

    def requirements(text: str) -> set[str]:
        block = re.search(r"\ndependencies = \[(.*?)\]", text, re.S)
        assert block
        return {re.split(r"[><=!\[]", line)[0].strip() for line in re.findall(r'"([^"]+)"', block.group(1))}

    extra = requirements(runtime_toml) - requirements(root)
    assert extra == {"aws-opentelemetry-distro"}, f"unexpected runtime-only dependency: {extra}"


def test_the_runtime_does_not_ship_the_api_server(runtime: dict[str, Any]) -> None:
    """FastAPI/uvicorn/Mangum belong to the API Lambda; shipping them bloats the CodeZip."""
    runtime_toml = (REPO / "runtime" / "pyproject.toml").read_text(encoding="utf-8")
    for package in ("fastapi", "uvicorn", "mangum", "sse-starlette"):
        assert f'"{package}' not in runtime_toml


def test_otel_is_enabled_so_the_cdk_wraps_the_entrypoint(runtime: dict[str, Any]) -> None:
    """``enableOtel`` is what makes the entry point ``opentelemetry-instrument main.py``."""
    assert runtime["instrumentation"]["enableOtel"] is True
    assert "aws-opentelemetry-distro" in (REPO / "runtime" / "pyproject.toml").read_text()


# --------------------------------------------------------------------------------------
# The wiring the deployed halves depend on
# --------------------------------------------------------------------------------------


def test_the_deployed_halves_both_read_the_trace_from_the_store(
    env_vars: dict[str, str], stack_source: str
) -> None:
    """Split across two processes, ``/api/events`` only works when both say ``store``."""
    assert env_vars["PORCHLIGHT_EVENTS_SOURCE"] == "store"
    assert "PORCHLIGHT_EVENTS_SOURCE: 'store'" in stack_source


def test_the_deployed_halves_both_run_live_against_dynamodb(
    env_vars: dict[str, str], stack_source: str
) -> None:
    """Demo mode or the sqlite store on either half would split the two into separate worlds."""
    assert env_vars["PORCHLIGHT_MODE"] == "live"
    assert env_vars["PORCHLIGHT_STORE"] == "dynamo"
    assert "PORCHLIGHT_MODE: 'live'" in stack_source
    assert "PORCHLIGHT_STORE: 'dynamo'" in stack_source


def test_the_stack_hands_the_api_the_runtime_arn_and_memory_id(stack_source: str) -> None:
    """The ARN handoff: `make deploy-runtime` writes it, `make deploy-infra` passes it here."""
    assert "PORCHLIGHT_AGENT_RUNTIME_ARN: runtimeArn" in stack_source
    assert "PORCHLIGHT_MEMORY_ID: memoryId" in stack_source


def test_the_stack_asks_for_no_bedrock_action_that_does_not_exist(stack_source: str) -> None:
    """Converse/ConverseStream authorise against InvokeModel — `bedrock:Converse` is not real."""
    actions = set(re.findall(r"'(bedrock:[A-Za-z]+)'", stack_source))
    assert not actions & {"bedrock:Converse", "bedrock:ConverseStream"}
    assert "bedrock:InvokeModel" in actions
    assert "bedrock:InvokeModelWithResponseStream" in actions


def test_the_model_ids_match_the_ones_the_app_defaults_to(env_vars: dict[str, str]) -> None:
    """Deploying a different model than the one the demo was tuned on is a silent regression."""
    defaults = Settings(mode="demo")
    assert env_vars["PORCHLIGHT_MODEL_SONNET"] == defaults.model_sonnet
    assert env_vars["PORCHLIGHT_MODEL_HAIKU"] == defaults.model_haiku
