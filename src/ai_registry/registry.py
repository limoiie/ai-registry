"""Validated, framework-independent registry lookup."""

from __future__ import annotations

import os
import re
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
    load_account_file,
    load_alias_file,
    load_deployments_file,
    load_provider_files,
    merge_providers,
)
from ai_registry.errors import ConfigurationError, RegistryError
from ai_registry.routing import DeploymentRouter, DeploymentTarget
from ai_registry.schemas import (
    Account,
    Alias,
    Deployment,
    ModelCapabilities,
    ModelCard,
    ModelMode,
    ModelType,
    Provider,
    RegistryConfig,
    SafeModel,
    SDKType,
    _is_sensitive_key,
)
from ai_registry.secrets import SecretResolver, resolve_credential

#: Provider ids that are already valid ``gen_ai.provider.name`` values.
_OTEL_PROVIDER_NAMES = frozenset(
    {
        "anthropic",
        "aws.bedrock",
        "azure.ai.inference",
        "azure.ai.openai",
        "cohere",
        "deepseek",
        "gcp.gemini",
        "gcp.gen_ai",
        "gcp.vertex_ai",
        "groq",
        "ibm.watsonx.ai",
        "mistral_ai",
        "openai",
        "perplexity",
        "x_ai",
    }
)

#: Fallback ``gen_ai.provider.name`` per SDK family, used when the provider id
#: is not itself a registered OpenTelemetry value. The attribute identifies the
#: telemetry *format flavor*, so an OpenAI-compatible gateway reports "openai".
_OTEL_PROVIDER_BY_SDK = {
    SDKType.OPENAI: "openai",
    SDKType.ANTHROPIC: "anthropic",
    SDKType.GOOGLE: "gcp.gen_ai",
}

#: ``gen_ai.operation.name`` per model type. Reranking has no registered
#: operation value, so it is omitted rather than reported inaccurately.
_OTEL_OPERATIONS = {
    ModelType.CHAT: "chat",
    ModelType.EMBEDDING: "embeddings",
}


@dataclass(frozen=True)
class Resolution:
    """Safe deployment information passed to an adapter."""

    provider: Provider
    model: ModelCard
    account: Account
    deployment_id: str
    endpoint: str | None
    sdk_type: SDKType
    endpoint_metadata: dict[str, Any]
    mode: ModelMode = ModelMode.CHAT
    _secret_resolver: SecretResolver | None = None

    @property
    def model_id(self) -> str:
        return self.model.id

    @property
    def account_id(self) -> str:
        return self.account.id

    @property
    def provider_id(self) -> str:
        return self.provider.id

    @property
    def target(self) -> DeploymentTarget:
        """Return the health-state identity of the resolved deployment."""
        return DeploymentTarget(account_id=self.account.id, model_id=self.model.id)

    def resolve_credential(self) -> str | None:
        """Resolve the account credential only when an adapter requests it."""
        if self.account.credential is None:
            return None
        return resolve_credential(self.account.credential, self._secret_resolver)

    def otel_attributes(self) -> dict[str, str]:
        """Return OpenTelemetry GenAI attributes describing this resolution.

        Keys follow the OpenTelemetry GenAI semantic conventions
        (``gen_ai.provider.name`` supersedes the deprecated ``gen_ai.system``).
        The ``ai_registry.*`` keys are this library's own additions: they record
        *which* alias and account produced the request, which the standard
        attributes cannot express. No secret is ever included.
        """
        attributes = {
            "gen_ai.provider.name": (
                self.provider.id
                if self.provider.id in _OTEL_PROVIDER_NAMES
                else _OTEL_PROVIDER_BY_SDK.get(self.sdk_type, self.provider.id)
            ),
            "gen_ai.request.model": self.model.id,
            "ai_registry.deployment_id": self.deployment_id,
            "ai_registry.provider_id": self.provider.id,
            "ai_registry.account_id": self.account.id,
        }
        operation = _OTEL_OPERATIONS.get(self.model.type)
        if operation is not None:
            attributes["gen_ai.operation.name"] = operation
        return attributes

    def __repr__(self) -> str:
        return (
            "Resolution("
            f"provider_id={self.provider.id!r}, model_id={self.model.id!r}, "
            f"account_id={self.account.id!r}, deployment_id={self.deployment_id!r}, "
            f"endpoint={self.endpoint!r}, "
            f"endpoint_metadata={_redact_metadata(self.endpoint_metadata)!r})"
        )

    __str__ = __repr__


@dataclass(frozen=True)
class CatalogEntry:
    """One model card together with the provider that offers it."""

    provider_id: str
    model: ModelCard

    @property
    def model_id(self) -> str:
        return self.model.id


def _required_capabilities(
    requires: ModelCapabilities | Mapping[str, bool] | None,
) -> tuple[str, ...]:
    if requires is None:
        return ()
    values = (
        requires._raw_dump()
        if isinstance(requires, ModelCapabilities)
        else dict(requires)
    )
    unknown = set(values) - set(ModelCapabilities.model_fields)
    if unknown:
        raise RegistryError(
            f"unknown capability {sorted(unknown)[0]!r}; use one of "
            f"{sorted(ModelCapabilities.model_fields)}"
        )
    return tuple(name for name, wanted in values.items() if wanted)


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
            accounts=_models(Account, config.accounts, "account"),
            aliases=_models(Alias, config.aliases, "alias"),
        )
        self._config = config.model_copy(deep=True)
        self._secret_resolver = secret_resolver
        self._router = router or DeploymentRouter()
        self._providers = {provider.id: provider for provider in self._config.providers}
        self._accounts = {account.id: account for account in self._config.accounts}
        self._aliases = {alias.id: alias for alias in self._config.aliases}
        self._validate_references()

    @classmethod
    def from_data(
        cls,
        *,
        providers: Sequence[Provider | Mapping[str, Any]],
        accounts: Sequence[Account | Mapping[str, Any]],
        aliases: Sequence[Alias | Mapping[str, Any]] = (),
        secret_resolver: SecretResolver | None = None,
        router: DeploymentRouter | None = None,
    ) -> Registry:
        """Build a registry from normalized objects or schema-compatible mappings."""
        config = RegistryConfig(
            providers=_models(Provider, providers, "provider"),
            accounts=_models(Account, accounts, "account"),
            aliases=_models(Alias, aliases, "alias"),
        )
        return cls(config, secret_resolver, router)

    @classmethod
    def from_files(
        cls,
        provider_files: Sequence[PathSource],
        account_files: Sequence[PathSource],
        alias_files: Sequence[PathSource] = (),
        *,
        secret_resolver: SecretResolver | None = None,
        router: DeploymentRouter | None = None,
    ) -> Registry:
        """Load provider, account, and optional alias documents without secrets."""
        aliases: list[dict[str, Any]] = []
        for source in alias_files:
            aliases.extend(load_alias_file(source))
        return cls.from_data(
            providers=load_provider_files(list(provider_files)),
            accounts=_load_accounts(account_files),
            aliases=aliases,
            secret_resolver=secret_resolver,
            router=router,
        )

    @classmethod
    def from_project(
        cls,
        root: str | Path | None = None,
        *,
        profile: str | None = None,
        search_parents: bool = True,
        secret_resolver: SecretResolver | None = None,
        router: DeploymentRouter | None = None,
    ) -> Registry:
        """Build a registry from built-in and project-scoped configuration.

        Discovery starts at ``root`` or the current working directory when
        omitted and walks upward to the first ancestor containing an
        ``.ai-registry`` directory, so the registry resolves identically from
        any subdirectory of a project. Pass ``search_parents=False`` to require
        the directory at ``root`` itself.

        The discovered directory must hold a ``registry.yaml`` (or
        ``.yml``/``.json``) file containing accounts and optional aliases. Pass
        ``profile`` (or set ``AI_REGISTRY_PROFILE``) to select a
        ``registry.<profile>.yaml`` file instead of the default.
        """
        start = Path(root) if root is not None else Path.cwd()
        resolved_profile = _resolve_profile(profile)
        root_path = _discover_project_root(start) if search_parents else start
        deployments_file = _discover_registry_file(root_path, resolved_profile)
        if deployments_file is None:
            expected = (
                f"registry.{resolved_profile}.yaml"
                if resolved_profile is not None
                else "registry.yaml"
            )
            raise ConfigurationError(
                f"Missing project registry file under "
                f"'{root_path / '.ai-registry'}'; expected {expected}. Create it "
                "from examples/registry.example.yaml"
            )
        deployments = load_deployments_file(deployments_file)
        return cls.from_data(
            providers=merge_providers(
                discover_builtin_providers(),
                discover_project_providers(root_path),
            ),
            accounts=deployments.accounts,
            aliases=deployments.aliases,
            secret_resolver=secret_resolver,
            router=router,
        )

    def resolve(self, reference: str) -> Resolution:
        """Resolve an alias first, then an explicit ``account-id/model-id``."""
        alias = self._aliases.get(reference)
        if alias is not None:
            selected = self._router.select(alias, eligible=self._account_enabled)
            return self._resolution(selected.deployment, selected.deployment_id)
        return self._resolve_direct(reference)

    def candidates(self, reference: str) -> list[Resolution]:
        """Return every available deployment for ``reference``, best first.

        This is the entry point for callers that implement their own
        request-time failover: walk the list, and report the outcome of each
        attempt with :meth:`record_success` / :meth:`record_failure`. An alias
        with no available deployment returns an empty list rather than raising,
        because "nothing to try" is a normal branch for a retry loop.
        """
        alias = self._aliases.get(reference)
        if alias is None:
            return [self._resolve_direct(reference)]
        return [
            self._resolution(selected.deployment, selected.deployment_id)
            for selected in self._router.candidates(
                alias, eligible=self._account_enabled
            )
        ]

    def record_success(self, resolution: Resolution) -> None:
        """Clear health state for the deployment behind ``resolution``."""
        self._router.health_store.record_success(resolution.target)

    def record_failure(self, resolution: Resolution) -> None:
        """Record a failure for the deployment behind ``resolution``."""
        self._router.health_store.record_failure(resolution.target)

    def list_aliases(self) -> list[str]:
        """Return every configured alias id, sorted."""
        return sorted(self._aliases)

    def list_accounts(self) -> list[Account]:
        """Return every configured account, sorted by id."""
        return [
            account.model_copy(deep=True)
            for account in sorted(self._accounts.values(), key=lambda a: a.id)
        ]

    def list_providers(self) -> list[Provider]:
        """Return every configured provider, sorted by id."""
        return [
            provider.model_copy(deep=True)
            for provider in sorted(self._providers.values(), key=lambda p: p.id)
        ]

    def get_provider(self, provider_id: str) -> Provider:
        """Return one provider by id."""
        provider = self._providers.get(provider_id)
        if provider is None:
            raise RegistryError("unknown provider; configure the provider")
        return provider.model_copy(deep=True)

    def get_account(self, account_id: str) -> Account:
        """Return one account by id."""
        account = self._accounts.get(account_id)
        if account is None:
            raise RegistryError("unknown account; configure the account")
        return account.model_copy(deep=True)

    def list_models(
        self,
        *,
        model_type: ModelType | str | None = None,
        provider_id: str | None = None,
        requires: ModelCapabilities | Mapping[str, bool] | None = None,
        min_context_tokens: int | None = None,
        enabled_only: bool = False,
    ) -> list[CatalogEntry]:
        """Return catalog entries matching every supplied constraint.

        ``requires`` selects models whose capabilities include each requested
        flag, so ``requires={"tools": True}`` returns only tool-capable models.
        ``enabled_only`` restricts the result to models some enabled account
        actually exposes.
        """
        wanted_type = ModelType(model_type) if model_type is not None else None
        required = _required_capabilities(requires)
        exposed = self._enabled_model_ids() if enabled_only else None
        entries: list[CatalogEntry] = []
        for provider in sorted(self._providers.values(), key=lambda p: p.id):
            if provider_id is not None and provider.id != provider_id:
                continue
            for card in provider.model_cards:
                if wanted_type is not None and card.type is not wanted_type:
                    continue
                if exposed is not None and (provider.id, card.id) not in exposed:
                    continue
                if min_context_tokens is not None and (
                    card.context_window_tokens is None
                    or card.context_window_tokens < min_context_tokens
                ):
                    continue
                if any(
                    getattr(card.capabilities, name) is not True for name in required
                ):
                    continue
                entries.append(
                    CatalogEntry(
                        provider_id=provider.id, model=card.model_copy(deep=True)
                    )
                )
        return entries

    def _enabled_model_ids(self) -> set[tuple[str, str]]:
        return {
            (account.provider_id, model_id)
            for account in self._accounts.values()
            if account.enabled
            for model_id in account.enabled_models
        }

    def _account_enabled(self, deployment: Deployment) -> bool:
        return self._accounts[deployment.account_id].enabled

    def _resolve_direct(self, reference: str) -> Resolution:
        if "/" not in reference:
            raise RegistryError(
                "unknown alias or model reference; use an alias or 'account/model'"
            )
        account_id, model_id = reference.split("/", 1)
        account = self._accounts.get(account_id)
        if account is None:
            raise RegistryError(
                "unknown account; configure the account or use an alias"
            )
        if not account.enabled:
            raise RegistryError(
                f"account '{account.id}' is disabled; enable it or use an alias"
            )
        self._validate_model_enabled(account, model_id)
        return self._resolution(
            Deployment(account_id=account_id, model_id=model_id), account_id
        )

    def _resolution(self, deployment: Any, deployment_id: str) -> Resolution:
        account = self._accounts[deployment.account_id]
        provider = self._providers[account.provider_id]
        result_provider = provider.model_copy(deep=True)
        result_account = account.model_copy(deep=True)
        result_model = next(
            card
            for card in result_provider.model_cards
            if card.id == deployment.model_id
        )
        endpoint = result_account.endpoint or result_provider.default_base_url
        sdk_type = result_provider.sdk_type
        mode = ModelMode.CHAT
        if result_account.endpoint_ref is not None:
            selected = result_provider.endpoints[result_account.endpoint_ref]
            endpoint = selected.base_url
            sdk_type = selected.sdk_type
            mode = selected.mode
        return Resolution(
            provider=result_provider,
            model=result_model,
            account=result_account,
            deployment_id=deployment_id,
            endpoint=endpoint,
            sdk_type=sdk_type,
            mode=mode,
            endpoint_metadata=deepcopy(result_account.metadata),
            _secret_resolver=self._secret_resolver,
        )

    def _validate_references(self) -> None:
        for account in self._accounts.values():
            provider = self._providers.get(account.provider_id)
            if provider is None:
                raise ConfigurationError(
                    f"account '{account.id}' references unknown provider "
                    f"'{account.provider_id}'; configure the provider"
                )
            for model_id in account.enabled_models:
                if not _find_model(provider, model_id):
                    raise ConfigurationError(
                        f"account '{account.id}' enables unknown model; "
                        f"add the model to provider '{provider.id}'"
                    )
            if (
                account.endpoint_ref is not None
                and account.endpoint_ref not in provider.endpoints
            ):
                raise ConfigurationError(
                    f"account '{account.id}' references unknown endpoint "
                    f"'{account.endpoint_ref}'; add it to provider "
                    f"'{provider.id}' endpoints"
                )
        for alias in self._aliases.values():
            for deployment in alias.deployments:
                alias_account = self._accounts.get(deployment.account_id)
                if alias_account is None:
                    raise ConfigurationError(
                        f"alias '{alias.id}' references unknown account "
                        f"'{deployment.account_id}'; configure the account"
                    )
                try:
                    self._validate_model_enabled(alias_account, deployment.model_id)
                except RegistryError as error:
                    raise ConfigurationError(
                        f"alias '{alias.id}' deployment is invalid: {error}"
                    ) from None

    def _validate_model_enabled(self, account: Account, model_id: str) -> None:
        provider = self._providers[account.provider_id]
        card = _find_model(provider, model_id)
        if card is None:
            raise RegistryError(
                f"unknown model for provider '{provider.id}'; add it to the provider"
            )
        if model_id not in account.enabled_models:
            raise RegistryError(
                f"model is not enabled by account '{account.id}'; "
                "enable it in the account"
            )
        if (
            account.endpoint_ref is not None
            and card.endpoints is not None
            and account.endpoint_ref not in card.endpoints
        ):
            raise RegistryError(
                f"model '{model_id}' is not supported by endpoint "
                f"'{account.endpoint_ref}'; the model card declares "
                f"endpoints {sorted(card.endpoints)}"
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


def _load_accounts(sources: Sequence[PathSource]) -> list[Account]:
    accounts: list[Account] = []
    for source in sources:
        accounts.extend(load_account_file(source))
    return accounts


_PROFILE_ENV = "AI_REGISTRY_PROFILE"
_PROJECT_DIR = ".ai-registry"
_REGISTRY_NAMES = ("registry.yaml", "registry.yml", "registry.json")


def _resolve_profile(profile: str | None) -> str | None:
    value = profile if profile is not None else os.environ.get(_PROFILE_ENV)
    if value is None or value.strip() == "":
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ConfigurationError(
            f"invalid registry profile name {value!r}; "
            "use letters, digits, '_' or '-' only"
        )
    return value


def _discover_project_root(start: Path) -> Path:
    """Return the nearest ancestor of ``start`` holding an ``.ai-registry`` dir.

    Falls back to ``start`` when no ancestor qualifies, so the caller still
    reports a missing-file error rooted where the search began.
    """
    current = start if start.is_dir() else start.parent
    for candidate in (current, *current.parents):
        if (candidate / _PROJECT_DIR).is_dir():
            return candidate
    return start


def _discover_registry_file(root: Path, profile: str | None) -> Path | None:
    deployments_dir = root / _PROJECT_DIR
    names = (
        (
            f"registry.{profile}.yaml",
            f"registry.{profile}.yml",
            f"registry.{profile}.json",
        )
        if profile is not None
        else _REGISTRY_NAMES
    )
    for name in names:
        candidate = deployments_dir / name
        if candidate.is_file():
            return candidate
    return None
