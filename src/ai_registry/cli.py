"""Optional command line interface.

Install with ``pip install "ai-registry[cli]"``. The core package does not
depend on Typer, so this module degrades to an actionable error rather than an
``ImportError`` traceback when the extra is missing.

No command prints a resolved credential. ``resolve`` and ``explain`` report
whether a credential is configured and whether it currently resolves, never its
name or value.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from ai_registry.catalog import (
    diff_models_dev,
    load_models_dev_snapshot,
    models_dev_provider_ids_from_documents,
    models_dev_snapshot_json,
    models_dev_snapshot_readme,
    sync_models_dev_snapshot,
)
from ai_registry.config import discover_builtin_provider_documents
from ai_registry.errors import (
    ConfigurationError,
    MissingDependencyError,
    RegistryError,
)
from ai_registry.registry import Registry, Resolution

try:  # pragma: no cover - exercised by environment, not by tests
    import typer
except ImportError:  # pragma: no cover - exercised by environment, not by tests
    typer = None  # type: ignore[assignment]

__all__ = ["main"]


def main() -> None:
    """Console-script entry point."""
    if typer is None:
        raise MissingDependencyError("typer", "cli")
    _build_app()()


def _build_app() -> Any:
    app = typer.Typer(
        add_completion=False,
        no_args_is_help=True,
        help="Inspect and resolve AI provider registry configuration.",
    )

    root_option = typer.Option(
        None, "--root", "-r", help="Project root to discover .ai-registry from."
    )
    profile_option = typer.Option(
        None, "--profile", "-p", help="Registry profile, e.g. 'prod'."
    )
    json_option = typer.Option(False, "--json", help="Emit JSON instead of text.")

    def load(root: str | None, profile: str | None) -> Registry:
        try:
            return Registry.from_project(root, profile=profile)
        except RegistryError as error:
            typer.echo(f"error: {error}", err=True)
            raise typer.Exit(code=2) from None

    @app.command()
    def validate(
        root: str | None = root_option, profile: str | None = profile_option
    ) -> None:
        """Load the project configuration and report any problem."""
        registry = load(root, profile)
        aliases = registry.list_aliases()
        accounts = registry.list_accounts()
        providers = registry.list_providers()
        typer.echo(
            f"ok: {len(providers)} providers, {len(accounts)} accounts, "
            f"{len(aliases)} aliases"
        )

    @app.command(name="aliases")
    def aliases_command(
        root: str | None = root_option,
        profile: str | None = profile_option,
        as_json: bool = json_option,
    ) -> None:
        """List configured aliases and the deployments behind them."""
        registry = load(root, profile)
        rows = [
            {
                "alias": alias,
                "deployments": [
                    f"{item.account_id}/{item.model_id}"
                    for item in registry.candidates(alias)
                ],
            }
            for alias in registry.list_aliases()
        ]
        if as_json:
            typer.echo(json.dumps(rows, indent=2))
            return
        if not rows:
            typer.echo("no aliases configured")
            return
        for row in rows:
            typer.echo(f"{row['alias']}\t{', '.join(row['deployments']) or '-'}")

    @app.command(name="models")
    def models_command(
        model_type: str | None = typer.Option(
            None, "--type", "-t", help="chat, embedding or reranking."
        ),
        tools: bool = typer.Option(False, "--tools", help="Only tool-capable models."),
        min_context: int | None = typer.Option(
            None, "--min-context", help="Minimum context window in tokens."
        ),
        enabled_only: bool = typer.Option(
            False, "--enabled", help="Only models an enabled account exposes."
        ),
        root: str | None = root_option,
        profile: str | None = profile_option,
        as_json: bool = json_option,
    ) -> None:
        """List catalog models, optionally filtered by capability."""
        registry = load(root, profile)
        try:
            entries = registry.list_models(
                model_type=model_type,
                requires={"tools": True} if tools else None,
                min_context_tokens=min_context,
                enabled_only=enabled_only,
            )
        except (RegistryError, ValueError) as error:
            typer.echo(f"error: {error}", err=True)
            raise typer.Exit(code=2) from None
        rows = [
            {
                "provider": entry.provider_id,
                "model": entry.model_id,
                "type": entry.model.type.value,
                "context": entry.model.context_window_tokens,
                "capabilities": sorted(
                    name
                    for name, enabled in entry.model.capabilities._raw_dump().items()
                    if enabled
                ),
            }
            for entry in entries
        ]
        if as_json:
            typer.echo(json.dumps(rows, indent=2))
            return
        for row in rows:
            capabilities = ",".join(row["capabilities"]) or "-"  # type: ignore[arg-type]
            typer.echo(
                f"{row['provider']}\t{row['model']}\t{row['type']}\t"
                f"{row['context'] or '-'}\t{capabilities}"
            )

    @app.command()
    def resolve(
        reference: str = typer.Argument(..., help="Alias or 'account-id/model-id'."),
        root: str | None = root_option,
        profile: str | None = profile_option,
        as_json: bool = json_option,
    ) -> None:
        """Resolve a reference and print the selected deployment."""
        registry = load(root, profile)
        try:
            resolution = registry.resolve(reference)
        except RegistryError as error:
            typer.echo(f"error: {error}", err=True)
            raise typer.Exit(code=1) from None
        payload = _describe(resolution)
        if as_json:
            typer.echo(json.dumps(payload, indent=2))
            return
        for key, value in payload.items():
            typer.echo(f"{key}: {value}")

    @app.command()
    def explain(
        reference: str = typer.Argument(..., help="Alias or 'account-id/model-id'."),
        root: str | None = root_option,
        profile: str | None = profile_option,
        as_json: bool = json_option,
    ) -> None:
        """Show every candidate deployment in the order routing would try them."""
        registry = load(root, profile)
        try:
            candidates = registry.candidates(reference)
        except RegistryError as error:
            typer.echo(f"error: {error}", err=True)
            raise typer.Exit(code=1) from None
        rows = [_describe(resolution) for resolution in candidates]
        if as_json:
            typer.echo(json.dumps(rows, indent=2))
            return
        if not rows:
            typer.echo(f"no available deployment for '{reference}'")
            raise typer.Exit(code=1)
        for position, row in enumerate(rows, start=1):
            typer.echo(
                f"{position}. {row['account_id']}/{row['model_id']} "
                f"-> {row['endpoint']} (credential: {row['credential']})"
            )

    catalog_app = typer.Typer(
        add_completion=False,
        no_args_is_help=True,
        help="Refresh the bundled catalog from a models.dev api.json.",
    )

    @catalog_app.command()
    def diff(
        source: str = typer.Argument(
            ..., help="Path to a downloaded models.dev api.json."
        ),
        as_json: bool = json_option,
    ) -> None:
        """Report drift between the vendored models.dev snapshot and api.json."""
        upstream = _load_upstream(source)
        provider_ids = _catalog_provider_ids()
        report = diff_models_dev(provider_ids, upstream)
        if as_json:
            typer.echo(json.dumps(report, indent=2))
        else:
            _echo_catalog_diff(report)
        if report["drift"]:
            raise typer.Exit(code=1)

    @catalog_app.command()
    def sync(
        source: str = typer.Argument(
            ..., help="Path to a downloaded models.dev api.json."
        ),
        output: str | None = typer.Option(
            None,
            "--output",
            "-o",
            help="Snapshot path to write; defaults to the packaged snapshot.",
        ),
        as_json: bool = json_option,
    ) -> None:
        """Rewrite the vendored models.dev snapshot, trimmed to the catalog."""
        upstream = _load_upstream(source)
        provider_ids = _catalog_provider_ids()
        report = diff_models_dev(provider_ids, upstream)
        try:
            document = sync_models_dev_snapshot(provider_ids, upstream)
        except ConfigurationError as error:
            typer.echo(f"error: {error}", err=True)
            raise typer.Exit(code=2) from None
        destination = (
            Path(output)
            if output
            else Path(__file__).resolve().parent / "data" / "models_dev" / "api.json"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(models_dev_snapshot_json(document), encoding="utf-8")
        readme = destination.parent / "README.md"
        readme.write_text(
            models_dev_snapshot_readme(
                source=source,
                generated_at=date.today().isoformat(),
                document=document,
            ),
            encoding="utf-8",
        )
        if as_json:
            typer.echo(json.dumps(report, indent=2))
        else:
            _echo_catalog_diff(report)
        typer.echo(f"wrote {destination} and {readme.name}")

    app.add_typer(catalog_app, name="catalog")

    return app


def _load_upstream(source: str) -> dict[str, Any]:
    """Parse a downloaded models.dev document, or exit with an actionable error."""
    try:
        return load_models_dev_snapshot(source)
    except ConfigurationError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=2) from None


def _catalog_provider_ids() -> list[str]:
    """Read the built-in provider files without hydrating them."""
    return models_dev_provider_ids_from_documents(discover_builtin_provider_documents())


def _echo_catalog_diff(report: dict[str, Any]) -> None:
    for provider_id, entry in sorted(report["providers"].items()):
        notes: list[str] = []
        if entry["provider_missing_upstream"]:
            notes.append("provider no longer in models.dev")
        for model_id, changes in sorted(entry["changed"].items()):
            fields = ", ".join(_changed_fields(changes))
            notes.append(f"{model_id} changed ({fields})")
        notes.extend(f"{item} added upstream" for item in entry["added_upstream"])
        gone = entry["missing_upstream"]
        notes.extend(f"{item} is no longer upstream" for item in gone)
        if entry["provider_changed"]:
            fields = ", ".join(sorted(entry["provider_changed"]))
            notes.append(f"provider metadata changed ({fields})")
        typer.echo(f"{provider_id}: {'; '.join(notes) if notes else 'ok'}")
    if report["drift"]:
        typer.echo("drift detected; refresh with 'ai-registry catalog sync <api.json>'")
    else:
        typer.echo("no drift: the vendored snapshot matches the supplied api.json")


def _changed_fields(changes: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for name, value in sorted(changes.items()):
        if name == "metadata" and isinstance(value, dict):
            fields.extend(f"metadata.{nested}" for nested in sorted(value))
        else:
            fields.append(name)
    return fields


def _describe(resolution: Resolution) -> dict[str, Any]:
    return {
        "reference": resolution.deployment_id,
        "provider_id": resolution.provider_id,
        "account_id": resolution.account_id,
        "model_id": resolution.model_id,
        "model_type": resolution.model.type.value,
        "endpoint": resolution.endpoint,
        "credential": _credential_status(resolution),
    }


def _credential_status(resolution: Resolution) -> str:
    """Describe credential health without naming the variable or secret."""
    if resolution.account.credential is None:
        return "none"
    kind = "env" if resolution.account.credential.env is not None else "secret_ref"
    try:
        resolution.resolve_credential()
    except RegistryError:
        return f"{kind} (unresolved)"
    return f"{kind} (ok)"
