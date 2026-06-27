"""OpenAPI tag helpers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class TagDocs(BaseModel):
    model_config = ConfigDict(frozen=True)

    description: str
    url: HttpUrl


class Tag(BaseModel):
    """An OpenAPI tag. ``external_docs`` serializes as ``externalDocs``."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str | None = None
    external_docs: TagDocs | None = Field(
        default=None,
        serialization_alias='externalDocs',
    )


def tags_metadata(*tags: Tag) -> list[dict[str, Any]]:
    """Build a list of OpenAPI tag objects (e.g. for FastAPI's ``openapi_tags``)."""
    return [tag.model_dump(mode='json', by_alias=True, exclude_none=True) for tag in tags]
