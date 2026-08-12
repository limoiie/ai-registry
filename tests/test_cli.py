from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from ai_registry.cli import _build_app

runner = CliRunner()

REGISTRY_YAML = """
accounts:
  - id: deepseek-primary
    provider_id: deepseek
    credential: {env: DEEPSEEK_API_KEY}
    enabled_models: [deepseek-chat, deepseek-reasoner]
aliases:
  - id: chat-default
    deployments:
      - account_id: deepseek-primary
        model_id: deepseek-chat
      - account_id: deepseek-primary
        model_id: deepseek-reasoner
        routing: {priority: 1}
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.delenv("AI_REGISTRY_PROFILE", raising=False)
    directory = tmp_path / ".ai-registry"
    directory.mkdir()
    (directory / "registry.yaml").write_text(REGISTRY_YAML, encoding="utf-8")
    return tmp_path


def invoke(project: Path, *args: str) -> Result:
    return runner.invoke(_build_app(), [*args, "--root", str(project)])


def test_validate_reports_the_loaded_object_counts(project: Path) -> None:
    result = invoke(project, "validate")

    assert result.exit_code == 0
    assert "1 accounts" in result.stdout
    assert "1 aliases" in result.stdout


def test_validate_reports_configuration_errors(tmp_path: Path) -> None:
    result = invoke(tmp_path, "validate")

    assert result.exit_code == 2
    assert "Missing project registry file" in result.stderr


def test_aliases_lists_deployments_in_routing_order(project: Path) -> None:
    result = invoke(project, "aliases")

    assert result.exit_code == 0
    assert "chat-default" in result.stdout
    assert "deepseek-primary/deepseek-chat" in result.stdout


def test_resolve_prints_the_selected_deployment(project: Path) -> None:
    result = invoke(project, "resolve", "chat-default", "--json")

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["account_id"] == "deepseek-primary"
    assert payload["model_id"] == "deepseek-chat"
    assert payload["endpoint"] == "https://api.deepseek.com/anthropic"


def test_resolve_never_prints_a_credential(project: Path) -> None:
    result = invoke(project, "resolve", "chat-default", "--json")

    assert "sk-test" not in result.stdout
    assert "DEEPSEEK_API_KEY" not in result.stdout
    assert json.loads(result.stdout)["credential"] == "env (ok)"


def test_resolve_reports_an_unresolvable_credential(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY")

    result = invoke(project, "resolve", "chat-default", "--json")

    assert json.loads(result.stdout)["credential"] == "env (unresolved)"


def test_resolve_reports_unknown_references(project: Path) -> None:
    result = invoke(project, "resolve", "nope")

    assert result.exit_code == 1
    assert "unknown alias" in result.stderr


def test_explain_orders_every_candidate(project: Path) -> None:
    result = invoke(project, "explain", "chat-default")

    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines[0].startswith("1. deepseek-primary/deepseek-chat")
    assert lines[1].startswith("2. deepseek-primary/deepseek-reasoner")


def test_models_filters_by_capability_and_context(project: Path) -> None:
    result = invoke(
        project, "models", "--type", "chat", "--tools", "--min-context", "500000"
    )

    assert result.exit_code == 0
    assert "deepseek-v4-flash" in result.stdout
    assert "deepseek-chat\t" not in result.stdout


def test_models_enabled_flag_limits_output_to_configured_models(
    project: Path,
) -> None:
    result = invoke(project, "models", "--enabled", "--json")

    assert result.exit_code == 0
    assert {row["model"] for row in json.loads(result.stdout)} == {
        "deepseek-chat",
        "deepseek-reasoner",
    }


def test_models_rejects_an_unknown_type(project: Path) -> None:
    result = invoke(project, "models", "--type", "nonsense")

    assert result.exit_code == 2
    assert "error:" in result.stderr
