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


def test_loads_yaml_and_json_documents() -> None:
    yaml_document = load_document(FIXTURES / "providers" / "alpha.yaml")
    json_document = load_document(FIXTURES / "providers" / "beta.json")

    assert yaml_document["id"] == "alpha"
    assert json_document["id"] == "beta"


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
