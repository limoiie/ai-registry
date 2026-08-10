"""Validated, secret-safe configuration schemas for the registry core."""

from __future__ import annotations

import json
import re
from datetime import date
from enum import StrEnum
from typing import Any, ClassVar, Self, cast
from urllib.parse import parse_qsl, urlsplit

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
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
    model_config = ConfigDict(
        extra="forbid", validate_assignment=True, hide_input_in_errors=True
    )
    _secret_fields: ClassVar[set[str]] = set()

    def _raw_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Return the unredacted representation for internal resolution only."""
        return super().model_dump(**kwargs)

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        return cast(
            dict[str, Any], _redact(self._raw_dump(**kwargs), self._secret_fields)
        )

    def model_dump_json(self, **kwargs: Any) -> str:
        value = json.loads(super().model_dump_json(**kwargs))
        return json.dumps(_redact(value, self._secret_fields), ensure_ascii=False)

    def safe_dump(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.safe_dump()!r})"

    def __str__(self) -> str:
        return repr(self)

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except ValidationError as error:
            raise _safe_validation_error(error) from None

    @classmethod
    def model_validate(
        cls,
        obj: Any,
        *,
        strict: bool | None = None,
        extra: Any = None,
        from_attributes: bool | None = None,
        context: Any = None,
        by_alias: bool | None = None,
        by_name: bool | None = None,
    ) -> Self:
        try:
            return super().model_validate(
                obj,
                strict=strict,
                extra=extra,
                from_attributes=from_attributes,
                context=context,
                by_alias=by_alias,
                by_name=by_name,
            )
        except ValidationError as error:
            raise _safe_validation_error(error) from None


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


def _safe_validation_error(error: ValidationError) -> ValidationError:
    details = []
    for detail in error.errors():
        safe_detail = dict(detail)
        safe_detail.pop("input", None)
        details.append(safe_detail)
    return ValidationError.from_exception_data(error.title, cast(Any, details))


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


def _check_model_id(value: str) -> str:
    if (
        not value
        or any(character.isspace() for character in value)
        or not all(character.isalnum() or character in "-_.:/" for character in value)
    ):
        raise ValueError("must be a non-empty model identifier without whitespace")
    return value


_ENDPOINT_SENSITIVE_WORDS = {"authorization", "credential", "password", "secret"}
_ENDPOINT_TOKEN_QUALIFIERS = {
    "access",
    "auth",
    "authentication",
    "bearer",
    "client",
    "id",
    "refresh",
    "session",
}


def _is_sensitive_endpoint_key(key: str) -> bool:
    words = [word for word in re.split(r"[^A-Za-z0-9]+", key.casefold()) if word]
    if any(word in _ENDPOINT_SENSITIVE_WORDS for word in words):
        return True
    if "apikey" in words or any(
        left == "api" and right == "key" for left, right in zip(words, words[1:])
    ):
        return True
    return words == ["token"] or (
        words[-1] == "token" and words[-2] in _ENDPOINT_TOKEN_QUALIFIERS
    )


def _validate_endpoint(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = urlsplit(value)
        has_userinfo = parsed.username is not None or parsed.password is not None
        query = parsed.query
    except ValueError:
        has_userinfo = True
        query = ""
    if has_userinfo or any(
        _is_sensitive_endpoint_key(key)
        for key, _ in parse_qsl(query, keep_blank_values=True)
    ):
        raise ValueError(
            "endpoint contains credential-bearing user info or sensitive query "
            "parameters; use credential references"
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
    metadata: dict[str, Any] = Field(default_factory=dict)

    _validate_id = field_validator("id")(_check_model_id)


class Provider(SafeModel):
    id: Identifier
    name: str
    description: str | None = None
    sdk_type: SDKType = SDKType.OPENAI
    default_base_url: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    model_cards: list[ModelCard] = Field(default_factory=list)

    _validate_id = field_validator("id")(_check_identifier)
    _validate_endpoint = field_validator("default_base_url")(_validate_endpoint)

    @model_validator(mode="before")
    @classmethod
    def normalize_nested_settings(cls, data: Any) -> Any:
        if isinstance(data, dict):
            settings = data.get("settings")
            if data.get("sdk_type") == "uniapi":
                data = dict(data)
                data["sdk_type"] = SDKType.OPENAI
            elif "sdk_type" not in data and isinstance(settings, dict):
                data = dict(data)
                data["sdk_type"] = settings.get("sdk_type", SDKType.OPENAI)
                if data["sdk_type"] == "uniapi":
                    data["sdk_type"] = SDKType.OPENAI
        return data


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
    metadata: dict[str, Any] = Field(default_factory=dict)

    _validate_id = field_validator("id", "provider_id")(_check_identifier)
    _validate_endpoint = field_validator("endpoint")(_validate_endpoint)

    @field_validator("enabled_models")
    @classmethod
    def validate_enabled_models(cls, values: list[str]) -> list[str]:
        return [_check_model_id(value) for value in values]


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

    _validate_id = field_validator("profile_id")(_check_identifier)
    _validate_model_id = field_validator("model_id")(_check_model_id)


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

        for values, label in (
            (self.providers, "provider"),
            (self.profiles, "profile"),
            (self.aliases, "alias"),
        ):
            ids = [item.id for item in values]
            if len(ids) != len(set(ids)):
                raise ConfigurationError(f"duplicate {label} id")
        return self
