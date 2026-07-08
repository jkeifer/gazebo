"""Response/request models: a plant, the plant collection, and a create body.

Also the GeoJSON models for the geospatial *beds* collection: ``Bed`` is a
:class:`~gazebo.geojson.Feature` over :class:`BedProperties`, and ``BedCollection``
the matching :class:`~gazebo.geojson.FeatureCollection`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from gazebo.collection import LinkedCollection
from gazebo.geojson import Feature, FeatureCollection, Point, Position2D
from gazebo.link import Link
from gazebo.negotiation import FormatEnum
from gazebo.params import CRS84, BBoxQuery, CrsEnum, DatetimeQuery
from gazebo.rels import MediaType, Rel


class Plant(BaseModel):
    id: str
    name: str
    links: list[Link] = Field(default_factory=list)


class PlantCollection(LinkedCollection[Plant], items_alias='plants'):
    """Items serialize under ``plants``; adds ``numberReturned``/``numberMatched``."""


class PlantCreate(BaseModel):
    name: str


class PlantSearch(BaseModel):
    """The POST-search body: a name filter plus offset/limit paging.

    Because the server is stateless, the ``next`` link must repeat the whole search
    body (criteria + the advanced offset) — see ``search_plants``.
    """

    name: str | None = None
    limit: int = Field(10, ge=1, le=10_000)
    offset: int = Field(0, ge=0)


class BedCrs(CrsEnum):
    """The closed CRS set the beds search endpoint advertises.

    A :class:`~gazebo.params.CrsEnum` subclass — a *real* class, so it drops onto
    :class:`BedQuery` as an ordinary field type (no ``type: ignore``). Members are CRS
    URIs, validated natively; an unsupported ``crs`` is a `400` problem.
    """

    CRS84 = CRS84
    WEB_MERCATOR = 'http://www.opengis.net/def/crs/EPSG/0/3857'


class BedFormat(FormatEnum):
    """The closed ``?f=`` output-format set the beds search endpoint advertises.

    A :class:`~gazebo.negotiation.FormatEnum` subclass folded into :class:`BedQuery` as a
    real field type. It sees only ``?f=`` (no ``Accept`` header at model-validation time);
    an unsupported value is a `400` problem.
    """

    geojson = 'geojson'
    json = 'json'


class BedQuery(BaseModel):
    """A *folded* query model for the beds search endpoint.

    Composes gazebo's standard OGC query field types (`bbox`, `datetime`) and its
    consumer-subclassable closed-set enums (`crs` via :class:`BedCrs`, `f` via
    :class:`BedFormat`) alongside the app's own paging fields into one model. Used as
    ``Annotated[BedQuery, Query()]``, FastAPI explodes it into individual, self-documented
    query parameters; a malformed `bbox`/`datetime`, or an unsupported `crs`/`f`, becomes
    a `400` problem, preserving OGC semantics.
    """

    bbox: BBoxQuery = None
    datetime: DatetimeQuery = None
    crs: BedCrs = BedCrs.CRS84
    f: BedFormat = BedFormat.geojson
    limit: int = Field(10, ge=1, le=10_000)
    offset: int = Field(0, ge=0)


class BedProperties(BaseModel):
    """Non-spatial attributes of a garden bed (a GeoJSON Feature's ``properties``)."""

    name: str
    planted: datetime


class Bed(Feature[BedProperties]):
    """A garden bed as a GeoJSON Feature (a Point geometry + typed properties)."""


class BedCollection(FeatureCollection[BedProperties]):
    """The beds FeatureCollection — items serialize under ``features``."""


def to_plant(row: dict) -> Plant:
    """Build a Plant with deferred self/collection links (resolved at serialization)."""
    return Plant(
        id=row['id'],
        name=row['name'],
        links=[
            # to_route resolves the route by its name; path params supplied here.
            Link.to_route(
                'get_plant', rel=Rel.SELF, type=MediaType.JSON, path={'plant_id': row['id']}
            ),
            Link.to_route('list_plants', rel=Rel.COLLECTION, type=MediaType.JSON),
            Link.root_link(),
        ],
    )


def to_bed(row: dict) -> Bed:
    """Build a Bed Feature (Point geometry + deferred links) from a raw row."""
    return Bed(
        id=row['id'],
        geometry=Point(type='Point', coordinates=Position2D(row['lon'], row['lat'])),
        properties=BedProperties(name=row['name'], planted=row['planted']),
        links=[
            Link.to_route(
                'get_bed', rel=Rel.SELF, type=MediaType.GEOJSON, path={'bed_id': row['id']}
            ),
            Link.to_route('list_beds', rel=Rel.COLLECTION, type=MediaType.GEOJSON),
            Link.root_link(),
        ],
    )
