"""Test doubles for applications that depend on the registry.

Everything here is public, supported API. Importing this module pulls in no
dependency beyond the core, so it is safe to use from a consumer's test suite
without installing any extra.

The credential helpers exist because literal keys are rejected by the schema on
purpose: a test that needs a concrete secret supplies a resolver rather than
weakening the configuration rules.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ai_registry.errors import RegistryError
from ai_registry.registry import Registry
from ai_registry.routing import DeploymentRouter, DeploymentTarget, HealthStore
from ai_registry.schemas import (
    Account,
    Alias,
    CredentialRef,
    Deployment,
    Model,
    ModelType,
    Provider,
    SDKType,
)
from ai_registry.secrets import SecretResolutionError, SecretResolver

__all__ = [
    "FakeSecretResolver",
    "ManualHealthStore",
    "build_registry",
    "constant_secret_resolver",
    "deterministic_router",
]


class FakeSecretResolver:
    """A :class:`~ai_registry.secrets.SecretResolver` backed by a dict.

    Records every requested reference in :attr:`requested`, so a test can assert
    that credentials are resolved lazily — that is, not at all until an adapter
    asks for one.
    """

    def __init__(self, secrets: Mapping[str, str] | None = None) -> None:
        self._secrets = dict(secrets or {})
        self.requested: list[str] = []

    def resolve(self, reference: str) -> str:
        self.requested.append(reference)
        try:
            return self._secrets[reference]
        except KeyError:
            raise SecretResolutionError(
                f"no fake secret registered for reference {reference!r}"
            ) from None


def constant_secret_resolver(value: str = "test-secret") -> SecretResolver:
    """Return a resolver that answers every reference with ``value``."""

    class _Constant:
        def resolve(self, reference: str) -> str:
            return value

    return _Constant()


class ManualHealthStore:
    """A :class:`~ai_registry.routing.HealthStore` with no clock.

    Availability is whatever the test last set. Use this when the point of the
    test is routing behavior rather than recovery timing; use
    :class:`~ai_registry.routing.DeploymentHealthStore` with an injected
    ``clock`` when the point is the cooldown itself.
    """

    def __init__(self, unavailable: Sequence[DeploymentTarget] = ()) -> None:
        self._unavailable = set(unavailable)
        self.successes: list[DeploymentTarget] = []
        self.failures: list[DeploymentTarget] = []

    def is_available(self, target: DeploymentTarget) -> bool:
        return target not in self._unavailable

    def record_success(self, target: DeploymentTarget) -> None:
        self.successes.append(target)
        self._unavailable.discard(target)

    def record_failure(self, target: DeploymentTarget) -> None:
        self.failures.append(target)
        self._unavailable.add(target)


def deterministic_router(
    *,
    pick: float = 0.0,
    health_store: HealthStore | None = None,
) -> DeploymentRouter:
    """Return a router whose weighted choice is reproducible.

    ``pick`` is the fixed value handed to the weighted-selection algorithm and
    must lie in ``[0, 1)``; ``0.0`` always selects the first candidate of the
    winning priority group.
    """
    if not 0 <= pick < 1:
        raise ValueError("pick must be in [0, 1)")
    return DeploymentRouter(health_store, random_source=lambda: pick)


def build_registry(
    aliases: Mapping[str, Sequence[str]] | None = None,
    *,
    provider_id: str = "test-provider",
    models: Sequence[str | Model] = ("test-model",),
    accounts: Sequence[str] = ("test-account",),
    model_type: ModelType | str = ModelType.CHAT,
    sdk_type: SDKType | str = SDKType.OPENAI,
    endpoint: str | None = "https://provider.test/v1",
    credential: Mapping[str, str] | str | None = "env:TEST_API_KEY",
    timeout_seconds: float | None = None,
    secret_resolver: SecretResolver | None = None,
    router: DeploymentRouter | None = None,
) -> Registry:
    """Build a small, valid registry for tests.

    ``aliases`` maps an alias id to the deployments behind it, each written as
    ``"account-id/model-id"``. Every account exposes every model, so aliases can
    reference any pair without further setup.

    >>> registry = build_registry({"chat-default": ["test-account/test-model"]})
    >>> registry.resolve("chat-default").model_id
    'test-model'
    """
    resolved_type = ModelType(model_type)
    built_models = [
        model if isinstance(model, Model) else Model(id=model, type=resolved_type)
        for model in models
    ]
    if not built_models:
        raise ValueError("build_registry requires at least one model")
    model_ids = [model.id for model in built_models]
    credential_ref = (
        None if credential is None else CredentialRef.model_validate(credential)
    )

    provider = Provider(
        id=provider_id,
        name=provider_id,
        sdk_type=SDKType(sdk_type),
        default_base_url=endpoint,
        models=built_models,
    )
    built_accounts = [
        Account(
            id=account_id,
            provider_id=provider_id,
            credential=credential_ref,
            enabled_models=model_ids,
            timeout_seconds=timeout_seconds,
        )
        for account_id in accounts
    ]
    built_aliases = [
        Alias(
            id=alias_id,
            deployments=[_deployment(reference, alias_id) for reference in references],
        )
        for alias_id, references in (aliases or {}).items()
    ]
    return Registry.from_data(
        providers=[provider],
        accounts=built_accounts,
        aliases=built_aliases,
        secret_resolver=secret_resolver,
        router=router,
    )


def _deployment(reference: str, alias_id: str) -> Deployment:
    account_id, separator, model_id = reference.partition("/")
    if not separator:
        raise RegistryError(
            f"alias '{alias_id}' deployment {reference!r} must be "
            "written as 'account-id/model-id'"
        )
    return Deployment(account_id=account_id, model_id=model_id)
