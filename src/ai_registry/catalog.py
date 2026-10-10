"""Import third-party model catalogs into the registry's provider schema.

Hand-maintaining context windows, pricing and capability flags does not scale:
the ecosystem now has community catalogs covering thousands of models. This
module converts them into :class:`~ai_registry.schemas.Provider` objects so the
registry can consume one instead.

Two integration points share the same mapping:

* :func:`load_models_dev` converts a models.dev ``api.json`` document you vendor
  yourself into providers, for catalogs that are entirely third-party.
* :func:`hydrate_models_dev_models` builds the built-in catalog's model set from
  a snapshot shipped as package data (``data/models_dev/api.json``): every model
  the snapshot carries becomes a card, and a provider file's ``models`` entries
  overlay it. Those entries are deltas — endpoint availability, vector
  dimensions, local overrides — not the model list itself, which comes from
  models.dev. Provider files opt in with ``source: models.dev`` (or
  ``source: {models.dev: <provider id>}``).

Because the set comes from the snapshot, adding or retiring a model is a
snapshot refresh rather than a catalog edit: ``ai-registry catalog diff`` reports
drift against a downloaded ``api.json`` and ``ai-registry catalog sync`` rewrites
the snapshot.

Consistent with the rest of the core, nothing here performs network access. A
resolution layer should not change behavior because an upstream file changed
under it, so the snapshot is pinned, reviewed, and refreshed deliberately.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from functools import lru_cache
from importlib import resources
from typing import Any

from ai_registry.config import (
    MODELS_DEV_SETTING,
    MODELS_DEV_SOURCE,
    PathSource,
    load_document,
)
from ai_registry.errors import ConfigurationError
from ai_registry.schemas import Model, ModelType, Provider, normalize_capabilities

__all__ = [
    "builtin_models_dev_snapshot",
    "diff_models_dev",
    "hydrate_models_dev_models",
    "load_models_dev",
    "load_models_dev_snapshot",
    "models_dev_provider",
    "models_dev_provider_ids",
    "models_dev_provider_ids_from_documents",
    "models_dev_snapshot_json",
    "models_dev_snapshot_readme",
    "sync_models_dev_snapshot",
]

#: models.dev capability keys, mapped onto ``ModelCapabilities`` fields by
#: :func:`~ai_registry.schemas.normalize_capabilities`.
_MODELS_DEV_ABILITIES = ("tool_call", "reasoning", "structured_output")

#: models.dev keys preserved on the model's free-form ``metadata``.
_MODELS_DEV_METADATA = (
    "cost",
    "family",
    "knowledge",
    "last_updated",
    "modalities",
    "open_weights",
    "reasoning_options",
    "status",
    "experimental",
)

#: Provider-level models.dev keys copied into a snapshot or provider settings.
_MODELS_DEV_PROVIDER_KEYS = ("doc", "env", "npm", "api")

#: models.dev ``type`` values that map straight onto :class:`ModelType`.
_MODELS_DEV_TYPES = {
    "chat": ModelType.CHAT,
    "embedding": ModelType.EMBEDDING,
    "reranking": ModelType.RERANKING,
}


def load_models_dev(
    source: PathSource | Mapping[str, Any],
    *,
    provider_ids: Callable[[str], bool] | None = None,
    default_base_url: Mapping[str, str] | None = None,
) -> list[Provider]:
    """Convert a models.dev catalog document into providers.

    ``source`` is a path to (or an already-parsed mapping of) the models.dev
    ``api.json`` document, whose top level maps a provider id to that provider's
    metadata and ``models`` mapping.

    ``provider_ids`` filters which providers are imported — importing all of
    them is rarely what you want, since the registry validates that every
    account references a configured provider. ``default_base_url`` supplies
    endpoints, because models.dev describes models rather than deployments.
    Models outside the schema — image, audio and video generators — are skipped.

    >>> providers = load_models_dev(
    ...     "api.json",
    ...     provider_ids={"openai", "anthropic"}.__contains__,
    ...     default_base_url={"openai": "https://api.openai.com/v1"},
    ... )
    """
    document = dict(source) if isinstance(source, Mapping) else load_document(source)
    base_urls = dict(default_base_url or {})
    providers = []
    for provider_id in sorted(document):
        if provider_ids is not None and not provider_ids(provider_id):
            continue
        entry = document[provider_id]
        if not isinstance(entry, Mapping):
            raise ConfigurationError(
                f"models.dev provider '{provider_id}' must be a mapping"
            )
        providers.append(
            models_dev_provider(
                provider_id, entry, default_base_url=base_urls.get(provider_id)
            )
        )
    return providers


def models_dev_provider(
    provider_id: str,
    entry: Mapping[str, Any],
    *,
    default_base_url: str | None = None,
) -> Provider:
    """Convert one models.dev provider entry into a :class:`Provider`."""
    models = _models(entry, provider_id=provider_id)
    settings: dict[str, Any] = {"source": MODELS_DEV_SOURCE}
    for key in _MODELS_DEV_PROVIDER_KEYS:
        if key in entry:
            settings[key] = entry[key]
    return Provider(
        id=provider_id,
        name=str(entry.get("name") or provider_id),
        default_base_url=default_base_url or _string_or_none(entry.get("api")),
        settings=settings,
        models=[
            card
            for card in (
                _representable_model(model_id, models[model_id])
                for model_id in sorted(models)
            )
            if card is not None
        ],
    )


def load_models_dev_snapshot(source: PathSource) -> dict[str, Any]:
    """Load a models.dev document, full or trimmed to the shipped catalog."""
    return load_document(source)


def builtin_models_dev_snapshot() -> dict[str, Any]:
    """Return the vendored models.dev snapshot shipped as package data.

    Each call returns a fresh document: callers may keep or edit what they get
    without disturbing other loads.
    """
    try:
        document = json.loads(_builtin_snapshot_text())
    except json.JSONDecodeError:
        raise ConfigurationError(
            "Unable to parse the vendored models.dev snapshot; "
            "regenerate it with 'ai-registry catalog sync'"
        ) from None
    if not isinstance(document, dict):
        raise ConfigurationError(
            "The vendored models.dev snapshot must contain a top-level mapping"
        )
    return document


def hydrate_models_dev_models(
    models: Sequence[Mapping[str, Any]],
    *,
    upstream_provider_id: str,
    source_name: str = "provider configuration",
    snapshot: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build a provider's model set from models.dev, with local cards on top.

    Every representable model in the snapshot becomes a card; a local entry with
    the same ``id`` overrides it field by field, and a local entry models.dev
    does not carry (a gateway id, or an embedding whose vector dimension
    models.dev cannot report) is kept as written. An unknown *provider* is an
    error: it means the snapshot no longer covers the catalog and must be
    regenerated.
    """
    vendored = builtin_models_dev_snapshot() if snapshot is None else snapshot
    upstream_provider = vendored.get(upstream_provider_id)
    if not isinstance(upstream_provider, Mapping):
        raise ConfigurationError(
            f"Provider '{source_name}' sources model metadata from models.dev "
            f"provider '{upstream_provider_id}', which the vendored snapshot does "
            "not cover; run 'ai-registry catalog sync' with a fresh models.dev "
            "api.json"
        )
    upstream_models = _models(upstream_provider, provider_id=upstream_provider_id)
    overrides: dict[str, dict[str, Any]] = {}
    for model in models:
        value = dict(model)
        model_id = value.get("id")
        if isinstance(model_id, str) and model_id:
            overrides[model_id] = value

    hydrated: list[dict[str, Any]] = []
    for model_id in sorted(upstream_models):
        entry = upstream_models[model_id]
        override = overrides.pop(model_id, None)
        if override is not None:
            hydrated.append(_overlay_model(override, entry))
            continue
        card = _models_dev_model_raw(model_id, entry)
        if card is not None:
            hydrated.append(card)
    hydrated.extend(overrides[model_id] for model_id in sorted(overrides))
    return hydrated


def models_dev_provider_ids(providers: Sequence[Provider]) -> list[str]:
    """Return the models.dev provider ids the given providers source from."""
    return sorted(
        {
            upstream_id
            for upstream_id in (
                provider.settings.get(MODELS_DEV_SETTING) for provider in providers
            )
            if isinstance(upstream_id, str) and upstream_id
        }
    )


def models_dev_provider_ids_from_documents(
    documents: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Build the same id list from unnormalized provider documents."""
    return sorted(
        {
            upstream_id
            for upstream_id in (_source_provider_id(document) for document in documents)
            if upstream_id is not None
        }
    )


def diff_models_dev(
    provider_ids: Sequence[str],
    upstream: Mapping[str, Any],
    *,
    snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare the vendored snapshot against a fresh models.dev document.

    ``provider_ids`` comes from :func:`models_dev_provider_ids` (or the document
    variant), and ``snapshot`` defaults to the vendored snapshot. Actionable
    drift is a model added or removed upstream or a changed field; provider-level
    field changes are reported without failing the check.
    """
    vendored = builtin_models_dev_snapshot() if snapshot is None else snapshot
    report: dict[str, Any] = {"drift": False, "providers": {}}
    for provider_id in sorted(set(provider_ids)):
        upstream_provider = upstream.get(provider_id)
        vendored_provider = vendored.get(provider_id)
        fresh_models = _models(upstream_provider, provider_id=provider_id)
        stale_models = _models(vendored_provider, provider_id=provider_id)
        entry: dict[str, Any] = {
            "provider_missing_upstream": not isinstance(upstream_provider, Mapping),
            "provider_changed": _diff_provider_fields(
                upstream_provider, vendored_provider
            ),
            "changed": {},
            "added_upstream": [],
            "missing_upstream": [],
        }
        for model_id in sorted(set(fresh_models) | set(stale_models)):
            fresh = _models_dev_model_raw(model_id, fresh_models.get(model_id))
            stale = _models_dev_model_raw(model_id, stale_models.get(model_id))
            if fresh is None and stale is None:
                continue
            if stale is None:
                entry["added_upstream"].append(model_id)
                report["drift"] = True
                continue
            if fresh is None:
                entry["missing_upstream"].append(model_id)
                report["drift"] = True
                continue
            changes = _diff_model_cards(fresh, stale)
            if changes:
                entry["changed"][model_id] = changes
                report["drift"] = True
        report["providers"][provider_id] = entry
    return report


def sync_models_dev_snapshot(
    provider_ids: Sequence[str], upstream: Mapping[str, Any]
) -> dict[str, Any]:
    """Copy the referenced models.dev provider entries into a snapshot.

    Only models the registry can represent are kept, so the snapshot stays a
    faithful but resolvable subset of the upstream document.
    """
    document: dict[str, Any] = {}
    for provider_id in sorted(set(provider_ids)):
        upstream_provider = upstream.get(provider_id)
        if not isinstance(upstream_provider, Mapping):
            raise ConfigurationError(
                f"Cannot sync models.dev provider '{provider_id}': "
                "it is not present in the supplied api.json"
            )
        entry: dict[str, Any] = {
            "id": provider_id,
            "name": upstream_provider.get("name", provider_id),
        }
        for key in _MODELS_DEV_PROVIDER_KEYS:
            if key in upstream_provider:
                entry[key] = upstream_provider[key]
        models = _models(upstream_provider, provider_id=provider_id)
        kept = {
            model_id: models[model_id]
            for model_id in sorted(models)
            if _models_dev_model_raw(model_id, models[model_id]) is not None
        }
        if kept:
            entry["models"] = kept
        document[provider_id] = entry
    return document


def models_dev_snapshot_json(document: Mapping[str, Any]) -> str:
    """Render a snapshot deterministically, so refreshes diff cleanly."""
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def models_dev_snapshot_readme(
    *,
    source: str,
    generated_at: str,
    document: Mapping[str, Any],
) -> str:
    """Describe where the vendored snapshot came from and how to refresh it."""
    providers = sorted(document)
    lines = [
        "# Vendored models.dev snapshot",
        "",
        "Copy of the [models.dev](https://models.dev) provider entries for the",
        "providers the built-in catalog is sourced from, kept as package data for",
        "`ai_registry.catalog`. Provider files under `data/providers/` declare only",
        "deltas — endpoints, vector dimensions, local overrides — while the model",
        "set comes from here. Generated by `ai-registry catalog sync`; do not edit",
        "by hand.",
        "",
        f"- Source: `{source}`",
        f"- Generated: `{generated_at}`",
        "- Providers: " + ", ".join(f"`{name}`" for name in providers),
        "",
        "| models.dev provider | models kept |",
        "| --- | --- |",
    ]
    for provider_id in providers:
        models = _models(document.get(provider_id), provider_id=provider_id)
        kept = ", ".join(
            f"`{model_id}`"
            for model_id in sorted(models)
            if _models_dev_model_raw(model_id, models[model_id]) is not None
        )
        lines.append(f"| {provider_id} | {kept} |")
    lines.extend(
        [
            "",
            "Refresh it when a provider ships new models or changes limits and",
            "pricing:",
            "",
            "```sh",
            "curl -o /tmp/models-dev-api.json https://models.dev/api.json",
            "ai-registry catalog diff /tmp/models-dev-api.json",
            "ai-registry catalog sync /tmp/models-dev-api.json",
            "```",
            "",
            "Models the registry cannot represent (image, audio and video",
            "generators) are omitted, as are gateway-only providers such as",
            "`uniapi`, whose models stay as local cards in",
            "`src/ai_registry/data/providers/*.yml`.",
            "",
        ]
    )
    return "\n".join(lines)


@lru_cache(maxsize=1)
def _builtin_snapshot_text() -> str:
    base = resources.files("ai_registry") / "data" / "models_dev"
    try:
        return (base / "api.json").read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ConfigurationError(
            f"Unable to read the vendored models.dev snapshot '{base}': {error}"
        ) from None


def _overlay_model(
    value: Mapping[str, Any], upstream_model: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a model card with models.dev data beneath the local declaration."""
    base = _models_dev_model_raw(
        str(upstream_model.get("id") or value.get("id")), upstream_model
    )
    if base is None:  # pragma: no cover - both paths filter unrepresentable models
        return dict(value)
    base_metadata = base.pop("metadata", {})
    local_metadata = value.get("metadata")
    merged = {**base, **value}
    if base_metadata or isinstance(local_metadata, Mapping):
        merged["metadata"] = {
            **base_metadata,
            **(local_metadata if isinstance(local_metadata, Mapping) else {}),
        }
    return merged


def _models_dev_model_raw(model_id: str, entry: Any) -> dict[str, Any] | None:
    """Return a model card in the provider-file shape, or ``None`` if unsupported."""
    if entry is None:
        return None
    card = _representable_model(model_id, entry)
    return None if card is None else card.safe_dump()


def _representable_model(model_id: str, entry: Any) -> Model | None:
    """Build a :class:`Model` from a models.dev entry, or return ``None``.

    models.dev covers more than the registry can resolve — image, audio and video
    generators have no :class:`ModelType` — so those entries are skipped rather
    than mistyped as chat models.
    """
    if not isinstance(entry, Mapping):
        raise ConfigurationError(f"models.dev model '{model_id}' must be a mapping")
    model_type = _model_type(entry)
    if model_type is None:
        return None
    limit = _mapping(entry.get("limit"))
    modalities = _mapping(entry.get("modalities"))
    abilities = {key: entry[key] for key in _MODELS_DEV_ABILITIES if key in entry}
    capabilities = normalize_capabilities(abilities)
    if "image" in _sequence(modalities.get("input")):
        capabilities["vision"] = True

    metadata = {key: entry[key] for key in _MODELS_DEV_METADATA if key in entry}
    if entry.get("status") == "deprecated":
        metadata["deprecated"] = True

    return Model(
        id=str(entry.get("id") or model_id),
        type=model_type,
        display_name=_string_or_none(entry.get("name")),
        description=_string_or_none(entry.get("description")),
        released_at=_date_or_none(entry.get("release_date")),
        context_window_tokens=_positive_int(limit.get("context")),
        max_output_tokens=_positive_int(limit.get("output")),
        capabilities=capabilities,  # type: ignore[arg-type]
        metadata=metadata,
    )


def _model_type(entry: Mapping[str, Any]) -> ModelType | None:
    """Classify a models.dev entry, or return ``None`` when unsupported.

    models.dev only sets an explicit ``type`` on aggregator entries. Native
    provider entries identify embeddings and rerankers by name instead, and
    report their output modality as plain text, so both signals are used.
    """
    declared = entry.get("type")
    if declared is not None:
        return _MODELS_DEV_TYPES.get(str(declared))
    outputs = set(_sequence(_mapping(entry.get("modalities")).get("output")))
    if "embedding" in outputs:
        return ModelType.EMBEDDING
    if outputs - {"text"}:
        return None
    name = f"{entry.get('id', '')} {entry.get('family', '')}".lower()
    if "embedding" in name:
        return ModelType.EMBEDDING
    if "rerank" in name:
        return ModelType.RERANKING
    return ModelType.CHAT


def _diff_model_cards(
    upstream_card: Mapping[str, Any], vendored_card: Mapping[str, Any]
) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for key in sorted(set(upstream_card) | set(vendored_card)):
        if key == "metadata":
            upstream_metadata = _mapping(upstream_card.get(key))
            vendored_metadata = _mapping(vendored_card.get(key))
            nested = {
                name: {
                    "upstream": upstream_metadata.get(name),
                    "snapshot": vendored_metadata.get(name),
                }
                for name in sorted(set(upstream_metadata) | set(vendored_metadata))
                if upstream_metadata.get(name) != vendored_metadata.get(name)
            }
            if nested:
                changes[key] = nested
            continue
        if upstream_card.get(key) != vendored_card.get(key):
            changes[key] = {
                "upstream": upstream_card.get(key),
                "snapshot": vendored_card.get(key),
            }
    return changes


def _diff_provider_fields(
    upstream_provider: Mapping[str, Any] | None,
    vendored_provider: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(upstream_provider, Mapping) or not isinstance(
        vendored_provider, Mapping
    ):
        return {}
    return {
        key: {
            "upstream": upstream_provider.get(key),
            "snapshot": vendored_provider.get(key),
        }
        for key in _MODELS_DEV_PROVIDER_KEYS
        if upstream_provider.get(key) != vendored_provider.get(key)
    }


def _source_provider_id(document: Mapping[str, Any]) -> str | None:
    """Return the models.dev provider a provider document sources data from."""
    source = document.get("source")
    if isinstance(source, str):
        provider_id = document.get("id")
        if source != MODELS_DEV_SOURCE or not isinstance(provider_id, str):
            return None
        return provider_id or None
    if isinstance(source, Mapping):
        upstream = source.get(MODELS_DEV_SOURCE)
        return upstream if isinstance(upstream, str) and upstream else None
    settings = document.get("settings")
    if isinstance(settings, Mapping):
        upstream = settings.get(MODELS_DEV_SETTING)
        return upstream if isinstance(upstream, str) and upstream else None
    return None


def _models(
    entry: Mapping[str, Any] | None, *, provider_id: str | None = None
) -> Mapping[str, Any]:
    """Return a provider entry's ``models`` mapping, tolerating malformed input."""
    if not isinstance(entry, Mapping):
        return {}
    models = entry.get("models")
    if models is None:
        return {}
    if not isinstance(models, Mapping):
        label = provider_id or entry.get("id", "?")
        raise ConfigurationError(
            f"models.dev provider '{label}' has a non-mapping 'models' value"
        )
    return models


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return ()


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _date_or_none(value: Any) -> date | None:
    """Parse a models.dev release date, ignoring partial values like '2026-01'."""
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None
