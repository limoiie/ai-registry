from datetime import date

import pytest
from pydantic import ValidationError

from ai_registry.errors import ConfigurationError, RegistryError
from ai_registry.schemas import (
    Alias,
    CredentialRef,
    Deployment,
    ModelCapabilities,
    ModelCard,
    ModelType,
    Profile,
    Provider,
    RegistryConfig,
    RoutingMetadata,
    SDKType,
)


def test_provider_and_model_card_have_safe_defaults_and_capabilities() -> None:
    provider = Provider(
        id="openai-compatible",
        name="OpenAI Compatible",
        model_cards=[
            ModelCard(
                id="chat-model",
                type=ModelType.CHAT,
                capabilities=ModelCapabilities(tools=True, vision=True),
                released_at=date(2026, 1, 1),
            )
        ],
    )

    assert provider.sdk_type is SDKType.OPENAI
    assert provider.default_base_url is None
    assert provider.model_cards[0].capabilities.tools is True
    assert provider.model_cards[0].capabilities.vision is True


def test_identifiers_are_constrained() -> None:
    with pytest.raises(ValidationError):
        Provider(id="bad id", name="Invalid")

    with pytest.raises(ValidationError):
        ModelCard(id="", type="chat")


def test_profile_carries_endpoint_enabled_models_and_credential_reference() -> None:
    profile = Profile(
        id="primary",
        provider_id="openai-compatible",
        endpoint="https://example.test/v1",
        credential=CredentialRef(env="AI_API_KEY"),
        enabled_models=["chat-model"],
    )

    assert profile.endpoint == "https://example.test/v1"
    assert profile.enabled_models == ["chat-model"]
    assert profile.credential.env == "AI_API_KEY"


def test_secret_ref_credentials_are_supported() -> None:
    credential = CredentialRef(secret_ref="vault://prod/ai/key")

    assert credential.secret_ref == "vault://prod/ai/key"


def test_credentials_require_exactly_one_reference_and_reject_literal_keys() -> None:
    with pytest.raises(ValidationError):
        CredentialRef(env="KEY", secret_ref="vault://key")

    with pytest.raises(ValidationError):
        CredentialRef(api_key="literal-api-key")


def test_alias_deployments_and_routing_metadata() -> None:
    alias = Alias(
        id="fast-chat",
        deployments=[
            Deployment(
                profile_id="primary",
                model_id="chat-model",
                routing=RoutingMetadata(priority=2, weight=10, enabled=True),
            )
        ],
    )

    deployment = alias.deployments[0]
    assert deployment.profile_id == "primary"
    assert deployment.model_id == "chat-model"
    assert deployment.routing.priority == 2
    assert deployment.routing.weight == 10


def test_routing_metadata_rejects_invalid_values() -> None:
    with pytest.raises(ValidationError):
        RoutingMetadata(priority=-1, weight=0)


def test_aggregate_rejects_duplicate_ids() -> None:
    provider = Provider(id="provider", name="Provider")
    with pytest.raises(ConfigurationError, match="duplicate provider id"):
        RegistryConfig(providers=[provider, provider])


def test_repr_and_safe_serialization_do_not_expose_secret_values() -> None:
    secret = "super-secret-api-key"
    config = RegistryConfig(
        profiles=[
            Profile(
                id="primary",
                provider_id="provider",
                credential=CredentialRef(env=secret),
            )
        ]
    )

    assert secret not in repr(config)
    assert secret not in repr(config.profiles[0])
    assert secret not in str(config.safe_dump())
    assert config.safe_dump()["profiles"][0]["credential"] == {"env": "<redacted>"}


def test_errors_have_stable_base_type() -> None:
    assert issubclass(ConfigurationError, RegistryError)
