# Rename Profile to Account

## Decision

Rename the connection/credential concept from `Profile` to `Account` to improve
reader clarity. An account is a real-world account with a provider: it owns a
credential reference, an endpoint, and the set of models the account exposes.

The project-scope registry-selection feature (`profile=` keyword,
`AI_REGISTRY_PROFILE`, `registry.<profile>.yaml`) is a **separate, unrelated
use of the word "profile"** and is NOT renamed by this change.

## Scope

Rename the account concept everywhere it appears:

- Python class `Profile` → `Account` (schemas.py).
- `Deployment.profile_id` → `account_id` (schema field and YAML alias
  `AliasChoices("account_id", "account")`).
- `RegistryConfig.profiles` → `accounts`.
- `Resolution.profile` → `account`, `Resolution.profile_id` → `account_id`.
- `Deployments.profiles` → `accounts` (config.py dataclass).
- `_parse_profiles` → `_parse_accounts`, `load_profile_file` →
  `load_account_file`, `load_profile_files` → `load_account_files`,
  `_load_profiles` → `_load_accounts`.
- `Registry.from_files(profile_files=...)` → `account_files=...`.
- `Registry._profiles` → `_accounts`, `_validate_model_enabled(profile, ...)` →
  `_validate_model_enabled(account, ...)`.
- YAML key `profiles:` → `accounts:` in examples, fixtures, and docs.
- Direct-reference syntax `profile-id/model-id` → `account-id/model-id` in
  errors and docs.
- File `tests/fixtures/profiles.yaml` → `tests/fixtures/accounts.yaml`.
- All user-facing docs: "Profile" → "Account", "profiles" → "accounts".

## Out of scope (keep unchanged)

- The registry file selection feature: `profile=` keyword, `_resolve_profile`,
  `AI_REGISTRY_PROFILE`, `registry.<profile>.yaml`, and the `profile` parameter
  of `Registry.from_project`.
- `ModelCard` fields and provider concepts unrelated to accounts.
- `Distribution`/provider metadata.
- The `examples/registry.example.yaml` `accounts:` value semantics (only the key
  name changes).

## Details

- `RegistryConfig` duplicate-id validation label changes from `"profile"` to
  `"account"`.
- Error/remediation messages that say "profile" for the account concept change
  to "account"; messages for the registry-selection feature keep "profile".
- The `AliasChoices("profile_id", "profile")` validation alias becomes
  `AliasChoices("account_id", "account")` so YAML `account: X` maps to
  `account_id`.

## Tests

- Update all references in tests; behavior is unchanged.
- Add/adjust a test asserting the YAML key is `accounts:` (not `profiles:`).
- Confirm the registry-selection `profile=` feature still works unchanged.

## Docs

Update `README.md`, `docs/overview.md`, `docs/getting-started.md`,
`docs/configuration.md`, `docs/use-cases.md`, `docs/api-reference.md`,
`docs/development.md`, and `docs/security.md` for the account terminology.