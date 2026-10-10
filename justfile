# Maintainer tasks for ai-registry.
#
# Optional. Every recipe is a thin wrapper over the same `uv` commands that
# docs/development.md documents as canonical, and it needs nothing but `uv`.
# Nothing in CI, the release workflow, or pre-commit depends on `just`, so skip
# it freely — copy the command out of a recipe and run it directly.

default:
    @just --list

# Install the locked dev environment (no extras, matching how the suite runs).
sync:
    uv sync --frozen

# Install every optional extra (for adapter work).
sync-all:
    uv sync --frozen --all-extras

# Lint with ruff.
lint:
    uv run --frozen ruff check .

# Check formatting without rewriting files.
fmt-check:
    uv run --frozen ruff format --check .

# Rewrite formatting in place.
fmt:
    uv run --frozen ruff format .

# Strict type checking.
typecheck:
    uv run --frozen mypy src tests

# Assert uv.lock matches pyproject.toml.
lock-check:
    uv lock --check

# Run the unit and integration tests.
test:
    uv run --frozen pytest -q

# Run the tests with a coverage report.
test-cov:
    uv run --frozen pytest -q --cov --cov-report=term-missing

# Every gate CI enforces, in one command.
check: lint fmt-check typecheck lock-check test

# Set the package version (pyproject.toml + uv.lock). Does not commit or tag.
bump version:
    uv version {{version}}
    @echo "Next: add a '## [{{version}}]' heading in CHANGELOG.md, run 'just check',"
    @echo "commit, push and let CI pass, then 'just release-check {{version}}'."

# Verify a version is safe to tag: version, changelog, lock, tree, and tag slot.
release-check version:
    #!/usr/bin/env bash
    set -euo pipefail
    version="{{version}}"
    tag="v${version}"
    fail() { printf 'release-check: %s\n' "$1" >&2; exit 1; }

    current="$(uv version --short)"
    [[ "$current" == "$version" ]] || fail "pyproject.toml says $current, expected $version"

    grep -qF "## [$version]" CHANGELOG.md || fail "CHANGELOG.md has no '## [$version]' heading"

    [[ -z "$(git status --porcelain)" ]] || fail "working tree is dirty; commit the release first"

    branch="$(git rev-parse --abbrev-ref HEAD)"
    [[ "$branch" == "main" ]] || fail "on branch $branch, not main"

    uv lock --check >/dev/null 2>&1 || fail "uv.lock is out of date; run 'uv lock'"

    if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
        fail "tag $tag already exists locally"
    fi
    if git ls-remote --tags origin "refs/tags/$tag" 2>/dev/null | grep -q "refs/tags/$tag$"; then
        fail "tag $tag already exists on origin"
    fi

    printf 'release-check: %s is ready. The tag is what publishes it:\n' "$version"
    printf '  git tag -a %s -m "ai-registry %s" && git push origin %s\n' "$tag" "$version" "$tag"

# Build the sdist and the wheel.
build:
    uv build

# Preview the documentation locally.
docs:
    uv run --group docs mkdocs serve

# Build the docs exactly as the Docs workflow does (stage, strict, clean up).
docs-check:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'rm -f docs/index.md docs/changelog.md' EXIT
    sed -e 's|](docs/|](|g' \
        -e 's|](LICENSE)|](https://github.com/limoiie/ai-registry/blob/main/LICENSE)|g' \
        README.md > docs/index.md
    cp CHANGELOG.md docs/changelog.md
    uv run --group docs mkdocs build --strict

# Report how the vendored snapshot differs from a local models.dev api.json.
catalog-diff path:
    # Fetch one first: curl -o /tmp/models-dev-api.json https://models.dev/api.json
    uv run --frozen ai-registry catalog diff {{path}}

# Rewrite the vendored snapshot from a local api.json.
catalog-sync path:
    uv run --frozen ai-registry catalog sync {{path}}

# Remove build and cache artifacts.
clean:
    rm -rf dist site .coverage .pytest_cache .mypy_cache .ruff_cache