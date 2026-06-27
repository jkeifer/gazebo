from __future__ import annotations

import json

from gazebo.collection import LinkedCollection
from gazebo.context import use_context
from gazebo.link import Link


class FeatureCollection(LinkedCollection[dict], items_alias='features'):
    pass


def test_items_alias_applied():
    fc = FeatureCollection(items=[{'id': 1}, {'id': 2}])
    data = json.loads(fc.model_dump_json(by_alias=True))
    assert 'features' in data
    assert 'items' not in data
    assert data['features'] == [{'id': 1}, {'id': 2}]


def test_number_returned_computed():
    fc = FeatureCollection(items=[{'id': 1}, {'id': 2}, {'id': 3}])
    data = json.loads(fc.model_dump_json(by_alias=True))
    assert data['numberReturned'] == 3


def test_number_matched_omitted_when_none():
    fc = FeatureCollection(items=[])
    data = json.loads(fc.model_dump_json(by_alias=True))
    assert 'numberMatched' not in data


def test_number_matched_included_when_set():
    fc = FeatureCollection(items=[{'id': 1}], number_matched=99)
    data = json.loads(fc.model_dump_json(by_alias=True))
    assert data['numberMatched'] == 99


def test_links_resolve(ctx):
    fc = FeatureCollection(items=[{'id': 1}], links=[Link.self_link()])
    with use_context(ctx):
        data = json.loads(fc.model_dump_json(by_alias=True))
    assert data['links'][0]['href'] == ctx.url


def test_default_items_field_name():
    coll = LinkedCollection[int](items=[1, 2])
    data = json.loads(coll.model_dump_json())
    assert data['items'] == [1, 2]
