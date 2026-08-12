# Multi-Protocol Provider Endpoints Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let a provider declare multiple named upstream endpoints (protocol + base URL + mode), let an account select one by name, and surface the effective `sdk_type`/`mode` on `Resolution` so adapters route correctly.

**Architecture:** Add an optional `endpoints` map to `Provider` (keys are endpoint ids; each entry bundles `sdk_type`, `base_url`, optional `mode` defaulting to `chat`). Add `Account.endpoint_ref` to name one. `_resolution` derives an effective `sdk_type`/`mode`/`endpoint` and validates model availability. Adapters read `resolution.sdk_type`/`resolution.mode` instead of `resolution.provider.sdk_type`. Providers without `endpoints` behave exactly as before (backward compatible).

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, ruff, mypy, uv.

---

### Task 1: Add ProviderEndpoint schema and Provider.endpoints

**Files:**
- Modify: `src/ai_registry/schemas.py`
- Test: `tests/test_schemas.py`

**Step 1: Read the current schema section**

Read `src/ai_registry/schemas.py` lines ~350-393 (the `Provider`/`SafeModel`/`SDKType`/`ModelCard` definitions) to place edits precisely.

**Step 2: Write the failing tests**

Add to `tests/test_schemas.py`:

```python
def test_provider_endpoint_and_mode_parsed() -> None:
    provider = Provider.model_validate(
        {
            "id": "deepseek",
            "name": "DeepSeek",
            "endpoints": {
                "openai-chat": {"sdk_type": "openai", "base_url": "https://api.deepseek.com"},
                "openai-responses": {
                    "sdk_type": "openai",
                    "base_url": "https://api.deepseek.com",
                    "mode": "responses",
                },
                "anthropic": {
                    "sdk_type": "anthropic",
                    "base_url": "https://api.deepseek.com/anthropic",
                },
            },
        }
    )
    assert provider.endpoints["openai-chat"].sdk_type is SDKType.OPENAI
    assert provider.endpoints["openai-responses"].mode == "responses"
    assert provider.endpoints["anthropic"].mode == "chat"


def test_provider_endpoint_rejects_unknown_mode() -> None:
    with pytest.raises(ValidationError):
        Provider.model_validate(
            {
                "id": "p",
                "name": "P",
                "endpoints": {"x": {"sdk_type": "openai", "mode": "bogus"}},
            }
        )


def test_account_endpoint_ref_roundtrip() -> None:
    account = Account.model_validate(
        {
            "id": "a",
            "provider_id": "p",
            "endpoint_ref": "openai-responses",
            "credential": "env:KEY",
        }
    )
    assert account.endpoint_ref == "openai-responses"


def test_account_rejects_endpoint_and_endpoint_ref() -> None:
    with pytest.raises(ValidationError):
        Account.model_validate(
            {
                "id": "a",
                "provider_id": "p",
                "endpoint": "https://x/v1",
                "endpoint_ref": "chat",
            }
        )
```

**Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_schemas.py -q`
Expected: FAIL (endpoints/mode/endpoint_ref attribute errors).

**Step 4: Implement**

In `src/ai_registry/schemas.py`:

- Add a `ModelMode` enum after `SDKType`:

```python
class ModelMode(StrEnum):
    CHAT = "chat"
    RESPONSES = "responses"
```

- Add a `ProviderEndpoint` model before `Provider`:

```python
class ProviderEndpoint(SafeModel):
    sdk_type: SDKType = SDKType.OPENAI
    base_url: str | None = None
    mode: ModelMode = ModelMode.CHAT

    _validate_endpoint = field_validator("base_url")(_validate_endpoint)
```

- On `Provider`, add the field:

```python
endpoints: Mapping[str, ProviderEndpoint] = Field(default_factory=dict)
```

- On `Account`, add the field plus a model validator rejecting the conflict:

```python
endpoint_ref: Identifier | None = None

@model_validator(mode="after")
def validate_endpoint_ref(self) -> Account:
    if self.endpoint_ref is not None and self.endpoint is not None:
        raise ValueError("cannot set both endpoint and endpoint_ref; use one")
    return self
```

Note: `Account` uses `Identifier` (already imported). Add the new validator inside the `Account` class and keep the existing `_validate_endpoint`/`_validate_id` validators.

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_schemas.py -q`
Expected: PASS.

**Step 6: Commit**

```bash
git add src/ai_registry/schemas.py tests/test_schemas.py
git commit -m "feat: add ProviderEndpoint and Account.endpoint_ref to schemas"
```

### Task 2: Normalize endpoints and validate endpoint_ref in config.py

**Files:**
- Modify: `src/ai_registry/config.py`
- Test: `tests/test_config.py`

**Step 1: Read `normalize_provider` and `_parse_accounts`**

Read `src/ai_registry/config.py` (~lines 123-168 for accounts, 217-309 for `normalize_provider`).

**Step 2: Write failing tests**

Add to `tests/test_config.py`:

```python
def test_provider_endpoints_parse_from_file(tmp_path: Path) -> None:
    path = tmp_path / "deepseek-multi.yml"
    path.write_text(
        "id: deepseek\n"
        "name: DeepSeek\n"
        "endpoints:\n"
        "  openai-chat:\n"
        "    sdk_type: openai\n"
        "    base_url: https://api.deepseek.com\n"
        "  openai-responses:\n"
        "    sdk_type: openai\n"
        "    base_url: https://api.deepseek.com\n"
        "    mode: responses\n",
        encoding="utf-8",
    )
    provider = load_provider_file(path)
    assert "openai-responses" in provider.endpoints
    assert provider.endpoints["openai-responses"].mode.value == "responses"


def test_account_endpoint_ref_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "accounts.yml"
    path.write_text(
        "accounts:\n"
        "  - id: a\n"
        "    provider_id: deepseek\n"
        "    endpoint_ref: anthropic\n"
        "    api_key_env: KEY\n",
        encoding="utf-8",
    )
    accounts = load_account_file(path)
    assert accounts[0].endpoint_ref == "anthropic"
```

**Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_provider_endpoints_parse_from_file tests/test_config.py::test_account_endpoint_ref_is_kept -q`
Expected: FAIL (endpoints not populated / endpoint_ref stripped).

**Step 4: Implement**

- `_parse_accounts`: `endpoint_ref` passes through `Account.model_validate` unchanged — no code needed; the failing test covers the round-trip. If `endpoint_ref` is rejected as `api_key_env` conflict, confirm order; no change required.
- `normalize_provider`: `endpoints` is already a mapping; `Provider` validates it. No transformation required beyond passing it through. Add a guard so `proxy_url.placeholder` only becomes `default_base_url` when `endpoints` is empty AND `default_base_url` is None (legacy behavior). Update the `_proxy_url_placeholder` call site:

```python
if value.get("default_base_url") is None:
    endpoints = value.get("endpoints") or {}
    if not endpoints:
        placeholder = _proxy_url_placeholder(settings)
        if placeholder is not None:
            value["default_base_url"] = placeholder
```

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -q`
Expected: PASS.

**Step 6: Commit**

```bash
git add src/ai_registry/config.py tests/test_config.py
git commit -m "feat: normalize provider endpoints and account endpoint_ref"
```

### Task 3: Resolve effective sdk_type, mode, and endpoint in Registry

**Files:**
- Modify: `src/ai_registry/registry.py`
- Test: `tests/test_registry.py`

**Step 1: Read `Resolution`, `_resolution`, `_validate_references`, `_validate_model_enabled`**

Read `src/ai_registry/registry.py` lines 81-150 (`Resolution`), 437-500 (`_resolution`/validation).

**Step 2: Write failing tests**

Add to `tests/test_registry.py`:

```python
from ai_registry.testing import build_registry


def test_resolution_exposes_selected_endpoint_mode() -> None:
    registry = build_registry({"a": ["p/m"]})
    # override provider with endpoints + account endpoint_ref
    provider = registry.get_provider("p").model_copy(
        update={
            "endpoints": {
                "chat": {"sdk_type": "openai", "base_url": "https://x/v1"},
                "responses": {
                    "sdk_type": "openai",
                    "base_url": "https://x",
                    "mode": "responses",
                },
            }
        }
    )
    account = registry.get_account("a").model_copy(update={"endpoint_ref": "responses"})
    registry2 = Registry.from_data(
        providers=[provider], accounts=[account], secret_resolver=...
    )
    resolution = registry2.resolve("a/m")
    assert resolution.sdk_type.value == "openai"
    assert resolution.mode.value == "responses"
    assert resolution.endpoint == "https://x"
```

(Hint: read `Registry.from_data` signature in `tests/test_registry.py` first and mirror an existing construction pattern with `constant_secret_resolver`.)

Add a model-availability rejection test:

```python
def test_model_not_supported_by_endpoint_is_rejected() -> None:
    # provider endpoints: only "responses"; model declares endpoints: [chat]
    # account endpoint_ref=responses enable=model -> raises RegistryError
    ...
```

**Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_registry.py::test_resolution_exposes_selected_endpoint_mode -v`
Expected: FAIL (no `sdk_type`/`mode` on Resolution / endpoint not applied).

**Step 4: Implement**

- Add `mode` field to `Resolution` (default resolved in `_resolution`). Change `_resolution`:

```python
endpoint = result_account.endpoint or result_provider.default_base_url
sdk_type = result_provider.sdk_type
mode_model = ModelMode.CHAT
if result_account.endpoint_ref is not None:
    selected = result_provider.endpoints[result_account.endpoint_ref]
    endpoint = selected.base_url
    sdk_type = selected.sdk_type
    mode_model = selected.mode
```

- Add `sdk_type: SDKType` and `mode: ModelMode` fields to `Resolution`. Update `otel_attributes` and `__repr__` to use `self.sdk_type`.
- Add model-availability validation in `_validate_model_enabled`: when `account.endpoint_ref` is set and the model card declares a non-empty `endpoints` set that excludes the endpoint, raise `RegistryError`. Thread the resolved provider endpoint set into the check (`card.endpoints`).
- Update adapters import: `ModelMode` may need to be imported into `registry.py` from `ai_registry.schemas`.

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_registry.py tests/test_adapters.py tests/test_integration.py -q`
Expected: PASS.

**Step 6: Commit**

```bash
git add src/ai_registry/registry.py tests/test_registry.py
git commit -m "feat: resolve sdk_type, mode, and endpoint from selected provider endpoint"
```

### Task 4: Add ModelCard.endpoints supported-set

**Files:**
- Modify: `src/ai_registry/schemas.py`
- Test: `tests/test_schemas.py`, `tests/test_registry.py`

**Step 1: Write failing test**

In `tests/test_schemas.py`:

```python
def test_model_card_endpoint_support_set() -> None:
    card = ModelCard.model_validate(
        {"id": "m", "type": "chat", "endpoints": ["openai-chat", "anthropic"]}
    )
    assert card.endpoints == ["openai-chat", "anthropic"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_schemas.py -q`
Expected: FAIL (no `endpoints` field).

**Step 3: Implement**

On `ModelCard`, add:

```python
endpoints: list[str] | None = Field(default=None, min_length=1)
```

(Names are validated against provider endpoint ids during registry resolution, not at card parse time.)

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_schemas.py -q`
Expected: PASS. (Re-run Task 3's availability test — it should now pass since `card.endpoints` parses.)

**Step 5: Commit**

```bash
git add src/ai_registry/schemas.py tests/test_schemas.py
git commit -m "feat: add optional endpoint supported-set to model cards"
```

### Task 5: Update adapters to use resolution.sdk_type and mode

**Files:**
- Modify: `src/ai_registry/adapters/openai.py`, `src/ai_registry/adapters/pydantic_ai.py`
- Test: `tests/test_adapters.py`

**Step 1: Write failing tests**

Update the `resolution(...)` helper in `tests/test_adapters.py` to accept and forward an endpoint `mode`, then add:

```python
def test_openai_adapter_reads_resolution_sdk_type() -> None:
    # resolution with provider.sdk_type ANTHROPIC but a selected openai endpoint
    # must still build an openai client (uses resolution.sdk_type)
    ...
```

Use `build_registry` with a provider whose `endpoints` select `openai` while `provider.sdk_type` stays `anthropic`, and assert `client_kwargs(resolution)` builds without raising.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_adapters.py -q`
Expected: FAIL (adapter still reads provider.sdk_type and raises).

**Step 3: Implement**

- `adapters/openai.py::_import_openai` and `client_kwargs`: read `resolution.sdk_type` instead of `resolution.provider.sdk_type`.
- `adapters/pydantic_ai.py::build_model`: read `resolution.sdk_type`; branch opens on that. Keep the error message referencing the resolved value.
- Keep `mode` available for future responses routing; the OpenAI adapter's `client_kwargs` does not change behavior for `mode` yet (responses call selection is out of scope beyond carrying the value on `Resolution`).

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_adapters.py tests/test_integration.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/ai_registry/adapters/openai.py src/ai_registry/adapters/pydantic_ai.py tests/test_adapters.py
git commit -m "feat: adapters read resolved sdk_type and mode"
```

### Task 6: Add an endpoint-aware DeepSeek fixture and docs

**Files:**
- Create: `tests/fixtures/deepseek-endpoints.yml`
- Modify: `tests/test_config.py`, `docs/configuration.md`, `docs/getting-started.md`, `docs/api-reference.md`

**Step 1: Create the multi-endpoint DeepSeek fixture**

`tests/fixtures/deepseek-endpoints.yml` with the three endpoints from the design and two model cards (`deepseek-v4-flash` with `endpoints: [openai-chat, openai-responses, anthropic]`, `deepseek-v4-pro` with `endpoints: [openai-chat, anthropic]`).

**Step 2: Write a test**

In `tests/test_config.py`:

```python
def test_multi_endpoint_fixture_loads() -> None:
    provider = load_provider_file(FIXTURES / "deepseek-endpoints.yml")
    assert set(provider.endpoints) == {"openai-chat", "openai-responses", "anthropic"}
    flash = next(c for c in provider.model_cards if c.id == "deepseek-v4-flash")
    assert flash.endpoints == ["openai-chat", "openai-responses", "anthropic"]
```

**Step 3: Update docs**

- `docs/configuration.md`: document the `endpoints` map, `Account.endpoint_ref`, `mode`, and the legacy `endpoint` + `sdk_type` default behavior. Add a `multi-endpoint_deepseek` example.
- `docs/getting-started.md`: brief mention that some providers declare multiple endpoints selectable per account.
- `docs/api-reference.md`: add `Provider.endpoints`, `ProviderEndpoint`, `Account.endpoint_ref`, `ModelCard.endpoints`, `Resolution.sdk_type`/`mode` to the field tables.

**Step 4: Run tests and lint**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src tests`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/fixtures/deepseek-endpoints.yml tests/test_config.py docs/configuration.md docs/getting-started.md docs/api-reference.md
git commit -m "docs: add multi-protocol endpoint examples and reference"
```

### Task 7: Full verification

**Step 1: Run the full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv lock --check`
Expected: all pass.

**Step 2: Commit any residual formatting**

```bash
git add -A && git commit -m "chore: final multi-protocol endpoint verification"
```