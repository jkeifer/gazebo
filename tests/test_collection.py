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


class NoCount(LinkedCollection[dict], items_alias='features', number_returned=False):
    pass


# --- python-mode dumps (independent of JSON) -------------------------------


def test_items_alias_applies_in_python_mode():
    # the alias must apply in python mode too (not just JSON), matching how a plain
    # serialization_alias behaves — otherwise model_dump(by_alias=True) leaks `items`.
    fc = FeatureCollection(items=[{'id': 1}])
    assert 'features' in fc.model_dump(by_alias=True)
    assert 'items' not in fc.model_dump(by_alias=True)
    # without by_alias the python field name is kept (so it round-trips)
    assert 'items' in fc.model_dump()


def test_number_returned_in_python_mode():
    fc = FeatureCollection(items=[{'id': 1}, {'id': 2}])
    assert fc.model_dump(by_alias=True)['numberReturned'] == 2
    assert fc.model_dump()['number_returned'] == 2


def test_number_returned_toggle_in_python_mode():
    dumped = NoCount(items=[{'id': 1}]).model_dump(by_alias=True)
    assert 'numberReturned' not in dumped
    assert 'number_returned' not in dumped
    assert 'features' in dumped


def test_number_matched_in_python_mode():
    fc = FeatureCollection(items=[{'id': 1}], number_matched=7)
    assert fc.model_dump(by_alias=True)['numberMatched'] == 7


# --- serialization JSON schema (OpenAPI) fidelity --------------------------


def test_serialization_schema_is_faithful():
    schema = FeatureCollection.model_json_schema(mode='serialization')
    props = schema['properties']
    # the alias, the computed count, and a non-opaque links array are all reflected
    assert 'features' in props
    assert 'items' not in props
    assert 'numberReturned' in props
    assert props['links']['items'] == {'$ref': '#/$defs/Link'}
    assert 'features' in schema['required']


def test_serialization_schema_omits_number_returned_when_toggled():
    schema = NoCount.model_json_schema(mode='serialization')
    props = schema['properties']
    assert 'numberReturned' not in props
    assert 'features' in props
    # the dropped member must also leave `required`, or OpenAPI advertises a field
    # the body never emits
    assert 'numberReturned' not in schema.get('required', [])
    assert 'number_returned' not in schema.get('required', [])


def test_validation_schema_keeps_python_field_names():
    # input schema is unchanged — the alias is a serialization concern only
    props = FeatureCollection.model_json_schema(mode='validation')['properties']
    assert 'items' in props
    assert 'features' not in props
