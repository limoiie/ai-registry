from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from ai_registry.catalog import builtin_models_dev_snapshot, models_dev_snapshot_json
from ai_registry.cli import _build_app

runner = CliRunner()

REGISTRY_YAML = """
accounts:
  - id: deepseek-primary
    provider_id: deepseek
    credential: {env: DEEPSEEK_API_KEY}
    enabled_models: [deepseek-v4-flash, deepseek-v4-pro]
aliases:
  - id: chat-default
    deployments:
      - account_id: deepseek-primary
        model_id: deepseek-v4-flash
      - account_id: deepseek-primary
        model_id: deepseek-v4-pro
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


def test_catalog_diff_reports_no_drift_for_the_vendored_snapshot(
    tmp_path: Path,
) -> None:
    document = builtin_models_dev_snapshot()
    upstream = tmp_path / "api.json"
    upstream.write_text(models_dev_snapshot_json(document), encoding="utf-8")

    result = runner.invoke(_build_app(), ["catalog", "diff", str(upstream)])

    assert result.exit_code == 0
    assert "no drift" in result.stdout


def test_catalog_diff_exits_nonzero_on_drift(tmp_path: Path) -> None:
    document = copy.deepcopy(builtin_models_dev_snapshot())
    document["minimax"]["models"]["MiniMax-M3"]["limit"]["context"] = 42
    upstream = tmp_path / "api.json"
    upstream.write_text(json.dumps(document), encoding="utf-8")

    result = runner.invoke(_build_app(), ["catalog", "diff", str(upstream)])

    assert result.exit_code == 1
    assert "MiniMax-M3 changed" in result.stdout
    assert "context_window_tokens" in result.stdout


def test_catalog_sync_writes_the_snapshot_and_its_readme(tmp_path: Path) -> None:
    upstream = tmp_path / "api.json"
    upstream.write_text(
        models_dev_snapshot_json(builtin_models_dev_snapshot()), encoding="utf-8"
    )
    destination = tmp_path / "out" / "api.json"

    result = runner.invoke(
        _build_app(),
        ["catalog", "sync", str(upstream), "--output", str(destination)],
    )

    assert result.exit_code == 0
    assert "wrote" in result.stdout
    snapshot = json.loads(destination.read_text(encoding="utf-8"))
    assert snapshot["minimax"]["models"]
    # Local-only cards are not vendored, so the snapshot stays a subset.
    assert "MiniMax-M2.1-highspeed" not in snapshot["minimax"]["models"]
    readme = destination.parent / "README.md"
    assert "Vendored models.dev snapshot" in readme.read_text(encoding="utf-8")


def test_aliases_lists_deployments_in_routing_order(project: Path) -> None:
    result = invoke(project, "aliases")

    assert result.exit_code == 0
    assert "chat-default" in result.stdout
    assert "deepseek-primary/deepseek-v4-flash" in result.stdout


def test_resolve_prints_the_selected_deployment(project: Path) -> None:
    result = invoke(project, "resolve", "chat-default", "--json")

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["account_id"] == "deepseek-primary"
    assert payload["model_id"] == "deepseek-v4-flash"
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
    assert lines[0].startswith("1. deepseek-primary/deepseek-v4-flash")
    assert lines[1].startswith("2. deepseek-primary/deepseek-v4-pro")


def test_models_filters_by_capability_and_context(project: Path) -> None:
    result = invoke(
        project, "models", "--type", "chat", "--tools", "--min-context", "500000"
    )

    assert result.exit_code == 0
    assert "deepseek-v4-flash" in result.stdout
    # MiniMax-M2 has a 204k window, so the --min-context filter drops it.
    assert "MiniMax-M2\t" not in result.stdout


def test_models_enabled_flag_limits_output_to_configured_models(
    project: Path,
) -> None:
    result = invoke(project, "models", "--enabled", "--json")

    assert result.exit_code == 0
    assert {row["model"] for row in json.loads(result.stdout)} == {
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    }


def test_models_rejects_an_unknown_type(project: Path) -> None:
    result = invoke(project, "models", "--type", "nonsense")

    assert result.exit_code == 2
    assert "error:" in result.stderr
