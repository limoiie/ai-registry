import pytest

from ai_registry.errors import RegistryError
from ai_registry.schemas import CredentialRef
from ai_registry.secrets import (
    EnvironmentSecretResolver,
    SecretResolutionError,
    SecretResolver,
    resolve_credential,
)


def test_environment_resolver_returns_value_for_named_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_REGISTRY_TEST_KEY", "resolved-value")

    assert (
        EnvironmentSecretResolver().resolve("AI_REGISTRY_TEST_KEY") == "resolved-value"
    )


def test_missing_environment_variable_raises_safe_error() -> None:
    reference = "AI_REGISTRY_MISSING_KEY"

    with pytest.raises(SecretResolutionError) as error:
        EnvironmentSecretResolver().resolve(reference)

    assert reference in str(error.value)
    assert "resolved-value" not in str(error.value)
    assert isinstance(error.value, RegistryError)


def test_dispatch_resolves_environment_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_REGISTRY_DISPATCH_KEY", "environment-value")

    assert (
        resolve_credential(CredentialRef(env="AI_REGISTRY_DISPATCH_KEY"))
        == "environment-value"
    )


def test_dispatch_calls_custom_resolver_for_secret_reference() -> None:
    class CustomResolver:
        def __init__(self) -> None:
            self.references: list[str] = []

        def resolve(self, reference: str) -> str:
            self.references.append(reference)
            return "custom-value"

    resolver = CustomResolver()
    reference = "vault://production/ai/key"

    assert (
        resolve_credential(CredentialRef(secret_ref=reference), resolver)
        == "custom-value"
    )
    assert resolver.references == [reference]
    assert isinstance(resolver, SecretResolver)


def test_unsupported_reference_is_rejected_without_resolving() -> None:
    with pytest.raises(SecretResolutionError, match="unsupported"):
        resolve_credential({"file": "/tmp/secret"})


def test_custom_resolver_errors_do_not_expose_resolved_value() -> None:
    secret = "sensitive-resolved-value"

    class FailingResolver:
        def resolve(self, reference: str) -> str:
            raise RuntimeError(f"backend returned {secret} for {reference}")

    with pytest.raises(SecretResolutionError) as error:
        resolve_credential(
            CredentialRef(secret_ref="vault://production/ai/key"), FailingResolver()
        )

    assert secret not in str(error.value)
