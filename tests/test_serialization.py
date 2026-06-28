"""Tests for the shared serialization helpers in ``gazebo.serialization``."""

from __future__ import annotations

import json

from typing import Annotated

from pydantic import PlainSerializer

from gazebo.serialization import OmitNullModel, drop_none


def test_drop_none_keeps_falsy_non_none():
    assert drop_none({'a': 0, 'b': '', 'c': None, 'd': False}) == {'a': 0, 'b': '', 'd': False}


def test_omit_null_model_omits_unset_members():
    class M(OmitNullModel):
        name: str
        note: str | None = None

    assert json.loads(M(name='x').model_dump_json()) == {'name': 'x'}
    assert json.loads(M(name='x', note='hi').model_dump_json()) == {'name': 'x', 'note': 'hi'}


def test_omit_null_model_serialization_schema_is_not_opaque():
    # the @model_serializer must not collapse the schema to an opaque object
    class M(OmitNullModel):
        name: str
        note: str | None = None

    schema = M.model_json_schema(mode='serialization')
    assert set(schema['properties']) == {'name', 'note'}


def test_field_level_serializer_is_preserved_in_schema():
    # regression: strip_model_serializers must drop only the model serializer, not a
    # field's PlainSerializer — so the documented type matches the serialized body
    class M(OmitNullModel):
        n: Annotated[int, PlainSerializer(lambda v: str(v), return_type=str)]

    schema = M.model_json_schema(mode='serialization')
    assert schema['properties']['n']['type'] == 'string'
    assert json.loads(M(n=5).model_dump_json()) == {'n': '5'}
