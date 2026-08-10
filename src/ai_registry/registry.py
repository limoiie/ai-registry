"""Validated, framework-independent registry lookup."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ai_registry.config import (
    PathSource,
    load_document,
    load_profile_file,
    load_provider_files,
)
from ai_registry.errors import ConfigurationError, RegistryError
from ai_registry.schemas import (
    Alias,
    Deployment,
    ModelCard,
    Profile,
    Provider,
    RegistryConfig,
)
from ai_registry.secrets import SecretResolver, resolve_credential


@dataclass(frozen=True)
class Resolution:
    """Safe deployment information passed to an adapter."""

    provider: Provider
    model: ModelCard
    profile: Profile
    deployment_id: str
    endpoint: str | None
    endpoint_metadata: dict[str, Any]
    _secret_resolver: SecretResolver | None = None

    @property
    def model_id(self) -> str:
        return self.model.id

    @property
    def profile_id(self) -> str:
        return self.profile.id

    def resolve_credential(self) -> str | None:
        """Resolve the profile credential only when an adapter requests it."""
        if self.profile.credential is None:
            return None
        return resolve_credential(self.profile.credential, self._secret_resolver)


class Registry:
    """Immutable configuration index for aliases and explicit deployments."""

    def __init__(self, config: RegistryConfig, secret_resolver: SecretResolver | None):
        self._config = config.model_copy(deep=True)
        self._secret_resolver = secret_resolver
        self._providers = {provider.id: provider for provider in self._config.providers}
        self._profiles = {profile.id: profile for profile in self._config.profiles}
        self._aliases = {alias.id: alias for alias in self._config.aliases}
        self._validate_references()

    @classmethod
    def from_data(
        cls,
        *,
        providers: Sequence[Provider | Mapping[str, Any]],
        profiles: Sequence[Profile | Mapping[str, Any]],
        aliases: Sequence[Alias | Mapping[str, Any]] = (),
        secret_resolver: SecretResolver | None = None,
    ) -> Registry:
        """Build a registry from normalized objects or schema-compatible mappings."""
        config = RegistryConfig(
            providers=_models(Provider, providers, "provider"),
            profiles=_models(Profile, profiles, "profile"),
            aliases=_models(Alias, aliases, "alias"),
        )
        return cls(config, secret_resolver)

    @classmethod
    def from_files(
        cls,
        provider_files: Sequence[PathSource],
        profile_files: Sequence[PathSource],
        alias_files: Sequence[PathSource] = (),
        *,
        secret_resolver: SecretResolver | None = None,
    ) -> Registry:
        """Load provider, profile, and optional alias documents without secrets."""
        aliases: list[dict[str, Any]] = []
        for source in alias_files:
            document = load_document(source)
            if "aliases" not in document:
                raise ConfigurationError(
                    "Alias configuration must contain a 'aliases' list"
                )
            values = document["aliases"]
            if not isinstance(values, list):
                raise ConfigurationError(
                    "Alias configuration must contain an 'aliases' list"
                )
            for value in values:
                if not isinstance(value, dict):
                    raise ConfigurationError(
                        "Alias configuration contains an invalid alias"
                    )
                aliases.append(value)
        return cls.from_data(
            providers=load_provider_files(list(provider_files)),
            profiles=_load_profiles(profile_files),
            aliases=aliases,
            secret_resolver=secret_resolver,
        )

    def resolve(self, reference: str) -> Resolution:
        """Resolve an alias first, then an explicit ``profile-id/model-id``."""
        alias = self._aliases.get(reference)
        if alias is not None:
            deployment = alias.deployments[0]
            return self._resolution(deployment, alias.id)

        if "/" not in reference:
            raise RegistryError(
                "unknown alias or model reference; use an alias or 'profile/model'"
            )
        profile_id, model_id = reference.split("/", 1)
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise RegistryError(
                "unknown profile; configure the profile or use an alias"
            )
        self._validate_model_enabled(profile, model_id, include_model=False)
        return self._resolution(
            Deployment(profile_id=profile_id, model_id=model_id), profile_id
        )

    def _resolution(self, deployment: Any, deployment_id: str) -> Resolution:
        profile = self._profiles[deployment.profile_id]
        provider = self._providers[profile.provider_id]
        model = next(
            card for card in provider.model_cards if card.id == deployment.model_id
        )
        return Resolution(
            provider=provider,
            model=model,
            profile=profile,
            deployment_id=deployment_id,
            endpoint=profile.endpoint or provider.default_base_url,
            endpoint_metadata=dict(profile.metadata),
            _secret_resolver=self._secret_resolver,
        )

    def _validate_references(self) -> None:
        for profile in self._profiles.values():
            provider = self._providers.get(profile.provider_id)
            if provider is None:
                raise ConfigurationError(
                    f"profile '{profile.id}' references unknown provider "
                    f"'{profile.provider_id}'; configure the provider"
                )
            for model_id in profile.enabled_models:
                if not _find_model(provider, model_id):
                    raise ConfigurationError(
                        f"profile '{profile.id}' enables unknown model '{model_id}'; "
                        f"add the model to provider '{provider.id}'"
                    )
        for alias in self._aliases.values():
            for deployment in alias.deployments:
                alias_profile = self._profiles.get(deployment.profile_id)
                if alias_profile is None:
                    raise ConfigurationError(
                        f"alias '{alias.id}' references unknown profile "
                        f"'{deployment.profile_id}'; configure the profile"
                    )
                try:
                    self._validate_model_enabled(alias_profile, deployment.model_id)
                except RegistryError as error:
                    raise ConfigurationError(
                        f"alias '{alias.id}' deployment is invalid: {error}"
                    ) from None

    def _validate_model_enabled(
        self, profile: Profile, model_id: str, *, include_model: bool = True
    ) -> None:
        provider = self._providers[profile.provider_id]
        if not _find_model(provider, model_id):
            model_detail = f" '{model_id}'" if include_model else ""
            raise RegistryError(
                f"unknown model{model_detail} for provider '{provider.id}'; "
                "add it to the provider"
            )
        if model_id not in profile.enabled_models:
            model_detail = f" '{model_id}'" if include_model else ""
            raise RegistryError(
                f"model{model_detail} is not enabled by profile '{profile.id}'; "
                "enable it in the profile"
            )


def _find_model(provider: Provider, model_id: str) -> ModelCard | None:
    return next((card for card in provider.model_cards if card.id == model_id), None)


def _models(model_type: Any, values: Iterable[Any], label: str) -> list[Any]:
    result: list[Any] = []
    for index, value in enumerate(values):
        identifier = (
            _safe_identifier(value.get("id")) if isinstance(value, Mapping) else None
        )
        try:
            result.append(
                value
                if isinstance(value, model_type)
                else model_type.model_validate(value)
            )
        except ValidationError as error:
            subject = f"{label} '{identifier}'" if identifier else label
            details = "; ".join(_validation_detail(detail) for detail in error.errors())
            raise ConfigurationError(
                f"invalid {subject} at index {index}: {details}; "
                f"{_validation_remediation(label, error)}"
            ) from None
    return result


def _validation_detail(detail: Any) -> str:
    location = ".".join(str(part) for part in detail.get("loc", ()))
    message = str(detail.get("msg", "invalid value"))
    return f"{location}: {message}" if location else message


def _safe_identifier(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if value.replace("-", "").replace("_", "").replace(".", "").isalnum():
        return value
    return None


def _validation_remediation(label: str, error: ValidationError) -> str:
    locations = {
        str(part) for detail in error.errors() for part in detail.get("loc", ())
    }
    if "model_id" in locations:
        return "define a deployment model_id"
    if label == "provider" and "type" in locations:
        return "use a valid model type"
    return f"fix the {label} fields to match the registry schema"


def _load_profiles(sources: Sequence[PathSource]) -> list[Profile]:
    profiles: list[Profile] = []
    for source in sources:
        profiles.extend(load_profile_file(source))
    return profiles
