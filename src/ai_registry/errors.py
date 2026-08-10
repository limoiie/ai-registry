"""Stable exception types for the registry core."""


class RegistryError(Exception):
    """Base class for all public registry errors."""


class ConfigurationError(RegistryError):
    """Raised when registry configuration is invalid."""


class SecretConfigurationError(ConfigurationError):
    """Raised when a credential is not a safe reference."""
