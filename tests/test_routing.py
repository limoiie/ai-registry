import pytest

from ai_registry.routing import (
    DeploymentHealthStore,
    DeploymentRouter,
    DeploymentTarget,
    HealthStore,
    NoAvailableDeploymentError,
)
from ai_registry.schemas import Alias, Deployment, RoutingMetadata


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def deployment(
    account_id: str,
    model_id: str = "chat",
    *,
    priority: int = 0,
    weight: int = 1,
    enabled: bool = True,
) -> Deployment:
    return Deployment(
        account_id=account_id,
        model_id=model_id,
        routing=RoutingMetadata(priority=priority, weight=weight, enabled=enabled),
    )


def target(account_id: str, model_id: str = "chat") -> DeploymentTarget:
    return DeploymentTarget(account_id=account_id, model_id=model_id)


def test_selects_enabled_healthy_deployment_with_lowest_priority() -> None:
    alias = Alias(
        id="chat",
        deployments=[
            deployment("slow", priority=2),
            deployment("disabled", priority=0, enabled=False),
            deployment("primary", priority=0),
            deployment("unhealthy", priority=0),
        ],
    )
    health = DeploymentHealthStore()
    health.record_failure(target("unhealthy"))

    selected = DeploymentRouter(health).select(alias)

    assert selected.deployment.account_id == "primary"
    assert selected.target == target("primary")
    assert selected.metadata == {
        "alias_id": "chat",
        "candidate_index": 2,
        "account_id": "primary",
        "model_id": "chat",
        "priority": 0,
        "weight": 1,
    }


def test_equal_priority_deployments_use_injected_weighted_random_source() -> None:
    alias = Alias(
        id="chat",
        deployments=[deployment("small", weight=1), deployment("large", weight=3)],
    )

    selected = DeploymentRouter(
        random_source=lambda: 0.5,
    ).select(alias)

    assert selected.deployment.account_id == "large"
    assert selected.metadata["weight"] == 3


def test_health_failure_excludes_deployment_until_cooldown_elapses() -> None:
    alias = Alias(id="chat", deployments=[deployment("primary"), deployment("backup")])
    clock = FakeClock()
    health = DeploymentHealthStore(cooldown_seconds=30.0, clock=clock)
    router = DeploymentRouter(health, random_source=lambda: 0.0)

    health.record_failure(target("primary"))
    assert router.select(alias).deployment.account_id == "backup"

    clock.advance(29.0)
    assert router.select(alias).deployment.account_id == "backup"

    clock.advance(2.0)
    assert router.select(alias).deployment.account_id == "primary"


def test_recorded_success_clears_cooldown_immediately() -> None:
    alias = Alias(id="chat", deployments=[deployment("primary"), deployment("backup")])
    clock = FakeClock()
    health = DeploymentHealthStore(cooldown_seconds=30.0, clock=clock)
    router = DeploymentRouter(health, random_source=lambda: 0.0)

    health.record_failure(target("primary"))
    assert router.select(alias).deployment.account_id == "backup"

    health.record_success(target("primary"))
    assert router.select(alias).deployment.account_id == "primary"


def test_repeated_failures_extend_the_cooldown_window_up_to_the_cap() -> None:
    clock = FakeClock()
    health = DeploymentHealthStore(
        cooldown_seconds=10.0, max_cooldown_seconds=25.0, clock=clock
    )
    primary = target("primary")

    health.record_failure(primary)
    assert health.cooldown_remaining(primary) == 10.0

    clock.advance(10.0)
    assert health.is_available(primary) is True
    health.record_failure(primary)
    assert health.cooldown_remaining(primary) == 20.0

    clock.advance(20.0)
    assert health.is_available(primary) is True
    health.record_failure(primary)
    assert health.cooldown_remaining(primary) == 25.0


def test_failure_threshold_tolerates_transient_errors() -> None:
    health = DeploymentHealthStore(failure_threshold=3)
    primary = target("primary")

    health.record_failure(primary)
    health.record_failure(primary)
    assert health.is_available(primary) is True

    health.record_failure(primary)
    assert health.is_available(primary) is False


def test_health_state_is_shared_across_aliases_for_the_same_target() -> None:
    fast = Alias(id="fast", deployments=[deployment("primary"), deployment("backup")])
    cheap = Alias(id="cheap", deployments=[deployment("primary"), deployment("backup")])
    health = DeploymentHealthStore()
    router = DeploymentRouter(health, random_source=lambda: 0.0)

    health.record_failure(target("primary"))

    assert router.select(fast).deployment.account_id == "backup"
    assert router.select(cheap).deployment.account_id == "backup"


def test_health_state_is_per_model_not_per_account() -> None:
    alias = Alias(
        id="chat",
        deployments=[
            deployment("primary", model_id="big"),
            deployment("primary", model_id="small"),
        ],
    )
    health = DeploymentHealthStore()
    router = DeploymentRouter(health, random_source=lambda: 0.0)

    health.record_failure(target("primary", "big"))

    assert router.select(alias).deployment.model_id == "small"


def test_health_state_survives_deployment_reordering() -> None:
    health = DeploymentHealthStore()
    health.record_failure(target("primary"))
    router = DeploymentRouter(health, random_source=lambda: 0.0)

    reordered = Alias(
        id="chat", deployments=[deployment("backup"), deployment("primary")]
    )

    assert router.select(reordered).deployment.account_id == "backup"


def test_no_available_deployment_error_is_safe() -> None:
    alias = Alias(id="chat", deployments=[deployment("primary")])
    health = DeploymentHealthStore()
    health.record_failure(target("primary"))

    with pytest.raises(NoAvailableDeploymentError) as caught:
        DeploymentRouter(health).select(alias)

    assert str(caught.value) == "no available deployment for alias 'chat'"
    assert "primary" not in str(caught.value)


def test_router_does_not_mutate_static_deployment_configuration() -> None:
    configured = deployment("primary", priority=1)
    alias = Alias(id="chat", deployments=[configured])
    router = DeploymentRouter(DeploymentHealthStore())

    selected = router.select(alias)
    selected.deployment.routing.priority = 99

    assert alias.deployments[0].routing.priority == 1


def test_candidates_are_ordered_by_priority_then_weight() -> None:
    alias = Alias(
        id="chat",
        deployments=[
            deployment("tertiary", priority=2),
            deployment("secondary", priority=1),
            deployment("primary", priority=0),
        ],
    )

    router = DeploymentRouter(random_source=lambda: 0.0)
    ordered = [item.deployment.account_id for item in router.candidates(alias)]

    assert ordered == ["primary", "secondary", "tertiary"]


def test_candidates_exclude_disabled_and_cooling_deployments() -> None:
    alias = Alias(
        id="chat",
        deployments=[
            deployment("primary"),
            deployment("off", enabled=False),
            deployment("cooling"),
        ],
    )
    health = DeploymentHealthStore()
    health.record_failure(target("cooling"))

    router = DeploymentRouter(health, random_source=lambda: 0.0)
    ordered = [item.deployment.account_id for item in router.candidates(alias)]

    assert ordered == ["primary"]


def test_candidates_return_empty_list_when_nothing_is_available() -> None:
    alias = Alias(id="chat", deployments=[deployment("primary", enabled=False)])

    assert DeploymentRouter().candidates(alias) == []


def test_default_health_store_satisfies_the_protocol() -> None:
    assert isinstance(DeploymentHealthStore(), HealthStore)


def test_health_store_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError, match=r"cooldown_seconds must be positive"):
        DeploymentHealthStore(cooldown_seconds=0)
    with pytest.raises(ValueError, match=r"max_cooldown_seconds must be"):
        DeploymentHealthStore(cooldown_seconds=10.0, max_cooldown_seconds=5.0)
    with pytest.raises(ValueError, match=r"failure_threshold must be at least 1"):
        DeploymentHealthStore(failure_threshold=0)
