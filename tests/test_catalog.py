from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ai_registry.catalog import load_models_dev, models_dev_provider
from ai_registry.errors import ConfigurationError
from ai_registry.schemas import ModelType

# Shaped after the real models.dev api.json document.
MODELS_DEV: dict[str, Any] = {
    "anthropic": {
        "name": "Anthropic",
        "doc": "https://docs.anthropic.com",
        "env": ["ANTHROPIC_API_KEY"],
        "models": {
            "claude-sonnet-4-6": {
                "id": "claude-sonnet-4-6",
                "name": "Claude Sonnet 4.6",
                "description": "Claude workhorse for coding agents.",
                "family": "claude-sonnet",
                "attachment": True,
                "reasoning": True,
                "reasoning_options": [{"type": "toggle"}],
                "tool_call": True,
                "temperature": True,
                "knowledge": "2025-08-31",
                "release_date": "2026-02-17",
                "last_updated": "2026-03-13",
                "modalities": {"input": ["text", "image", "pdf"], "output": ["text"]},
                "open_weights": False,
                "limit": {"context": 1000000, "output": 64000},
                "cost": {
                    "input": 3,
                    "output": 15,
                    "cache_read": 0.3,
                    "cache_write": 3.75,
                },
            }
        },
    },
    "openai": {
        "name": "OpenAI",
        "env": ["OPENAI_API_KEY"],
        "models": {
            "text-embedding-3-small": {
                "id": "text-embedding-3-small",
                "name": "Text Embedding 3 Small",
                "tool_call": False,
                "modalities": {"input": ["text"], "output": ["embedding"]},
                "limit": {"context": 8191, "output": 0},
                "cost": {"input": 0.02, "output": 0},
            }
        },
    },
}


def test_models_dev_entry_maps_onto_the_provider_schema() -> None:
    provider = models_dev_provider(
        "anthropic",
        MODELS_DEV["anthropic"],
        default_base_url="https://api.anthropic.com/v1",
    )

    assert provider.id == "anthropic"
    assert provider.name == "Anthropic"
    assert provider.default_base_url == "https://api.anthropic.com/v1"
    assert provider.settings["env"] == ["ANTHROPIC_API_KEY"]
    assert provider.settings["source"] == "models.dev"

    card = provider.models[0]
    assert card.id == "claude-sonnet-4-6"
    assert card.display_name == "Claude Sonnet 4.6"
    assert card.type is ModelType.CHAT
    assert card.context_window_tokens == 1_000_000
    assert card.max_output_tokens == 64_000
    assert str(card.released_at) == "2026-02-17"


def test_models_dev_capabilities_use_the_shared_synonym_table() -> None:
    provider = models_dev_provider("anthropic", MODELS_DEV["anthropic"])
    capabilities = provider.models[0].capabilities

    # models.dev spells tool support "tool_call", not "tools".
    assert capabilities.tools is True
    assert capabilities.reasoning is True
    # An "image" input modality implies vision.
    assert capabilities.vision is True
    assert capabilities.structured_output is False


def test_models_dev_pricing_and_extras_are_preserved_as_metadata() -> None:
    card = models_dev_provider("anthropic", MODELS_DEV["anthropic"]).models[0]

    assert card.metadata["cost"] == {
        "input": 3,
        "output": 15,
        "cache_read": 0.3,
        "cache_write": 3.75,
    }
    assert card.metadata["knowledge"] == "2025-08-31"
    assert card.metadata["modalities"]["input"] == ["text", "image", "pdf"]
    assert card.metadata["open_weights"] is False


def test_embedding_output_modality_selects_the_embedding_model_type() -> None:
    provider = models_dev_provider("openai", MODELS_DEV["openai"])
    card = provider.models[0]

    assert card.type is ModelType.EMBEDDING
    assert card.context_window_tokens == 8191
    # models.dev reports 0 for "not applicable"; the schema requires >= 1.
    assert card.max_output_tokens is None


def test_load_models_dev_filters_providers_and_assigns_endpoints() -> None:
    providers = load_models_dev(
        MODELS_DEV,
        provider_ids={"openai"}.__contains__,
        default_base_url={"openai": "https://api.openai.com/v1"},
    )

    assert [provider.id for provider in providers] == ["openai"]
    assert providers[0].default_base_url == "https://api.openai.com/v1"


def test_load_models_dev_reads_a_vendored_json_document(tmp_path: Path) -> None:
    document = tmp_path / "api.json"
    document.write_text(json.dumps(MODELS_DEV), encoding="utf-8")

    providers = load_models_dev(document)

    assert [provider.id for provider in providers] == ["anthropic", "openai"]


def test_load_models_dev_rejects_malformed_entries() -> None:
    with pytest.raises(ConfigurationError, match=r"must be a mapping"):
        load_models_dev({"broken": ["not", "a", "mapping"]})

    with pytest.raises(ConfigurationError, match=r"non-mapping 'models'"):
        load_models_dev({"broken": {"name": "Broken", "models": []}})

    with pytest.raises(ConfigurationError, match=r"model 'bad' must be a mapping"):
        load_models_dev({"broken": {"models": {"bad": "oops"}}})


def test_imported_providers_are_usable_by_the_registry() -> None:
    from ai_registry import Registry

    registry = Registry.from_data(
        providers=load_models_dev(
            MODELS_DEV,
            provider_ids={"anthropic"}.__contains__,
            default_base_url={"anthropic": "https://api.anthropic.com/v1"},
        ),
        accounts=[
            {
                "id": "anthropic-primary",
                "provider_id": "anthropic",
                "credential": "env:ANTHROPIC_API_KEY",
                "enabled_models": ["claude-sonnet-4-6"],
            }
        ],
        aliases=[
            {
                "id": "chat-default",
                "deployments": [
                    {
                        "account_id": "anthropic-primary",
                        "model_id": "claude-sonnet-4-6",
                    }
                ],
            }
        ],
    )

    resolution = registry.resolve("chat-default")

    assert resolution.model.context_window_tokens == 1_000_000
    assert resolution.model.capabilities.tools is True
    assert resolution.endpoint == "https://api.anthropic.com/v1"
