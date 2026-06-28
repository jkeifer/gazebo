"""The collection-envelope shape: items + links + counts.

Generic over the item type only. Subclasses set the serialization alias for the
items field (OGC calls it ``features``, ``records`` ...) via the ``items_alias``
class keyword. Because links are deferred, a ``LinkedCollection`` is fully
constructible in business logic with no request in hand.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

from pydantic import (
    BaseModel,
    Field,
    GetJsonSchemaHandler,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    computed_field,
    model_serializer,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from gazebo.jsonschema import drop_none, faithful_serialization_schema
from gazebo.link import Link


class LinkedCollection[T](BaseModel):
    """A list of ``T`` with hypermedia links and counts.

    >>> class FeatureCollection(LinkedCollection[Feature], items_alias='features'): ...

    Two class keywords tune serialization, both held as class variables (so they
    survive generic parametrization like ``FeatureCollection[P]`` — mutating
    ``model_fields`` would not, as pydantic rebuilds them per specialization):

    - ``items_alias`` — the JSON key the items serialize under (OGC ``features`` /
      ``records`` / ``collections`` ...).
    - ``number_returned`` — set ``False`` to omit the computed ``numberReturned``
      member (e.g. an OGC ``/collections`` listing, where it isn't defined).

    >>> class Collections(LinkedCollection[C], items_alias='collections',
    ...                   number_returned=False): ...
    """

    _items_alias: ClassVar[str] = 'items'
    _emit_number_returned: ClassVar[bool] = True

    items: Sequence[T]
    links: list[Link] = Field(default_factory=list)
    number_matched: int | None = Field(default=None, serialization_alias='numberMatched')

    @computed_field(alias='numberReturned')
    @property
    def number_returned(self) -> int:
        return len(self.items)

    @model_serializer(mode='wrap', when_used='always')
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        # The alias and the numberReturned toggle apply in every mode (matching how a
        # plain serialization_alias would behave); the OGC-style null-dropping is for
        # the JSON wire format only, so a python-mode dump still round-trips.
        data = handler(self)
        if info.by_alias and self._items_alias != 'items':
            data = {(self._items_alias if k == 'items' else k): v for k, v in data.items()}
        if not self._emit_number_returned:
            # The computed field carries alias='numberReturned', so the key the handler
            # emitted is determined by by_alias — pop exactly that one (same condition
            # the items rename above keys on) rather than guessing both names.
            data.pop('numberReturned' if info.by_alias else 'number_returned', None)
        if info.mode == 'json':
            data = drop_none(data)
        return data

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        # Reconstruct the real (non-opaque) serialization schema, then mirror what the
        # serializer does to the JSON: rename the items key to its alias and drop the
        # numberReturned member when toggled off — applied to both ``properties`` and
        # ``required`` so OpenAPI matches the emitted body.
        json_schema = faithful_serialization_schema(core_schema, handler)
        if handler.mode != 'serialization':
            return json_schema

        rename = {'items': cls._items_alias} if cls._items_alias != 'items' else {}
        drop = set() if cls._emit_number_returned else {'numberReturned', 'number_returned'}

        properties = json_schema.get('properties')
        if isinstance(properties, dict):
            json_schema['properties'] = {
                rename.get(k, k): v for k, v in properties.items() if k not in drop
            }
        required = json_schema.get('required')
        if isinstance(required, list):
            json_schema['required'] = [
                rename.get(name, name) for name in required if name not in drop
            ]
        return json_schema

    def __init_subclass__(
        cls,
        *,
        items_alias: str | None = None,
        number_returned: bool | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if items_alias is not None:
            cls._items_alias = items_alias
        if number_returned is not None:
            cls._emit_number_returned = number_returned
