"""Explicit readers and compatibility normalizers for registry configuration."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, TextIO

import yaml
from pydantic import ValidationError

from ai_registry.errors import ConfigurationError
from ai_registry.schemas import (
    Account,
    Provider,
    canonical_sdk_type,
    normalize_capabilities,
)

PathSource = str | Path | TextIO


def load_document(source: PathSource) -> dict[str, Any]:
    """Load one YAML or JSON mapping without resolving any secrets."""
    source_name, text, suffix = _read_source(source)
    return _parse_document_text(text, suffix, source_name, kind="configuration")


def _parse_document_text(
    text: str, suffix: str, source_name: str, *, kind: str
) -> dict[str, Any]:
    """Parse one YAML or JSON mapping, wrapping failures in ConfigurationError."""
    try:
        value = json.loads(text) if suffix == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError):
        format_name = "JSON" if suffix == ".json" else "YAML"
        raise ConfigurationError(
            f"Unable to parse {format_name} {kind} '{source_name}'; "
            f"check {format_name} syntax and remove malformed values"
        ) from None
    if not isinstance(value, dict):
        raise ConfigurationError(
            f"{kind.capitalize()} '{source_name}' must contain a top-level mapping"
        )
    return value


def load_provider_file(source: PathSource) -> Provider:
    source_name, _, _ = _source_details(source)
    return normalize_provider(load_document(source), source_name=source_name)


def load_provider_files(sources: list[PathSource]) -> list[Provider]:
    providers = [load_provider_file(source) for source in sources]
    _ensure_unique_provider_ids(providers)
    return providers


def discover_builtin_providers() -> list[Provider]:
    """Discover and parse the built-in providers shipped as package data."""
    base = resources.files("ai_registry") / "data" / "providers"
    try:
        entries = list(base.iterdir())
    except FileNotFoundError as error:
        raise ConfigurationError(
            f"Unable to read built-in provider data '{base}': {error}"
        ) from None
    providers = [
        _provider_from_text(entry.name, entry.read_text(encoding="utf-8"))
        for entry in entries
        if entry.is_file() and entry.name.lower().endswith((".yaml", ".yml", ".json"))
    ]
    providers.sort(key=lambda provider: provider.id)
    _ensure_unique_provider_ids(providers)
    return providers


def _provider_from_text(name: str, text: str) -> Provider:
    suffix = Path(name).suffix.lower()
    document = _parse_document_text(text, suffix, name, kind="provider")
    return normalize_provider(document, source_name=name)


def _ensure_unique_provider_ids(providers: list[Provider]) -> None:
    seen: set[str] = set()
    for provider in providers:
        if provider.id in seen:
            raise ConfigurationError(f"duplicate provider id '{provider.id}'")
        seen.add(provider.id)


def discover_project_providers(root: str | Path) -> list[Provider]:
    """Discover and parse project providers under <root>/.ai-registry/providers."""
    providers_dir = Path(root) / ".ai-registry" / "providers"
    if not providers_dir.is_dir():
        return []
    providers = [
        load_provider_file(entry)
        for entry in sorted(providers_dir.iterdir())
        if entry.is_file() and entry.suffix.lower() in {".yaml", ".yml", ".json"}
    ]
    _ensure_unique_provider_ids(providers)
    return providers


def merge_providers(
    builtin: Sequence[Provider], project: Sequence[Provider]
) -> list[Provider]:
    """Merge project providers over built-ins, keyed by provider id."""
    builtin_providers = list(builtin)
    project_providers = list(project)
    _ensure_unique_provider_ids(builtin_providers)
    _ensure_unique_provider_ids(project_providers)
    merged = {provider.id: provider for provider in builtin_providers}
    for provider in project_providers:
        merged[provider.id] = provider
    return list(merged.values())


def load_account_file(source: PathSource) -> list[Account]:
    source_name, _, _ = _source_details(source)
    return _parse_accounts(load_document(source), source_name)


def _parse_accounts(document: Mapping[str, Any], source_name: str) -> list[Account]:
    values = document.get("accounts")
    if not isinstance(values, list):
        raise ConfigurationError(
            f"Account configuration '{source_name}' must contain an 'accounts' list"
        )
    accounts: list[Account] = []
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise ConfigurationError(
                f"Account configuration '{source_name}' has an invalid account "
                f"at index {index}"
            )
        normalized = dict(value)
        has_api_key_env = "api_key_env" in normalized
        api_key_env = normalized.pop("api_key_env", None)
        if has_api_key_env and "credential" in normalized:
            raise ConfigurationError(
                f"Account configuration '{source_name}' at index {index} "
                "cannot define both api_key_env and credential"
            )
        metadata = (
            _require_mapping(
                normalized.pop("metadata"), "account metadata", source_name
            )
            if "metadata" in normalized
            else {}
        )
        for key in ("remark", "description"):
            if key in normalized:
                metadata[key] = normalized.pop(key)
        normalized["metadata"] = metadata
        if api_key_env is not None:
            normalized["credential"] = {"env": api_key_env}
        try:
            accounts.append(Account.model_validate(normalized))
        except ValidationError as error:
            raise ConfigurationError(
                f"Invalid account in '{source_name}' at index {index}: {error}"
            ) from None
    return accounts


def load_alias_file(source: PathSource) -> list[dict[str, Any]]:
    source_name, _, _ = _source_details(source)
    document = load_document(source)
    return _parse_aliases(document, source_name, required=True)


def _parse_aliases(
    document: Mapping[str, Any], source_name: str, *, required: bool
) -> list[dict[str, Any]]:
    if "aliases" not in document:
        if required:
            raise ConfigurationError(
                f"Alias configuration '{source_name}' must contain an 'aliases' list"
            )
        return []
    values = document["aliases"]
    if not isinstance(values, list):
        raise ConfigurationError(
            f"Alias configuration '{source_name}' must contain an 'aliases' list"
        )
    aliases: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise ConfigurationError(
                f"Alias configuration '{source_name}' has an invalid alias "
                f"at index {index}"
            )
        aliases.append(dict(value))
    return aliases


@dataclass(frozen=True)
class Deployments:
    accounts: list[Account]
    aliases: list[dict[str, Any]]


def load_deployments_file(source: PathSource) -> Deployments:
    source_name, _, _ = _source_details(source)
    document = load_document(source)
    return Deployments(
        accounts=_parse_accounts(document, source_name),
        aliases=_parse_aliases(document, source_name, required=False),
    )


def normalize_provider(
    document: dict[str, Any], *, source_name: str = "provider configuration"
) -> Provider:
    """Normalize the current provider catalog shape into a Provider schema."""
    value = dict(document)
    settings = (
        _require_mapping(value["settings"], "settings", source_name)
        if "settings" in value
        else {}
    )
    for key in ("url", "check_model", "models_url"):
        if key in value:
            settings[key] = value[key]
            value.pop(key)
    value["settings"] = settings
    if value.get("default_base_url") is None:
        # The catalog format carries the provider's base URL under
        # settings.proxy_url.placeholder. Without this, providers that only
        # declare it there resolve to a null endpoint and adapters silently fall
        # back to their own default host. Only backfill for single-endpoint
        # providers that declare no explicit endpoints map.
        endpoints = value.get("endpoints") or {}
        if not endpoints:
            placeholder = _proxy_url_placeholder(settings)
            if placeholder is not None:
                value["default_base_url"] = placeholder
    top_sdk_type = value.get("sdk_type")
    nested_sdk_type = settings.get("sdk_type")
    try:
        canonical_sdk_type(top_sdk_type, nested_sdk_type)
    except ConfigurationError:
        raise ConfigurationError(
            f"conflicting sdk_type values in '{source_name}'; "
            "use one canonical SDK type"
        ) from None
    if top_sdk_type is not None:
        if top_sdk_type == "uniapi":
            value["sdk_type"] = "openai"
    elif nested_sdk_type == "uniapi":
        value["sdk_type"] = "openai"
    raw_models = value.get("models")
    if raw_models is None:
        raw_models = value.get("model_cards")
    if raw_models is None:
        raw_models = []
    if not isinstance(raw_models, list):
        raise ConfigurationError(f"Invalid models in '{source_name}': expected a list")
    models = []
    for index, model in enumerate(raw_models):
        if not isinstance(model, Mapping):
            raise ConfigurationError(
                f"Invalid model in '{source_name}' at index {index}: expected a mapping"
            )
        model_value = dict(model)
        abilities = (
            _require_mapping(model_value["abilities"], "abilities", source_name)
            if "abilities" in model_value
            else {}
        )
        known_capabilities = normalize_capabilities(abilities)
        if known_capabilities:
            model_value["capabilities"] = known_capabilities
        metadata = (
            _require_mapping(model_value.pop("metadata"), "metadata", source_name)
            if "metadata" in model_value
            else {}
        )
        for key in ("abilities", "pricing", "deprecated", "settings"):
            if key in model_value:
                metadata[key] = model_value.pop(key)
        if "max_dimension" in model_value:
            max_dimension = model_value.pop("max_dimension")
            model_value.setdefault("embedding_dimension", max_dimension)
            metadata["max_dimension"] = max_dimension
        if model_value.get("context_window_tokens") == 0:
            metadata["context_window_tokens"] = model_value["context_window_tokens"]
            model_value["context_window_tokens"] = None
        model_value["metadata"] = metadata
        models.append(model_value)
    value["models"] = models
    value.pop("model_cards", None)
    try:
        provider = Provider.model_validate(value)
    except ValidationError as error:
        raise ConfigurationError(
            f"Invalid provider in '{source_name}': {error}"
        ) from None
    model_ids = [model.id for model in provider.models]
    duplicates = sorted(
        {model_id for model_id in model_ids if model_ids.count(model_id) > 1}
    )
    if duplicates:
        raise ConfigurationError(
            f"duplicate model id '{duplicates[0]}' in provider '{provider.id}'"
        )
    return provider


def _proxy_url_placeholder(settings: Mapping[str, Any]) -> str | None:
    proxy_url = settings.get("proxy_url")
    if not isinstance(proxy_url, Mapping):
        return None
    placeholder = proxy_url.get("placeholder")
    return placeholder if isinstance(placeholder, str) and placeholder else None


def _require_mapping(value: Any, field: str, source_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(
            f"Invalid {field} in '{source_name}': expected a mapping"
        )
    return dict(value)


def _source_details(source: PathSource) -> tuple[str, str, str]:
    if hasattr(source, "read"):
        stream = source
        name = str(getattr(stream, "name", "<stream>"))
        suffix = Path(name).suffix.lower()
        return name, "", suffix
    path = Path(source)
    return str(path), "", path.suffix.lower()


def _read_source(source: PathSource) -> tuple[str, str, str]:
    name, _, suffix = _source_details(source)
    if hasattr(source, "read"):
        text = source.read()
    else:
        try:
            text = Path(source).read_text(encoding="utf-8")
        except OSError as error:
            raise ConfigurationError(
                f"Unable to read configuration '{name}': {error}"
            ) from None
    if suffix not in {".json", ".yaml", ".yml", ""} or (
        not hasattr(source, "read") and suffix == ""
    ):
        raise ConfigurationError(
            f"Unsupported configuration format for '{name}'; use .json, .yaml, or .yml"
        )
    return name, text, suffix
