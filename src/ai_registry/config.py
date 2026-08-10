"""Explicit readers and compatibility normalizers for registry configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TextIO

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from ai_registry.errors import ConfigurationError
from ai_registry.schemas import Profile, Provider

PathSource = str | Path | TextIO


def load_document(source: PathSource) -> dict[str, Any]:
    """Load one YAML or JSON mapping without resolving any secrets."""
    source_name, text, suffix = _read_source(source)
    try:
        value = json.loads(text) if suffix == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        format_name = "JSON" if suffix == ".json" else "YAML"
        raise ConfigurationError(
            f"Unable to parse {format_name} configuration '{source_name}': {error}"
        ) from None
    if not isinstance(value, dict):
        raise ConfigurationError(
            f"Configuration '{source_name}' must contain a top-level mapping"
        )
    return value


def load_provider_file(source: PathSource) -> Provider:
    source_name, _, _ = _source_details(source)
    return normalize_provider(load_document(source), source_name=source_name)


def load_provider_files(sources: list[PathSource]) -> list[Provider]:
    providers = [load_provider_file(source) for source in sources]
    seen: set[str] = set()
    for provider in providers:
        if provider.id in seen:
            raise ConfigurationError(f"duplicate provider id '{provider.id}'")
        seen.add(provider.id)
    return providers


def load_profile_file(source: PathSource) -> list[Profile]:
    source_name, _, _ = _source_details(source)
    document = load_document(source)
    values = document.get("profiles")
    if not isinstance(values, list):
        raise ConfigurationError(
            f"Profile configuration '{source_name}' must contain a 'profiles' list"
        )
    profiles: list[Profile] = []
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise ConfigurationError(
                f"Profile configuration '{source_name}' has an invalid profile "
                f"at index {index}"
            )
        normalized = dict(value)
        api_key_env = normalized.pop("api_key_env", None)
        if api_key_env is not None:
            normalized["credential"] = {"env": api_key_env}
        try:
            profiles.append(Profile.model_validate(normalized))
        except ValidationError as error:
            raise ConfigurationError(
                f"Invalid profile in '{source_name}' at index {index}: {error}"
            ) from None
    return profiles


def normalize_provider(
    document: dict[str, Any], *, source_name: str = "provider configuration"
) -> Provider:
    """Normalize the current provider catalog shape into a Provider schema."""
    value = dict(document)
    settings = dict(value.get("settings") or {})
    for key in ("url", "check_model", "models_url"):
        if key in value:
            settings[key] = value[key]
            value.pop(key)
    value["settings"] = settings
    model_cards = []
    for card in value.get("model_cards") or []:
        card_value = dict(card)
        abilities = dict(card_value.get("abilities") or {})
        known_capabilities = {
            key: abilities[key]
            for key in ("reasoning", "structured_output", "vision", "tools")
            if key in abilities
        }
        if known_capabilities:
            card_value["capabilities"] = known_capabilities
        metadata = dict(card_value.pop("metadata", {}) or {})
        for key in ("abilities", "pricing"):
            if key in card_value:
                metadata[key] = card_value.pop(key)
        card_value["metadata"] = metadata
        model_cards.append(card_value)
    value["model_cards"] = model_cards
    try:
        provider = Provider.model_validate(value)
    except ValidationError as error:
        raise ConfigurationError(
            f"Invalid provider in '{source_name}': {error}"
        ) from None
    model_ids = [card.id for card in provider.model_cards]
    duplicates = sorted(
        {model_id for model_id in model_ids if model_ids.count(model_id) > 1}
    )
    if duplicates:
        raise ConfigurationError(
            f"duplicate model id '{duplicates[0]}' in provider '{provider.id}'"
        )
    return provider


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
    if suffix not in {".json", ".yaml", ".yml"}:
        raise ConfigurationError(
            f"Unsupported configuration format for '{name}'; use .json, .yaml, or .yml"
        )
    return name, text, suffix
