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
    deployment: Deployment
    metadata: dict[str, Any]

    @property
    def deployment_id(self) -> str:
        """Return the alias reference used by the registry resolution layer."""
        return self.alias_id


class DeploymentHealthStore:
    """Mutable runtime health state kept separate from static configuration."""

    def __init__(self) -> None:
        self._healthy: dict[tuple[str, str, str, int, int], bool] = {}

    def mark_failure(self, alias_id: str, deployment: Deployment) -> None:
        self._healthy[_health_key(alias_id, deployment)] = False

    def mark_success(self, alias_id: str, deployment: Deployment) -> None:
        self._healthy[_health_key(alias_id, deployment)] = True

    def is_healthy(self, alias_id: str, deployment: Deployment) -> bool:
        return self._healthy.get(_health_key(alias_id, deployment), True)


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

    def select(self, alias: Alias) -> SelectedDeployment:
        available = [
            deployment
            for deployment in alias.deployments
            if deployment.routing.enabled
            and self.health_store.is_healthy(alias.id, deployment)
        ]
        if not available:
            raise NoAvailableDeploymentError(
                f"no available deployment for alias '{alias.id}'"
            )

        priority = min(deployment.routing.priority for deployment in available)
        candidates = [
            deployment
            for deployment in available
            if deployment.routing.priority == priority
        ]
        selected = deepcopy(_weighted_choice(candidates, self._random_source))
        return SelectedDeployment(
            alias_id=alias.id,
            deployment=selected,
            metadata={
                "alias_id": alias.id,
                "profile_id": selected.profile_id,
                "model_id": selected.model_id,
                "priority": selected.routing.priority,
                "weight": selected.routing.weight,
            },
        )


def _health_key(
    alias_id: str, deployment: Deployment
) -> tuple[str, str, str, int, int]:
    return (
        alias_id,
        deployment.profile_id,
        deployment.model_id,
        deployment.routing.priority,
        deployment.routing.weight,
    )


def _weighted_choice(
    deployments: Sequence[Deployment], random_source: Callable[[], float]
) -> Deployment:
    random_value = random_source()
    if not 0 <= random_value < 1:
        raise ValueError("random source must return a value in [0, 1)")
    total_weight = sum(deployment.routing.weight for deployment in deployments)
    target = random_value * total_weight
    for deployment in deployments:
        target -= deployment.routing.weight
        if target < 0:
            return deployment
    return deployments[-1]
