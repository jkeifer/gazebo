"""The collection-envelope shape: items + links + counts.

Generic over the item type only. Subclasses set the serialization alias for the
items field (OGC calls it ``features``, ``records`` ...) via the ``items_alias``
class keyword. Because links are deferred, a ``LinkedCollection`` is fully
constructible in business logic with no request in hand.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import (
    BaseModel,
    Field,
    SerializerFunctionWrapHandler,
    computed_field,
    model_serializer,
)

from gazebo.link import Link


class LinkedCollection[T](BaseModel):
    """A list of ``T`` with hypermedia links and counts.

    >>> class FeatureCollection(LinkedCollection[Feature], items_alias='features'): ...
    """

    items: Sequence[T]
    links: list[Link] = Field(default_factory=list)
    number_matched: int | None = Field(default=None, serialization_alias='numberMatched')

    @computed_field(alias='numberReturned')
    @property
    def number_returned(self) -> int:
        return len(self.items)

    @model_serializer(mode='wrap', when_used='json')
    def _drop_none(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return {k: v for k, v in handler(self).items() if v is not None}

    def __init_subclass__(cls, *, items_alias: str | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if items_alias is not None:
            cls.model_fields['items'].serialization_alias = items_alias
            cls.model_rebuild(force=True)
