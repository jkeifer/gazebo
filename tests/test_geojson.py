from __future__ import annotations

import json

import pytest

from pydantic import BaseModel, ValidationError

from gazebo.context import use_context
from gazebo.geojson import Feature, FeatureCollection, Point, Position2D
from gazebo.link import Link


class PlantProps(BaseModel):
    name: str


def _feature(fid: str = '1') -> Feature[PlantProps]:
    return Feature[PlantProps](
        geometry=Point(type='Point', coordinates=Position2D(1.0, 2.0)),
        properties=PlantProps(name='rose'),
        id=fid,
        links=[Link.self_link(href='https://api.example.com/features/' + fid)],
    )


def test_feature_carries_links_and_geometry():
    data = json.loads(_feature().model_dump_json())
    assert data['type'] == 'Feature'
    assert data['geometry']['type'] == 'Point'
    assert data['properties']['name'] == 'rose'
    assert data['links'][0]['rel'] == 'self'


def test_feature_rejects_bad_coordinates():
    with pytest.raises(ValidationError):
        Feature[PlantProps](
            geometry=Point(type='Point', coordinates=('not', 'numbers')),  # type: ignore[arg-type]
            properties=PlantProps(name='x'),
        )


def test_featurecollection_serializes_as_geojson():
    fc = FeatureCollection[PlantProps](items=[_feature('1'), _feature('2')], bbox=[1, 2, 1, 2])
    data = json.loads(fc.model_dump_json(by_alias=True))
    # items serialize under the GeoJSON `features` key (survives generic parametrization)
    assert [f['id'] for f in data['features']] == ['1', '2']
    assert data['type'] == 'FeatureCollection'
    assert data['bbox'] == [1, 2, 1, 2]
    assert data['numberReturned'] == 2
    assert 'items' not in data


def test_featurecollection_deferred_links_resolve(ctx):
    fc = FeatureCollection[PlantProps](
        items=[_feature()],
        links=[Link.self_link()],
    )
    with use_context(ctx):
        data = json.loads(fc.model_dump_json(by_alias=True))
    self_link = next(link for link in data['links'] if link['rel'] == 'self')
    assert self_link['href'] == ctx.url
