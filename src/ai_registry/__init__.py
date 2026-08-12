"""Public package interface for the AI registry.

Resolve a stable alias to a concrete deployment — provider, model card, account
and endpoint — then build any framework-native client from the result. Nothing
in this package performs network access, and credentials are held as references
until an adapter asks for one.

Names re-exported here are the supported API surface. Adapters live under
``ai_registry.adapters`` and are never imported from this module, so the core
import cost stays at Pydantic and PyYAML.
"""

__version__ = "0.1.0"

from ai_registry.errors import (
    AdapterError as AdapterError,
)
from ai_registry.errors import (
    ConfigurationError as ConfigurationError,
)
from ai_registry.errors import (
    MissingDependencyError as MissingDependencyError,
)
from ai_registry.errors import (
    RegistryError as RegistryError,
)
from ai_registry.errors import (
    SecretConfigurationError as SecretConfigurationError,
)
from ai_registry.errors import (
    UnsupportedProviderError as UnsupportedProviderError,
)
from ai_registry.registry import (
    CatalogEntry as CatalogEntry,
)
from ai_registry.registry import (
    Registry as Registry,
)
from ai_registry.registry import (
    Resolution as Resolution,
)
from ai_registry.routing import (
    DeploymentHealthStore as DeploymentHealthStore,
)
from ai_registry.routing import (
    DeploymentRouter as DeploymentRouter,
)
from ai_registry.routing import (
    DeploymentTarget as DeploymentTarget,
)
from ai_registry.routing import (
    HealthStore as HealthStore,
)
from ai_registry.routing import (
    NoAvailableDeploymentError as NoAvailableDeploymentError,
)
from ai_registry.routing import (
    SelectedDeployment as SelectedDeployment,
)
from ai_registry.schemas import (
    Account as Account,
)
from ai_registry.schemas import (
    Alias as Alias,
)
from ai_registry.schemas import (
    CredentialRef as CredentialRef,
)
from ai_registry.schemas import (
    Deployment as Deployment,
)
from ai_registry.schemas import (
    Model as Model,
)
from ai_registry.schemas import (
    ModelCapabilities as ModelCapabilities,
)
from ai_registry.schemas import (
    ModelType as ModelType,
)
from ai_registry.schemas import (
    Provider as Provider,
)
from ai_registry.schemas import (
    RegistryConfig as RegistryConfig,
)
from ai_registry.schemas import (
    RoutingMetadata as RoutingMetadata,
)
from ai_registry.schemas import (
    SDKType as SDKType,
)
from ai_registry.secrets import (
    EnvironmentSecretResolver as EnvironmentSecretResolver,
)
from ai_registry.secrets import (
    SecretResolutionError as SecretResolutionError,
)
from ai_registry.secrets import (
    SecretResolver as SecretResolver,
)

__all__ = [
    "Account",
    "AdapterError",
    "Alias",
    "CatalogEntry",
    "ConfigurationError",
    "CredentialRef",
    "Deployment",
    "DeploymentHealthStore",
    "DeploymentRouter",
    "DeploymentTarget",
    "EnvironmentSecretResolver",
    "HealthStore",
    "MissingDependencyError",
    "Model",
    "ModelCapabilities",
    "ModelType",
    "NoAvailableDeploymentError",
    "Provider",
    "Registry",
    "RegistryConfig",
    "RegistryError",
    "Resolution",
    "RoutingMetadata",
    "SDKType",
    "SecretConfigurationError",
    "SecretResolutionError",
    "SecretResolver",
    "SelectedDeployment",
    "UnsupportedProviderError",
    "__version__",
]
