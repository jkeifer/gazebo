"""Derive OGC queryables/sortables from a pydantic model.

Core layer: pydantic + stdlib only. Because a queryables resource *is* a JSON Schema and
pydantic already emits JSON Schema, the endpoint body **and** the filter allow-list both
fall out of the model a service already wrote. Nested models flatten to dotted accessors
(``site.coord.lat``) — load-bearing for filtering nested data — geometry fields are
advertised as spatial queryables, and the resulting property-name set validates that a
filter only references filterable fields.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from gazebo.filtering.engine import Filter, FilterError
from gazebo.filtering.models import Queryables, Sortables

GEOJSON_GEOMETRY_SCHEMA = 'https://geojson.org/schema/Geometry.json'
"""The schema a geometry queryable references (the field is filterable by spatial ops)."""

_GEOMETRY_TYPES = frozenset(
    {
        'Point',
        'MultiPoint',
        'LineString',
        'MultiLineString',
        'Polygon',
        'MultiPolygon',
        'GeometryCollection',
    },
)

# JSON-Schema keywords worth forwarding onto a queryable (a conservative, advisory subset;
# the authoritative artifact is the property-name set, not these).
_KEEP = frozenset(
    {
        'type',
        'format',
        'enum',
        'const',
        'title',
        'description',
        'minimum',
        'maximum',
        'exclusiveMinimum',
        'exclusiveMaximum',
        'minLength',
        'maxLength',
        'pattern',
    },
)


def _unwrap_nullable(prop: dict[str, Any]) -> dict[str, Any]:
    """Collapse ``Optional[X]`` (``anyOf: [<X>, {type: null}]``) to ``<X>``."""
    options = prop.get('anyOf')
    if not isinstance(options, list):
        return prop
    non_null = [o for o in options if isinstance(o, dict) and o.get('type') != 'null']
    if len(non_null) != 1:
        return prop
    merged = dict(non_null[0])
    for key in ('title', 'description'):  # pydantic hangs these on the wrapper
        if key in prop and key not in merged:
            merged[key] = prop[key]
    return merged


def _resolve_ref(prop: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any] | None:
    ref = prop.get('$ref')
    if isinstance(ref, str) and ref.startswith('#/$defs/'):
        return defs.get(ref.rsplit('/', 1)[-1], {})
    return None


def _is_geometry_def(target: dict[str, Any]) -> bool:
    """Whether a ``$defs`` entry is a GeoJSON geometry (vs a coincidentally-named model)."""
    if target.get('title') not in _GEOMETRY_TYPES:
        return False
    props = target.get('properties', {})
    # all GeoJSON geometries carry `coordinates`, except GeometryCollection (`geometries`)
    return isinstance(props, dict) and ('coordinates' in props or 'geometries' in props)


def _is_geometry(prop: dict[str, Any], defs: dict[str, Any]) -> bool:
    """Detect a geojson-pydantic geometry field — a concrete type *or* a union of them."""
    target = _resolve_ref(prop, defs)  # a concrete single geometry (e.g. `loc: Point`)
    if target is not None and _is_geometry_def(target):
        return True
    disc = prop.get('discriminator')  # the discriminated `Geometry` union
    if isinstance(disc, dict) and disc.get('propertyName') == 'type':
        mapping = disc.get('mapping')
        if isinstance(mapping, dict) and set(mapping).issubset(_GEOMETRY_TYPES):
            return True
    branches = prop.get('oneOf') or prop.get('anyOf')  # a bare union with no discriminator
    if isinstance(branches, list) and branches:
        targets = [_resolve_ref(b, defs) for b in branches if isinstance(b, dict)]
        return bool(targets) and all(t is not None and _is_geometry_def(t) for t in targets)
    return False


def _scalar(prop: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in prop.items() if k in _KEEP}
    items = prop.get('items')
    if out.get('type') == 'array' and isinstance(items, dict):
        out['items'] = _scalar(_unwrap_nullable(items))
    return out


def _flatten(
    prop: dict[str, Any],
    defs: dict[str, Any],
    prefix: str,
    out: dict[str, dict[str, Any]],
    depth: int,
    max_depth: int,
    *,
    scalars_only: bool,
) -> None:
    prop = _unwrap_nullable(prop)

    if _is_geometry(prop, defs):
        if not scalars_only:  # geometry is filterable (spatial ops) but not sortable
            out[prefix] = {'$ref': GEOJSON_GEOMETRY_SCHEMA}
        return

    ref = prop.get('$ref')
    if isinstance(ref, str) and ref.startswith('#/$defs/'):
        prop = defs.get(ref.rsplit('/', 1)[-1], {})

    if prop.get('type') == 'object' and isinstance(prop.get('properties'), dict):
        if depth >= max_depth:  # guard pathological / recursive models
            return
        for child, child_prop in prop['properties'].items():
            _flatten(
                child_prop,
                defs,
                f'{prefix}.{child}',
                out,
                depth + 1,
                max_depth,
                scalars_only=scalars_only,
            )
        return

    if scalars_only and prop.get('type') == 'array':  # can't sort by an array
        return
    out[prefix] = _scalar(prop)


def _build(
    model: type[BaseModel],
    *,
    title: str | None,
    max_depth: int,
    scalars_only: bool,
) -> tuple[dict[str, dict[str, Any]], str]:
    schema = model.model_json_schema(by_alias=True)
    defs = schema.get('$defs', {})
    out: dict[str, dict[str, Any]] = {}
    for name, prop in schema.get('properties', {}).items():
        _flatten(prop, defs, name, out, 1, max_depth, scalars_only=scalars_only)
    return out, (title if title is not None else schema.get('title', ''))


def queryables_from_model(
    model: type[BaseModel],
    *,
    id: str | None = None,
    title: str | None = None,
    additional: bool = False,
    max_depth: int = 4,
) -> Queryables:
    """Build a :class:`~gazebo.filtering.models.Queryables` from a pydantic model.

    Scalars (and their constraints/enums/formats) are advertised as-is; nested models are
    flattened to dotted accessors; geometry fields become spatial queryables; arrays
    advertise their item type. ``additional`` sets ``additionalProperties`` — keep it
    ``False`` for an honest closed allow-list. ``max_depth`` guards recursive models.
    """
    properties, resolved_title = _build(
        model,
        title=title,
        max_depth=max_depth,
        scalars_only=False,
    )
    return Queryables(
        id=id,
        title=resolved_title,
        properties=properties,
        additional_properties=additional,
    )


def sortables_from_model(
    model: type[BaseModel],
    *,
    id: str | None = None,
    title: str | None = None,
    max_depth: int = 4,
) -> Sortables:
    """Build a :class:`~gazebo.filtering.models.Sortables` from a pydantic model.

    Like :func:`queryables_from_model` but scalar-only: geometry and array fields (which
    have no total order) are excluded, while nested scalar leaves are still flattened.
    """
    properties, resolved_title = _build(
        model,
        title=title,
        max_depth=max_depth,
        scalars_only=True,
    )
    return Sortables(id=id, title=resolved_title, properties=properties)


def validate_properties(filter: Filter, queryables: Queryables) -> None:
    """Raise :class:`FilterError` if ``filter`` references a non-queryable property.

    The check is the filter's referenced-property set minus the queryables' declared
    names; dotted nested references are compared against the flattened allow-list.
    """
    unknown = filter.properties() - queryables.names
    if unknown:
        listed = ', '.join(sorted(unknown))
        raise FilterError(f'filter references non-queryable properties: {listed}')


__all__ = [
    'GEOJSON_GEOMETRY_SCHEMA',
    'queryables_from_model',
    'sortables_from_model',
    'validate_properties',
]
