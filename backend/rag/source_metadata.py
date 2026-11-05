"""Explicit, free-text source labels; no academic taxonomy or inferred scope."""

from typing import Annotated
import unicodedata

from pydantic import BaseModel, BeforeValidator, ConfigDict, model_validator


def normalize_metadata(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Metadata must be a string or null")
    normalized = unicodedata.normalize("NFC", " ".join(value.split()))
    return normalized or None


def normalize_filter(value: object) -> str | None:
    normalized = normalize_metadata(value)
    if value is not None and normalized is None:
        raise ValueError("A supplied metadata filter must not be blank")
    return normalized


MetadataValue = Annotated[str | None, BeforeValidator(normalize_metadata)]
MetadataFilter = Annotated[str | None, BeforeValidator(normalize_filter)]


class SourceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: MetadataValue = None
    audience: MetadataValue = None


class SourceMetadataPatch(SourceMetadata):
    @model_validator(mode="after")
    def require_fields(self) -> "SourceMetadataPatch":
        if not self.model_fields_set:
            raise ValueError("At least one metadata field must be provided")
        return self


class RetrievalFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: MetadataFilter = None
    audience: MetadataFilter = None
