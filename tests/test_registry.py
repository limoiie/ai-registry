from pathlib import Path

import pytest

from ai_registry import Registry
from ai_registry.errors import ConfigurationError, RegistryError
from ai_registry.schemas import (
    Alias,
    CredentialRef,
    Deployment,
    ModelCard,
    ModelType,
    Profile,
    Provider,
)


def provider() -> Provider:
    return Provider(
        id="openai",
        name="OpenAI",
        default_base_url="https://api.example.test",
        model_cards=[
            ModelCard(id="chat", type=ModelType.CHAT, display_name="Chat Model"),
            ModelCard(id="other", type=ModelType.CHAT),
        ],
    )


def profile() -> Profile:
    return Profile(
        id="primary",
        provider_id="openai",
        endpoint="https://profile.example.test",
        credential=CredentialRef(secret_ref="REGISTRY_KEY"),
        enabled_models=["chat"],
        metadata={"region": "us"},
    )


def test_constructs_from_normalized_data_and_resolves_alias() -> None:
    registry = Registry.from_data(
        providers=[provider()],
        profiles=[profile()],
        aliases=[
            Alias(
                id="fast",
                deployments=[Deployment(profile_id="primary", model_id="chat")],
            )
        ],
    )

    result = registry.resolve("fast")

    assert result.provider.id == "openai"
    assert result.model.id == "chat"
    assert result.profile_id == "primary"
    assert result.deployment_id == "fast"
    assert result.endpoint == "https://profile.example.test"
    assert result.endpoint_metadata == {"region": "us"}


def test_alias_wins_over_direct_profile_model_reference() -> None:
    registry = Registry.from_data(
        providers=[provider()],
        profiles=[
            Profile(
                id="primary",
                provider_id="openai",
                enabled_models=["chat", "other"],
            )
        ],
        aliases=[
            Alias(
                id="primary",
                deployments=[Deployment(profile_id="primary", model_id="other")],
            )
        ],
    )

    assert registry.resolve("primary").model.id == "other"


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ("missing", "unknown alias or model reference 'missing'"),
        ("unknown/chat", "unknown profile 'unknown'"),
        ("primary/other", "model 'other' is not enabled by profile 'primary'"),
    ],
)
def test_resolution_errors_are_descriptive_and_safe(
    reference: str, message: str
) -> None:
    registry = Registry.from_data(providers=[provider()], profiles=[profile()])

    with pytest.raises(RegistryError, match=message):
        registry.resolve(reference)


def test_aggregate_validation_reports_invalid_alias_deployment() -> None:
    with pytest.raises(ConfigurationError, match="alias 'fast'.*model 'missing'"):
        Registry.from_data(
            providers=[provider()],
            profiles=[profile()],
            aliases=[
                Alias(
                    id="fast",
                    deployments=[Deployment(profile_id="primary", model_id="missing")],
                )
            ],
        )


def test_aggregate_validation_reports_unknown_provider_and_model() -> None:
    with pytest.raises(
        ConfigurationError, match="profile 'orphan'.*provider 'missing'"
    ):
        Registry.from_data(
            providers=[provider()],
            profiles=[Profile(id="orphan", provider_id="missing")],
        )

    with pytest.raises(ConfigurationError, match="profile 'primary'.*model 'missing'"):
        Registry.from_data(
            providers=[provider()],
            profiles=[
                Profile(
                    id="primary",
                    provider_id="openai",
                    enabled_models=["missing"],
                )
            ],
        )


def test_credentials_are_resolved_lazily_at_adapter_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Resolver:
        def resolve(self, reference: str) -> str:
            calls.append(reference)
            return "transient-secret"

    registry = Registry.from_data(
        providers=[provider()], profiles=[profile()], secret_resolver=Resolver()
    )
    result = registry.resolve("primary/chat")

    assert calls == []
    assert result.resolve_credential() == "transient-secret"
    assert calls == ["REGISTRY_KEY"]
    monkeypatch.delenv("REGISTRY_KEY", raising=False)


def test_from_files_loads_existing_config_shapes(tmp_path: Path) -> None:
    provider_path = tmp_path / "provider.yaml"
    provider_path.write_text(
        "id: openai\nname: OpenAI\nmodel_cards:\n  - id: chat\n    type: chat\n",
        encoding="utf-8",
    )
    profile_path = tmp_path / "profiles.yaml"
    profile_path.write_text(
        "profiles:\n  - id: primary\n    provider_id: openai\n"
        "    enabled_models: [chat]\n",
        encoding="utf-8",
    )

    registry = Registry.from_files([provider_path], [profile_path])

    assert registry.resolve("primary/chat").model.id == "chat"
