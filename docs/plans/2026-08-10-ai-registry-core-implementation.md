# AI Registry Core Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a uv-managed, framework-independent AI registry core that loads the existing provider data, validates profiles and aliases, resolves credentials safely, and selects healthy deployments.

**Architecture:** Use a standard `src/ai_registry/` package with Pydantic schemas, explicit config normalization, a secret resolver boundary, registry resolution, and a separate routing state/policy layer. Keep framework adapters out of this milestone and make all runtime behavior testable without network access or optional framework imports.

**Tech Stack:** Python 3.11+, uv, Pydantic 2, PyYAML, pytest, ruff, mypy (or pyright if selected during setup).

---

### Task 1: Initialize the uv project

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `src/ai_registry/__init__.py`
- Create: `tests/__init__.py`
- Create: `README.md`
- Create: `.gitignore`
- Generate: `uv.lock`

**Step 1: Write the project smoke test**

Create `tests/test_import.py` asserting that `from ai_registry import Registry` succeeds and the package exposes a version.

**Step 2: Run the failing test**

Run: `uv run pytest tests/test_import.py -q`

Expected: fail because the uv project and package do not exist.

**Step 3: Create uv metadata and package skeleton**

Declare the package under `src/`, Python compatibility, runtime dependency `pydantic>=2`, YAML dependency `pyyaml`, and a development dependency group containing pytest, ruff, and a type checker. Add project commands for tests, lint, and type checking. Use uv to generate the lockfile.

**Step 4: Run the smoke test**

Run: `uv run pytest tests/test_import.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add pyproject.toml .python-version src tests README.md .gitignore uv.lock
git commit -m "chore: initialize uv package"
```

### Task 2: Define core schemas and safe representations

**Files:**
- Create: `src/ai_registry/schemas.py`
- Create: `src/ai_registry/errors.py`
- Test: `tests/test_schemas.py`

**Step 1: Write failing validation tests**

Cover provider/model cards, profiles, credential references (`env` and `secret_ref`), aliases/deployments, routing metadata, duplicate IDs at the aggregate level, and rejection of literal API keys by default. Assert that `repr()` and serialized safe views contain no secret values.

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_schemas.py -q`

Expected: collection or import failures because schemas are absent.

**Step 3: Implement minimal Pydantic models**

Add constrained identifiers, model type and SDK type enums/literals, provider defaults, model capabilities, profile endpoint and enabled-model fields, credential reference validation, deployment routing fields, and aggregate configuration models. Add redacted `repr`/safe serialization behavior and stable base error types.

**Step 4: Run tests**

Run: `uv run pytest tests/test_schemas.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/ai_registry/schemas.py src/ai_registry/errors.py tests/test_schemas.py
git commit -m "feat: add registry configuration schemas"
```

### Task 3: Add configuration loading and normalization

**Files:**
- Create: `src/ai_registry/config.py`
- Create: `tests/fixtures/providers/`
- Create: `tests/fixtures/profiles.yaml`
- Test: `tests/test_config.py`

**Step 1: Write failing loader tests**

Test YAML and JSON loading, loading one provider file, loading multiple provider files, and normalizing the existing `id`, `settings.sdk_type`, and `model_cards` shape. Test normalization of `profiles: - id/provider_id/api_key_env/enabled_models` into credential references. Test malformed YAML and duplicate provider/model IDs produce safe actionable errors.

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_config.py -q`

Expected: fail because loader functions are absent.

**Step 3: Implement loaders**

Provide path-or-file loading for YAML/JSON, explicit parsing functions for normalized documents, and compatibility normalization for the current catalog/profile files. Do not resolve credentials during loading. Preserve model metadata and provider settings needed by later adapters.

**Step 4: Run tests**

Run: `uv run pytest tests/test_config.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/ai_registry/config.py tests/fixtures tests/test_config.py
git commit -m "feat: load and normalize registry configuration"
```

### Task 4: Implement secret resolution

**Files:**
- Create: `src/ai_registry/secrets.py`
- Test: `tests/test_secrets.py`

**Step 1: Write failing resolver tests**

Cover environment lookup, missing environment variables, custom resolver calls for `secret_ref`, unsupported references, and redaction of resolved values from exception text.

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_secrets.py -q`

Expected: fail because secret resolution is absent.

**Step 3: Implement resolver boundary**

Define the `SecretResolver` protocol, environment resolver, reference dispatch, and safe credential errors. Keep resolved values transient and out of public model serialization and logging.

**Step 4: Run tests**

Run: `uv run pytest tests/test_secrets.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/ai_registry/secrets.py tests/test_secrets.py
git commit -m "feat: resolve registry secret references"
```

### Task 5: Build validated registry resolution

**Files:**
- Create: `src/ai_registry/registry.py`
- Modify: `src/ai_registry/__init__.py`
- Test: `tests/test_registry.py`

**Step 1: Write failing registry tests**

Test construction from normalized data/files, unknown providers/models, models not enabled by profiles, invalid alias deployments, global alias precedence, direct `profile/model` fallback, canonical model metadata, and lazy credential resolution.

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_registry.py -q`

Expected: fail because `Registry` and resolution results are absent.

**Step 3: Implement registry construction and resolution**

Add `Registry.from_files`, normalized-data construction, aggregate validation, alias-first lookup, explicit direct-reference parsing, and a safe resolution result. Return descriptive errors that include only alias/profile/model identifiers and remediation.

**Step 4: Run tests**

Run: `uv run pytest tests/test_registry.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/ai_registry/__init__.py src/ai_registry/registry.py tests/test_registry.py
git commit -m "feat: resolve registry aliases and deployments"
```

### Task 6: Implement deployment routing and health state

**Files:**
- Create: `src/ai_registry/routing.py`
- Test: `tests/test_routing.py`

**Step 1: Write failing routing tests**

Test disabled and unhealthy exclusion, lowest-priority selection, weighted choice among equal-priority deployments using an injected random source, no-available-deployment errors, failure marking, recovery, and observable selected deployment metadata.

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_routing.py -q`

Expected: fail because selection and health state are absent.

**Step 3: Implement routing**

Keep static deployment configuration immutable. Add a separate health store and a selector that filters unavailable deployments, chooses the lowest priority, then applies weights. Make randomness injectable for deterministic tests and avoid secret-bearing objects in routing errors.

**Step 4: Run tests**

Run: `uv run pytest tests/test_routing.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/ai_registry/routing.py tests/test_routing.py
git commit -m "feat: add health-aware deployment routing"
```

### Task 7: Add integration fixtures, documentation, and quality checks

**Files:**
- Create: `tests/fixtures/catalog.yaml`
- Create: `tests/fixtures/registry.yaml`
- Modify: `README.md`
- Modify: `pyproject.toml` if needed for tool configuration
- Test: `tests/test_integration.py`

**Step 1: Write failing end-to-end tests**

Load representative DeepSeek, UniAPI, Minimax, embedding, and reranking catalog data with profiles and aliases. Verify a complete alias resolution and that custom OpenAI-compatible endpoint metadata is retained without importing an SDK.

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_integration.py -q`

Expected: fail until the fixture shape and public API are wired together.

**Step 3: Add fixtures and user documentation**

Document uv setup, `uv sync`, `uv run pytest`, normalized configuration, compatibility loading of current data, environment secret references, aliases, direct references, and the current non-goals.

**Step 4: Run the full verification suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

Expected: all tests pass and lint/format checks succeed.

**Step 5: Commit**

```bash
git add README.md pyproject.toml tests
git commit -m "test: cover registry core integration"
```

### Task 8: Final verification

**Files:**
- Modify: any files required by verification findings only

**Step 1: Verify the lockfile and clean install path**

Run: `uv lock --check && uv sync --dev`

Expected: the lockfile is current and the development environment installs successfully.

**Step 2: Run all project checks through uv**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

Expected: all commands exit successfully.

**Step 3: Inspect repository state**

Run: `git status --short && git log --oneline -10`

Expected: only intended files are present and each completed task has a focused commit.

**Step 4: Commit verification fixes if required**

```bash
git add <only-files-fixed-by-verification>
git commit -m "fix: address core verification findings"
```
