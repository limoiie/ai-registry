"""Validated, secret-safe configuration schemas for the registry core."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence, Set
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


def canonical_sdk_type(top_sdk_type: Any, nested_sdk_type: Any) -> Any:
    """Validate equivalent SDK declarations and return the canonical value."""
    if top_sdk_type is not None and nested_sdk_type is not None:
        canonical_top = "openai" if top_sdk_type == "uniapi" else top_sdk_type
        canonical_nested = "openai" if nested_sdk_type == "uniapi" else nested_sdk_type
        if canonical_top != canonical_nested:
            raise ConfigurationError(
                "conflicting sdk_type values; use one canonical SDK type"
            )
    canonical = top_sdk_type if top_sdk_type is not None else nested_sdk_type
    return "openai" if canonical == "uniapi" else canonical


class SafeModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", validate_assignment=True, hide_input_in_errors=True
    )
    _secret_fields: ClassVar[set[str]] = set()

    def _raw_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Return the unredacted representation for internal resolution only."""
        if kwargs.get("mode") == "json":
            kwargs.setdefault("fallback", _json_fallback)
        return super().model_dump(**kwargs)

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        return cast(
            dict[str, Any], _redact(self._raw_dump(**kwargs), self._secret_fields)
        )

    def model_dump_json(self, **kwargs: Any) -> str:
        kwargs.setdefault("fallback", _json_fallback)
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


def _json_fallback(value: Any) -> Any:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    if isinstance(value, Set):
        return set(value)
    raise TypeError(f"unsupported serialization type: {type(value).__name__}")


def _redact(value: Any, secret_fields: set[str]) -> Any:
    if isinstance(value, Mapping):
        return {
            key: "<redacted>"
            if key in secret_fields
            or key in {"env", "secret_ref", "api_key"}
            or (
                isinstance(key, str)
                and _is_sensitive_key(key)
                and not (
                    key.casefold() == "credential"
                    and (item is None or isinstance(item, Mapping))
                )
            )
            else _redact(item, secret_fields)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if (
            len(value) == 2
            and isinstance(value[0], str)
            and _is_sensitive_key(value[0])
        ):
            redacted = (value[0], "<redacted>")
        else:
            redacted = tuple(_redact(item, secret_fields) for item in value)
        return redacted if isinstance(value, tuple) else list(redacted)
    if isinstance(value, Set):
        return {_redact(item, secret_fields) for item in value}
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


_SENSITIVE_KEY_WORDS = {
    "authorization",
    "credential",
    "credentials",
    "env",
    "passphrase",
    "passwd",
    "password",
    "secret",
    "secret_ref",
    "sig",
    "signature",
}
_SENSITIVE_KEY_QUALIFIERS = {
    "access",
    "api",
    "auth",
    "authentication",
    "bearer",
    "client",
    "device",
    "functions",
    "id",
    "openai",
    "private",
    "refresh",
    "sas",
    "secret",
    "security",
    "session",
    "signing",
    "user",
}
_SENSITIVE_KEY_TOKENS = {"apikey", "authkey", "sessionid"}


def _key_words(key: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key)
    return [word.casefold() for word in re.split(r"[^A-Za-z0-9]+", spaced) if word]


def _is_sensitive_key(key: str) -> bool:
    words = _key_words(key)
    if not words:
        return False
    if any(word in _SENSITIVE_KEY_WORDS for word in words):
        return True
    if any(token in words for token in _SENSITIVE_KEY_TOKENS):
        return True
    if len(words) > 1:
        if words[-1] in {"key", "token"} and words[-2] in _SENSITIVE_KEY_QUALIFIERS:
            return True
        if words[-1] == "id" and words[-2] == "session":
            return True
    return words == ["token"]


def _validate_endpoint(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = urlsplit(value)
        has_userinfo = parsed.username is not None or parsed.password is not None
        query = parsed.query
        fragment = parsed.fragment
    except ValueError:
        has_userinfo = True
        query = ""
        fragment = ""
    if has_userinfo:
        raise ValueError(
            "endpoint contains credential-bearing user info or sensitive query "
            "parameters; use credential references"
        )
    for parameters in (query, fragment):
        for key, _ in parse_qsl(parameters.replace(";", "&"), keep_blank_values=True):
            if not key:
                raise ValueError("endpoint query parameter names must be non-empty")
            if _is_sensitive_key(key):
                raise ValueError(
                    "endpoint contains credential-bearing user info or sensitive "
                    "query parameters; use credential references"
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
            top_sdk_type = data.get("sdk_type")
            nested_sdk_type = (
                settings.get("sdk_type") if isinstance(settings, dict) else None
            )
            if top_sdk_type is not None or nested_sdk_type is not None:
                data = dict(data)
                data["sdk_type"] = canonical_sdk_type(top_sdk_type, nested_sdk_type)
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
