"""Public package interface for the AI registry."""

__version__ = "0.1.0"

from ai_registry.registry import Registry
from ai_registry.routing import (
    DeploymentHealthStore,
    DeploymentRouter,
    NoAvailableDeploymentError,
    SelectedDeployment,
)

__all__ = [
    "DeploymentHealthStore",
    "DeploymentRouter",
    "NoAvailableDeploymentError",
    "Registry",
    "SelectedDeployment",
    "__version__",
]
