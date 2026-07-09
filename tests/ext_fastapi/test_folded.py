"""Folded query models: the composable field types explode into documented params."""

from __future__ import annotations

from typing import Annotated

import pytest

from fastapi import Query
from fastapi.testclient import TestClient
from pydantic import BaseModel

from gazebo.ext.fastapi import (
    BBoxQuery,
    CrsEnum,
    DatetimeQuery,
    FormatEnum,
    GazeboApp,
    Providers,
)
from gazebo.params import CRS84

from .support import openapi_params, resolve_ref_schema


class _FoldedCrs(CrsEnum):
    CRS84 = CRS84


class _FoldedFormat(FormatEnum):
    json = 'json', 'application/json'
    html = 'html', 'text/html'


class _FoldedQuery(BaseModel):
    bbox: BBoxQuery = None
    datetime: DatetimeQuery = None
    # Real classes (CrsEnum / FormatEnum subclasses): usable field types, NO type: ignore.
    crs: _FoldedCrs = _FoldedCrs.CRS84
    f: _FoldedFormat = _FoldedFormat.json


def _folded_app() -> GazeboApp:
    app = GazeboApp(Providers())

    @app.get('/items')
    async def items(query: Annotated[_FoldedQuery, Query()]) -> dict:
        return {
            'bbox': None if query.bbox is None else [query.bbox.minx, query.bbox.maxx],
            'has_datetime': query.datetime is not None,
            'crs': query.crs,
            'f': query.f.value,
        }

    return app


@pytest.fixture
def folded_client():
    with TestClient(_folded_app()) as c:
        yield c


def test_folded_model_explodes_into_documented_params(folded_client):
    spec = folded_client.get('/openapi.json').json()
    params = openapi_params(spec, '/items')
    # exploded into individual query params, not a single collapsed object
    assert {'bbox', 'datetime', 'crs', 'f'} <= set(params)
    assert 'A bounding box' in params['bbox']['description']
    assert params['bbox']['schema'].get('examples') or params['bbox'].get('examples')
    # crs/f are closed-set enums: FastAPI $refs the reusable component schema, which
    # carries both the enum members and the base's injected description.
    crs_schema = resolve_ref_schema(spec, params['crs']['schema'])
    assert crs_schema['enum'] == [CRS84]
    assert 'coordinate reference system' in crs_schema['description']
    f_schema = resolve_ref_schema(spec, params['f']['schema'])
    assert f_schema['enum'] == ['json', 'html']
    assert 'output format' in f_schema['description']


def test_folded_good_values_parse(folded_client):
    body = folded_client.get(
        '/items?bbox=-1,-2,3,4&datetime=2020-01-01T00:00:00Z&f=html',
    ).json()
    assert body['bbox'] == [-1, 3]
    assert body['has_datetime'] is True
    assert body['crs'] == CRS84  # absent crs falls back to the field default
    assert body['f'] == 'html'


def test_folded_bad_value_is_400_problem(folded_client):
    r = folded_client.get('/items?bbox=1,2,3')  # wrong coordinate count
    assert r.status_code == 400  # a malformed query param is an OGC client error
    assert r.headers['content-type'] == 'application/problem+json'
    body = r.json()
    assert body['status'] == 400
    assert body['parameter'] == 'bbox'
    assert any(err['loc'][-1] == 'bbox' for err in body['errors'])


def test_folded_bad_f_is_400_problem(folded_client):
    r = folded_client.get('/items?f=xml')
    assert r.status_code == 400
    assert r.json()['parameter'] == 'f'


def test_folded_multiple_bad_params_lists_parameters(folded_client):
    r = folded_client.get('/items?bbox=1,2,3&f=xml')
    assert r.status_code == 400
    body = r.json()
    # more than one offending query param -> a `parameters` list rather than a scalar
    assert set(body['parameters']) == {'bbox', 'f'}
    assert 'parameter' not in body
