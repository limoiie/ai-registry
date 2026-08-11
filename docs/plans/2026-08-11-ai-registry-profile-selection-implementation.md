# Profile-Based Registry Selection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let users select between multiple project registry files by profile (env/tenant), via an explicit `profile=` argument or the `AI_REGISTRY_PROFILE` env var, with a safe default.

**Architecture:** Extend `Registry.from_project` with a `profile` keyword. Resolve the active file name as `registry.<profile>.yaml` (or `.yml`/`.json`) under `<root>/.ai-registry/`, falling back to the default `registry.yaml` when no profile is set. Validate profile names against path traversal and never silently fall back when a requested profile file is missing.

**Tech Stack:** Python 3.11+, stdlib `os`, `pathlib`, Pydantic, pytest, ruff, mypy, uv.

---

### Task 1: Add profile selection and safe file resolution

**Files:**
- Modify: `src/ai_registry/registry.py`
- Test: `tests/test_project.py`

**Step 1: Write the failing tests**

Add to `tests/test_project.py`:

```python
def _write_registry(
    tmp_path: Path, filename: str, model_id: str = "deepseek-chat"
) -> None:
    (tmp_path / ".ai-registry").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai-registry" / filename).write_text(
        "profiles:\n"
        "  - id: primary\n"
        "    provider_id: deepseek\n"
        "    credential: {env: DEEPSEEK_API_KEY}\n"
        "    enabled_models: [deepseek-chat]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - profile_id: primary\n"
        "        model_id: deepseek-chat\n",
        encoding="utf-8",
    )


def test_from_project_no_profile_uses_default_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AI_REGISTRY_PROFILE", raising=False)
    _write_registry(tmp_path, "registry.yaml")
    assert (
        Registry.from_project(tmp_path).resolve("chat-default").model_id
        == "deepseek-chat"
    )


def test_from_project_profile_argument_selects_named_file(tmp_path: Path) -> None:
    _write_registry(tmp_path, "registry.prod.yaml")
    registry = Registry.from_project(tmp_path, profile="prod")
    assert registry.resolve("chat-default").model_id == "deepseek-chat"


def test_from_project_env_var_selects_named_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_REGISTRY_PROFILE", "dev")
    _write_registry(tmp_path, "registry.dev.yaml")
    assert (
        Registry.from_project(tmp_path).resolve("chat-default").model_id
        == "deepseek-chat"
    )


def test_from_project_explicit_profile_overrides_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_REGISTRY_PROFILE", "dev")
    _write_registry(tmp_path, "registry.prod.yaml")
    registry = Registry.from_project(tmp_path, profile="prod")
    assert registry.resolve("chat-default").model_id == "deepseek-chat"


def test_from_project_missing_profile_file_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError) as caught:
        Registry.from_project(tmp_path, profile="prod")
    assert "registry.prod.yaml" in str(caught.value)


def test_from_project_invalid_profile_name_is_rejected(tmp_path: Path) -> None:
    for bad in ("../escape", "a/b", "a\\b", "a..b"):
        with pytest.raises(ConfigurationError):
            Registry.from_project(tmp_path, profile=bad)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_project.py -k "profile or default_registry" -q`

Expected: FAIL — `from_project` has no `profile` parameter and ignores the env var.

**Step 3: Implement**

Update `from_project` signature and add a helper to resolve the registry file:

```python
_PROFILE_ENV = "AI_REGISTRY_PROFILE"
_REGISTRY_NAMES = ("registry.yaml", "registry.yml", "registry.json")


def _resolve_profile(profile: str | None) -> str | None:
    if profile is not None:
        value = profile
    else:
        value = os.environ.get(_PROFILE_ENV)
    if value is None or value == "":
        return None
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ConfigurationError(
            f"invalid registry profile name {value!r}; use a simple name"
        )
    return value


def _discover_registry_file(root: Path, profile: str | None) -> Path | None:
    deployments_dir = root / ".ai-registry"
    names = (
        (
            f"registry.{profile}.yaml",
            f"registry.{profile}.yml",
            f"registry.{profile}.json",
        )
        if profile is not None
        else _REGISTRY_NAMES
    )
    for name in names:
        candidate = deployments_dir / name
        if candidate.is_file():
            return candidate
    return None
```

In `from_project`:

```python
@classmethod
def from_project(cls, root=None, *, profile=None, secret_resolver=None, router=None):
    root_path = Path(root) if root is not None else Path.cwd()
    resolved_profile = _resolve_profile(profile)
    deployments_file = _discover_registry_file(root_path, resolved_profile)
    if deployments_file is None:
        expected = (
            f"registry.{resolved_profile}.yaml"
            if resolved_profile is not None
            else "registry.yaml"
        )
        raise ConfigurationError(
            f"Missing project registry file under '{root_path / '.ai-registry'}'; "
            f"expected {expected}. Create it from examples/registry.example.yaml"
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

Remove/replace `_discover_deployments_file` with `_discover_registry_file`, and
add `import os` at the top of `registry.py`.

**Step 4: Run tests**

Run: `uv run pytest tests/test_project.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/ai_registry/registry.py tests/test_project.py
git commit -m "feat: add profile-based registry file selection"
```

### Task 2: Update documentation

**Files:**
- Modify: `README.md`, `docs/overview.md`, `docs/getting-started.md`, `docs/configuration.md`, `docs/use-cases.md`, `docs/api-reference.md`

**Step 1: Review current docs**

Run: `rg -n "registry.yaml|from_project|AI_REGISTRY" README.md docs/`

**Step 2: Update each doc**

- `configuration.md`: document the named-file layout (`registry.yaml`,
  `registry.<env>.yaml`), the `profile=` argument, the `AI_REGISTRY_PROFILE` env
  var, selection precedence, and the no-silent-fallback rule.
- `api-reference.md`: add `profile` to the `from_project` signature and document
  `AI_REGISTRY_PROFILE`.
- `getting-started.md`: add a short "select by environment" subsection.
- `use-cases.md`: add an environment-switching use case.
- `overview.md` / `README.md`: mention profile selection in the layout/features.

Run: `uv run ruff format .` on edited markdown so the format check stays green.

**Step 3: Verify**

Run: `uv run ruff format --check . && uv run pytest -q`

**Step 4: Commit**

```bash
git add README.md docs/
git commit -m "docs: document profile-based registry selection"
```

### Task 3: Final verification

**Files:**
- Modify: only files flagged by verification

**Step 1: Run all checks**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv lock --check`

**Step 2: End-to-end probe**

Create a temp project with `registry.yaml` and `registry.prod.yaml`, confirm
`from_project()` uses the default and `from_project(profile="prod")` uses the
prod file, and that a missing profile file raises without falling back.

**Step 3: Commit verification fixes if required**

```bash
git add <only-files-fixed-by-verification>
git commit -m "fix: address profile-selection verification findings"
```