"""Import third-party model catalogs into the registry's provider schema.

Hand-maintaining context windows, pricing and capability flags does not scale:
the ecosystem now has community catalogs covering thousands of models. This
module converts them into :class:`~ai_registry.schemas.Provider` objects so the
registry can consume one instead.

Consistent with the rest of the core, nothing here performs network access. Point
these loaders at a catalog file you vendor and refresh deliberately — a
resolution layer should not change behavior because an upstream file changed
under it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ai_registry.config import PathSource, load_document
from ai_registry.errors import ConfigurationError
from ai_registry.schemas import (
    ModelCard,
    ModelType,
    Provider,
    normalize_capabilities,
)

__all__ = ["load_models_dev", "models_dev_provider"]

#: models.dev capability keys, mapped onto ``ModelCapabilities`` fields by
#: :func:`~ai_registry.schemas.normalize_capabilities`.
_MODELS_DEV_ABILITIES = ("tool_call", "reasoning", "structured_output")

#: models.dev keys preserved on the model card's free-form ``metadata``.
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
    models = entry.get("models", {})
    if models is None:
        models = {}
    if not isinstance(models, Mapping):
        raise ConfigurationError(
            f"models.dev provider '{provider_id}' has a non-mapping 'models' value"
        )
    settings: dict[str, Any] = {"source": "models.dev"}
    for key in ("doc", "env", "npm", "api"):
        if key in entry:
            settings[key] = entry[key]
    return Provider(
        id=provider_id,
        name=str(entry.get("name") or provider_id),
        default_base_url=default_base_url or _string_or_none(entry.get("api")),
        settings=settings,
        model_cards=[
            _model_card(model_id, models[model_id]) for model_id in sorted(models)
        ],
    )


def _model_card(model_id: str, entry: Any) -> ModelCard:
    if not isinstance(entry, Mapping):
        raise ConfigurationError(f"models.dev model '{model_id}' must be a mapping")
    limit = _mapping(entry.get("limit"))
    modalities = _mapping(entry.get("modalities"))
    abilities = {key: entry[key] for key in _MODELS_DEV_ABILITIES if key in entry}
    capabilities = normalize_capabilities(abilities)
    if "image" in _sequence(modalities.get("input")):
        capabilities["vision"] = True

    return ModelCard(
        id=str(entry.get("id") or model_id),
        type=_model_type(modalities),
        display_name=_string_or_none(entry.get("name")),
        description=_string_or_none(entry.get("description")),
        released_at=_string_or_none(entry.get("release_date")),  # type: ignore[arg-type]
        context_window_tokens=_positive_int(limit.get("context")),
        max_output_tokens=_positive_int(limit.get("output")),
        capabilities=capabilities,  # type: ignore[arg-type]
        metadata={key: entry[key] for key in _MODELS_DEV_METADATA if key in entry},
    )


def _model_type(modalities: Mapping[str, Any]) -> ModelType:
    outputs = _sequence(modalities.get("output"))
    if "embedding" in outputs:
        return ModelType.EMBEDDING
    return ModelType.CHAT


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return ()


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None
