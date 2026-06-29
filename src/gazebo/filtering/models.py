"""Filtering models: ``sortby``, and the queryables/sortables schema resources.

Core layer: pydantic + stdlib only. ``SortBy`` parses the OGC/STAC ``sortby`` value and
applies a stable in-memory sort; ``Queryables`` and ``Sortables`` are the JSON-Schema
resources OGC serves at ``/collections/{id}/queryables`` and ``.../sortables``. The
builders that derive them from a pydantic model live in :mod:`gazebo.filtering.queryables`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from gazebo.link import Link
from gazebo.params import ParamError
from gazebo.serialization import OmitNullModel

JSON_SCHEMA_DIALECT = 'https://json-schema.org/draft/2019-09/schema'
"""The JSON Schema dialect OGC queryables/sortables declare via ``$schema``."""

# --- conformance classes (roadmap #11 feeds these into the honest declaration) -------
CONF_FILTER = 'http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/filter'
CONF_FEATURES_FILTER = 'http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/features-filter'
CONF_QUERYABLES = 'http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/queryables'
CONF_SORTBY = 'http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/sorting'
CONF_CQL2_TEXT = 'http://www.opengis.net/spec/cql2/1.0/conf/cql2-text'
CONF_CQL2_JSON = 'http://www.opengis.net/spec/cql2/1.0/conf/cql2-json'

REL_QUERYABLES = 'http://www.opengis.net/def/rel/ogc/1.0/queryables'
REL_SORTABLES = 'http://www.opengis.net/def/rel/ogc/1.0/sortables'


def filter_conformance_classes(*, cql2_text: bool = True, cql2_json: bool = True) -> list[str]:
    """The conformance-class URIs a CQL2-filterable collection should declare."""
    uris = [CONF_FILTER, CONF_FEATURES_FILTER, CONF_QUERYABLES, CONF_SORTBY]
    if cql2_text:
        uris.append(CONF_CQL2_TEXT)
    if cql2_json:
        uris.append(CONF_CQL2_JSON)
    return uris


class Direction(StrEnum):
    """Sort direction; ``-`` in a ``sortby`` term selects :attr:`DESC`."""

    ASC = 'asc'
    DESC = 'desc'


class Sort(BaseModel):
    """One ``sortby`` term: a (possibly dotted) field name and a direction."""

    field: str
    direction: Direction = Direction.ASC


def _dotted_get(item: Any, path: str) -> Any:
    """Resolve a dotted path into nested mappings; missing/non-mapping yields ``None``."""
    cur = item
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


class _Last:
    """Sort sentinel that orders after every real value (so nulls sort last, ascending)."""

    __slots__ = ()

    def __lt__(self, other: object) -> bool:
        return False

    def __gt__(self, other: object) -> bool:
        return not isinstance(other, _Last)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Last)

    def __hash__(self) -> int:
        return 0


_LAST = _Last()


class SortBy(BaseModel):
    """A parsed OGC/STAC ``sortby`` value: an ordered list of :class:`Sort` terms."""

    sorts: list[Sort] = Field(default_factory=list)

    @classmethod
    def parse(cls, raw: str, *, sortables: Iterable[str] | None = None) -> SortBy:
        """Parse a ``sortby`` query value (``+name``/``-name``/``name``, comma-separated).

        A leading ``-`` selects descending, ``+`` or no sign ascending. Fields may be
        dotted (matching flattened sortables). Raises :class:`~gazebo.params.ParamError`
        (-> 400) on an empty term, a missing field name, a duplicate field, or — when
        ``sortables`` is given — a field outside that allow-list.
        """
        allow = set(sortables) if sortables is not None else None
        sorts: list[Sort] = []
        seen: set[str] = set()
        for term in raw.split(','):
            term = term.strip()
            if not term:
                raise ParamError('sortby', f'empty sort term in {raw!r}')
            direction = Direction.ASC
            if term[0] in '+-':
                direction = Direction.DESC if term[0] == '-' else Direction.ASC
                term = term[1:].strip()
            if not term:
                raise ParamError('sortby', f'missing field name in {raw!r}')
            if term in seen:
                raise ParamError('sortby', f'duplicate sort field {term!r}')
            if allow is not None and term not in allow:
                raise ParamError('sortby', f'{term!r} is not sortable')
            seen.add(term)
            sorts.append(Sort(field=term, direction=direction))
        return cls(sorts=sorts)

    def apply[T](self, items: Sequence[T]) -> list[T]:
        """Return ``items`` stably sorted by these terms.

        Multi-key order is achieved by sorting on the least-significant term first (Python
        sort is stable). Missing/null values sort last under ascending order (hence first
        under descending). Field access is dotted, consistent with the queryables.
        """
        out = list(items)
        for sort in reversed(self.sorts):

            def key(item: T, field: str = sort.field) -> Any:
                value = _dotted_get(item, field)
                return _LAST if value is None else value

            out.sort(key=key, reverse=sort.direction is Direction.DESC)
        return out


class _SchemaResource(OmitNullModel):
    """Shared shape for the queryables/sortables JSON-Schema resources."""

    model_config = ConfigDict(populate_by_name=True)

    schema_dialect: str = Field(default=JSON_SCHEMA_DIALECT, serialization_alias='$schema')
    id: str | None = Field(default=None, serialization_alias='$id')
    type: Literal['object'] = 'object'
    title: str = ''
    description: str = ''
    properties: dict[str, dict[str, Any]] = Field(default_factory=dict)
    additional_properties: bool = Field(default=False, serialization_alias='additionalProperties')
    links: list[Link] = Field(default_factory=list)

    @property
    def names(self) -> set[str]:
        """The set of declared property names — the filter/sort allow-list."""
        return set(self.properties)


class Queryables(_SchemaResource):
    """The OGC queryables resource (``GET /collections/{id}/queryables``).

    A JSON Schema whose ``properties`` are the fields a CQL2 ``filter`` may reference;
    :attr:`names` is the allow-list :func:`~gazebo.filtering.queryables.validate_properties`
    checks against. Build one from a model with
    :func:`~gazebo.filtering.queryables.queryables_from_model`.
    """


class Sortables(_SchemaResource):
    """The sortables resource (``GET /collections/{id}/sortables``).

    A JSON Schema whose ``properties`` are the fields ``sortby`` may name. Build one with
    :func:`~gazebo.filtering.queryables.sortables_from_model`.
    """


__all__ = [
    'CONF_CQL2_JSON',
    'CONF_CQL2_TEXT',
    'CONF_FEATURES_FILTER',
    'CONF_FILTER',
    'CONF_QUERYABLES',
    'CONF_SORTBY',
    'JSON_SCHEMA_DIALECT',
    'REL_QUERYABLES',
    'REL_SORTABLES',
    'Direction',
    'Queryables',
    'Sort',
    'SortBy',
    'Sortables',
    'filter_conformance_classes',
]
