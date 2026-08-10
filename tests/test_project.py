from pathlib import Path

import pytest

from ai_registry import Registry
from ai_registry.errors import ConfigurationError


def _write_deployments(
    tmp_path: Path, text: str, *, name: str = "registry.yaml"
) -> None:
    deployments_dir = tmp_path / ".ai-registry"
    deployments_dir.mkdir(exist_ok=True)
    (deployments_dir / name).write_text(text, encoding="utf-8")


def _write_registry(
    tmp_path: Path, filename: str, model_id: str = "deepseek-chat"
) -> None:
    (tmp_path / ".ai-registry").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai-registry" / filename).write_text(
        "profiles:\n"
        "  - id: primary\n"
        "    provider_id: deepseek\n"
        "    credential: {env: DEEPSEEK_API_KEY}\n"
        "    enabled_models: [deepseek-chat]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - profile_id: primary\n"
        "        model_id: deepseek-chat\n",
        encoding="utf-8",
    )


def test_from_project_no_profile_uses_default_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AI_REGISTRY_PROFILE", raising=False)
    _write_registry(tmp_path, "registry.yaml")
    registry = Registry.from_project(tmp_path)
    assert registry.resolve("chat-default").model_id == "deepseek-chat"


def test_from_project_profile_argument_selects_named_file(tmp_path: Path) -> None:
    _write_registry(tmp_path, "registry.prod.yaml")
    registry = Registry.from_project(tmp_path, profile="prod")
    assert registry.resolve("chat-default").model_id == "deepseek-chat"


def test_from_project_env_var_selects_named_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_REGISTRY_PROFILE", "dev")
    _write_registry(tmp_path, "registry.dev.yaml")
    registry = Registry.from_project(tmp_path)
    assert registry.resolve("chat-default").model_id == "deepseek-chat"


def test_from_project_explicit_profile_overrides_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_REGISTRY_PROFILE", "dev")
    _write_registry(tmp_path, "registry.prod.yaml")
    registry = Registry.from_project(tmp_path, profile="prod")
    assert registry.resolve("chat-default").model_id == "deepseek-chat"


def test_from_project_missing_profile_file_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError) as caught:
        Registry.from_project(tmp_path, profile="prod")
    assert "registry.prod.yaml" in str(caught.value)


def test_from_project_invalid_profile_name_is_rejected(tmp_path: Path) -> None:
    for bad in ("../escape", "a/b", "a\\b", "a..b"):
        with pytest.raises(ConfigurationError):
            Registry.from_project(tmp_path, profile=bad)


def test_from_project_loads_builtin_providers_and_deployments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_deployments(
        tmp_path,
        "profiles:\n"
        "  - id: deepseek-primary\n"
        "    provider_id: deepseek\n"
        "    credential: {env: DEEPSEEK_API_KEY}\n"
        "    enabled_models: [deepseek-chat]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - profile_id: deepseek-primary\n"
        "        model_id: deepseek-chat\n",
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")

    registry = Registry.from_project(tmp_path)

    resolution = registry.resolve("chat-default")
    assert resolution.model_id == "deepseek-chat"
    assert resolution.provider.id == "deepseek"


def test_from_project_uses_cwd_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_deployments(
        tmp_path,
        "profiles:\n"
        "  - id: deepseek-primary\n"
        "    provider_id: deepseek\n"
        "    credential: {env: DEEPSEEK_API_KEY}\n"
        "    enabled_models: [deepseek-chat]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - profile_id: deepseek-primary\n"
        "        model_id: deepseek-chat\n",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")

    resolution = Registry.from_project().resolve("chat-default")

    assert resolution.model_id == "deepseek-chat"
    assert resolution.provider.id == "deepseek"


def test_from_project_adds_new_project_provider(tmp_path: Path) -> None:
    providers_dir = tmp_path / ".ai-registry" / "providers"
    providers_dir.mkdir(parents=True)
    (providers_dir / "local-vllm.yml").write_text(
        "id: local-vllm\n"
        "name: Local vLLM\n"
        "model_cards:\n"
        "  - id: qwen:32b\n"
        "    type: chat\n",
        encoding="utf-8",
    )
    _write_deployments(
        tmp_path,
        "profiles:\n"
        "  - id: vllm-primary\n"
        "    provider_id: local-vllm\n"
        "    enabled_models: [qwen:32b]\n"
        "aliases:\n"
        "  - id: local-chat\n"
        "    deployments:\n"
        "      - profile_id: vllm-primary\n"
        "        model_id: qwen:32b\n",
    )

    registry = Registry.from_project(tmp_path)

    resolution = registry.resolve("local-chat")
    assert resolution.provider.id == "local-vllm"
    assert resolution.provider.name == "Local vLLM"
    assert resolution.model_id == "qwen:32b"


def test_from_project_missing_deployments_file_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="examples/registry.example.yaml"):
        Registry.from_project(tmp_path)


def test_from_project_project_provider_overrides_builtin(tmp_path: Path) -> None:
    providers_dir = tmp_path / ".ai-registry" / "providers"
    providers_dir.mkdir(parents=True)
    (providers_dir / "deepseek.yml").write_text(
        "id: deepseek\n"
        "name: Project DeepSeek\n"
        "model_cards:\n"
        "  - id: project-model\n"
        "    type: chat\n",
        encoding="utf-8",
    )
    _write_deployments(
        tmp_path,
        "profiles:\n"
        "  - id: deepseek-primary\n"
        "    provider_id: deepseek\n"
        "    enabled_models: [project-model]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - profile_id: deepseek-primary\n"
        "        model_id: project-model\n",
    )

    registry = Registry.from_project(tmp_path)

    resolution = registry.resolve("chat-default")
    assert resolution.provider.id == "deepseek"
    assert resolution.provider.name == "Project DeepSeek"
    assert resolution.model_id == "project-model"


def test_from_project_invalid_alias_fails_at_construction(tmp_path: Path) -> None:
    _write_deployments(
        tmp_path,
        "profiles:\n"
        "  - id: deepseek-primary\n"
        "    provider_id: deepseek\n"
        "    enabled_models: [deepseek-chat]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - profile_id: deepseek-primary\n",
    )

    with pytest.raises(
        ConfigurationError,
        match="alias 'chat-default'.*index 0.*model_id.*define a deployment model",
    ):
        Registry.from_project(tmp_path)


def test_from_project_accepts_str_root(tmp_path: Path) -> None:
    _write_deployments(
        tmp_path,
        "profiles:\n"
        "  - id: deepseek-primary\n"
        "    provider_id: deepseek\n"
        "    enabled_models: [deepseek-chat]\n",
    )

    registry = Registry.from_project(str(tmp_path))

    resolution = registry.resolve("deepseek-primary/deepseek-chat")
    assert resolution.provider.id == "deepseek"
    assert resolution.model_id == "deepseek-chat"


def test_from_project_resolves_explicit_profile_model(tmp_path: Path) -> None:
    _write_deployments(
        tmp_path,
        "profiles:\n"
        "  - id: deepseek-primary\n"
        "    provider_id: deepseek\n"
        "    credential: {env: DEEPSEEK_API_KEY}\n"
        "    enabled_models: [deepseek-chat, deepseek-reasoner]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - profile_id: deepseek-primary\n"
        "        model_id: deepseek-chat\n",
    )

    registry = Registry.from_project(tmp_path)

    resolution = registry.resolve("deepseek-primary/deepseek-reasoner")

    assert resolution.profile_id == "deepseek-primary"
    assert resolution.deployment_id == "deepseek-primary"
    assert resolution.provider.id == "deepseek"
    assert resolution.model_id == "deepseek-reasoner"


@pytest.mark.parametrize("name", ["registry.yml", "registry.json"])
def test_from_project_loads_alternate_deployments_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    document = (
        "profiles:\n"
        "  - id: deepseek-primary\n"
        "    provider_id: deepseek\n"
        "    credential: {env: DEEPSEEK_API_KEY}\n"
        "    enabled_models: [deepseek-chat]\n"
        if name.endswith(".yml")
        else (
            '{"profiles": [{"id": "deepseek-primary", "provider_id": "deepseek", '
            '"credential": {"env": "DEEPSEEK_API_KEY"}, '
            '"enabled_models": ["deepseek-chat"]}]}'
        )
    )
    _write_deployments(tmp_path, document, name=name)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")

    registry = Registry.from_project(tmp_path)

    resolution = registry.resolve("deepseek-primary/deepseek-chat")
    assert resolution.provider.id == "deepseek"
    assert resolution.model_id == "deepseek-chat"


def test_from_project_deployment_references_unknown_profile(tmp_path: Path) -> None:
    _write_deployments(
        tmp_path,
        "profiles:\n"
        "  - id: deepseek-primary\n"
        "    provider_id: deepseek\n"
        "    enabled_models: [deepseek-chat]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - profile_id: missing-profile\n"
        "        model_id: deepseek-chat\n",
    )

    with pytest.raises(
        ConfigurationError, match="alias 'chat-default'.*unknown profile"
    ):
        Registry.from_project(tmp_path)
