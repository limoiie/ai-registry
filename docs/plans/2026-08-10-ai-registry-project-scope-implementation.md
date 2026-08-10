# Project-Scope Configuration Discovery Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship the built-in provider catalog as package data, add project-scoped discovery (`.ai-registry/`), merge profiles+aliases into one `deployments.yaml`, and expose it through `Registry.from_project`.

**Architecture:** Move the 4 provider YAMLs into `src/ai_registry/data/providers/` and configure uv package data so they ship in the wheel. Add config-level discovery functions that read built-in providers from `importlib.resources`, project providers from `<root>/.ai-registry/providers/*`, and a single merged file `<root>/.ai-registry/deployments.yaml` containing `profiles` and optional `aliases`. Project providers override built-ins by id. `Registry.from_project` orchestrates discovery and reuses existing validation.

**Tech Stack:** Python 3.11+, uv build backend (`uv_build`), `importlib.resources.files`, PyYAML, Pydantic, pytest, ruff, mypy.

---

### Task 1: Relocate built-in providers into package data

**Files:**
- Create: `src/ai_registry/data/providers/deepseek.yml`, `uniapi.yml`, `minimax.yml`, `uniapi-rerankers.yml` (moved from `data/ai/providers/`)
- Modify: `pyproject.toml` (add package data)
- Modify: `tests/test_config.py` (update `DATA` constant)
- Remove: `data/ai/providers/*.yml`

**Step 1: Write the failing test**

Update `DATA` in `tests/test_config.py`:

```python
DATA = Path(__file__).parents[1] / "src" / "ai_registry" / "data" / "providers"
```

Add a test asserting the data is reachable as package resources:

```python
def test_builtin_provider_data_is_package_data() -> None:
    from importlib import resources

    base = resources.files("ai_registry") / "data" / "providers"
    names = {entry.name for entry in base.iterdir()}
    assert {
        "deepseek.yml",
        "uniapi.yml",
        "minimax.yml",
        "uniapi-rerankers.yml",
    } <= names
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_builtin_provider_data_is_package_data -q`

Expected: FAIL because `src/ai_registry/data/providers/` does not exist.

**Step 3: Move files and confirm package data**

- Move the 4 provider YAML files from `data/ai/providers/` to
  `src/ai_registry/data/providers/` (git mv, same content).
- No `[tool.uv] package-data` key is needed: the `uv_build` backend
  auto-includes every file under the package module directory in the wheel.
  Adding such a key is invalid for uv and breaks settings discovery.

**Step 4: Run test and verify the wheel**

Run: `uv run pytest tests/test_config.py -q` and `uv build`

Expected: provider-loading tests pass from the new path and the wheel contains
the YAML files (inspect with `python -m zipfile -l dist/*.whl`).

**Step 5: Commit**

```bash
git add src/ai_registry/data pyproject.toml tests/test_config.py data/ai/providers
git commit -m "chore: ship built-in provider catalog as package data"
```

### Task 2: Add built-in provider discovery

**Files:**
- Modify: `src/ai_registry/config.py`
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

```python
def test_discovers_builtin_providers_from_package_data() -> None:
    providers = discover_builtin_providers()
    ids = {provider.id for provider in providers}
    assert {"deepseek", "uniapi", "minimax", "uniapi-rerankers"} == ids
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_discovers_builtin_providers_from_package_data -q`

Expected: FAIL with `ImportError: cannot import name 'discover_builtin_providers'`.

**Step 3: Implement discovery**

Add to `config.py`:

```python
from importlib import resources


def discover_builtin_providers() -> list[Provider]:
    base = resources.files("ai_registry") / "data" / "providers"
    providers = [
        _provider_from_text(entry.name, entry.read_text(encoding="utf-8"))
        for entry in base.iterdir()
        if entry.name.lower().endswith((".yaml", ".yml", ".json"))
    ]
    providers.sort(key=lambda provider: provider.id)
    _ensure_unique_provider_ids(providers)
    return providers


def _provider_from_text(name: str, text: str) -> Provider:
    suffix = Path(name).suffix.lower()
    try:
        value = json.loads(text) if suffix == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError):
        format_name = "JSON" if suffix == ".json" else "YAML"
        raise ConfigurationError(
            f"Unable to parse {format_name} provider '{name}'; "
            "check syntax and remove malformed values"
        ) from None
    if not isinstance(value, dict):
        raise ConfigurationError(f"Provider '{name}' must contain a top-level mapping")
    return normalize_provider(value, source_name=name)


def _ensure_unique_provider_ids(providers: list[Provider]) -> None:
    ids = [provider.id for provider in providers]
    duplicates = sorted(
        {provider_id for provider_id in ids if ids.count(provider_id) > 1}
    )
    if duplicates:
        raise ConfigurationError(f"duplicate provider id '{duplicates[0]}'")
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_config.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/ai_registry/config.py tests/test_config.py
git commit -m "feat: discover built-in providers from package data"
```

### Task 3: Project provider discovery and merge

**Files:**
- Modify: `src/ai_registry/config.py`
- Test: `tests/test_config.py`

**Step 1: Write the failing tests**

```python
def test_discovers_project_providers_when_directory_missing(tmp_path: Path) -> None:
    assert discover_project_providers(tmp_path) == []


def test_project_provider_overrides_builtin_by_id(tmp_path: Path) -> None:
    providers_dir = tmp_path / ".ai-registry" / "providers"
    providers_dir.mkdir(parents=True)
    (providers_dir / "uniapi.yml").write_text(
        "id: uniapi\nname: My Uni API\nmodel_cards:\n  - id: custom\n    type: chat\n",
        encoding="utf-8",
    )
    merged = merge_providers(
        discover_builtin_providers(), discover_project_providers(tmp_path)
    )
    uniapi = next(provider for provider in merged if provider.id == "uniapi")
    assert uniapi.name == "My Uni API"
    assert [card.id for card in uniapi.model_cards] == ["custom"]
    assert len({provider.id for provider in merged}) == len(merged)


def test_project_provider_adds_unique_provider(tmp_path: Path) -> None:
    providers_dir = tmp_path / ".ai-registry" / "providers"
    providers_dir.mkdir(parents=True)
    (providers_dir / "my-vllm.yaml").write_text(
        "id: my-vllm\nname: Local vLLM\nmodel_cards:\n  - id: qwen:32b\n    type: chat\n",
        encoding="utf-8",
    )
    merged = merge_providers(
        discover_builtin_providers(), discover_project_providers(tmp_path)
    )
    assert "my-vllm" in {provider.id for provider in merged}
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -k "discover_project or override" -q`

Expected: FAIL with `ImportError`.

**Step 3: Implement**

```python
def discover_project_providers(root: str | Path) -> list[Provider]:
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
    merged = {provider.id: provider for provider in builtin}
    for provider in project:
        merged[provider.id] = provider
    return list(merged.values())
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_config.py -k "discover_project or override" -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/ai_registry/config.py tests/test_config.py
git commit -m "feat: discover and merge project providers"
```

### Task 4: Load merged deployments.yaml

**Files:**
- Modify: `src/ai_registry/config.py` (refactor profile/alias parsing)
- Modify: `src/ai_registry/registry.py` (reuse alias parsing in `from_files`)
- Test: `tests/test_config.py`

**Step 1: Write the failing tests**

```python
def test_loads_merged_deployments_file(tmp_path: Path) -> None:
    path = tmp_path / "deployments.yaml"
    path.write_text(
        "profiles:\n"
        "  - id: primary\n"
        "    provider_id: deepseek\n"
        "    api_key_env: DEEPSEEK_API_KEY\n"
        "    enabled_models: [deepseek-chat]\n"
        "    remark: legacy\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - profile_id: primary\n"
        "        model_id: deepseek-chat\n",
        encoding="utf-8",
    )
    deployments = load_deployments_file(path)
    assert deployments.profiles[0].id == "primary"
    assert deployments.profiles[0].credential is not None
    assert deployments.profiles[0].credential.env == "DEEPSEEK_API_KEY"
    assert deployments.profiles[0].metadata["remark"] == "legacy"
    assert deployments.aliases == [
        {
            "id": "chat-default",
            "deployments": [{"profile_id": "primary", "model_id": "deepseek-chat"}],
        }
    ]


def test_deployments_file_requires_profiles_and_optional_aliases(
    tmp_path: Path,
) -> None:
    path = tmp_path / "deployments.yaml"
    path.write_text("aliases: []\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="profiles"):
        load_deployments_file(path)

    path.write_text("profiles: []\n", encoding="utf-8")
    deployments = load_deployments_file(path)
    assert deployments.profiles == [] and deployments.aliases == []
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -k "deployments" -q`

Expected: FAIL with `ImportError: cannot import name 'load_deployments_file'`.

**Step 3: Implement**

Refactor `config.py`: extract the profile loop from `load_profile_file` into
`_parse_profiles(document, source_name)` and add alias parsing:

```python
def load_profile_file(source: PathSource) -> list[Profile]:
    source_name, _, _ = _source_details(source)
    return _parse_profiles(load_document(source), source_name)


def _parse_profiles(document: Mapping[str, Any], source_name: str) -> list[Profile]:
    values = document.get("profiles")
    if not isinstance(values, list):
        raise ConfigurationError(
            f"Profile configuration '{source_name}' must contain a 'profiles' list"
        )
    profiles: list[Profile] = []
    for index, value in enumerate(values):
        # existing normalization body (api_key_env, remark, description, metadata)
        ...
    return profiles


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
                f"Alias configuration '{source_name}' has an invalid alias at index {index}"
            )
        aliases.append(dict(value))
    return aliases


@dataclass(frozen=True)
class Deployments:
    profiles: list[Profile]
    aliases: list[dict[str, Any]]


def load_deployments_file(source: PathSource) -> Deployments:
    source_name, _, _ = _source_details(source)
    document = load_document(source)
    return Deployments(
        profiles=_parse_profiles(document, source_name),
        aliases=_parse_aliases(document, source_name, required=False),
    )
```

Update `Registry.from_files` in `registry.py` to replace the inline alias loop
with `load_alias_file`:

```python
from ai_registry.config import load_alias_file, ...

@classmethod
def from_files(cls, provider_files, profile_files, alias_files=(), *, secret_resolver=None, router=None):
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
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_config.py tests/test_registry.py -q`

Expected: PASS (existing `from_files` behavior preserved).

**Step 5: Commit**

```bash
git add src/ai_registry/config.py src/ai_registry/registry.py tests/test_config.py
git commit -m "feat: load merged profiles and aliases deployments file"
```

### Task 5: Add Registry.from_project

**Files:**
- Modify: `src/ai_registry/registry.py`
- Modify: `src/ai_registry/__init__.py`
- Test: `tests/test_project.py` (new)

**Step 1: Write the failing tests**

```python
def test_from_project_loads_builtin_providers_and_deployments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deployments_dir = tmp_path / ".ai-registry"
    deployments_dir.mkdir()
    (deployments_dir / "deployments.yaml").write_text(
        "profiles:\n"
        "  - id: deepseek-primary\n"
        "    provider_id: deepseek\n"
        "    credential: {env: DEEPSEEK_API_KEY}\n"
        "    enabled_models: [deepseek-chat]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - profile_id: deepseek-primary\n"
        "        model_id: deepseek-chat\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    registry = Registry.from_project(tmp_path)
    resolution = registry.resolve("chat-default")
    assert resolution.model_id == "deepseek-chat"
    assert resolution.provider.id == "deepseek"


def test_from_project_missing_deployments_file_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="deployments.yaml"):
        Registry.from_project(tmp_path)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_project.py -q`

Expected: FAIL with `AttributeError` / `ImportError`.

**Step 3: Implement**

In `registry.py`:

```python
from ai_registry.config import (
    discover_builtin_providers,
    discover_project_providers,
    load_deployments_file,
    merge_providers,
    ...
)

@classmethod
def from_project(
    cls,
    root: str | Path | None = None,
    *,
    secret_resolver: SecretResolver | None = None,
    router: DeploymentRouter | None = None,
) -> Registry:
    root_path = Path(root) if root is not None else Path.cwd()
    deployments_file = root_path / ".ai-registry" / "deployments.yaml"
    if not deployments_file.is_file():
        raise ConfigurationError(
            f"Missing project deployments file '{deployments_file}'; "
            "create it from examples/deployments.example.yaml"
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
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_project.py tests/test_registry.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/ai_registry/registry.py src/ai_registry/__init__.py tests/test_project.py
git commit -m "feat: discover project configuration from_project"
```

### Task 6: Examples, cleanup, and docs

**Files:**
- Create: `examples/deployments.example.yaml`
- Remove: `data/ai/providers/profiles/builtin.yaml`
- Modify: `tests/test_config.py` (replace builtin profile test with legacy-fields test)
- Modify: `README.md`, `docs/overview.md`, `docs/getting-started.md`, `docs/configuration.md`, `docs/use-cases.md`, `docs/api-reference.md`

**Step 1: Write the failing test**

Replace `test_loads_actual_builtin_profiles_and_preserves_legacy_metadata` with a
legacy-fields test that loads a temp profile containing `api_key_env`, `remark`,
and `description` (same assertions), and add:

```python
def test_example_deployments_file_loads() -> None:
    example = Path(__file__).parents[1] / "examples" / "deployments.example.yaml"
    deployments = load_deployments_file(example)
    assert deployments.profiles
    assert deployments.aliases
    profile_ids = {profile.id for profile in deployments.profiles}
    assert {
        deployment.profile_id
        for alias in deployments.aliases
        for deployment in alias["deployments"]
    } <= profile_ids
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -k example -q`

Expected: FAIL because the example file does not exist.

**Step 3: Create the example and remove the old data tree**

Create `examples/deployments.example.yaml` referencing the built-in providers
(`deepseek`, `uniapi`, `uniapi-rerankers`) with a `profiles` list and `aliases`
list using the normalized credential form. Remove
`data/ai/providers/profiles/builtin.yaml` and the now-empty `data/` tree.

**Step 4: Update the docs**

- README: show the `.ai-registry/` layout and a `from_project` quick start;
  keep `from_files` mention.
- docs/overview.md: document provider scope (built-in + project override) and
  the `.ai-registry/deployments.yaml` merged file.
- docs/getting-started.md: add a "discover from your project" section using
  `Registry.from_project`.
- docs/configuration.md: replace the separate profile/alias file sections with
  the merged `deployments.yaml`; add provider scope/merge rules and the
  directory layout.
- docs/use-cases.md: add a project-layout use case; keep explicit-path examples
  tagged as `from_files`.
- docs/api-reference.md: document `from_project`, `discover_builtin_providers`,
  `discover_project_providers`, `merge_providers`, `load_alias_file`,
  `load_deployments_file`, and `Deployments`.

**Step 5: Run the full suite**

Run: `uv run pytest -q`

Expected: PASS (131 prior + new tests, example loads).

**Step 6: Commit**

```bash
git add examples data docs README.md tests/test_config.py
git commit -m "docs: add project layout examples and update guides"
```

### Task 7: Final verification

**Files:**
- Modify: only files flagged by verification

**Step 1: Verify lockfile and environment**

Run: `uv lock --check && uv sync --dev`

**Step 2: Run all checks**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests`

**Step 3: Verify the wheel ships provider data and installs cleanly**

Run: `uv build`, then install the wheel into a clean venv and confirm
`discover_builtin_providers()` returns the built-ins with no optional SDKs
imported.

**Step 4: Inspect repository state**

Run: `git status --short && git log --oneline -12`

**Step 5: Commit verification fixes if required**

```bash
git add <only-files-fixed-by-verification>
git commit -m "fix: address project-scope verification findings"
```
