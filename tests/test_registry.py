from pathlib import Path
from typing import cast

import pytest

from ai_registry import Registry
from ai_registry.errors import ConfigurationError, RegistryError
from ai_registry.routing import DeploymentHealthStore, DeploymentRouter
from ai_registry.schemas import (
    Alias,
    CredentialRef,
    Deployment,
    ModelCard,
    ModelType,
    Profile,
    Provider,
)
from ai_registry.secrets import SecretResolver


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


def test_alias_resolution_uses_injected_router_and_health_recovery() -> None:
    alias = Alias(
        id="fast",
        deployments=[
            Deployment(profile_id="primary", model_id="chat"),
            Deployment(profile_id="backup", model_id="other"),
        ],
    )
    health = DeploymentHealthStore()
    router = DeploymentRouter(health, random_source=lambda: 0.0)
    registry = Registry.from_data(
        providers=[provider()],
        profiles=[
            profile(),
            Profile(id="backup", provider_id="openai", enabled_models=["other"]),
        ],
        aliases=[alias],
        router=router,
    )

    health.mark_failure("fast", 0)
    assert registry.resolve("fast").profile_id == "backup"
    health.mark_success("fast", 0)
    assert registry.resolve("fast").profile_id == "primary"


def test_registry_isolated_from_mutations_to_input_configuration() -> None:
    source_provider = provider()
    source_profile = profile()
    source_provider.model_cards[0].metadata["limits"] = {"regions": ["us"]}
    source_profile.metadata["limits"] = {"regions": ["us"]}
    source_alias = Alias(
        id="fast",
        deployments=[Deployment(profile_id="primary", model_id="chat")],
    )
    registry = Registry.from_data(
        providers=[source_provider], profiles=[source_profile], aliases=[source_alias]
    )

    source_provider.model_cards[0].id = "changed"
    source_profile.enabled_models.clear()
    source_alias.deployments[0].model_id = "other"

    result = registry.resolve("fast")

    assert result.model_id == "chat"
    assert result.profile_id == "primary"


def test_resolution_isolated_from_nested_result_mutations() -> None:
    source_provider = provider()
    source_provider.model_cards[0].metadata["limits"] = {"regions": ["us"]}
    source_profile = profile()
    source_profile.metadata["limits"] = {"regions": ["us"]}
    registry = Registry.from_data(
        providers=[source_provider],
        profiles=[source_profile],
        aliases=[
            Alias(
                id="fast",
                deployments=[Deployment(profile_id="primary", model_id="chat")],
            )
        ],
    )

    result = registry.resolve("fast")
    result.provider.model_cards[0].metadata["limits"]["regions"].append("eu")
    result.model.metadata["limits"]["regions"].append("ap")
    result.profile.metadata["limits"]["regions"].append("ca")
    result.endpoint_metadata["limits"]["regions"].append("au")
    result.profile.endpoint = "https://mutated.example.test"

    fresh = registry.resolve("fast")

    assert fresh.model.metadata["limits"] == {"regions": ["us"]}
    assert fresh.profile.metadata["limits"] == {"regions": ["us"]}
    assert fresh.endpoint_metadata == {"region": "us", "limits": {"regions": ["us"]}}
    assert fresh.endpoint == "https://profile.example.test"


def test_resolution_repr_redacts_nested_sensitive_metadata_and_resolver() -> None:
    registry = Registry.from_data(
        providers=[provider()],
        profiles=[
            profile().model_copy(
                update={
                    "metadata": {
                        "region": "us",
                        "api_key": "secret-key",
                        "nested": {
                            "api-key": "hyphen-key",
                            "x-api-key": "prefixed-key",
                            "apiKey": "camel-key",
                            "X-API-Key": "uppercase-key",
                            "access-token": "access-secret",
                            "authorization-header": "auth-secret",
                            "token": "secret-token",
                            "env": "environment-secret",
                            "model_token_count": 42,
                            "safe": "value",
                        },
                    }
                }
            )
        ],
        secret_resolver=cast(SecretResolver, object()),
    )

    result = registry.resolve("primary/chat")
    rendered = f"{result!r} {result!s}"

    assert "secret-key" not in rendered
    assert "secret-token" not in rendered
    assert "hyphen-key" not in rendered
    assert "prefixed-key" not in rendered
    assert "camel-key" not in rendered
    assert "uppercase-key" not in rendered
    assert "access-secret" not in rendered
    assert "auth-secret" not in rendered
    assert "environment-secret" not in rendered
    assert "_secret_resolver" not in rendered
    assert "'api_key': '<redacted>'" in rendered
    assert "'api-key': '<redacted>'" in rendered
    assert "'x-api-key': '<redacted>'" in rendered
    assert "'apiKey': '<redacted>'" in rendered
    assert "'X-API-Key': '<redacted>'" in rendered
    assert "'access-token': '<redacted>'" in rendered
    assert "'authorization-header': '<redacted>'" in rendered
    assert "'token': '<redacted>'" in rendered
    assert "'env': '<redacted>'" in rendered
    assert "'model_token_count': 42" in rendered


def test_resolution_repr_preserves_valid_custom_endpoint_without_credentials() -> None:
    registry = Registry.from_data(
        providers=[provider()],
        profiles=[
            profile().model_copy(
                update={"endpoint": "https://gateway.example.test/v1?api-version=1"}
            )
        ],
    )

    result = registry.resolve("primary/chat")

    assert result.endpoint == "https://gateway.example.test/v1?api-version=1"
    assert "gateway.example.test" in repr(result)
    assert "api-version=1" in str(result)


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


def test_disabled_profile_is_not_resolvable_directly() -> None:
    registry = Registry.from_data(
        providers=[provider()],
        profiles=[profile().model_copy(update={"enabled": False})],
    )

    with pytest.raises(RegistryError, match="profile 'primary' is disabled"):
        registry.resolve("primary/chat")


def test_disabled_alias_candidates_are_excluded_from_routing() -> None:
    registry = Registry.from_data(
        providers=[provider()],
        profiles=[
            profile().model_copy(update={"enabled": False}),
            Profile(id="backup", provider_id="openai", enabled_models=["other"]),
        ],
        aliases=[
            Alias(
                id="fast",
                deployments=[
                    Deployment(profile_id="primary", model_id="chat"),
                    Deployment(profile_id="backup", model_id="other"),
                ],
            )
        ],
    )

    assert registry.resolve("fast").profile_id == "backup"


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ("missing", "unknown alias or model reference"),
        ("unknown/chat", "unknown profile"),
        ("primary/other", "model is not enabled by profile 'primary'"),
    ],
)
def test_resolution_errors_are_descriptive_and_safe(
    reference: str, message: str
) -> None:
    registry = Registry.from_data(providers=[provider()], profiles=[profile()])

    with pytest.raises(RegistryError, match=message):
        registry.resolve(reference)


@pytest.mark.parametrize(
    ("reference", "diagnostic"),
    [
        (
            "sk-live-secret-value",
            "unknown alias or model reference; use an alias or 'profile/model'",
        ),
        (
            "sk-live-secret/chat",
            "unknown profile; configure the profile or use an alias",
        ),
    ],
)
def test_unknown_reference_errors_never_echo_caller_input(
    reference: str, diagnostic: str
) -> None:
    registry = Registry.from_data(providers=[provider()], profiles=[profile()])

    with pytest.raises(RegistryError) as caught:
        registry.resolve(reference)

    error = caught.value
    for rendered in (str(error), repr(error), str(error.args), str(error.__dict__)):
        assert reference not in rendered
        assert "sk-live-secret" not in rendered
    assert diagnostic in str(error)


def test_aggregate_validation_reports_invalid_alias_deployment() -> None:
    with pytest.raises(ConfigurationError, match="alias 'fast'.*unknown model"):
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

    with pytest.raises(ConfigurationError, match="profile 'primary'.*unknown model"):
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


def test_validation_redacts_untrusted_model_id() -> None:
    secret_like_model_id = "sk-live-secret/model"

    with pytest.raises(ConfigurationError) as caught:
        Registry.from_data(
            providers=[provider()],
            profiles=[
                Profile(
                    id="primary",
                    provider_id="openai",
                    enabled_models=[secret_like_model_id],
                )
            ],
        )

    error = caught.value
    for rendered in (str(error), repr(error), str(error.args), str(error.__dict__)):
        assert secret_like_model_id not in rendered
    assert "profile 'primary' enables unknown model" in str(error)
    assert "add the model to provider 'openai'" in str(error)


def test_from_data_preserves_context_for_malformed_normalized_input() -> None:
    with pytest.raises(
        ConfigurationError,
        match="provider 'openai'.*index 0.*type.*valid model type",
    ):
        Registry.from_data(
            providers=[
                {
                    "id": "openai",
                    "name": "OpenAI",
                    "model_cards": [{"id": "chat", "type": "invalid"}],
                }
            ],
            profiles=[],
        )


def test_validation_error_redacts_invalid_secret_like_identifier() -> None:
    secret_like_id = "sk-live-secret/value"

    with pytest.raises(ConfigurationError) as caught:
        Registry.from_data(
            providers=[
                {
                    "id": secret_like_id,
                    "name": "OpenAI",
                    "model_cards": [{"id": "chat", "type": "invalid"}],
                }
            ],
            profiles=[],
        )

    error = caught.value
    assert secret_like_id not in str(error)
    assert secret_like_id not in repr(error)
    assert secret_like_id not in str(error.args)
    assert secret_like_id not in str(error.__dict__)
    assert "provider at index 0" in str(error)
    assert "model_cards.0.type" in str(error)
    assert "use a valid model type" in str(error)


def test_from_data_preserves_context_for_malformed_alias() -> None:
    with pytest.raises(
        ConfigurationError,
        match="alias 'fast'.*index 0.*model_id.*define a deployment model",
    ):
        Registry.from_data(
            providers=[provider()],
            profiles=[profile()],
            aliases=[
                {
                    "id": "fast",
                    "deployments": [{"profile_id": "primary"}],
                }
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


def test_from_files_preserves_context_for_malformed_alias(tmp_path: Path) -> None:
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
    alias_path = tmp_path / "aliases.yaml"
    alias_path.write_text(
        "aliases:\n  - id: fast\n    deployments:\n      - profile_id: primary\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ConfigurationError,
        match="alias 'fast'.*index 0.*model_id.*define a deployment model",
    ):
        Registry.from_files([provider_path], [profile_path], [alias_path])


def test_from_files_requires_aliases_list(tmp_path: Path) -> None:
    provider_path = tmp_path / "provider.yaml"
    provider_path.write_text("id: openai\nname: OpenAI\n", encoding="utf-8")
    profile_path = tmp_path / "profiles.yaml"
    profile_path.write_text(
        "profiles:\n  - id: primary\n    provider_id: openai\n",
        encoding="utf-8",
    )
    alias_path = tmp_path / "aliases.yaml"
    alias_path.write_text("version: 1\n", encoding="utf-8")

    with pytest.raises(
        ConfigurationError,
        match="Alias configuration .*must contain a 'aliases' list",
    ):
        Registry.from_files([provider_path], [profile_path], [alias_path])
