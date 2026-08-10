"""Transient resolution of credential references."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from ai_registry.errors import SecretConfigurationError
from ai_registry.schemas import CredentialRef


class SecretResolutionError(SecretConfigurationError):
    """Raised when a credential reference cannot be resolved safely."""


@runtime_checkable
class SecretResolver(Protocol):
    """Application-provided boundary for external secret stores."""

    def resolve(self, reference: str) -> str:
        """Resolve a reference to a transient secret value."""


class EnvironmentSecretResolver:
    """Resolve references as names in the process environment."""

    def resolve(self, reference: str) -> str:
        value = os.environ.get(reference)
        if value is None:
            raise SecretResolutionError(
                f"environment variable {reference!r} is not set"
            )
        if value == "":
            raise SecretResolutionError(
                f"environment variable {reference!r} is empty; set a non-empty value"
            )
        return value


def resolve_credential(
    reference: object,
    resolver: SecretResolver | None = None,
) -> str:
    """Resolve one credential reference without retaining the resolved value."""
    if not isinstance(reference, CredentialRef):
        if isinstance(reference, Mapping):
            kind = next(iter(reference), "unknown")
            raise SecretResolutionError(f"unsupported credential reference: {kind}")
        raise SecretResolutionError("unsupported credential reference")

    if reference.env is not None:
        return EnvironmentSecretResolver().resolve(reference.env)

    if reference.secret_ref is not None:
        if resolver is None:
            raise SecretResolutionError("no resolver configured for secret reference")
        try:
            value = resolver.resolve(reference.secret_ref)
        except Exception:
            raise SecretResolutionError("failed to resolve secret reference") from None
        if not isinstance(value, str):
            raise SecretResolutionError("secret resolver returned an invalid value")
        return value

    raise SecretResolutionError("unsupported credential reference")
