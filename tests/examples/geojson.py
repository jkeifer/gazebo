"""Runnable examples backing ``docs/core/geojson.md``."""

from __future__ import annotations

import json

from collections.abc import Mapping


class _Ctx:
    base_url = 'https://api.example.com/'
    url = 'https://api.example.com/features'
    query_params: Mapping[str, str] = {}

    def url_for(self, name: str, /, **path: object) -> str:
        return f'https://api.example.com/{name}'


# --8<-- [start:feature]
from pydantic import BaseModel

from gazebo.geojson import Feature, FeatureCollection, Point, Position2D
from gazebo.link import Link
from gazebo.rels import MediaType, Rel


class BedProperties(BaseModel):
    name: str


# `Feature` is generic over its `properties` model; geometry is coordinate-validated
# by geojson-pydantic, and gazebo adds the deferred `links`.
rose_bed = Feature[BedProperties](
    id='roses',
    geometry=Point(type='Point', coordinates=Position2D(-122.6, 45.5)),
    properties=BedProperties(name='Rose Bed'),
    links=[Link.self_link(type=MediaType.GEOJSON)],
)

# `FeatureCollection` is a LinkedCollection: items serialize under `features`, and
# it carries `links` + `numberReturned` (and an optional top-level `bbox`).
beds = FeatureCollection[BedProperties](
    items=[rose_bed],
    links=[Link.root_link(rel=Rel.ROOT)],
)
# --8<-- [end:feature]


dumped = json.loads(beds.model_dump_json(by_alias=True, context={'request': _Ctx()}))
assert dumped['type'] == 'FeatureCollection'
assert dumped['features'][0]['geometry']['coordinates'] == [-122.6, 45.5]
assert dumped['numberReturned'] == 1
assert 'items' not in dumped
