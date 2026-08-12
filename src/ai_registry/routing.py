"""Health-aware, framework-independent deployment selection."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ai_registry.errors import RegistryError
from ai_registry.schemas import Alias, Deployment


class NoAvailableDeploymentError(RegistryError):
    """Raised when an alias has no enabled and healthy deployment."""


@dataclass(frozen=True)
class DeploymentTarget:
    """The identity of a deployment, independent of the alias referencing it.

    Health state is keyed by this value so that a failing account/model pair is
    withheld from *every* alias that references it, and so that reordering
    deployments in configuration never reassigns state to a different target.
    """

    account_id: str
    model_id: str


@runtime_checkable
class HealthStore(Protocol):
    """Pluggable runtime availability state for deployment targets."""

    def is_available(self, target: DeploymentTarget) -> bool:
        """Return whether the target may currently be selected."""

    def record_success(self, target: DeploymentTarget) -> None:
        """Clear any recorded failure state for the target."""

    def record_failure(self, target: DeploymentTarget) -> None:
        """Record a failure, cooling the target down once the threshold is met."""


@dataclass
class _TargetState:
    consecutive_failures: int = 0
    cooldown_rounds: int = 0
    cooldown_until: float | None = None


class DeploymentHealthStore:
    """In-memory, thread-safe health state with time-based recovery.

    A target is withheld only until its cooldown elapses. The first selection
    after that window is a half-open trial: a success clears the state, and a
    failure cools it down again with an exponentially longer window, capped by
    ``max_cooldown_seconds``.
    """

    def __init__(
        self,
        *,
        cooldown_seconds: float = 60.0,
        max_cooldown_seconds: float = 600.0,
        failure_threshold: int = 1,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")
        if max_cooldown_seconds < cooldown_seconds:
            raise ValueError("max_cooldown_seconds must be >= cooldown_seconds")
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        self._cooldown_seconds = cooldown_seconds
        self._max_cooldown_seconds = max_cooldown_seconds
        self._failure_threshold = failure_threshold
        self._clock = clock
        self._lock = threading.Lock()
        self._states: dict[DeploymentTarget, _TargetState] = {}

    def is_available(self, target: DeploymentTarget) -> bool:
        with self._lock:
            state = self._states.get(target)
            if state is None or state.cooldown_until is None:
                return True
            if self._clock() >= state.cooldown_until:
                # Half-open: allow one trial without clearing the failure count.
                state.cooldown_until = None
                return True
            return False

    def record_success(self, target: DeploymentTarget) -> None:
        with self._lock:
            self._states.pop(target, None)

    def record_failure(self, target: DeploymentTarget) -> None:
        with self._lock:
            state = self._states.setdefault(target, _TargetState())
            state.consecutive_failures += 1
            if state.consecutive_failures < self._failure_threshold:
                return
            window = min(
                self._cooldown_seconds * (2**state.cooldown_rounds),
                self._max_cooldown_seconds,
            )
            state.cooldown_rounds += 1
            state.cooldown_until = self._clock() + window

    def cooldown_remaining(self, target: DeploymentTarget) -> float:
        """Return seconds until the target recovers, or ``0.0`` if available."""
        with self._lock:
            state = self._states.get(target)
            if state is None or state.cooldown_until is None:
                return 0.0
            return max(0.0, state.cooldown_until - self._clock())


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

    @property
    def target(self) -> DeploymentTarget:
        """Return the health-state identity of the selected deployment."""
        return DeploymentTarget(
            account_id=self.deployment.account_id,
            model_id=self.deployment.model_id,
        )


class DeploymentRouter:
    """Select an available deployment according to priority and weight."""

    def __init__(
        self,
        health_store: HealthStore | None = None,
        *,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        self.health_store: HealthStore = health_store or DeploymentHealthStore()
        self._random_source = random_source

    def select(
        self,
        alias: Alias,
        *,
        eligible: Callable[[Deployment], bool] | None = None,
    ) -> SelectedDeployment:
        """Return the single preferred deployment for ``alias``."""
        available = self._available(alias, eligible)
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
        return _selected(alias.id, candidate_index, selected)

    def candidates(
        self,
        alias: Alias,
        *,
        eligible: Callable[[Deployment], bool] | None = None,
    ) -> list[SelectedDeployment]:
        """Return every available deployment in preference order.

        Callers that implement their own request-time failover can walk this
        list instead of re-selecting after each failure. Deployments are ordered
        by ascending priority; within a priority, order is a weighted shuffle
        drawn from the injected random source.
        """
        available = self._available(alias, eligible)
        ordered: list[SelectedDeployment] = []
        remaining = sorted(available, key=lambda item: item[1].routing.priority)
        while remaining:
            priority = remaining[0][1].routing.priority
            group = [item for item in remaining if item[1].routing.priority == priority]
            remaining = [
                item for item in remaining if item[1].routing.priority != priority
            ]
            while group:
                candidate_index, selected = _weighted_choice(group, self._random_source)
                group = [item for item in group if item[0] != candidate_index]
                ordered.append(_selected(alias.id, candidate_index, selected))
        return ordered

    def _available(
        self,
        alias: Alias,
        eligible: Callable[[Deployment], bool] | None,
    ) -> list[tuple[int, Deployment]]:
        eligibility = eligible or (lambda deployment: True)
        return [
            (candidate_index, deployment)
            for candidate_index, deployment in enumerate(alias.deployments)
            if deployment.routing.enabled
            and eligibility(deployment)
            and self.health_store.is_available(
                DeploymentTarget(
                    account_id=deployment.account_id, model_id=deployment.model_id
                )
            )
        ]


def _selected(
    alias_id: str, candidate_index: int, deployment: Deployment
) -> SelectedDeployment:
    selected = deepcopy(deployment)
    return SelectedDeployment(
        alias_id=alias_id,
        candidate_index=candidate_index,
        deployment=selected,
        metadata=deepcopy(
            {
                "alias_id": alias_id,
                "candidate_index": candidate_index,
                "account_id": selected.account_id,
                "model_id": selected.model_id,
                "priority": selected.routing.priority,
                "weight": selected.routing.weight,
            }
        ),
    )


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
