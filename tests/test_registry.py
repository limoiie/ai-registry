from collections import UserList, deque
from pathlib import Path
from typing import cast

import pytest

from ai_registry import Registry
from ai_registry.errors import ConfigurationError, RegistryError
from ai_registry.routing import DeploymentHealthStore, DeploymentRouter
from ai_registry.schemas import (
    Account,
    Alias,
    CredentialRef,
    Deployment,
    ModelCapabilities,
    ModelCard,
    ModelType,
    Provider,
    RegistryConfig,
    RoutingMetadata,
    SDKType,
)
from ai_registry.secrets import SecretResolver
from ai_registry.testing import build_registry, constant_secret_resolver


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


def account() -> Account:
    return Account(
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
        accounts=[account()],
        aliases=[
            Alias(
                id="fast",
                deployments=[Deployment(account_id="primary", model_id="chat")],
            )
        ],
    )

    result = registry.resolve("fast")

    assert result.provider.id == "openai"
    assert result.model.id == "chat"
    assert result.account_id == "primary"
    assert result.deployment_id == "fast"
    assert result.endpoint == "https://profile.example.test"
    assert result.endpoint_metadata == {"region": "us"}


def test_from_data_revalidates_model_instances_with_updated_endpoints() -> None:
    invalid_account = account().model_copy(
        update={"endpoint": "https://gateway.example.test/v1#access_token=leaked"}
    )

    with pytest.raises(ConfigurationError) as caught:
        Registry.from_data(providers=[provider()], accounts=[invalid_account])

    assert "leaked" not in str(caught.value)


def test_from_data_rejects_conflicting_provider_sdk_type_mappings() -> None:
    with pytest.raises(ConfigurationError, match=r"conflicting sdk_type"):
        Registry.from_data(
            providers=[
                {
                    "id": "openai",
                    "name": "OpenAI",
                    "sdk_type": "anthropic",
                    "settings": {"sdk_type": "openai"},
                }
            ],
            accounts=[],
        )


def test_registry_constructor_revalidates_smuggled_endpoint() -> None:
    smuggled = RegistryConfig(
        providers=[provider()],
        accounts=[
            account().model_copy(
                update={"endpoint": "https://g.example.test/v1?api_key=LEAK"}
            )
        ],
    )

    with pytest.raises(ConfigurationError) as caught:
        Registry(smuggled, None)

    assert "LEAK" not in str(caught.value)


def test_registry_constructor_revalidates_conflicting_sdk_types() -> None:
    smuggled = provider().model_copy(
        update={"sdk_type": SDKType.ANTHROPIC, "settings": {"sdk_type": "openai"}}
    )

    with pytest.raises(ConfigurationError, match=r"conflicting sdk_type"):
        Registry(RegistryConfig(providers=[smuggled], accounts=[]), None)


def test_resolution_repr_redacts_credential_family_keys() -> None:
    registry = Registry.from_data(
        providers=[provider()],
        accounts=[
            account().model_copy(
                update={
                    "metadata": {
                        "private_key": "pk-secret",
                        "auth_key": "ak-secret",
                        "session_id": "sid-secret",
                        "sas_token": "st-secret",
                        "security_token": "sect-secret",
                        "device_token": "dt-secret",
                        "user_token": "ut-secret",
                        "X-Amz-Signature": "azsig-secret",
                        "x-functions-key": "fk-secret",
                        "openai_key": "ok-secret",
                        "aws_access_key_id": "aws-secret",
                        "connection_string": "conn-secret",
                        "client_assertion": "assert-secret",
                        "primary_key": "pk-secret",
                        "storage_account_key": "storage-secret",
                        "oauth_token": "oauth-secret",
                        "jwt": "jwt-secret",
                        "bearer": "bearer-secret",
                        "client_id": "client-ok",
                        "username": "user-ok",
                        "model_token_count": 7,
                    }
                }
            )
        ],
    )

    result = registry.resolve("primary/chat")
    rendered = f"{result!r} {result!s}"

    for value in (
        "pk-secret",
        "ak-secret",
        "sid-secret",
        "st-secret",
        "sect-secret",
        "dt-secret",
        "ut-secret",
        "azsig-secret",
        "fk-secret",
        "ok-secret",
        "aws-secret",
        "conn-secret",
        "assert-secret",
        "storage-secret",
        "oauth-secret",
        "jwt-secret",
        "bearer-secret",
    ):
        assert value not in rendered
    assert "client-ok" in rendered
    assert "user-ok" in rendered
    assert "'model_token_count': 7" in rendered


def test_alias_resolution_uses_injected_router_and_health_recovery() -> None:
    alias = Alias(
        id="fast",
        deployments=[
            Deployment(account_id="primary", model_id="chat"),
            Deployment(account_id="backup", model_id="other"),
        ],
    )
    health = DeploymentHealthStore()
    router = DeploymentRouter(health, random_source=lambda: 0.0)
    registry = Registry.from_data(
        providers=[provider()],
        accounts=[
            account(),
            Account(id="backup", provider_id="openai", enabled_models=["other"]),
        ],
        aliases=[alias],
        router=router,
    )

    primary = registry.resolve("fast")
    assert primary.account_id == "primary"

    registry.record_failure(primary)
    fallback = registry.resolve("fast")
    assert fallback.account_id == "backup"

    registry.record_success(primary)
    assert registry.resolve("fast").account_id == "primary"

    assert health.cooldown_remaining(primary.target) == 0.0


def test_registry_isolated_from_mutations_to_input_configuration() -> None:
    source_provider = provider()
    source_account = account()
    source_provider.model_cards[0].metadata["limits"] = {"regions": ["us"]}
    source_account.metadata["limits"] = {"regions": ["us"]}
    source_alias = Alias(
        id="fast",
        deployments=[Deployment(account_id="primary", model_id="chat")],
    )
    registry = Registry.from_data(
        providers=[source_provider],
        accounts=[source_account],
        aliases=[source_alias],
    )

    source_provider.model_cards[0].id = "changed"
    source_account.enabled_models.clear()
    source_alias.deployments[0].model_id = "other"

    result = registry.resolve("fast")

    assert result.model_id == "chat"
    assert result.account_id == "primary"


def test_resolution_isolated_from_nested_result_mutations() -> None:
    source_provider = provider()
    source_provider.model_cards[0].metadata["limits"] = {"regions": ["us"]}
    source_account = account()
    source_account.metadata["limits"] = {"regions": ["us"]}
    registry = Registry.from_data(
        providers=[source_provider],
        accounts=[source_account],
        aliases=[
            Alias(
                id="fast",
                deployments=[Deployment(account_id="primary", model_id="chat")],
            )
        ],
    )

    result = registry.resolve("fast")
    result.provider.model_cards[0].metadata["limits"]["regions"].append("eu")
    result.model.metadata["limits"]["regions"].append("ap")
    result.account.metadata["limits"]["regions"].append("ca")
    result.endpoint_metadata["limits"]["regions"].append("au")
    result.account.endpoint = "https://mutated.example.test"

    fresh = registry.resolve("fast")

    assert fresh.model.metadata["limits"] == {"regions": ["us"]}
    assert fresh.account.metadata["limits"] == {"regions": ["us"]}
    assert fresh.endpoint_metadata == {"region": "us", "limits": {"regions": ["us"]}}
    assert fresh.endpoint == "https://profile.example.test"


def test_resolution_repr_redacts_nested_sensitive_metadata_and_resolver() -> None:
    registry = Registry.from_data(
        providers=[provider()],
        accounts=[
            account().model_copy(
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
                            "tuple_pairs": (
                                ("api_key", "TUPLE_LEAK"),
                                ("ordinary", "tuple-value"),
                            ),
                            "set_pairs": {
                                ("token", "SET_LEAK"),
                                ("ordinary", "set-value"),
                            },
                            "frozenset_pairs": frozenset(
                                {
                                    ("authorization", "FROZEN_LEAK"),
                                    ("ordinary", "frozenset-value"),
                                }
                            ),
                            "list_container": UserList(
                                [{"password": "USERLIST_LEAK"}, "list-ok"]
                            ),
                            "deque_container": deque(
                                [{"token": "DEQUE_LEAK"}, "deque-ok"]
                            ),
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
    assert "TUPLE_LEAK" not in rendered
    assert "SET_LEAK" not in rendered
    assert "FROZEN_LEAK" not in rendered
    assert "USERLIST_LEAK" not in rendered
    assert "DEQUE_LEAK" not in rendered
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
    assert "tuple-value" in rendered
    assert "set-value" in rendered
    assert "frozenset-value" in rendered
    assert "list-ok" in rendered
    assert "deque-ok" in rendered
    assert "'model_token_count': 42" in rendered


def test_resolution_repr_preserves_valid_custom_endpoint_without_credentials() -> None:
    registry = Registry.from_data(
        providers=[provider()],
        accounts=[
            account().model_copy(
                update={"endpoint": "https://gateway.example.test/v1?api-version=1"}
            )
        ],
    )

    result = registry.resolve("primary/chat")

    assert result.endpoint == "https://gateway.example.test/v1?api-version=1"
    assert "gateway.example.test" in repr(result)
    assert "api-version=1" in str(result)


def test_alias_wins_over_direct_account_model_reference() -> None:
    registry = Registry.from_data(
        providers=[provider()],
        accounts=[
            Account(
                id="primary",
                provider_id="openai",
                enabled_models=["chat", "other"],
            )
        ],
        aliases=[
            Alias(
                id="primary",
                deployments=[Deployment(account_id="primary", model_id="other")],
            )
        ],
    )

    assert registry.resolve("primary").model.id == "other"


def test_disabled_account_is_not_resolvable_directly() -> None:
    registry = Registry.from_data(
        providers=[provider()],
        accounts=[account().model_copy(update={"enabled": False})],
    )

    with pytest.raises(RegistryError, match=r"account 'primary' is disabled"):
        registry.resolve("primary/chat")


def test_disabled_alias_candidates_are_excluded_from_routing() -> None:
    registry = Registry.from_data(
        providers=[provider()],
        accounts=[
            account().model_copy(update={"enabled": False}),
            Account(id="backup", provider_id="openai", enabled_models=["other"]),
        ],
        aliases=[
            Alias(
                id="fast",
                deployments=[
                    Deployment(account_id="primary", model_id="chat"),
                    Deployment(account_id="backup", model_id="other"),
                ],
            )
        ],
    )

    assert registry.resolve("fast").account_id == "backup"


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ("missing", "unknown alias or model reference"),
        ("unknown/chat", "unknown account"),
        ("primary/other", "model is not enabled by account 'primary'"),
    ],
)
def test_resolution_errors_are_descriptive_and_safe(
    reference: str, message: str
) -> None:
    registry = Registry.from_data(providers=[provider()], accounts=[account()])

    with pytest.raises(RegistryError, match=message):
        registry.resolve(reference)


@pytest.mark.parametrize(
    ("reference", "diagnostic"),
    [
        (
            "sk-live-secret-value",
            "unknown alias or model reference; use an alias or 'account/model'",
        ),
        (
            "sk-live-secret/chat",
            "unknown account; configure the account or use an alias",
        ),
    ],
)
def test_unknown_reference_errors_never_echo_caller_input(
    reference: str, diagnostic: str
) -> None:
    registry = Registry.from_data(providers=[provider()], accounts=[account()])

    with pytest.raises(RegistryError) as caught:
        registry.resolve(reference)

    error = caught.value
    for rendered in (str(error), repr(error), str(error.args), str(error.__dict__)):
        assert reference not in rendered
        assert "sk-live-secret" not in rendered
    assert diagnostic in str(error)


def test_aggregate_validation_reports_invalid_alias_deployment() -> None:
    with pytest.raises(ConfigurationError, match=r"alias 'fast'.*unknown model"):
        Registry.from_data(
            providers=[provider()],
            accounts=[account()],
            aliases=[
                Alias(
                    id="fast",
                    deployments=[Deployment(account_id="primary", model_id="missing")],
                )
            ],
        )


def test_aggregate_validation_reports_unknown_provider_and_model() -> None:
    with pytest.raises(
        ConfigurationError, match=r"account 'orphan'.*provider 'missing'"
    ):
        Registry.from_data(
            providers=[provider()],
            accounts=[Account(id="orphan", provider_id="missing")],
        )

    with pytest.raises(ConfigurationError, match=r"account 'primary'.*unknown model"):
        Registry.from_data(
            providers=[provider()],
            accounts=[
                Account(
                    id="primary",
                    provider_id="openai",
                    enabled_models=["missing"],
                )
            ],
        )


def test_aggregate_validation_reports_unknown_endpoint_ref() -> None:
    with pytest.raises(
        ConfigurationError, match=r"account 'orphan'.*unknown endpoint.*'bogus'"
    ):
        Registry.from_data(
            providers=[
                Provider.model_validate(
                    {
                        "id": "openai",
                        "name": "OpenAI",
                        "endpoints": {"chat": {"sdk_type": "openai"}},
                    }
                )
            ],
            accounts=[Account(id="orphan", provider_id="openai", endpoint_ref="bogus")],
        )


def test_validation_redacts_untrusted_model_id() -> None:
    secret_like_model_id = "sk-live-secret/model"

    with pytest.raises(ConfigurationError) as caught:
        Registry.from_data(
            providers=[provider()],
            accounts=[
                Account(
                    id="primary",
                    provider_id="openai",
                    enabled_models=[secret_like_model_id],
                )
            ],
        )

    error = caught.value
    for rendered in (str(error), repr(error), str(error.args), str(error.__dict__)):
        assert secret_like_model_id not in rendered
    assert "account 'primary' enables unknown model" in str(error)
    assert "add the model to provider 'openai'" in str(error)


def test_from_data_preserves_context_for_malformed_normalized_input() -> None:
    with pytest.raises(
        ConfigurationError,
        match=r"provider 'openai'.*index 0.*type.*valid model type",
    ):
        Registry.from_data(
            providers=[
                {
                    "id": "openai",
                    "name": "OpenAI",
                    "model_cards": [{"id": "chat", "type": "invalid"}],
                }
            ],
            accounts=[],
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
            accounts=[],
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
        match=r"alias 'fast'.*index 0.*model_id.*define a deployment model",
    ):
        Registry.from_data(
            providers=[provider()],
            accounts=[account()],
            aliases=[
                {
                    "id": "fast",
                    "deployments": [{"account_id": "primary"}],
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
        providers=[provider()],
        accounts=[account()],
        secret_resolver=Resolver(),
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
    account_path = tmp_path / "accounts.yaml"
    account_path.write_text(
        "accounts:\n  - id: primary\n    provider_id: openai\n"
        "    enabled_models: [chat]\n",
        encoding="utf-8",
    )

    registry = Registry.from_files([provider_path], [account_path])

    assert registry.resolve("primary/chat").model.id == "chat"


def test_from_files_preserves_context_for_malformed_alias(tmp_path: Path) -> None:
    provider_path = tmp_path / "provider.yaml"
    provider_path.write_text(
        "id: openai\nname: OpenAI\nmodel_cards:\n  - id: chat\n    type: chat\n",
        encoding="utf-8",
    )
    account_path = tmp_path / "accounts.yaml"
    account_path.write_text(
        "accounts:\n  - id: primary\n    provider_id: openai\n"
        "    enabled_models: [chat]\n",
        encoding="utf-8",
    )
    alias_path = tmp_path / "aliases.yaml"
    alias_path.write_text(
        "aliases:\n  - id: fast\n    deployments:\n      - account_id: primary\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ConfigurationError,
        match=r"alias 'fast'.*index 0.*model_id.*define a deployment model",
    ):
        Registry.from_files([provider_path], [account_path], [alias_path])


def test_from_files_requires_aliases_list(tmp_path: Path) -> None:
    provider_path = tmp_path / "provider.yaml"
    provider_path.write_text("id: openai\nname: OpenAI\n", encoding="utf-8")
    account_path = tmp_path / "accounts.yaml"
    account_path.write_text(
        "accounts:\n  - id: primary\n    provider_id: openai\n",
        encoding="utf-8",
    )
    alias_path = tmp_path / "aliases.yaml"
    alias_path.write_text("version: 1\n", encoding="utf-8")

    with pytest.raises(
        ConfigurationError,
        match=r"Alias configuration .*must contain an 'aliases' list",
    ):
        Registry.from_files([provider_path], [account_path], [alias_path])


def catalog_registry() -> Registry:
    return Registry.from_data(
        providers=[
            Provider(
                id="openai",
                name="OpenAI",
                default_base_url="https://api.openai.com/v1",
                model_cards=[
                    ModelCard(
                        id="chat",
                        type=ModelType.CHAT,
                        context_window_tokens=128_000,
                        capabilities=ModelCapabilities(tools=True),
                    ),
                    ModelCard(
                        id="small",
                        type=ModelType.CHAT,
                        context_window_tokens=8_000,
                    ),
                    ModelCard(id="embed", type=ModelType.EMBEDDING),
                ],
            )
        ],
        accounts=[
            Account(id="primary", provider_id="openai", enabled_models=["chat"]),
            Account(
                id="retired",
                provider_id="openai",
                enabled_models=["small"],
                enabled=False,
            ),
        ],
    )


def test_list_models_filters_by_type_capability_and_context() -> None:
    registry = catalog_registry()

    # Providers are sorted by id; models keep their catalog order, which the
    # provider author controls and often uses to express preference.
    assert [entry.model_id for entry in registry.list_models()] == [
        "chat",
        "small",
        "embed",
    ]
    assert [
        entry.model_id for entry in registry.list_models(model_type=ModelType.EMBEDDING)
    ] == ["embed"]
    assert [
        entry.model_id for entry in registry.list_models(requires={"tools": True})
    ] == ["chat"]
    assert [
        entry.model_id for entry in registry.list_models(min_context_tokens=100_000)
    ] == ["chat"]


def test_list_models_enabled_only_ignores_disabled_accounts() -> None:
    registry = catalog_registry()

    assert [entry.model_id for entry in registry.list_models(enabled_only=True)] == [
        "chat"
    ]


def test_list_models_accepts_a_capabilities_object() -> None:
    registry = catalog_registry()

    entries = registry.list_models(requires=ModelCapabilities(tools=True))

    assert [entry.model_id for entry in entries] == ["chat"]


def test_list_models_rejects_an_unknown_capability() -> None:
    with pytest.raises(RegistryError, match=r"unknown capability"):
        catalog_registry().list_models(requires={"telepathy": True})


def test_list_models_returns_copies_that_cannot_corrupt_the_registry() -> None:
    registry = catalog_registry()

    registry.list_models()[0].model.metadata["injected"] = True

    assert registry.list_models()[0].model.metadata == {}


def test_registry_exposes_providers_accounts_and_aliases() -> None:
    registry = catalog_registry()

    assert [provider.id for provider in registry.list_providers()] == ["openai"]
    assert [account.id for account in registry.list_accounts()] == [
        "primary",
        "retired",
    ]
    assert registry.list_aliases() == []
    assert registry.get_provider("openai").name == "OpenAI"
    assert registry.get_account("primary").provider_id == "openai"


def test_registry_lookups_report_unknown_identifiers_safely() -> None:
    registry = catalog_registry()

    with pytest.raises(RegistryError, match=r"unknown provider"):
        registry.get_provider("nope")
    with pytest.raises(RegistryError, match=r"unknown account"):
        registry.get_account("nope")


def test_candidates_list_every_deployment_in_routing_order() -> None:
    registry = Registry.from_data(
        providers=[provider()],
        accounts=[
            account(),
            Account(id="backup", provider_id="openai", enabled_models=["other"]),
        ],
        aliases=[
            Alias(
                id="fast",
                deployments=[
                    Deployment(account_id="primary", model_id="chat"),
                    Deployment(
                        account_id="backup",
                        model_id="other",
                        routing=RoutingMetadata(priority=1),
                    ),
                ],
            )
        ],
    )

    assert [item.account_id for item in registry.candidates("fast")] == [
        "primary",
        "backup",
    ]


def test_candidates_return_the_direct_reference_for_a_non_alias() -> None:
    registry = Registry.from_data(providers=[provider()], accounts=[account()])

    candidates = registry.candidates("primary/chat")

    assert [item.model_id for item in candidates] == ["chat"]


def test_candidates_are_empty_when_every_deployment_is_unavailable() -> None:
    registry = Registry.from_data(
        providers=[provider()],
        accounts=[account()],
        aliases=[
            Alias(
                id="fast",
                deployments=[
                    Deployment(
                        account_id="primary",
                        model_id="chat",
                        routing=RoutingMetadata(enabled=False),
                    )
                ],
            )
        ],
    )

    assert registry.candidates("fast") == []


def test_otel_attributes_describe_the_resolution_without_secrets() -> None:
    registry = Registry.from_data(providers=[provider()], accounts=[account()])

    attributes = registry.resolve("primary/chat").otel_attributes()

    assert attributes == {
        "gen_ai.provider.name": "openai",
        "gen_ai.request.model": "chat",
        "gen_ai.operation.name": "chat",
        "ai_registry.deployment_id": "primary",
        "ai_registry.provider_id": "openai",
        "ai_registry.account_id": "primary",
    }


def test_otel_provider_name_falls_back_to_the_sdk_family() -> None:
    registry = Registry.from_data(
        providers=[
            Provider(
                id="internal-gateway",
                name="Internal gateway",
                sdk_type=SDKType.OPENAI,
                model_cards=[ModelCard(id="chat", type=ModelType.CHAT)],
            )
        ],
        accounts=[
            Account(
                id="primary", provider_id="internal-gateway", enabled_models=["chat"]
            )
        ],
    )

    attributes = registry.resolve("primary/chat").otel_attributes()

    assert attributes["gen_ai.provider.name"] == "openai"
    assert attributes["ai_registry.provider_id"] == "internal-gateway"


def test_otel_attributes_omit_the_operation_for_reranking_models() -> None:
    registry = Registry.from_data(
        providers=[
            Provider(
                id="openai",
                name="OpenAI",
                model_cards=[ModelCard(id="rerank", type=ModelType.RERANKING)],
            )
        ],
        accounts=[
            Account(id="primary", provider_id="openai", enabled_models=["rerank"])
        ],
    )

    attributes = registry.resolve("primary/rerank").otel_attributes()

    assert "gen_ai.operation.name" not in attributes


def test_resolution_exposes_selected_endpoint_and_mode() -> None:
    provider = Provider.model_validate(
        {
            "id": "deepseek",
            "name": "DeepSeek",
            "sdk_type": "anthropic",
            "default_base_url": "https://api.deepseek.com/anthropic",
            "endpoints": {
                "openai-chat": {
                    "sdk_type": "openai",
                    "base_url": "https://api.deepseek.com",
                },
                "openai-responses": {
                    "sdk_type": "openai",
                    "base_url": "https://api.deepseek.com",
                    "mode": "responses",
                },
                "anthropic": {
                    "sdk_type": "anthropic",
                    "base_url": "https://api.deepseek.com/anthropic",
                },
            },
            "model_cards": [
                {"id": "deepseek-v4-flash", "type": "chat"},
                {
                    "id": "deepseek-chat",
                    "type": "chat",
                    "endpoints": ["openai-chat", "anthropic"],
                },
            ],
        }
    )
    account = Account.model_validate(
        {
            "id": "a",
            "provider_id": "deepseek",
            "endpoint_ref": "openai-responses",
            "credential": "env:KEY",
            "enabled_models": ["deepseek-v4-flash"],
        }
    )
    registry = Registry.from_data(
        providers=[provider],
        accounts=[account],
        secret_resolver=constant_secret_resolver("sk"),
    )
    resolution = registry.resolve("a/deepseek-v4-flash")
    assert resolution.sdk_type.value == "openai"
    assert resolution.mode.value == "responses"
    assert resolution.endpoint == "https://api.deepseek.com"


def test_resolution_legacy_single_endpoint_defaults() -> None:
    registry = build_registry({"chat": ["test-account/test-model"]})
    resolution = registry.resolve("chat")
    assert resolution.sdk_type.value == "openai"
    assert resolution.mode.value == "chat"


def test_model_not_supported_by_endpoint_is_rejected() -> None:
    provider = Provider.model_validate(
        {
            "id": "deepseek",
            "name": "DeepSeek",
            "endpoints": {"responses": {"sdk_type": "openai", "mode": "responses"}},
            "model_cards": [{"id": "m", "type": "chat", "endpoints": ["chat"]}],
        }
    )
    account = Account.model_validate(
        {
            "id": "a",
            "provider_id": "deepseek",
            "endpoint_ref": "responses",
            "enabled_models": ["m"],
        }
    )
    registry = Registry.from_data(providers=[provider], accounts=[account])
    with pytest.raises(RegistryError):
        registry.resolve("a/m")
