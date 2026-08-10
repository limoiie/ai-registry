"""Validated, secret-safe configuration schemas for the registry core."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, ClassVar, cast

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from ai_registry.errors import ConfigurationError


class ModelType(StrEnum):
    CHAT = "chat"
    EMBEDDING = "embedding"
    RERANKING = "reranking"


class SDKType(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    CUSTOM = "custom"


class SafeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    _secret_fields: ClassVar[set[str]] = set()

    def safe_dump(self) -> dict[str, Any]:
        value = self.model_dump(mode="json", exclude_none=True)
        return cast(dict[str, Any], _redact(value, self._secret_fields))

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.safe_dump()!r})"

    def __str__(self) -> str:
        return repr(self)


def _redact(value: Any, secret_fields: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: "<redacted>"
            if key in secret_fields or key in {"env", "secret_ref", "api_key"}
            else _redact(item, secret_fields)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, secret_fields) for item in value]
    return value


Identifier = StrictStr


def _check_identifier(value: str) -> str:
    if (
        not value
        or not value.replace("-", "").replace("_", "").replace(".", "").isalnum()
    ):
        raise ValueError(
            "must be a non-empty identifier using letters, numbers, -, _, or ."
        )
    return value


class ModelCapabilities(SafeModel):
    tools: bool = False
    structured_output: bool = False
    vision: bool = False
    reasoning: bool = False


class ModelCard(SafeModel):
    id: Identifier
    type: ModelType
    display_name: str | None = None
    description: str | None = None
    released_at: date | None = None
    context_window_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    embedding_dimension: int | None = Field(default=None, ge=1)
    capabilities: ModelCapabilities = Field(
        default_factory=ModelCapabilities,
        validation_alias=AliasChoices("capabilities", "abilities"),
    )

    _validate_id = field_validator("id")(_check_identifier)


class Provider(SafeModel):
    id: Identifier
    name: str
    description: str | None = None
    sdk_type: SDKType = Field(
        default=SDKType.OPENAI,
        validation_alias=AliasChoices("sdk_type", "settings.sdk_type"),
    )
    default_base_url: str | None = None
    model_cards: list[ModelCard] = Field(default_factory=list)

    _validate_id = field_validator("id")(_check_identifier)


class CredentialRef(SafeModel):
    env: StrictStr | None = Field(default=None, min_length=1)
    secret_ref: StrictStr | None = Field(default=None, min_length=1)
    api_key: StrictStr | None = None
    _secret_fields = {"env", "secret_ref", "api_key"}

    @model_validator(mode="after")
    def validate_reference(self) -> CredentialRef:
        references = [self.env, self.secret_ref, self.api_key]
        if sum(value is not None for value in references) != 1:
            raise ValueError("credential must contain exactly one env or secret_ref")
        if self.api_key is not None:
            raise ValueError("literal API keys are rejected; use env or secret_ref")
        return self


class Profile(SafeModel):
    id: Identifier
    provider_id: Identifier
    endpoint: str | None = Field(
        default=None, validation_alias=AliasChoices("endpoint", "base_url")
    )
    credential: CredentialRef | None = Field(
        default=None, validation_alias=AliasChoices("credential", "api_key")
    )
    enabled_models: list[Identifier] = Field(default_factory=list)
    enabled: bool = True
    timeout_seconds: float | None = Field(default=None, gt=0)

    _validate_id = field_validator("id", "provider_id")(_check_identifier)

    @field_validator("enabled_models")
    @classmethod
    def validate_enabled_models(cls, values: list[str]) -> list[str]:
        return [_check_identifier(value) for value in values]


class RoutingMetadata(SafeModel):
    priority: StrictInt = Field(default=0, ge=0)
    weight: StrictInt = Field(default=1, ge=1)
    enabled: bool = True
    timeout_seconds: float | None = Field(default=None, gt=0)


class Deployment(SafeModel):
    profile_id: Identifier = Field(
        validation_alias=AliasChoices("profile_id", "profile")
    )
    model_id: Identifier = Field(validation_alias=AliasChoices("model_id", "model"))
    routing: RoutingMetadata = Field(default_factory=RoutingMetadata)

    _validate_id = field_validator("profile_id", "model_id")(_check_identifier)


class Alias(SafeModel):
    id: Identifier
    deployments: list[Deployment] = Field(min_length=1)

    _validate_id = field_validator("id")(_check_identifier)


class RegistryConfig(SafeModel):
    providers: list[Provider] = Field(default_factory=list)
    profiles: list[Profile] = Field(default_factory=list)
    aliases: list[Alias] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> RegistryConfig:
        for provider in self.providers:
            model_ids = [card.id for card in provider.model_cards]
            if len(model_ids) != len(set(model_ids)):
                raise ConfigurationError("duplicate model id")

        for field_name, values, label in (
            ("providers", self.providers, "provider"),
            ("profiles", self.profiles, "profile"),
            ("aliases", self.aliases, "alias"),
        ):
            del field_name
            ids = [item.id for item in values]
            if len(ids) != len(set(ids)):
                raise ConfigurationError(f"duplicate {label} id")
        return self
