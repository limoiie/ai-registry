from __future__ import annotations

import pytest

from ai_registry import RegistryError
from ai_registry.routing import DeploymentTarget
from ai_registry.schemas import ModelCard, ModelType
from ai_registry.secrets import SecretResolutionError
from ai_registry.testing import (
    FakeSecretResolver,
    ManualHealthStore,
    build_registry,
    constant_secret_resolver,
    deterministic_router,
)


def test_build_registry_resolves_a_single_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_API_KEY", "sk-test")
    registry = build_registry({"chat-default": ["test-account/test-model"]})

    resolution = registry.resolve("chat-default")

    assert resolution.account_id == "test-account"
    assert resolution.model_id == "test-model"
    assert resolution.endpoint == "https://provider.test/v1"
    assert resolution.resolve_credential() == "sk-test"


def test_build_registry_accepts_multiple_accounts_and_model_cards() -> None:
    registry = build_registry(
        {"chat-default": ["primary/big", "backup/small"]},
        models=[
            ModelCard(id="big", type=ModelType.CHAT, context_window_tokens=200_000),
            "small",
        ],
        accounts=["primary", "backup"],
        router=deterministic_router(),
    )

    assert [entry.model_id for entry in registry.list_models()] == ["big", "small"]
    assert [item.account_id for item in registry.candidates("chat-default")] == [
        "primary",
        "backup",
    ]


def test_build_registry_rejects_a_deployment_without_a_model() -> None:
    with pytest.raises(RegistryError, match=r"account-id/model-id"):
        build_registry({"chat-default": ["test-account"]})


def test_build_registry_requires_at_least_one_model() -> None:
    with pytest.raises(ValueError, match=r"at least one model"):
        build_registry(models=[])


def test_fake_secret_resolver_records_requests_and_resolves_lazily() -> None:
    resolver = FakeSecretResolver({"vault/key": "sk-fake"})
    registry = build_registry(
        {"chat-default": ["test-account/test-model"]},
        credential="secret_ref:vault/key",
        secret_resolver=resolver,
    )

    resolution = registry.resolve("chat-default")
    assert resolver.requested == []

    assert resolution.resolve_credential() == "sk-fake"
    assert resolver.requested == ["vault/key"]


def test_fake_secret_resolver_reports_unknown_references() -> None:
    resolver = FakeSecretResolver()
    registry = build_registry(
        {"chat-default": ["test-account/test-model"]},
        credential="secret_ref:missing",
        secret_resolver=resolver,
    )

    with pytest.raises(SecretResolutionError):
        registry.resolve("chat-default").resolve_credential()


def test_constant_secret_resolver_answers_every_reference() -> None:
    registry = build_registry(
        {"chat-default": ["test-account/test-model"]},
        credential="secret_ref:anything",
        secret_resolver=constant_secret_resolver("sk-constant"),
    )

    assert registry.resolve("chat-default").resolve_credential() == "sk-constant"


def test_manual_health_store_controls_selection_and_records_outcomes() -> None:
    store = ManualHealthStore()
    registry = build_registry(
        {"chat-default": ["primary/test-model", "backup/test-model"]},
        accounts=["primary", "backup"],
        router=deterministic_router(health_store=store),
    )

    first = registry.resolve("chat-default")
    assert first.account_id == "primary"

    registry.record_failure(first)
    assert store.failures == [DeploymentTarget("primary", "test-model")]
    assert registry.resolve("chat-default").account_id == "backup"

    registry.record_success(first)
    assert registry.resolve("chat-default").account_id == "primary"


def test_manual_health_store_can_start_with_targets_down() -> None:
    store = ManualHealthStore([DeploymentTarget("primary", "test-model")])
    registry = build_registry(
        {"chat-default": ["primary/test-model", "backup/test-model"]},
        accounts=["primary", "backup"],
        router=deterministic_router(health_store=store),
    )

    assert registry.resolve("chat-default").account_id == "backup"


def test_deterministic_router_rejects_out_of_range_picks() -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\)"):
        deterministic_router(pick=1.0)
