# Security

`ai-registry` treats credentials as the most sensitive data it handles. This
page describes the guarantees, the mechanisms behind them, and the practices to
follow when using the library.

## Guarantees

1. **No literal keys in configuration.** A `CredentialRef` requires exactly one
   of `env` or `secret_ref`. A literal `api_key` value is rejected at
   validation time. There is no supported path to store a raw key in a
   catalog/account/alias document.
2. **Resolved secrets are transient.** `Resolution.resolve_credential()` is the
   only API that returns a raw secret, and it is invoked lazily — only when an
   adapter asks. Resolved values are never stored on objects, never serialized,
   and never included in logs.
3. **Safe representations.** `repr()`, `str()`, `model_dump()`,
   `model_dump_json()`, and `safe_dump()` redact secrets recursively. This
   applies to configuration models (`SafeModel`) and to `Resolution`.
4. **Safe errors.** Exceptions never contain API keys, resolved values, or raw
   caller input that could be secret-like. Validation errors hide the input
   value; registry errors describe the problem and remediation without echoing
   the offending identifier.
5. **Safe endpoints.** Credential-bearing URLs are rejected at load time:
   userinfo (`user:pass@host`), sensitive query/fragment parameters, and empty
   query keys.
6. **Isolation.** Registry configuration is deep-copied at construction, and
   every `Resolution` returns deep copies. Caller mutations cannot alter
   resolution behavior or leak into other results.

## How redaction works

### Configuration models

`SafeModel` overrides the Pydantic serialization entry points. The redactor
replaces sensitive values with the placeholder `"<redacted>"` recursively
across:

- mappings (including `UserDict` and generic `Mapping` implementations),
- sequences (lists, tuples, `UserList`, `deque`; strings/bytes are left
  intact),
- sets and frozensets,
- two-element pairs whose first element is a sensitive key, e.g.
  `("api_key", "value")`.

### Sensitive keys

A key is treated as sensitive if its words (split on non-alphanumeric
boundaries and camelCase) match any of:

- exact sensitive words: `authorization`, `bearer`, `credential(s)`, `env`,
  `passphrase`, `passwd`, `password`, `secret`, `secret_ref`, `sig`,
  `signature`, `assertion`, `jwt`;
- compact tokens: `apikey`, `authkey`, `sessionid`;
- sensitive phrases: `connection_string`;
- a last word of `key` or `token` (or `key_id`) preceded by a qualifying word
  such as `access`, `api`, `auth`, `aws`-style prefixes, `client`, `consumer`,
  `device`, `master`, `oauth`, `primary`, `private`, `sas`, `security`,
  `session`, `signing`, `subscription`, `user`, and similar;
- the bare word `token`.

Examples that are redacted: `api_key`, `x-api-key`, `accessToken`,
`aws_access_key_id`, `connection_string`, `client_assertion`,
`subscription_key`, `sas_token`, `openai_key`, `session_id`, `authorization`.

Ordinary metadata such as `model_token_count`, `client_id`, `username`, and
`api-version` remains visible.

### `Resolution`

`Resolution.__repr__`/`__str__` render the selected provider/model/account and
a redacted view of `endpoint_metadata`. The secret resolver object is excluded
from the representation.

## Endpoint validation

`default_base_url` (provider) and `endpoint`/`base_url` (account) reject:

- userinfo components, including percent-encoded credentials;
- query or fragment parameter names that are sensitive (see above), including
  when `;` is used as a separator in addition to `&`;
- empty parameter names.

```python
# All rejected
"https://user:pass@host/v1"

"https://host/v1?api_key=secret"
"https://host/v1?x=y;access_token=secret"
"https://host/v1#aws_access_key_id=secret"
"https://host/v1?=x"
```

Use a `credential: {env: ...}` or `credential: {secret_ref: ...}` reference
instead. See [Credentials](configuration.md#credentials).

## Credential resolution errors

- **Missing or empty environment variable** → `SecretResolutionError` naming
  the variable, never its value.
- **Custom resolver failure** → wrapped in `SecretResolutionError` without the
  underlying exception details.
- **Custom resolver returns a non-string or empty string** → rejected.
- **`secret_ref` without a configured resolver** → rejected.

## Practices for users

- Keep credential references (`env`/`secret_ref`) in configuration; never write
  keys into files.
- Treat `Resolution.resolve_credential()` as an adapter-boundary call. Resolve
  once at client construction, keep the value in the client, and avoid logging
  it.
- Use redacted representations (`repr(resolution)`, `safe_dump()`) in logs and
  traces.
- Do not place secrets in URLs; the loader will reject them anyway.
- External secret integrations belong in `SecretResolver` implementations, not
  in the registry.

## Practices for adapters (roadmap)

Adapters are the intended consumers of `Resolution`. When building them:

- call `resolve_credential()` once at client construction;
- never return the resolved secret from any public adapter API;
- include the relevant extra in installation-error messages
  (`pip install ai-registry[openai]`);
- propagate `Resolution` metadata into observability without serializing
  credentials.

## Known limitations

- Redaction is key-name heuristics. A secret stored under an unusual key name
  (for example `description`) is not detected by generic redaction. The
  endpoint validator is a denylist, not a parameter allowlist.
- `Provider.settings` and `Account.metadata` are free-form and forwarded
  verbatim to adapters; redaction applies at serialization boundaries only.
- The default health store is in-process. It is thread-safe and bounded by the
  number of configured deployments, but is not shared between processes —
  implement the `HealthStore` protocol for that.
- `model_dump_json()` requires values that are JSON-serializable; exotic custom
  objects in `metadata` may raise.
- `client_kwargs()` and the adapters resolve the credential by design; their
  return values are secret and must not be logged.

## Command line

The `ai-registry` CLI never prints a credential. `resolve` and `explain` report
a status only — `none`, `env (ok)`, `env (unresolved)`, or the `secret_ref`
equivalent — deliberately omitting the variable name so that command output and
CI logs are safe to paste.

```console
$ ai-registry explain chat-default
1. deepseek-primary/deepseek-chat -> https://api.deepseek.com/anthropic (credential: env (ok))
2. uniapi-chat/deepseek-v4-flash -> https://uni-api.cstcloud.cn (credential: env (unresolved))
```

## Supply chain

The runtime dependency closure is six packages (`pydantic`, `pydantic-core`,
`annotated-types`, `typing-extensions`, `typing-inspection`, `pyyaml`). The CLI
and the adapters are optional extras that the core never imports, so a
dependency you have not installed cannot be part of your attack surface. This is
a deliberate property of a component that sits next to every API key you own.

See [SECURITY.md](../SECURITY.md) for reporting and release provenance.
