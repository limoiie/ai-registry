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


def _write_registry(tmp_path: Path, filename: str) -> None:
    _write_deployments(
        tmp_path,
        "accounts:\n"
        "  - id: primary\n"
        "    provider_id: deepseek\n"
        "    credential: {env: DEEPSEEK_API_KEY}\n"
        "    enabled_models: [deepseek-chat]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - account_id: primary\n"
        "        model_id: deepseek-chat\n",
        name=filename,
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


def test_from_project_whitespace_profile_argument_uses_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AI_REGISTRY_PROFILE", raising=False)
    _write_registry(tmp_path, "registry.yaml")
    registry = Registry.from_project(tmp_path, profile="   ")
    assert registry.resolve("chat-default").model_id == "deepseek-chat"


def test_from_project_whitespace_env_profile_uses_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_REGISTRY_PROFILE", " ")
    _write_registry(tmp_path, "registry.yaml")
    registry = Registry.from_project(tmp_path)
    assert registry.resolve("chat-default").model_id == "deepseek-chat"


def test_from_project_explicit_profile_overrides_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_REGISTRY_PROFILE", "dev")
    _write_registry(tmp_path, "registry.prod.yaml")
    registry = Registry.from_project(tmp_path, profile="prod")
    assert registry.resolve("chat-default").model_id == "deepseek-chat"


@pytest.mark.parametrize("name", ["registry.prod.yml", "registry.prod.json"])
def test_from_project_profile_loads_alternate_deployments_file(
    tmp_path: Path, name: str
) -> None:
    document = (
        "accounts:\n"
        "  - id: primary\n"
        "    provider_id: deepseek\n"
        "    credential: {env: DEEPSEEK_API_KEY}\n"
        "    enabled_models: [deepseek-chat]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - account_id: primary\n"
        "        model_id: deepseek-chat\n"
        if name.endswith(".yml")
        else (
            '{"accounts": [{"id": "primary", "provider_id": "deepseek", '
            '"credential": {"env": "DEEPSEEK_API_KEY"}, '
            '"enabled_models": ["deepseek-chat"]}], '
            '"aliases": [{"id": "chat-default", "deployments": '
            '[{"account_id": "primary", "model_id": "deepseek-chat"}]}]}'
        )
    )
    _write_deployments(tmp_path, document, name=name)

    registry = Registry.from_project(tmp_path, profile="prod")

    assert registry.resolve("chat-default").model_id == "deepseek-chat"


def test_from_project_missing_profile_file_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError) as caught:
        Registry.from_project(tmp_path, profile="prod")
    assert "registry.prod.yaml" in str(caught.value)


def test_from_project_invalid_profile_name_is_rejected(tmp_path: Path) -> None:
    for bad in (
        "../escape",
        "a/b",
        "a\\b",
        "a..b",
        ".",
        "..",
        "a b",
        "a\tb",
        "a\x00b",
        "prod✨",
    ):
        if "/" not in bad and "\\" not in bad and "\x00" not in bad:
            _write_registry(tmp_path, f"registry.{bad}.yaml")
        with pytest.raises(ConfigurationError):
            Registry.from_project(tmp_path, profile=bad)


def test_from_project_missing_profile_does_not_fall_back_to_default(
    tmp_path: Path,
) -> None:
    _write_registry(tmp_path, "registry.yaml")
    with pytest.raises(ConfigurationError) as caught:
        Registry.from_project(tmp_path, profile="prod")
    assert "registry.prod.yaml" in str(caught.value)


def test_from_project_loads_builtin_providers_and_deployments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_deployments(
        tmp_path,
        "accounts:\n"
        "  - id: deepseek-primary\n"
        "    provider_id: deepseek\n"
        "    credential: {env: DEEPSEEK_API_KEY}\n"
        "    enabled_models: [deepseek-chat]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - account_id: deepseek-primary\n"
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
        "accounts:\n"
        "  - id: deepseek-primary\n"
        "    provider_id: deepseek\n"
        "    credential: {env: DEEPSEEK_API_KEY}\n"
        "    enabled_models: [deepseek-chat]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - account_id: deepseek-primary\n"
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
        "id: local-vllm\nname: Local vLLM\nmodels:\n  - id: qwen:32b\n    type: chat\n",
        encoding="utf-8",
    )
    _write_deployments(
        tmp_path,
        "accounts:\n"
        "  - id: vllm-primary\n"
        "    provider_id: local-vllm\n"
        "    enabled_models: [qwen:32b]\n"
        "aliases:\n"
        "  - id: local-chat\n"
        "    deployments:\n"
        "      - account_id: vllm-primary\n"
        "        model_id: qwen:32b\n",
    )

    registry = Registry.from_project(tmp_path)

    resolution = registry.resolve("local-chat")
    assert resolution.provider.id == "local-vllm"
    assert resolution.provider.name == "Local vLLM"
    assert resolution.model_id == "qwen:32b"


def test_from_project_missing_deployments_file_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match=r"examples/registry.example.yaml"):
        Registry.from_project(tmp_path)


def test_from_project_project_provider_overrides_builtin(tmp_path: Path) -> None:
    providers_dir = tmp_path / ".ai-registry" / "providers"
    providers_dir.mkdir(parents=True)
    (providers_dir / "deepseek.yml").write_text(
        "id: deepseek\n"
        "name: Project DeepSeek\n"
        "models:\n"
        "  - id: project-model\n"
        "    type: chat\n",
        encoding="utf-8",
    )
    _write_deployments(
        tmp_path,
        "accounts:\n"
        "  - id: deepseek-primary\n"
        "    provider_id: deepseek\n"
        "    enabled_models: [project-model]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - account_id: deepseek-primary\n"
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
        "accounts:\n"
        "  - id: deepseek-primary\n"
        "    provider_id: deepseek\n"
        "    enabled_models: [deepseek-chat]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - account_id: deepseek-primary\n",
    )

    with pytest.raises(
        ConfigurationError,
        match=r"alias 'chat-default'.*index 0.*model_id.*define a deployment model",
    ):
        Registry.from_project(tmp_path)


def test_from_project_accepts_str_root(tmp_path: Path) -> None:
    _write_deployments(
        tmp_path,
        "accounts:\n"
        "  - id: deepseek-primary\n"
        "    provider_id: deepseek\n"
        "    enabled_models: [deepseek-chat]\n",
    )

    registry = Registry.from_project(str(tmp_path))

    resolution = registry.resolve("deepseek-primary/deepseek-chat")
    assert resolution.provider.id == "deepseek"
    assert resolution.model_id == "deepseek-chat"


def test_from_project_resolves_explicit_account_model(tmp_path: Path) -> None:
    _write_deployments(
        tmp_path,
        "accounts:\n"
        "  - id: deepseek-primary\n"
        "    provider_id: deepseek\n"
        "    credential: {env: DEEPSEEK_API_KEY}\n"
        "    enabled_models: [deepseek-chat, deepseek-reasoner]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - account_id: deepseek-primary\n"
        "        model_id: deepseek-chat\n",
    )

    registry = Registry.from_project(tmp_path)

    resolution = registry.resolve("deepseek-primary/deepseek-reasoner")

    assert resolution.account_id == "deepseek-primary"
    assert resolution.deployment_id == "deepseek-primary"
    assert resolution.provider.id == "deepseek"
    assert resolution.model_id == "deepseek-reasoner"


@pytest.mark.parametrize("name", ["registry.yml", "registry.json"])
def test_from_project_loads_alternate_deployments_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    document = (
        "accounts:\n"
        "  - id: deepseek-primary\n"
        "    provider_id: deepseek\n"
        "    credential: {env: DEEPSEEK_API_KEY}\n"
        "    enabled_models: [deepseek-chat]\n"
        if name.endswith(".yml")
        else (
            '{"accounts": [{"id": "deepseek-primary", "provider_id": "deepseek", '
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


def test_from_project_deployment_references_unknown_account(tmp_path: Path) -> None:
    _write_deployments(
        tmp_path,
        "accounts:\n"
        "  - id: deepseek-primary\n"
        "    provider_id: deepseek\n"
        "    enabled_models: [deepseek-chat]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - account_id: missing-profile\n"
        "        model_id: deepseek-chat\n",
    )

    with pytest.raises(
        ConfigurationError, match=r"alias 'chat-default'.*unknown account"
    ):
        Registry.from_project(tmp_path)


def test_from_project_discovers_the_registry_from_a_subdirectory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AI_REGISTRY_PROFILE", raising=False)
    _write_registry(tmp_path, "registry.yaml")
    nested = tmp_path / "services" / "api" / "src"
    nested.mkdir(parents=True)

    registry = Registry.from_project(nested)

    assert registry.resolve("chat-default").account_id == "primary"


def test_from_project_can_require_the_directory_at_the_given_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AI_REGISTRY_PROFILE", raising=False)
    _write_registry(tmp_path, "registry.yaml")
    nested = tmp_path / "services"
    nested.mkdir()

    with pytest.raises(ConfigurationError, match=r"Missing project registry file"):
        Registry.from_project(nested, search_parents=False)


def test_from_project_defaults_to_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AI_REGISTRY_PROFILE", raising=False)
    _write_registry(tmp_path, "registry.yaml")
    nested = tmp_path / "deep" / "nested"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    assert Registry.from_project().resolve("chat-default").model_id == "deepseek-chat"


def test_builtin_provider_endpoints_come_from_the_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AI_REGISTRY_PROFILE", raising=False)
    _write_registry(tmp_path, "registry.yaml")

    resolution = Registry.from_project(tmp_path).resolve("chat-default")

    assert resolution.endpoint == "https://api.deepseek.com/anthropic"
