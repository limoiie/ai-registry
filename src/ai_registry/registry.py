"""Validated, framework-independent registry lookup."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence, Set
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ai_registry.config import (
    PathSource,
    discover_builtin_providers,
    discover_project_providers,
    load_alias_file,
    load_deployments_file,
    load_profile_file,
    load_provider_files,
    merge_providers,
)
from ai_registry.errors import ConfigurationError, RegistryError
from ai_registry.routing import DeploymentRouter
from ai_registry.schemas import (
    Alias,
    Deployment,
    ModelCard,
    Profile,
    Provider,
    RegistryConfig,
    SafeModel,
    _is_sensitive_key,
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

    def __repr__(self) -> str:
        return (
            "Resolution("
            f"provider_id={self.provider.id!r}, model_id={self.model.id!r}, "
            f"profile_id={self.profile.id!r}, deployment_id={self.deployment_id!r}, "
            f"endpoint={self.endpoint!r}, "
            f"endpoint_metadata={_redact_metadata(self.endpoint_metadata)!r})"
        )

    __str__ = __repr__


class Registry:
    """Immutable configuration index for aliases and explicit deployments."""

    def __init__(
        self,
        config: RegistryConfig,
        secret_resolver: SecretResolver | None,
        router: DeploymentRouter | None = None,
    ):
        config = RegistryConfig(
            providers=_models(Provider, config.providers, "provider"),
            profiles=_models(Profile, config.profiles, "profile"),
            aliases=_models(Alias, config.aliases, "alias"),
        )
        self._config = config.model_copy(deep=True)
        self._secret_resolver = secret_resolver
        self._router = router or DeploymentRouter()
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
        router: DeploymentRouter | None = None,
    ) -> Registry:
        """Build a registry from normalized objects or schema-compatible mappings."""
        config = RegistryConfig(
            providers=_models(Provider, providers, "provider"),
            profiles=_models(Profile, profiles, "profile"),
            aliases=_models(Alias, aliases, "alias"),
        )
        return cls(config, secret_resolver, router)

    @classmethod
    def from_files(
        cls,
        provider_files: Sequence[PathSource],
        profile_files: Sequence[PathSource],
        alias_files: Sequence[PathSource] = (),
        *,
        secret_resolver: SecretResolver | None = None,
        router: DeploymentRouter | None = None,
    ) -> Registry:
        """Load provider, profile, and optional alias documents without secrets."""
        aliases: list[dict[str, Any]] = []
        for source in alias_files:
            aliases.extend(load_alias_file(source))
        return cls.from_data(
            providers=load_provider_files(list(provider_files)),
            profiles=_load_profiles(profile_files),
            aliases=aliases,
            secret_resolver=secret_resolver,
            router=router,
        )

    @classmethod
    def from_project(
        cls,
        root: str | Path | None = None,
        *,
        secret_resolver: SecretResolver | None = None,
        router: DeploymentRouter | None = None,
    ) -> Registry:
        """Build a registry from built-in and project-scoped configuration.

        Discovery starts at ``root`` or the current working directory when
        omitted, and requires a ``<root>/.ai-registry/deployments.yaml`` (or
        ``.yml``/``.json``) file containing profiles and optional aliases.
        """
        root_path = Path(root) if root is not None else Path.cwd()
        deployments_file = _discover_deployments_file(root_path)
        if deployments_file is None:
            raise ConfigurationError(
                f"Missing project deployments file under "
                f"'{root_path / '.ai-registry'}'; expected deployments.yaml, "
                "deployments.yml, or deployments.json. Create it from "
                "examples/deployments.example.yaml"
            )
        deployments = load_deployments_file(deployments_file)
        return cls.from_data(
            providers=merge_providers(
                discover_builtin_providers(),
                discover_project_providers(root_path),
            ),
            profiles=deployments.profiles,
            aliases=deployments.aliases,
            secret_resolver=secret_resolver,
            router=router,
        )

    def resolve(self, reference: str) -> Resolution:
        """Resolve an alias first, then an explicit ``profile-id/model-id``."""
        alias = self._aliases.get(reference)
        if alias is not None:
            selected = self._router.select(
                alias,
                eligible=lambda deployment: (
                    self._profiles[deployment.profile_id].enabled
                ),
            )
            return self._resolution(selected.deployment, selected.deployment_id)

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
        if not profile.enabled:
            raise RegistryError(
                f"profile '{profile.id}' is disabled; enable it or use an alias"
            )
        self._validate_model_enabled(profile, model_id)
        return self._resolution(
            Deployment(profile_id=profile_id, model_id=model_id), profile_id
        )

    def _resolution(self, deployment: Any, deployment_id: str) -> Resolution:
        profile = self._profiles[deployment.profile_id]
        provider = self._providers[profile.provider_id]
        result_provider = provider.model_copy(deep=True)
        result_profile = profile.model_copy(deep=True)
        result_model = next(
            card
            for card in result_provider.model_cards
            if card.id == deployment.model_id
        )
        return Resolution(
            provider=result_provider,
            model=result_model,
            profile=result_profile,
            deployment_id=deployment_id,
            endpoint=result_profile.endpoint or result_provider.default_base_url,
            endpoint_metadata=deepcopy(result_profile.metadata),
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
                        f"profile '{profile.id}' enables unknown model; "
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

    def _validate_model_enabled(self, profile: Profile, model_id: str) -> None:
        provider = self._providers[profile.provider_id]
        if not _find_model(provider, model_id):
            raise RegistryError(
                f"unknown model for provider '{provider.id}'; add it to the provider"
            )
        if model_id not in profile.enabled_models:
            raise RegistryError(
                f"model is not enabled by profile '{profile.id}'; "
                "enable it in the profile"
            )


def _find_model(provider: Provider, model_id: str) -> ModelCard | None:
    return next((card for card in provider.model_cards if card.id == model_id), None)


def _redact_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: "<redacted>"
            if isinstance(key, str) and _is_sensitive_key(key)
            else _redact_metadata(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if _is_sensitive_pair(value):
            redacted = (value[0], "<redacted>")
        else:
            redacted = tuple(_redact_metadata(item) for item in value)
        return redacted if isinstance(value, tuple) else list(redacted)
    if isinstance(value, Set):
        return {_redact_metadata(item) for item in value}
    return value


def _is_sensitive_pair(value: Sequence[Any]) -> bool:
    return len(value) == 2 and isinstance(value[0], str) and _is_sensitive_key(value[0])


def _models(model_type: Any, values: Iterable[Any], label: str) -> list[Any]:
    result: list[Any] = []
    for index, value in enumerate(values):
        identifier = (
            _safe_identifier(value.get("id")) if isinstance(value, Mapping) else None
        )
        try:
            normalized = value._raw_dump() if isinstance(value, SafeModel) else value
            result.append(model_type.model_validate(normalized))
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


def _discover_deployments_file(root: Path) -> Path | None:
    deployments_dir = root / ".ai-registry"
    for name in ("deployments.yaml", "deployments.yml", "deployments.json"):
        candidate = deployments_dir / name
        if candidate.is_file():
            return candidate
    return None
