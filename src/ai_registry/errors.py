"""Stable exception types for the registry core.

Every exception raised by this package derives from :class:`RegistryError`, so
callers can catch one type at an integration boundary. Messages describe the
problem and its remedy, and never echo credentials or caller-supplied input that
could be secret-like.
"""


class RegistryError(Exception):
    """Base class for all public registry errors."""


class ConfigurationError(RegistryError):
    """Raised when registry configuration is invalid."""


class SecretConfigurationError(ConfigurationError):
    """Raised when a credential is not a safe reference."""


class AdapterError(RegistryError):
    """Base class for failures raised while building a framework client."""


class MissingDependencyError(AdapterError):
    """Raised when an optional extra required by an adapter is not installed."""

    def __init__(self, package: str, extra: str) -> None:
        super().__init__(
            f"{package!r} is required for this adapter; "
            f'install it with: pip install "ai-registry[{extra}]"'
        )
        self.package = package
        self.extra = extra


class UnsupportedProviderError(AdapterError):
    """Raised when an adapter cannot build a client for a provider's SDK type."""
