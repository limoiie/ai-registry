# Rename Profile to Account Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rename the connection/credential concept from `Profile` to `Account` across the codebase, YAML, fixtures, and docs, without changing behavior.

**Architecture:** Mechanical, precision-safe rename. The `Profile` account concept becomes `Account`; the unrelated registry-selection `profile` feature (`profile=`, `AI_REGISTRY_PROFILE`, `registry.<profile>.yaml`) is preserved verbatim. YAML key `profiles:` → `accounts:`, `profile_id` → `account_id`, files `profiles.yaml` → `accounts.yaml`.

**Tech Stack:** Python 3.11+, Pydantic, pytest, ruff, mypy, uv.

---

### Task 1: Rename schema identifiers

**Files:**
- Modify: `src/ai_registry/schemas.py`
- Test: `tests/test_schemas.py`

**Step 1: Rename in schemas.py**

- `class Profile` → `class Account`.
- `Deployment.profile_id` field → `account_id`, with
  `validation_alias=AliasChoices("account_id", "account")`.
- `_validate_id = field_validator("profile_id")` → `"account_id"`.
- `RegistryConfig.profiles: list[Profile]` → `accounts: list[Account]`.
- Duplicate-id loop label `"profile"` → `"account"` (but keep `"provider"`/`"alias"`).

**Step 2: Run tests**

Run: `uv run pytest tests/test_schemas.py -q`

Expected: FAIL (references to `Profile`/`profiles`/`profile_id`).

**Step 3: Update test references**

Replace all `Profile`/`profiles`/`profile_id`/`"profile"` references in
`tests/test_schemas.py` with the account equivalents. Add a small test asserting
`Account` accepts `account:` YAML alias and `RegistryConfig.accounts`.

**Step 4: Run tests**

Run: `uv run pytest tests/test_schemas.py -q && uv run mypy src tests`

**Step 5: Commit**

```bash
git add src/ai_registry/schemas.py tests/test_schemas.py
git commit -m "refactor: rename Profile to Account in schemas"
```

### Task 2: Rename config loaders

**Files:**
- Modify: `src/ai_registry/config.py`
- Test: `tests/test_config.py`, `tests/fixtures/profiles.yaml` → `accounts.yaml`

**Step 1: Rename in config.py**

- `from ai_registry.schemas import Profile, ...` → `Account`.
- `load_profile_file` → `load_account_file`, `_parse_profiles` →
  `_parse_accounts`, return type `list[Account]`.
- Inside `_parse_accounts`: `document.get("profiles")` → `document.get("accounts")`;
  error messages "Profile configuration" → "Account configuration",
  `'profiles' list` → `'accounts' list`; local `profiles` → `accounts`.
- `Deployments.profiles: list[Profile]` → `accounts: list[Account]`;
  `_parse_profiles(document, ...)` → `_parse_accounts(document, ...)`.

**Step 2: Rename the fixture file**

```bash
git mv tests/fixtures/profiles.yaml tests/fixtures/accounts.yaml
```

Replace its `profiles:` key with `accounts:` and profile-ids with account-ids.
Update `tests/fixtures/registry.yaml`: `profiles:` → `accounts:`, and every
`profile_id:` in alias deployments → `account_id:`.

**Step 3: Update test references**

Replace `load_profile_file`/`_parse_profiles`/`profiles`/`Profile` references in
`tests/test_config.py` and `tests/test_integration.py` with account equivalents,
and the `DATA/"profiles"/...` / fixture path references.

**Step 4: Run tests**

Run: `uv run pytest tests/test_config.py tests/test_integration.py -q`

**Step 5: Commit**

```bash
git add src/ai_registry/config.py tests
git commit -m "refactor: rename Profile to Account in config loaders"
```

### Task 3: Rename registry internals

**Files:**
- Modify: `src/ai_registry/registry.py`
- Test: `tests/test_registry.py`, `tests/test_project.py`

**Step 1: Rename in registry.py**

- Import `Account` instead of `Profile`.
- `Resolution.profile: Profile` → `account: Account`; property `profile_id` →
  `account_id`; `resolve_credential` docstring/body `self.profile` →
  `self.account`; repr `profile_id=` → `account_id=`.
- `RegistryConfig(... profiles=_models(Profile, config.profiles, "profile"))` →
  `accounts=_models(Account, config.accounts, "account")`.
- `self._profiles` → `self._accounts`; `self._config.profiles` →
  `self._config.accounts`.
- `from_data(profiles=...)` → `accounts=...`; `Sequence[Profile|Mapping]` →
  `Sequence[Account|Mapping]`; `_models(Profile, profiles, "profile")` →
  `_models(Account, accounts, "account")`.
- `from_files(profile_files=...)` → `account_files=...`; `_load_profiles(profile_files)`
  → `_load_accounts(account_files)`; docstring "profile" → "account".
- `_load_profiles` → `_load_accounts`; `load_profile_file` import →
  `load_account_file`.
- `resolve()`: `profile_id/model_id` split → `account_id/model_id`; `profile` →
  `account`; error messages "profile" → "account"; `_validate_model_enabled(account, ...)`;
  `Deployment(account_id=account_id, ...)`.
- `_resolution()`: `profile` → `account`; `result_profile` → `result_account`;
  `Resolution(account=result_account, ...)`.
- `_validate_references()`: `profile`/`alias_profile` → `account`/`alias_account`;
  messages "profile" → "account".
- `_validate_model_enabled(self, profile: Profile, ...)` →
  `(self, account: Account, ...)`; messages "profile" → "account".
- Do NOT rename the registry-selection `profile=`/`_resolve_profile`/
  `_discover_registry_file`/`resolved_profile` (Task 1 out-of-scope preserved).

**Step 2: Update routing.py**

- `SelectedDeployment` metadata key `"profile_id"` → `"account_id"`.

**Step 3: Update test references**

Replace `Profile`/`profiles`/`profile_id`/`profile`/`_load_profiles`/
`load_profile_file` references in `tests/test_registry.py`,
`tests/test_project.py`, `tests/test_routing.py` with account equivalents. Keep
the registry-selection `profile=`/`AI_REGISTRY_PROFILE` tests unchanged.

**Step 4: Run tests**

Run: `uv run pytest -q`

**Step 5: Commit**

```bash
git add src/ai_registry tests
git commit -m "refactor: rename Profile to Account in registry"
```

### Task 4: Update examples and docs

**Files:**
- Modify: `examples/registry.example.yaml`, `README.md`, `docs/*.md`

**Step 1: Update examples/registry.example.yaml**

Replace `profiles:` → `accounts:`, profile-ids → account-ids, `profile_id` →
`account_id` in alias deployments. Run `uv run pytest tests/test_config.py::test_example_deployments_file_loads -q` (rename test name if it references profiles).

**Step 2: Update docs**

Replace the account-concept uses of "Profile"/"profile"/"profiles"/"profile_id"
with "Account"/"account"/"accounts"/"account_id" in `README.md`,
`docs/overview.md`, `docs/getting-started.md`, `docs/configuration.md`,
`docs/use-cases.md`, `docs/api-reference.md`, `docs/development.md`,
`docs/security.md`. Preserve the registry-selection `profile=`/`AI_REGISTRY_PROFILE`
wording. Update YAML examples to use `accounts:` and `account_id:`.

Run: `uv run ruff format .` on edited markdown.

**Step 3: Verify**

Run: `uv run ruff format --check . && uv run pytest -q`

**Step 4: Commit**

```bash
git add examples docs README.md
git commit -m "docs: rename Profile to Account in examples and guides"
```

### Task 5: Final verification

**Files:**
- Modify: only files flagged by verification

**Step 1: Run all checks**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv lock --check`

**Step 2: Grep for leftover account-concept "profile"**

Run: `rg -n "Profile|_parse_profiles|load_profile_file|_load_profiles|profile_id|profiles:" src/ tests/ examples/`

Expected: only hits matching the registry-selection feature (`profile=`,
`AI_REGISTRY_PROFILE`, `_resolve_profile`, `_discover_registry_file`,
`registry.<profile>.yaml`, `resolved_profile`) and the standalone `profile`
word in unrelated prose.

**Step 3: End-to-end probe**

Confirm `examples/registry.example.yaml` (with `accounts:`) loads via
`Registry.from_project`, and that `from_project(profile="prod")` still works.

**Step 4: Commit verification fixes if required**

```bash
git add <only-files-fixed-by-verification>
git commit -m "fix: address account-rename verification findings"
```