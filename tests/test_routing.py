import pytest

from ai_registry.routing import (
    DeploymentHealthStore,
    DeploymentRouter,
    NoAvailableDeploymentError,
)
from ai_registry.schemas import Alias, Deployment, RoutingMetadata


def deployment(
    profile_id: str,
    model_id: str = "chat",
    *,
    priority: int = 0,
    weight: int = 1,
    enabled: bool = True,
) -> Deployment:
    return Deployment(
        profile_id=profile_id,
        model_id=model_id,
        routing=RoutingMetadata(priority=priority, weight=weight, enabled=enabled),
    )


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
    health.mark_failure("chat", alias.deployments[3])

    selected = DeploymentRouter(health).select(alias)

    assert selected.deployment.profile_id == "primary"
    assert selected.metadata == {
        "alias_id": "chat",
        "profile_id": "primary",
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

    assert selected.deployment.profile_id == "large"
    assert selected.metadata["weight"] == 3


def test_health_failure_excludes_deployment_until_recovery() -> None:
    first = deployment("primary")
    second = deployment("backup")
    alias = Alias(id="chat", deployments=[first, second])
    health = DeploymentHealthStore()
    router = DeploymentRouter(health, random_source=lambda: 0.0)

    health.mark_failure("chat", first)
    assert router.select(alias).deployment.profile_id == "backup"

    health.mark_success("chat", first)
    assert router.select(alias).deployment.profile_id == "primary"


def test_no_available_deployment_error_is_safe() -> None:
    secret_like = deployment("primary", model_id="chat")
    alias = Alias(id="chat", deployments=[secret_like])
    health = DeploymentHealthStore()
    health.mark_failure("chat", secret_like)

    with pytest.raises(NoAvailableDeploymentError) as caught:
        DeploymentRouter(health).select(alias)

    assert str(caught.value) == "no available deployment for alias 'chat'"
    assert "primary" not in str(caught.value)


def test_router_does_not_mutate_static_deployment_configuration() -> None:
    configured = deployment("primary", priority=1)
    alias = Alias(id="chat", deployments=[configured])
    health = DeploymentHealthStore()
    router = DeploymentRouter(health)

    selected = router.select(alias)
    selected.deployment.routing.priority = 99

    assert alias.deployments[0].routing.priority == 1
