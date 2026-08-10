"""Health-aware, framework-independent deployment selection."""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from ai_registry.errors import RegistryError
from ai_registry.schemas import Alias, Deployment


class NoAvailableDeploymentError(RegistryError):
    """Raised when an alias has no enabled and healthy deployment."""


@dataclass(frozen=True)
class SelectedDeployment:
    """A safe routing decision and metadata for adapter observability."""

    alias_id: str
    candidate_index: int
    deployment: Deployment
    metadata: dict[str, Any]

    @property
    def deployment_id(self) -> str:
        """Return the alias reference used by the registry resolution layer."""
        return self.alias_id


class DeploymentHealthStore:
    """Mutable runtime health state kept separate from static configuration."""

    def __init__(self) -> None:
        self._healthy: dict[tuple[str, int], bool] = {}

    def mark_failure(self, alias_id: str, candidate_index: int) -> None:
        self._healthy[_health_key(alias_id, candidate_index)] = False

    def mark_success(self, alias_id: str, candidate_index: int) -> None:
        self._healthy[_health_key(alias_id, candidate_index)] = True

    def is_healthy(self, alias_id: str, candidate_index: int) -> bool:
        return self._healthy.get(_health_key(alias_id, candidate_index), True)


class DeploymentRouter:
    """Select an available deployment according to priority and weight."""

    def __init__(
        self,
        health_store: DeploymentHealthStore | None = None,
        *,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        self.health_store = health_store or DeploymentHealthStore()
        self._random_source = random_source

    def select(
        self,
        alias: Alias,
        *,
        eligible: Callable[[Deployment], bool] | None = None,
    ) -> SelectedDeployment:
        eligibility = eligible or (lambda deployment: True)
        available = [
            (candidate_index, deployment)
            for candidate_index, deployment in enumerate(alias.deployments)
            if deployment.routing.enabled
            and eligibility(deployment)
            and self.health_store.is_healthy(alias.id, candidate_index)
        ]
        if not available:
            raise NoAvailableDeploymentError(
                f"no available deployment for alias '{alias.id}'"
            )

        priority = min(deployment.routing.priority for _, deployment in available)
        candidates = [
            (candidate_index, deployment)
            for candidate_index, deployment in available
            if deployment.routing.priority == priority
        ]
        candidate_index, selected = _weighted_choice(candidates, self._random_source)
        selected = deepcopy(selected)
        return SelectedDeployment(
            alias_id=alias.id,
            candidate_index=candidate_index,
            deployment=selected,
            metadata=deepcopy(
                {
                    "alias_id": alias.id,
                    "candidate_index": candidate_index,
                    "profile_id": selected.profile_id,
                    "model_id": selected.model_id,
                    "priority": selected.routing.priority,
                    "weight": selected.routing.weight,
                }
            ),
        )


def _health_key(alias_id: str, candidate_index: int) -> tuple[str, int]:
    if candidate_index < 0:
        raise ValueError("candidate index must be non-negative")
    return alias_id, candidate_index


def _weighted_choice(
    candidates: Sequence[tuple[int, Deployment]], random_source: Callable[[], float]
) -> tuple[int, Deployment]:
    random_value = random_source()
    if not 0 <= random_value < 1:
        raise ValueError("random source must return a value in [0, 1)")
    total_weight = sum(deployment.routing.weight for _, deployment in candidates)
    target = random_value * total_weight
    for candidate_index, deployment in candidates:
        target -= deployment.routing.weight
        if target < 0:
            return candidate_index, deployment
    return candidates[-1]
