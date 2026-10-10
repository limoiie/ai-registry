from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ai_registry.catalog import (
    builtin_models_dev_snapshot,
    diff_models_dev,
    hydrate_models_dev_models,
    load_models_dev,
    models_dev_provider,
    models_dev_provider_ids,
    models_dev_provider_ids_from_documents,
    models_dev_snapshot_json,
    models_dev_snapshot_readme,
    sync_models_dev_snapshot,
)
from ai_registry.errors import ConfigurationError
from ai_registry.schemas import Model, ModelType, Provider

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


# --- representable models ----------------------------------------------------


def test_unsupported_output_modalities_are_not_mistyped_as_chat() -> None:
    provider = models_dev_provider(
        "openai",
        {
            "models": {
                "gpt-image-2": {
                    "id": "gpt-image-2",
                    "modalities": {"input": ["text"], "output": ["image"]},
                },
                "gpt-5.6": {
                    "id": "gpt-5.6",
                    "modalities": {"input": ["text"], "output": ["text"]},
                },
            }
        },
    )

    assert [card.id for card in provider.models] == ["gpt-5.6"]


def test_native_embeddings_and_rerankers_are_typed_by_name() -> None:
    # models.dev reports text output for native embeddings and rerankers, so only
    # the id/family distinguish them.
    provider = models_dev_provider(
        "openai",
        {
            "models": {
                "text-embedding-3-large": {
                    "id": "text-embedding-3-large",
                    "family": "text-embedding",
                    "modalities": {"input": ["text"], "output": ["text"]},
                },
                "bge-reranker-v2-m3": {
                    "id": "bge-reranker-v2-m3",
                    "family": "bge",
                    "modalities": {"input": ["text"], "output": ["text"]},
                },
            }
        },
    )

    types = {card.id: card.type for card in provider.models}
    assert types["text-embedding-3-large"] is ModelType.EMBEDDING
    assert types["bge-reranker-v2-m3"] is ModelType.RERANKING


def test_declared_types_win_and_unknown_ones_are_skipped() -> None:
    provider = models_dev_provider(
        "gateway",
        {
            "models": {
                "embed": {
                    "id": "embed",
                    "type": "embedding",
                    "modalities": {"input": ["text"], "output": ["text"]},
                },
                "future": {"id": "future", "type": "hologram"},
            }
        },
    )

    assert [(card.id, card.type) for card in provider.models] == [
        ("embed", ModelType.EMBEDDING)
    ]


# --- vendored snapshot and hydration -----------------------------------------

#: A trimmed models.dev document shaped exactly like the vendored snapshot.
SNAPSHOT: dict[str, Any] = {
    "minimax": {
        "id": "minimax",
        "name": "MiniMax",
        "env": ["MINIMAX_API_KEY"],
        "doc": "https://platform.minimaxi.com",
        "api": "https://api.minimax.io/v1",
        "models": {
            "MiniMax-M3": {
                "id": "MiniMax-M3",
                "name": "MiniMax M3",
                "description": "Flagship model.",
                "release_date": "2026-06-01",
                "tool_call": True,
                "reasoning": True,
                "modalities": {"input": ["text", "image"], "output": ["text"]},
                "limit": {"context": 1_000_000, "output": 512_000},
                "cost": {"input": 0.3, "output": 1.2},
            },
            "MiniMax-M2": {
                "id": "MiniMax-M2",
                "name": "MiniMax M2",
                "status": "deprecated",
                "release_date": "2026-01",
                "modalities": {"input": ["text"], "output": ["text"]},
                "limit": {"context": 204_800, "output": 131_072},
            },
            "MiniMax-image": {
                "id": "MiniMax-image",
                "modalities": {"input": ["text"], "output": ["image"]},
            },
        },
    }
}


def _by_id(cards: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(card["id"]): card for card in cards}


def test_hydration_builds_the_model_set_from_the_snapshot() -> None:
    hydrated = hydrate_models_dev_models(
        [], upstream_provider_id="minimax", snapshot=SNAPSHOT
    )

    # Every representable snapshot model becomes a card; unsupported output
    # modalities are skipped.
    assert sorted(_by_id(hydrated)) == ["MiniMax-M2", "MiniMax-M3"]
    m3 = _by_id(hydrated)["MiniMax-M3"]
    assert m3["type"] == "chat"
    assert m3["display_name"] == "MiniMax M3"
    assert m3["context_window_tokens"] == 1_000_000
    assert m3["max_output_tokens"] == 512_000
    assert m3["released_at"] == "2026-06-01"
    assert m3["capabilities"]["vision"] is True
    assert m3["metadata"]["cost"] == {"input": 0.3, "output": 1.2}


def test_hydration_keeps_local_declarations_on_top() -> None:
    hydrated = hydrate_models_dev_models(
        [
            {
                "id": "MiniMax-M3",
                "context_window_tokens": 123,
                "endpoints": ["cn-openai"],
                "metadata": {"cost": {"input": 9.0}},
            }
        ],
        upstream_provider_id="minimax",
        snapshot=SNAPSHOT,
    )

    m3 = _by_id(hydrated)["MiniMax-M3"]
    assert m3["context_window_tokens"] == 123
    assert m3["endpoints"] == ["cn-openai"]
    # A declared field replaces the upstream value outright.
    assert m3["metadata"]["cost"] == {"input": 9.0}
    assert m3["max_output_tokens"] == 512_000
    # Models without a local entry still come from the snapshot.
    assert hydrated and "MiniMax-M2" in _by_id(hydrated)


def test_hydration_derives_deprecated_from_upstream_status() -> None:
    hydrated = hydrate_models_dev_models(
        [], upstream_provider_id="minimax", snapshot=SNAPSHOT
    )

    m2 = _by_id(hydrated)["MiniMax-M2"]
    assert m2["metadata"]["deprecated"] is True
    # models.dev also carries partial release dates; only full dates are parsed.
    assert "released_at" not in m2


def test_hydration_keeps_local_only_cards() -> None:
    card = {"id": "MiniMax-M1", "type": "chat", "embedding_dimension": 1024}

    hydrated = hydrate_models_dev_models(
        [card], upstream_provider_id="minimax", snapshot=SNAPSHOT
    )

    # Local-only ids are appended; the upstream set is unaffected.
    assert sorted(_by_id(hydrated)) == [
        "MiniMax-M1",
        "MiniMax-M2",
        "MiniMax-M3",
    ]
    assert _by_id(hydrated)["MiniMax-M1"] == card


def test_hydration_rejects_a_provider_missing_from_the_snapshot() -> None:
    with pytest.raises(ConfigurationError, match="catalog sync"):
        hydrate_models_dev_models(
            [{"id": "mistral-large"}],
            upstream_provider_id="mistral",
            snapshot=SNAPSHOT,
        )


def test_builtin_catalog_is_the_models_dev_set_plus_local_deltas() -> None:
    from ai_registry.config import discover_builtin_providers

    providers = {provider.id: provider for provider in discover_builtin_providers()}
    snapshot = builtin_models_dev_snapshot()

    # Every source'd provider exposes exactly the representable snapshot models.
    for provider_id in models_dev_provider_ids(list(providers.values())):
        upstream = snapshot[provider_id]["models"]
        expected = {
            model_id
            for model_id, entry in upstream.items()
            if entry.get("modalities", {}).get("output", ["text"]) == ["text"]
        }
        assert {model.id for model in providers[provider_id].models} == expected

    # Local deltas survive hydration: embedding dimensions and endpoint
    # availability that models.dev does not report.
    openai = {model.id: model for model in providers["openai"].models}
    assert openai["text-embedding-3-large"].type is ModelType.EMBEDDING
    assert openai["text-embedding-3-large"].embedding_dimension == 3072
    deepseek = {model.id: model for model in providers["deepseek"].models}
    assert deepseek["deepseek-v4-flash"].endpoints == [
        "openai-chat",
        "openai-responses",
        "anthropic",
    ]
    assert deepseek["deepseek-v4-flash"].metadata["deprecated"] is True

    # uniapi is not carried by models.dev, so it stays fully local.
    assert "uniapi" not in snapshot
    uniapi = providers["uniapi"]
    assert any(model.type is ModelType.RERANKING for model in uniapi.models)


def test_vendored_snapshot_holds_only_representable_models() -> None:
    snapshot = builtin_models_dev_snapshot()

    assert sorted(snapshot) == [
        "alibaba",
        "anthropic",
        "deepseek",
        "google",
        "minimax",
        "moonshotai",
        "openai",
        "xai",
        "zhipuai",
    ]
    for provider_id, entry in snapshot.items():
        assert entry["id"] == provider_id
        for model_id, model in entry["models"].items():
            output = model.get("modalities", {}).get("output", ["text"])
            assert output == ["text"], (provider_id, model_id)


# --- provider ids, diff and sync ---------------------------------------------


def test_provider_ids_read_the_source_shorthand() -> None:
    documents: list[dict[str, Any]] = [
        {"id": "google", "source": "models.dev", "models": []},
        {"id": "kimi", "source": {"models.dev": "moonshotai"}},
        {"id": "uniapi", "models": []},
        {"id": "zhipuai", "settings": {"models_dev": "zhipuai"}},
    ]

    assert models_dev_provider_ids_from_documents(documents) == [
        "google",
        "moonshotai",
        "zhipuai",
    ]


def test_provider_ids_can_come_from_providers() -> None:
    provider = Provider(
        id="google",
        name="Google",
        settings={"models_dev": "google"},
        models=[Model(id="gemini-3.6-flash", type=ModelType.CHAT)],
    )

    assert models_dev_provider_ids([provider]) == ["google"]


def test_diff_reports_added_changed_and_removed_models() -> None:
    upstream = json.loads(json.dumps(SNAPSHOT))
    upstream["minimax"]["models"]["MiniMax-M3"]["limit"]["context"] = 2_000_000
    del upstream["minimax"]["models"]["MiniMax-M2"]
    upstream["minimax"]["models"]["MiniMax-M9"] = {
        "id": "MiniMax-M9",
        "modalities": {"input": ["text"], "output": ["text"]},
        "limit": {"context": 100, "output": 100},
    }

    report = diff_models_dev(["minimax"], upstream, snapshot=SNAPSHOT)

    assert report["drift"] is True
    entry = report["providers"]["minimax"]
    assert entry["changed"]["MiniMax-M3"]["context_window_tokens"] == {
        "upstream": 2_000_000,
        "snapshot": 1_000_000,
    }
    assert entry["added_upstream"] == ["MiniMax-M9"]
    assert entry["missing_upstream"] == ["MiniMax-M2"]


def test_diff_ignores_unrepresentable_models() -> None:
    # SNAPSHOT carries MiniMax-image, which the schema cannot represent: it is
    # neither drift when it appears nor when it disappears.
    report = diff_models_dev(["minimax"], SNAPSHOT, snapshot=SNAPSHOT)

    assert report["drift"] is False
    assert report["providers"]["minimax"]["changed"] == {}


def test_diff_reports_provider_changes_without_failing_the_check() -> None:
    upstream = json.loads(json.dumps(SNAPSHOT))
    upstream["minimax"]["doc"] = "https://new.example"

    report = diff_models_dev(["minimax"], upstream, snapshot=SNAPSHOT)

    assert report["drift"] is False
    assert report["providers"]["minimax"]["provider_changed"] == {
        "doc": {
            "upstream": "https://new.example",
            "snapshot": "https://platform.minimaxi.com",
        }
    }


def test_sync_copies_provider_entries_without_unrepresentable_models() -> None:
    document = sync_models_dev_snapshot(["minimax"], SNAPSHOT)

    assert list(document) == ["minimax"]
    entry = document["minimax"]
    assert entry["name"] == "MiniMax"
    assert entry["api"] == "https://api.minimax.io/v1"
    assert sorted(entry["models"]) == ["MiniMax-M2", "MiniMax-M3"]


def test_sync_requires_the_referenced_provider_upstream() -> None:
    with pytest.raises(ConfigurationError, match="not present"):
        sync_models_dev_snapshot(["mistral"], SNAPSHOT)


def test_snapshot_json_and_readme_describe_the_vendored_data() -> None:
    rendered = models_dev_snapshot_json(SNAPSHOT)

    # Deterministic output keeps refresh diffs reviewable.
    assert rendered == models_dev_snapshot_json(SNAPSHOT)
    assert rendered.endswith("\n")
    assert json.loads(rendered) == SNAPSHOT

    readme = models_dev_snapshot_readme(
        source="https://models.dev/api.json",
        generated_at="2026-10-10",
        document=SNAPSHOT,
    )
    assert "| minimax | `MiniMax-M2`, `MiniMax-M3` |" in readme
    assert "ai-registry catalog sync" in readme
