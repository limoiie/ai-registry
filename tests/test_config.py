from io import StringIO
from pathlib import Path

import pytest

from ai_registry.config import (
    load_document,
    load_profile_file,
    load_provider_file,
    load_provider_files,
)
from ai_registry.errors import ConfigurationError

FIXTURES = Path(__file__).parent / "fixtures"
DATA = Path(__file__).parents[1] / "data" / "ai" / "providers"


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


def test_loads_provider_and_profile_from_unnamed_streams() -> None:
    provider = load_provider_file(
        StringIO("id: stream-provider\nname: Stream Provider\n")
    )
    profiles = load_profile_file(
        StringIO(
            "profiles:\n  - id: stream-profile\n    provider_id: stream-provider\n"
            "    api_key_env: STREAM_API_KEY\n"
        )
    )

    assert provider.id == "stream-provider"
    assert profiles[0].provider_id == provider.id


def test_normalizes_single_provider_and_preserves_metadata() -> None:
    provider = load_provider_file(FIXTURES / "providers" / "alpha.yaml")

    assert provider.id == "alpha"
    assert provider.sdk_type.value == "custom"
    assert provider.settings["proxy_url"] == "https://proxy.example.test"
    assert provider.settings["url"] == "https://alpha.example.test"
    assert provider.model_cards[0].metadata["pricing"] == {"input": 1}
    assert provider.model_cards[0].capabilities.reasoning is True
    assert provider.model_cards[0].metadata["abilities"]["function_call"] is True


def test_loads_multiple_provider_files() -> None:
    providers = load_provider_files(
        [FIXTURES / "providers" / "alpha.yaml", FIXTURES / "providers" / "beta.json"]
    )

    assert [provider.id for provider in providers] == ["alpha", "beta"]


def test_normalizes_profiles_without_resolving_credentials() -> None:
    profiles = load_profile_file(FIXTURES / "profiles.yaml")

    assert profiles[0].credential is not None
    assert profiles[0].credential.env == "ALPHA_API_KEY"
    assert profiles[0].enabled_models == ["alpha-chat"]


def test_malformed_yaml_has_safe_actionable_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("id: [broken", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="Unable to parse YAML.*broken.yaml"):
        load_document(path)


def test_duplicate_provider_ids_are_rejected(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_text("id: duplicate\nname: First\n", encoding="utf-8")
    second.write_text("id: duplicate\nname: Second\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="duplicate provider id 'duplicate'"):
        load_provider_files([first, second])


def test_duplicate_model_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text(
        "id: provider\nname: Provider\nmodel_cards:\n"
        "  - id: same\n    type: chat\n  - id: same\n    type: chat\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="duplicate model id 'same'.*provider"):
        load_provider_file(path)


def test_loads_actual_catalog_legacy_model_fields() -> None:
    uniapi = load_provider_file(DATA / "uniapi.yml")
    minimax = load_provider_file(DATA / "minimax.yml")

    embedding = next(
        card for card in uniapi.model_cards if card.id == "bge-large-zh:latest"
    )
    unknown_context = next(
        card for card in uniapi.model_cards if card.id == "qwen2.5-vl:72b"
    )
    deprecated = next(
        card for card in minimax.model_cards if card.id == "MiniMax-M2-Stable"
    )

    assert embedding.embedding_dimension == 1024
    assert embedding.metadata["max_dimension"] == 1024
    assert unknown_context.context_window_tokens is None
    assert unknown_context.metadata["context_window_tokens"] == 0
    assert deprecated.metadata["deprecated"] is True
    assert deprecated.metadata["settings"] == {"search_impl": "params"}


def test_normalizes_actual_uniapi_reranker_to_openai() -> None:
    provider = load_provider_file(DATA / "uniapi-rerankers.yml")

    assert provider.sdk_type.value == "openai"
    assert provider.settings["sdk_type"] == "uniapi"
    assert provider.model_cards[0].type.value == "reranking"


def test_rejects_unsupported_sdk_type(tmp_path: Path) -> None:
    path = tmp_path / "unsupported.yaml"
    path.write_text(
        "id: provider\nname: Provider\nsettings:\n  sdk_type: unsupported\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="sdk_type"):
        load_provider_file(path)


def test_loads_actual_builtin_profiles_and_preserves_legacy_metadata() -> None:
    profiles = load_profile_file(DATA / "profiles" / "builtin.yaml")

    assert profiles[0].metadata == {
        "remark": "builtin-deepseek",
        "description": "Built-in DeepSeek profile",
    }
    assert profiles[0].credential is not None
    assert profiles[0].credential.env == "DEEPSEEK_API_KEY"


def test_non_mapping_model_card_has_safe_actionable_error(tmp_path: Path) -> None:
    path = tmp_path / "bad-card.yaml"
    path.write_text(
        "id: provider\nname: Provider\nmodel_cards:\n  - bad\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ConfigurationError, match="Invalid model card.*index 0.*mapping"
    ):
        load_provider_file(path)
