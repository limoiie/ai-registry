from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ai_registry import Registry
from ai_registry.config import (
    load_account_file,
    load_document,
    normalize_provider,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_representative_catalog_resolves_aliases_and_preserves_adapter_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = load_document(FIXTURES / "catalog.yaml")
    registry_data = load_document(FIXTURES / "registry.yaml")
    providers = [normalize_provider(provider) for provider in catalog["providers"]]
    accounts = load_account_file(FIXTURES / "registry.yaml")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    registry = Registry.from_data(
        providers=providers,
        accounts=accounts,
        aliases=registry_data["aliases"],
    )

    expected_aliases = {
        "deepseek-chat": ("deepseek-account", "deepseek-chat"),
        "minimax-coding": ("minimax-account", "MiniMax-M2.7"),
        "embedding-default": ("uniapi-account", "bge-large-zh:latest"),
        "reranking-default": ("reranker-account", "bge-reranker-v2-m3"),
    }
    for alias, (account_id, model_id) in expected_aliases.items():
        result = registry.resolve(alias)
        assert (result.account_id, result.model_id) == (account_id, model_id)

    direct = registry.resolve("uniapi-account/bge-large-zh:latest")
    assert direct.model.type.value == "embedding"
    assert direct.model.embedding_dimension == 1024

    custom_endpoint = registry.resolve("custom-openai-chat")
    assert custom_endpoint.endpoint == "https://gateway.example.test/v1"
    assert custom_endpoint.endpoint_metadata == {
        "provider_name": "internal-gateway",
        "supports_json_mode": True,
    }
    assert custom_endpoint.resolve_credential() == "test-secret"

    assert {provider.id for provider in providers} == {
        "deepseek",
        "uniapi",
        "minimax",
        "uniapi-rerankers",
    }


def test_registry_core_does_not_import_optional_sdks() -> None:
    script = """
import sys

from ai_registry import Registry
from ai_registry.schemas import Account, Model, Provider

provider = Provider(
    id="provider",
    name="Provider",
    models=[Model(id="chat", type="chat")],
)
account = Account(id="account", provider_id="provider", enabled_models=["chat"])
Registry.from_data(providers=[provider], accounts=[account])

optional_sdks = {"openai", "anthropic", "langchain", "litellm"}
loaded = optional_sdks.intersection(sys.modules)
if loaded:
    raise SystemExit(f"optional SDKs imported: {sorted(loaded)}")
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
