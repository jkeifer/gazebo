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
from gazebo.rels import MediaType, Rel


class Plant(BaseModel):
    id: str
    name: str
    links: list[Link] = Field(default_factory=list)


class PlantCollection(LinkedCollection[Plant], items_alias='plants'):
    """Items serialize under ``plants``; adds ``numberReturned``/``numberMatched``."""


class PlantCreate(BaseModel):
    name: str


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
