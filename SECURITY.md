# Security policy

## Reporting a vulnerability

Report suspected vulnerabilities privately through
[GitHub Security Advisories](https://github.com/limoiie/ai-registry/security/advisories/new).
Please do not open a public issue for anything credential-related.

Include the affected version, a description of the impact, and the smallest
reproduction you can manage. Expect an acknowledgement within 5 working days.

## Supported versions

While the project is `0.x`, only the latest released version receives fixes.

## Threat model

This package sits on the path between your configuration and your API keys, so
its security properties are part of its contract:

- **No network access.** The core makes no outbound requests. Resolution is a
  pure function of configuration plus the process environment.
- **Small dependency closure.** The runtime requires only `pydantic` and
  `pyyaml`. Adapters and the CLI are optional extras that the core never
  imports. A dependency that is not installed cannot be compromised.
- **No literal secrets in configuration.** `CredentialRef` accepts exactly one
  of `env` or `secret_ref`; a literal key is a validation error, not a warning.
- **Secrets stay references until asked for.** `Resolution.resolve_credential()`
  is the only API that returns a raw value. Resolved values are never stored on
  objects, serialized, cached, or logged.
- **Redacted representations.** `repr`, `str`, `model_dump`, `model_dump_json`
  and validation errors redact credential-shaped keys and never echo the
  offending input.
- **Endpoints are validated.** URLs carrying userinfo or credential-bearing
  query or fragment parameters are rejected at load time.

See [docs/security.md](docs/security.md) for the mechanisms, the exact redaction
rules, and the known limitations.

## Supply chain

Releases are published from GitHub Actions using PyPI Trusted Publishing; no API
token exists in this repository. Distributions carry PEP 740 attestations, so a
build's provenance can be verified against this repository.

To verify what you installed:

```bash
pip download --no-deps ai-registry
# then check the attestation on https://pypi.org/project/ai-registry/#files
```
