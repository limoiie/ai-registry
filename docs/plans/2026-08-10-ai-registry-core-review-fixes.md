# AI Registry Core Review Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the final core review findings without adding adapters or changing the existing registry scope.

**Architecture:** Keep routing state injectable and separate from static configuration by giving `Registry` a `DeploymentRouter` dependency. Validate all candidate references during construction, reject disabled profiles consistently, and expose only redacted resolution representations. Normalize legacy SDK values before schema validation while retaining original settings metadata.

**Tech Stack:** Python 3.11+, Pydantic 2, pytest, ruff, mypy, uv.

---

### Task 1: Add failing regression tests

**Files:** `tests/test_registry.py`, `tests/test_config.py`, `tests/test_schemas.py`, `tests/test_secrets.py`

Add tests for Registry-level multi-deployment routing with injected randomness and health recovery, disabled profiles in direct and alias references, safe nested metadata repr/str without the secret resolver, top-level and nested `uniapi` normalization with preserved settings, unsupported SDK rejection, and empty environment values producing a safe actionable secret error.

Run the targeted tests and confirm they fail for the current behavior.

### Task 2: Implement minimal core fixes

**Files:** `src/ai_registry/registry.py`, `src/ai_registry/schemas.py`, `src/ai_registry/config.py`, `src/ai_registry/secrets.py`

Inject a router into `Registry`, route aliases through it, expose connected health state through the router dependency, validate all candidate profiles/models, reject disabled profiles, implement explicit redacted `Resolution.__repr__` and `__str__`, normalize both SDK locations, and reject empty environment values.

Run targeted tests and then the complete pytest suite.

### Task 3: Verify and commit

Run `uv lock --check`, `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy .`. Inspect the diff and commit only the review-fix files and this plan with a focused message.
