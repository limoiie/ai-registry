from io import StringIO
from pathlib import Path

import pytest

from ai_registry import Registry
from ai_registry.config import (
    _ensure_unique_provider_ids,
    _provider_from_text,
    discover_builtin_providers,
    discover_project_providers,
    load_account_file,
    load_alias_file,
    load_deployments_file,
    load_document,
    load_provider_file,
    load_provider_files,
    merge_providers,
    normalize_provider,
)
from ai_registry.errors import ConfigurationError

FIXTURES = Path(__file__).parent / "fixtures"
DATA = Path(__file__).parents[1] / "src" / "ai_registry" / "data" / "providers"


def test_builtin_provider_data_is_package_data() -> None:
    from importlib import resources

    base = resources.files("ai_registry") / "data" / "providers"
    names = {entry.name for entry in base.iterdir()}
    assert {
        "deepseek.yml",
        "uniapi.yml",
        "minimax.yml",
        "uniapi-rerankers.yml",
        "openai.yml",
        "anthropic.yml",
        "gemini.yml",
        "moonshot.yml",
        "zhipu.yml",
        "qwen.yml",
        "xai.yml",
    } <= names


def test_discovers_builtin_providers_from_package_data() -> None:
    providers = discover_builtin_providers()

    assert {provider.id for provider in providers} == {
        "deepseek",
        "uniapi",
        "minimax",
        "uniapi-rerankers",
        "openai",
        "anthropic",
        "gemini",
        "moonshot",
        "zhipu",
        "qwen",
        "xai",
    }


def test_discovered_builtin_providers_are_sorted_by_id() -> None:
    providers = discover_builtin_providers()

    assert [provider.id for provider in providers] == sorted(
        provider.id for provider in providers
    )


def test_discover_builtin_providers_missing_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "importlib.resources.files", lambda _package: tmp_path / "missing"
    )

    with pytest.raises(ConfigurationError, match=r"built-in provider data"):
        discover_builtin_providers()


def test_provider_from_text_parses_yaml() -> None:
    provider = _provider_from_text("custom.yaml", "id: custom\nname: Custom\n")

    assert provider.id == "custom"
    assert provider.name == "Custom"


def test_provider_from_text_parses_json() -> None:
    provider = _provider_from_text("custom.json", '{"id": "custom", "name": "Custom"}')

    assert provider.id == "custom"
    assert provider.name == "Custom"


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("broken.yaml", "id: [broken"),
        ("broken.json", '{"id":'),
    ],
)
def test_provider_from_text_wraps_parse_failures(name: str, text: str) -> None:
    with pytest.raises(
        ConfigurationError, match=f"Unable to parse (?:JSON|YAML) provider '{name}'"
    ):
        _provider_from_text(name, text)


def test_provider_from_text_requires_top_level_mapping() -> None:
    with pytest.raises(ConfigurationError, match=r"top-level mapping"):
        _provider_from_text("list.yaml", "- not\n- a\n- mapping\n")


def test_discovers_project_providers_when_directory_missing(
    tmp_path: Path,
) -> None:
    assert discover_project_providers(tmp_path) == []


def test_project_provider_overrides_builtin_by_id(tmp_path: Path) -> None:
    providers_dir = tmp_path / ".ai-registry" / "providers"
    providers_dir.mkdir(parents=True)
    (providers_dir / "uniapi.yml").write_text(
        "id: uniapi\nname: My Uni API\nmodels:\n  - id: custom\n    type: chat\n",
        encoding="utf-8",
    )

    merged = merge_providers(
        discover_builtin_providers(), discover_project_providers(tmp_path)
    )

    uniapi = next(provider for provider in merged if provider.id == "uniapi")
    assert uniapi.name == "My Uni API"
    assert [card.id for card in uniapi.models] == ["custom"]
    assert len({provider.id for provider in merged}) == len(merged)


def test_project_provider_adds_unique_provider(tmp_path: Path) -> None:
    providers_dir = tmp_path / ".ai-registry" / "providers"
    providers_dir.mkdir(parents=True)
    (providers_dir / "my-vllm.yaml").write_text(
        "id: my-vllm\nname: Local vLLM\nmodels:\n  - id: qwen:32b\n    type: chat\n",
        encoding="utf-8",
    )

    merged = merge_providers(
        discover_builtin_providers(), discover_project_providers(tmp_path)
    )

    assert "my-vllm" in {provider.id for provider in merged}


def test_discover_project_providers_rejects_duplicate_ids(
    tmp_path: Path,
) -> None:
    providers_dir = tmp_path / ".ai-registry" / "providers"
    providers_dir.mkdir(parents=True)
    (providers_dir / "first.yaml").write_text(
        "id: duplicate\nname: First\n", encoding="utf-8"
    )
    (providers_dir / "second.yml").write_text(
        "id: duplicate\nname: Second\n", encoding="utf-8"
    )

    with pytest.raises(ConfigurationError, match=r"duplicate provider id 'duplicate'"):
        discover_project_providers(tmp_path)


def test_discover_project_providers_loads_json_files(tmp_path: Path) -> None:
    providers_dir = tmp_path / ".ai-registry" / "providers"
    providers_dir.mkdir(parents=True)
    (providers_dir / "custom.json").write_text(
        '{"id": "custom", "name": "Custom"}', encoding="utf-8"
    )

    assert [provider.id for provider in discover_project_providers(tmp_path)] == [
        "custom"
    ]


def test_discover_project_providers_malformed_yaml_is_actionable(
    tmp_path: Path,
) -> None:
    providers_dir = tmp_path / ".ai-registry" / "providers"
    providers_dir.mkdir(parents=True)
    (providers_dir / "broken.yaml").write_text("id: [broken", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=r"Unable to parse YAML.*broken.yaml"):
        discover_project_providers(tmp_path)


def test_merge_providers_empty_project_returns_builtins() -> None:
    builtin = discover_builtin_providers()

    assert merge_providers(builtin, []) == builtin


def test_merge_providers_rejects_duplicate_project_ids(tmp_path: Path) -> None:
    project = [
        normalize_provider({"id": "dup", "name": "First"}),
        normalize_provider({"id": "dup", "name": "Second"}),
    ]

    with pytest.raises(ConfigurationError, match=r"duplicate provider id 'dup'"):
        merge_providers([], project)


def test_merge_providers_rejects_duplicate_builtin_ids() -> None:
    builtin = [
        normalize_provider({"id": "dup", "name": "First"}),
        normalize_provider({"id": "dup", "name": "Second"}),
    ]

    with pytest.raises(ConfigurationError, match=r"duplicate provider id 'dup'"):
        merge_providers(builtin, [])


def test_ensure_unique_provider_ids_rejects_duplicates() -> None:
    providers = [
        normalize_provider({"id": "dup", "name": "First"}),
        normalize_provider({"id": "dup", "name": "Second"}),
    ]

    with pytest.raises(ConfigurationError, match=r"duplicate provider id 'dup'"):
        _ensure_unique_provider_ids(providers)


def test_loads_yaml_and_json_documents() -> None:
    yaml_document = load_document(FIXTURES / "providers" / "alpha.yaml")
    json_document = load_document(FIXTURES / "providers" / "beta.json")

    assert yaml_document["id"] == "alpha"
    assert json_document["id"] == "beta"


def test_loads_unnamed_yaml_and_json_streams() -> None:
    yaml_document = load_document(StringIO("id: stream-yaml\n"))
    json_document = load_document(StringIO('{"id": "stream-json"}'))

    assert yaml_document["id"] == "stream-yaml"
    assert json_document["id"] == "stream-json"


def test_loads_provider_and_account_from_unnamed_streams() -> None:
    provider = load_provider_file(
        StringIO("id: stream-provider\nname: Stream Provider\n")
    )
    accounts = load_account_file(
        StringIO(
            "accounts:\n  - id: stream-account\n    provider_id: stream-provider\n"
            "    api_key_env: STREAM_API_KEY\n"
        )
    )

    assert provider.id == "stream-provider"
    assert accounts[0].provider_id == provider.id


def test_normalizes_single_provider_and_preserves_metadata() -> None:
    provider = load_provider_file(FIXTURES / "providers" / "alpha.yaml")

    assert provider.id == "alpha"
    assert provider.sdk_type.value == "custom"
    assert provider.settings["proxy_url"] == "https://proxy.example.test"
    assert provider.settings["url"] == "https://alpha.example.test"
    assert provider.models[0].metadata["pricing"] == {"input": 1}
    assert provider.models[0].capabilities.reasoning is True
    assert provider.models[0].metadata["abilities"]["function_call"] is True


def test_loads_multiple_provider_files() -> None:
    providers = load_provider_files(
        [FIXTURES / "providers" / "alpha.yaml", FIXTURES / "providers" / "beta.json"]
    )

    assert [provider.id for provider in providers] == ["alpha", "beta"]


@pytest.mark.parametrize("models", [0, False, ""])
def test_rejects_falsy_non_list_models(tmp_path: Path, models: object) -> None:
    path = tmp_path / "invalid-models.yaml"
    path.write_text(
        f"id: provider\nname: Provider\nmodels: {models!r}\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match=r"Invalid models.*expected a list"):
        load_provider_file(path)


@pytest.mark.parametrize("models", [None, []])
def test_allows_empty_models_values(tmp_path: Path, models: object) -> None:
    path = tmp_path / "empty-models.yaml"
    document = "id: provider\nname: Provider\n"
    if models is None:
        document += "models: null\n"
    else:
        document += "models: []\n"
    path.write_text(document, encoding="utf-8")

    assert load_provider_file(path).models == []


def test_legacy_model_cards_key_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "legacy-models.yaml"
    path.write_text(
        "id: provider\nname: Provider\nmodel_cards:\n  - id: chat\n    type: chat\n",
        encoding="utf-8",
    )

    provider = load_provider_file(path)
    assert [model.id for model in provider.models] == ["chat"]


def test_normalizes_accounts_without_resolving_credentials() -> None:
    accounts = load_account_file(FIXTURES / "accounts.yaml")

    assert accounts[0].credential is not None
    assert accounts[0].credential.env == "ALPHA_API_KEY"
    assert accounts[0].enabled_models == ["alpha-chat"]


def test_malformed_yaml_has_safe_actionable_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("id: [broken", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=r"Unable to parse YAML.*broken.yaml"):
        load_document(path)


def test_yaml_parse_error_redacts_secret_like_input(tmp_path: Path) -> None:
    secret_like_value = "sk-live-secret"
    path = tmp_path / "broken-secret.yaml"
    path.write_text(f"id: [{secret_like_value}\n", encoding="utf-8")

    with pytest.raises(ConfigurationError) as caught:
        load_document(path)

    error = caught.value
    for rendered in (str(error), repr(error), str(error.args), str(error.__dict__)):
        assert secret_like_value not in rendered
    assert "Unable to parse YAML configuration" in str(error)
    assert "check YAML syntax" in str(error)


def test_duplicate_provider_ids_are_rejected(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_text("id: duplicate\nname: First\n", encoding="utf-8")
    second.write_text("id: duplicate\nname: Second\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=r"duplicate provider id 'duplicate'"):
        load_provider_files([first, second])


def test_duplicate_model_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text(
        "id: provider\nname: Provider\nmodels:\n"
        "  - id: same\n    type: chat\n  - id: same\n    type: chat\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ConfigurationError, match=r"duplicate model id 'same'.*provider"
    ):
        load_provider_file(path)


def test_loads_actual_catalog_normalized_model_fields() -> None:
    uniapi = load_provider_file(DATA / "uniapi.yml")
    minimax = load_provider_file(DATA / "minimax.yml")

    embedding = next(card for card in uniapi.models if card.id == "bge-large-zh:latest")
    vision = next(card for card in uniapi.models if card.id == "qwen2.5-vl:72b")
    deprecated = next(card for card in minimax.models if card.id == "MiniMax-M2-Stable")

    assert embedding.embedding_dimension == 1024
    assert vision.context_window_tokens == 131072
    assert vision.capabilities.vision is True
    assert deprecated.metadata["deprecated"] is True


def test_normalizes_actual_uniapi_reranker_to_openai() -> None:
    provider = load_provider_file(DATA / "uniapi-rerankers.yml")

    assert provider.sdk_type.value == "openai"
    assert provider.models[0].type.value == "reranking"


def test_rejects_unsupported_sdk_type(tmp_path: Path) -> None:
    path = tmp_path / "unsupported.yaml"
    path.write_text(
        "id: provider\nname: Provider\nsettings:\n  sdk_type: unsupported\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match=r"sdk_type"):
        load_provider_file(path)


def test_normalizes_top_level_uniapi_and_preserves_settings(tmp_path: Path) -> None:
    path = tmp_path / "provider.yml"
    path.write_text(
        "id: provider\nname: Provider\nsdk_type: uniapi\n"
        "settings:\n  sdk_type: uniapi\n  custom: value\n",
        encoding="utf-8",
    )

    provider = load_provider_file(path)

    assert provider.sdk_type.value == "openai"
    assert provider.settings == {"sdk_type": "uniapi", "custom": "value"}


def test_rejects_conflicting_canonical_and_nested_sdk_types(tmp_path: Path) -> None:
    path = tmp_path / "conflicting-provider.yml"
    path.write_text(
        "id: provider\nname: Provider\nsdk_type: anthropic\n"
        "settings:\n  sdk_type: openai\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match=r"conflicting sdk_type"):
        load_provider_file(path)


def test_provider_endpoints_parse_from_file(tmp_path: Path) -> None:
    path = tmp_path / "deepseek-multi.yml"
    path.write_text(
        "id: deepseek\n"
        "name: DeepSeek\n"
        "endpoints:\n"
        "  openai-chat:\n"
        "    sdk_type: openai\n"
        "    base_url: https://api.deepseek.com\n"
        "  openai-responses:\n"
        "    sdk_type: openai\n"
        "    base_url: https://api.deepseek.com\n"
        "    mode: responses\n"
        "default_endpoint: openai-chat\n",
        encoding="utf-8",
    )
    provider = load_provider_file(path)
    assert "openai-responses" in provider.endpoints
    assert provider.endpoints["openai-responses"].mode.value == "responses"


def test_multi_endpoint_fixture_loads() -> None:
    provider = load_provider_file(FIXTURES / "deepseek-endpoints.yml")
    assert set(provider.endpoints) == {"openai-chat", "openai-responses", "anthropic"}
    flash = next(c for c in provider.models if c.id == "deepseek-v4-flash")
    assert flash.endpoints == ["openai-chat", "openai-responses", "anthropic"]


def test_proxy_placeholder_skipped_when_endpoints_declared(tmp_path: Path) -> None:
    path = tmp_path / "multi-endpoint.yml"
    path.write_text(
        "id: deepseek\n"
        "name: DeepSeek\n"
        "endpoints:\n"
        "  openai-chat:\n"
        "    sdk_type: openai\n"
        "    base_url: https://api.deepseek.com\n"
        "settings:\n"
        "  proxy_url:\n"
        "    placeholder: https://proxy.example.test\n",
        encoding="utf-8",
    )
    provider = load_provider_file(path)
    assert provider.default_base_url is None
    assert provider.settings["proxy_url"] == {
        "placeholder": "https://proxy.example.test"
    }


def test_proxy_placeholder_backfill_when_no_endpoints(tmp_path: Path) -> None:
    path = tmp_path / "single-endpoint.yml"
    path.write_text(
        "id: deepseek\n"
        "name: DeepSeek\n"
        "settings:\n"
        "  proxy_url:\n"
        "    placeholder: https://proxy.example.test\n",
        encoding="utf-8",
    )
    provider = load_provider_file(path)
    assert provider.default_base_url == "https://proxy.example.test"


def test_account_endpoint_ref_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "accounts.yml"
    path.write_text(
        "accounts:\n"
        "  - id: a\n"
        "    provider_id: deepseek\n"
        "    endpoint_ref: anthropic\n"
        "    api_key_env: KEY\n",
        encoding="utf-8",
    )
    accounts = load_account_file(path)
    assert accounts[0].endpoint_ref == "anthropic"


def test_loads_legacy_account_fields_into_metadata(tmp_path: Path) -> None:
    path = tmp_path / "legacy-account.yaml"
    path.write_text(
        "accounts:\n"
        "  - id: builtin-deepseek\n"
        "    provider_id: deepseek\n"
        "    api_key_env: DEEPSEEK_API_KEY\n"
        "    remark: builtin-deepseek\n"
        "    description: Built-in DeepSeek account\n",
        encoding="utf-8",
    )

    accounts = load_account_file(path)

    assert accounts[0].metadata == {
        "remark": "builtin-deepseek",
        "description": "Built-in DeepSeek account",
    }
    assert accounts[0].credential is not None
    assert accounts[0].credential.env == "DEEPSEEK_API_KEY"


def test_non_mapping_model_has_safe_actionable_error(tmp_path: Path) -> None:
    path = tmp_path / "bad-card.yaml"
    path.write_text(
        "id: provider\nname: Provider\nmodels:\n  - bad\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match=r"Invalid model.*index 0.*mapping"):
        load_provider_file(path)


@pytest.mark.parametrize(
    ("label", "document"),
    [
        ("settings", "id: provider\nname: Provider\nsettings: bad\n"),
        (
            "abilities",
            "id: provider\nname: Provider\nmodels:\n"
            "  - id: model\n    type: chat\n    abilities: bad\n",
        ),
        (
            "metadata",
            "id: provider\nname: Provider\nmodels:\n"
            "  - id: model\n    type: chat\n    metadata: bad\n",
        ),
    ],
)
def test_non_mapping_provider_fields_have_safe_errors(
    tmp_path: Path, label: str, document: str
) -> None:
    path = tmp_path / f"bad-{label}.yaml"
    path.write_text(document, encoding="utf-8")

    with pytest.raises(ConfigurationError, match=f"Invalid {label}.*mapping"):
        load_provider_file(path)


def test_non_mapping_account_metadata_has_safe_error(tmp_path: Path) -> None:
    path = tmp_path / "bad-account-metadata.yaml"
    path.write_text(
        "accounts:\n  - id: account\n    provider_id: provider\n    metadata: bad\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match=r"Invalid account metadata.*mapping"):
        load_account_file(path)


def test_rejects_conflicting_account_credentials(tmp_path: Path) -> None:
    path = tmp_path / "conflicting-credentials.yaml"
    path.write_text(
        "accounts:\n  - id: account\n    provider_id: provider\n"
        "    api_key_env: API_KEY\n    credential:\n      env: OTHER_KEY\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match=r"api_key_env.*credential"):
        load_account_file(path)


def test_loads_merged_deployments_file(tmp_path: Path) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(
        "accounts:\n"
        "  - id: primary\n"
        "    provider_id: deepseek\n"
        "    api_key_env: DEEPSEEK_API_KEY\n"
        "    enabled_models: [deepseek-chat]\n"
        "    remark: legacy\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - account_id: primary\n"
        "        model_id: deepseek-chat\n",
        encoding="utf-8",
    )

    deployments = load_deployments_file(path)

    assert deployments.accounts[0].id == "primary"
    assert deployments.accounts[0].credential is not None
    assert deployments.accounts[0].credential.env == "DEEPSEEK_API_KEY"
    assert deployments.accounts[0].metadata["remark"] == "legacy"
    assert deployments.aliases == [
        {
            "id": "chat-default",
            "deployments": [{"account_id": "primary", "model_id": "deepseek-chat"}],
        }
    ]


def test_deployments_file_requires_accounts_and_optional_aliases(
    tmp_path: Path,
) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text("aliases: []\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match=r"accounts"):
        load_deployments_file(path)

    path.write_text("accounts: []\n", encoding="utf-8")
    deployments = load_deployments_file(path)
    assert deployments.accounts == [] and deployments.aliases == []


def test_deployments_file_rejects_non_list_aliases(tmp_path: Path) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text("accounts: []\naliases: not-a-list\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=r"'aliases' list"):
        load_deployments_file(path)


def test_example_registry_file_loads() -> None:
    example = Path(__file__).parents[1] / "examples" / "registry.example.yaml"
    deployments = load_deployments_file(example)
    assert deployments.accounts
    assert deployments.aliases
    account_ids = {account.id for account in deployments.accounts}
    assert {
        deployment["account_id"]
        for alias in deployments.aliases
        for deployment in alias["deployments"]
    } <= account_ids

    Registry.from_data(
        providers=discover_builtin_providers(),
        accounts=deployments.accounts,
        aliases=deployments.aliases,
    )


def test_load_alias_file_requires_aliases_list(tmp_path: Path) -> None:
    path = tmp_path / "aliases.yaml"
    path.write_text("version: 1\n", encoding="utf-8")

    with pytest.raises(
        ConfigurationError,
        match=r"Alias configuration .*must contain an 'aliases' list",
    ):
        load_alias_file(path)


def test_load_alias_file_rejects_non_list_aliases(tmp_path: Path) -> None:
    path = tmp_path / "aliases.yaml"
    path.write_text("aliases: not-a-list\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=r"'aliases' list"):
        load_alias_file(path)


def test_load_alias_file_rejects_non_mapping_alias(tmp_path: Path) -> None:
    path = tmp_path / "aliases.yaml"
    path.write_text("aliases:\n  - just-a-string\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=r"invalid alias at index 0"):
        load_alias_file(path)


def test_load_alias_file_returns_mappings(tmp_path: Path) -> None:
    path = tmp_path / "aliases.yaml"
    path.write_text(
        "aliases:\n  - id: chat-default\n    deployments: []\n", encoding="utf-8"
    )

    assert load_alias_file(path) == [{"id": "chat-default", "deployments": []}]
