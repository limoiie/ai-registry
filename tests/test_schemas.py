from collections import UserDict
from datetime import date
from typing import Any, cast

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


def test_provider_accepts_nested_sdk_type_settings() -> None:
    provider = Provider.model_validate(
        {
            "id": "anthropic-provider",
            "name": "Anthropic",
            "settings": {
                "sdk_type": "anthropic",
                "proxy_url": {"placeholder": "https://example.test"},
                "show_model_fetcher": True,
            },
        }
    )

    assert provider.sdk_type is SDKType.ANTHROPIC
    assert provider.settings["show_model_fetcher"] is True


def test_identifiers_are_constrained() -> None:
    with pytest.raises(ValidationError):
        Provider(id="bad id", name="Invalid")

    with pytest.raises(ValidationError):
        ModelCard(id="", type=ModelType.CHAT)


def test_model_ids_allow_catalog_native_separators() -> None:
    catalog_ids = ["bge-large-zh:latest", "Qwen/Qwen3-32B"]

    for model_id in catalog_ids:
        assert ModelCard(id=model_id, type=ModelType.CHAT).id == model_id

    profile = Profile(
        id="catalog-profile",
        provider_id="provider",
        enabled_models=catalog_ids,
    )
    assert profile.enabled_models == catalog_ids
    assert (
        Deployment(profile_id="catalog-profile", model_id=catalog_ids[1]).model_id
        == catalog_ids[1]
    )


def test_logical_ids_retain_strict_constraints() -> None:
    with pytest.raises(ValidationError):
        Provider(id="provider/name", name="Provider")

    with pytest.raises(ValidationError):
        Profile(id="profile:name", provider_id="provider")

    with pytest.raises(ValidationError):
        Alias(
            id="alias/name",
            deployments=[Deployment(profile_id="profile", model_id="model")],
        )


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
    assert profile.credential is not None
    assert profile.credential.env == "AI_API_KEY"


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:password@example.test/v1",
        "https://gateway.example.test/v1?api-key=query-secret",
        "https://gateway.example.test/v1?access_token=query-secret",
    ],
)
def test_profile_rejects_credential_bearing_endpoints_without_echoing_secrets(
    endpoint: str,
) -> None:
    with pytest.raises(ValidationError) as caught:
        Profile(id="primary", provider_id="provider", endpoint=endpoint)

    rendered = " ".join(
        (str(caught.value), repr(caught.value), str(caught.value.errors()))
    )
    assert "password" not in rendered
    assert "query-secret" not in rendered


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://gateway.example.test/v1?accessToken=query-secret",
        "https://gateway.example.test/v1?clientToken=query-secret",
        "https://gateway.example.test/v1?authorizationHeader=query-secret",
    ],
)
def test_profile_rejects_camel_case_credential_query_keys(endpoint: str) -> None:
    with pytest.raises(ValidationError, match="credential-bearing"):
        Profile(id="primary", provider_id="provider", endpoint=endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://gateway.example.test/v1#access_token=fragment-secret",
        "https://gateway.example.test/v1#clientToken=fragment-secret",
    ],
)
def test_profile_rejects_credential_bearing_fragments_without_echoing_secrets(
    endpoint: str,
) -> None:
    with pytest.raises(ValidationError, match="credential-bearing") as caught:
        Profile(id="primary", provider_id="provider", endpoint=endpoint)

    assert "fragment-secret" not in str(caught.value)


def test_profile_rejects_empty_query_key_with_clean_validation_error() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        Profile(
            id="primary",
            provider_id="provider",
            endpoint="https://gateway.example.test/v1?=query-value",
        )


def test_provider_rejects_credential_bearing_default_endpoint() -> None:
    with pytest.raises(ValidationError, match="credential-bearing"):
        Provider(
            id="provider",
            name="Provider",
            default_base_url="https://gateway.example.test/v1?token=secret",
        )


def test_secret_ref_credentials_are_supported() -> None:
    credential = CredentialRef(secret_ref="vault://prod/ai/key")

    assert credential.secret_ref == "vault://prod/ai/key"


def test_credentials_require_exactly_one_reference_and_reject_literal_keys() -> None:
    with pytest.raises(ValidationError):
        CredentialRef(env="KEY", secret_ref="vault://key")

    with pytest.raises(ValidationError):
        CredentialRef(api_key="literal-api-key")

    with pytest.raises(ValidationError):
        CredentialRef(env="")

    with pytest.raises(ValidationError):
        CredentialRef(secret_ref="")


def test_invalid_credential_errors_do_not_expose_supplied_values() -> None:
    env_value = "PRIVATE_ENV_NAME"
    secret_ref_value = "vault://private/credential"
    literal_value = "private-literal-api-key"

    with pytest.raises(ValidationError) as conflicting_error:
        CredentialRef(env=env_value, secret_ref=secret_ref_value)
    assert env_value not in str(conflicting_error.value)
    assert secret_ref_value not in str(conflicting_error.value)
    for error in conflicting_error.value.errors():
        assert env_value not in repr(error.get("input"))
        assert secret_ref_value not in repr(error.get("input"))

    with pytest.raises(ValidationError) as literal_error:
        CredentialRef(api_key=literal_value)
    assert literal_value not in str(literal_error.value)
    for error in literal_error.value.errors():
        assert literal_value not in repr(error.get("input"))

    with pytest.raises(ValidationError) as nested_error:
        Profile.model_validate(
            {
                "id": "primary",
                "provider_id": "provider",
                "credential": {"env": env_value, "secret_ref": secret_ref_value},
            }
        )
    assert env_value not in str(nested_error.value)
    assert secret_ref_value not in str(nested_error.value)
    for error in nested_error.value.errors():
        assert env_value not in repr(error.get("input"))
        assert secret_ref_value not in repr(error.get("input"))


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


def test_aggregate_rejects_duplicate_profile_and_alias_ids() -> None:
    with pytest.raises(ConfigurationError, match="duplicate profile id"):
        RegistryConfig(
            profiles=[
                Profile(id="profile", provider_id="provider"),
                Profile(id="profile", provider_id="provider"),
            ]
        )

    deployment = Deployment(profile_id="profile", model_id="model")
    with pytest.raises(ConfigurationError, match="duplicate alias id"):
        RegistryConfig(
            aliases=[
                Alias(id="alias", deployments=[deployment]),
                Alias(id="alias", deployments=[deployment]),
            ]
        )


def test_aggregate_rejects_duplicate_model_ids_within_provider() -> None:
    provider = Provider(
        id="provider",
        name="Provider",
        model_cards=[
            ModelCard(id="chat-model", type=ModelType.CHAT),
            ModelCard(id="chat-model", type=ModelType.CHAT),
        ],
    )

    with pytest.raises(ConfigurationError, match="duplicate model id"):
        RegistryConfig(providers=[provider])


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
    assert secret not in str(config)
    assert secret not in str(config.model_dump())
    assert secret not in config.model_dump_json()
    assert secret not in str(config.safe_dump())
    assert config.safe_dump()["profiles"][0]["credential"] == {"env": "<redacted>"}
    assert config._raw_dump()["profiles"][0]["credential"]["env"] == secret


def test_nested_sensitive_metadata_is_redacted_across_schema_serialization() -> None:
    config = RegistryConfig(
        profiles=[
            Profile(
                id="primary",
                provider_id="provider",
                metadata={
                    "nested": {
                        "password": "password-value",
                        "secret": "secret-value",
                        "authorization": "authorization-value",
                        "accessToken": "token-value",
                        "tuple_data": ({"password": "tuple-secret"},),
                        "set_data": {
                            ("accessToken", "set-secret"),
                            ("ordinary", "value"),
                        },
                        "model_token_count": 42,
                    }
                },
            )
        ]
    )

    for rendered in (repr(config), str(config.model_dump()), config.model_dump_json()):
        assert "password-value" not in rendered
        assert "secret-value" not in rendered
        assert "authorization-value" not in rendered
        assert "token-value" not in rendered
        assert "tuple-secret" not in rendered
        assert "set-secret" not in rendered
    assert "'model_token_count': 42" in str(config.model_dump())
    assert config.model_dump()["profiles"][0]["metadata"]["nested"]["password"] == (
        "<redacted>"
    )


def test_userdict_metadata_is_recursively_redacted() -> None:
    config = RegistryConfig(
        profiles=[
            Profile(
                id="primary",
                provider_id="provider",
                metadata=cast(
                    Any,
                    UserDict(
                        {
                            "nested": UserDict(
                                {"password": "userdict-secret", "safe": "value"}
                            )
                        }
                    ),
                ),
            )
        ]
    )

    for rendered in (repr(config), str(config.model_dump()), config.model_dump_json()):
        assert "userdict-secret" not in rendered
    assert "value" in str(config.model_dump())


def test_errors_have_stable_base_type() -> None:
    assert issubclass(ConfigurationError, RegistryError)
