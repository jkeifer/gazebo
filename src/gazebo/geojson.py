"""GeoJSON models (RFC 7946) with gazebo hypermedia, for OGC API Features.

Optional extra: importing this module requires ``geojson-pydantic`` (the
``gazebo[geojson]`` extra). It reuses geojson-pydantic for the coordinate-validated
geometry and feature shapes — the tedious, easy-to-get-wrong part — and layers
gazebo's deferred links on top:

- :class:`Feature` subclasses geojson-pydantic's ``Feature`` to add a ``links`` array.
- :class:`FeatureCollection` is a :class:`~gazebo.collection.LinkedCollection`
  (so it carries ``links`` + ``numberReturned``/``numberMatched``) rather than
  geojson-pydantic's plain collection, which has none of that. Items serialize
  under ``features`` and an optional top-level ``bbox`` is supported (RFC 7946 §5).

The geometry types are re-exported for convenience.
"""

from __future__ import annotations

from typing import Literal

from geojson_pydantic import Feature as _Feature
from geojson_pydantic.geometries import (
    Geometry,
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from geojson_pydantic.types import Position2D, Position3D
from pydantic import BaseModel, Field

from gazebo.collection import LinkedCollection
from gazebo.link import Link

__all__ = [
    'Feature',
    'FeatureCollection',
    'Geometry',
    'GeometryCollection',
    'LineString',
    'MultiLineString',
    'MultiPoint',
    'MultiPolygon',
    'Point',
    'Polygon',
    'Position2D',
    'Position3D',
]


class Feature[P: BaseModel](_Feature[Geometry, P]):
    """A GeoJSON ``Feature`` with OGC-style hypermedia links.

    Generic over the ``properties`` model ``P``. Inherits geojson-pydantic's
    coordinate validation for ``geometry`` and adds gazebo's deferred ``links``,
    resolved at serialization like every other gazebo link.
    """

    type: Literal['Feature'] = 'Feature'
    links: list[Link] = Field(default_factory=list)


class FeatureCollection[P: BaseModel](LinkedCollection[Feature[P]], items_alias='features'):
    """A GeoJSON ``FeatureCollection`` that is also a gazebo ``LinkedCollection``.

    Items serialize under ``features``; the envelope additionally carries
    ``links``, ``numberReturned``/``numberMatched`` (from ``LinkedCollection``),
    and an optional top-level ``bbox``.
    """

    type: Literal['FeatureCollection'] = 'FeatureCollection'
    bbox: list[float] | None = None
