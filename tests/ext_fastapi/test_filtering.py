"""CQL2 filtering and sortby adapters: matching, sorting, and the 400 problem paths."""

from __future__ import annotations

from typing import Annotated, Literal

import pytest

from fastapi.testclient import TestClient
from pydantic import BaseModel

from gazebo.ext.fastapi import FilterParam, GazeboApp, Providers, SortByParam
from gazebo.filtering import Filter, SortBy, queryables_from_model, sortables_from_model
from gazebo.filtering.cql2 import Cql2Engine
from gazebo.params import CRS84


class PlantProps(BaseModel):
    name: str
    sun: Literal['full', 'part', 'shade']
    depth: int


PLANT_QUERYABLES = queryables_from_model(PlantProps, id='plants')
PLANT_SORTABLES = sortables_from_model(PlantProps)
_EXPLICIT_FILTER = FilterParam(PLANT_QUERYABLES, engine=Cql2Engine())

_PLANTS = [
    {'name': 'rose', 'sun': 'full', 'depth': 10},
    {'name': 'fern', 'sun': 'shade', 'depth': 4},
    {'name': 'sage', 'sun': 'full', 'depth': 8},
]


def _filtering_app() -> GazeboApp:
    app = GazeboApp(Providers())

    @app.get('/plants')
    async def plants(
        filter: Annotated[Filter | None, FilterParam(PLANT_QUERYABLES)] = None,
        sortby: Annotated[SortBy | None, SortByParam(PLANT_SORTABLES)] = None,
    ) -> dict:
        rows = [p for p in _PLANTS if filter is None or filter.matches(p)]
        if sortby is not None:
            rows = sortby.apply(rows)
        return {'numberReturned': len(rows), 'names': [p['name'] for p in rows]}

    @app.get('/plants/queryables')
    async def queryables() -> dict:
        return PLANT_QUERYABLES.model_dump(mode='json', by_alias=True)

    return app


@pytest.fixture
def filtering_client():
    with TestClient(_filtering_app()) as c:
        yield c


def test_filter_absent_returns_all(filtering_client):
    assert filtering_client.get('/plants').json()['numberReturned'] == 3


def test_filter_text(filtering_client):
    body = filtering_client.get('/plants', params={'filter': "sun = 'full'"}).json()
    assert sorted(body['names']) == ['rose', 'sage']


def test_filter_json(filtering_client):
    expr = '{"op": ">", "args": [{"property": "depth"}, 5]}'
    body = filtering_client.get('/plants', params={'filter': expr}).json()
    assert sorted(body['names']) == ['rose', 'sage']


def test_sortby_applies(filtering_client):
    body = filtering_client.get('/plants', params={'sortby': '-depth'}).json()
    assert body['names'] == ['rose', 'sage', 'fern']


def test_filter_bad_syntax_is_400_problem(filtering_client):
    r = filtering_client.get('/plants', params={'filter': '?? nope ??'})
    assert r.status_code == 400
    assert r.headers['content-type'] == 'application/problem+json'
    assert r.json()['parameter'] == 'filter'


def test_filter_lenient_noop_is_400_problem(filtering_client):
    # 'depth =' parses leniently to a bare property; validate() must turn it into a 400
    r = filtering_client.get('/plants', params={'filter': 'depth ='})
    assert r.status_code == 400
    assert r.json()['parameter'] == 'filter'


def test_filter_unknown_property_is_400_problem(filtering_client):
    r = filtering_client.get('/plants', params={'filter': "color = 'red'"})
    assert r.status_code == 400
    assert 'color' in r.json()['detail']


def test_unknown_filter_lang_is_400_problem(filtering_client):
    r = filtering_client.get('/plants', params={'filter': 'depth > 1', 'filter-lang': 'sql'})
    assert r.status_code == 400
    assert r.json()['parameter'] == 'filter-lang'


def test_non_sortable_field_is_400_problem(filtering_client):
    r = filtering_client.get('/plants', params={'sortby': 'color'})
    assert r.status_code == 400
    assert r.json()['parameter'] == 'sortby'


def test_filter_crs_default_is_accepted(filtering_client):
    # the OGC default filter-crs (CRS84) is allowed; the filter still applies
    r = filtering_client.get('/plants', params={'filter': "sun = 'full'", 'filter-crs': CRS84})
    assert r.status_code == 200
    assert sorted(r.json()['names']) == ['rose', 'sage']


def test_unsupported_filter_crs_is_400_problem(filtering_client):
    r = filtering_client.get(
        '/plants',
        params={'filter': 'depth > 1', 'filter-crs': 'http://example.com/crs/nope'},
    )
    assert r.status_code == 400
    assert r.json()['parameter'] == 'filter-crs'


def test_queryables_endpoint_serializes(filtering_client):
    body = filtering_client.get('/plants/queryables').json()
    assert body['$schema'].startswith('https://json-schema.org/')
    assert set(body['properties']) == {'name', 'sun', 'depth'}


def test_filter_param_explicit_engine_used():
    # the engine marker must reference module-level names so get_type_hints can resolve the
    # Annotated metadata (the same closure-alias gotcha the param adapters document)
    app = GazeboApp(Providers())

    @app.get('/p')
    async def p(
        filter: Annotated[Filter | None, _EXPLICIT_FILTER] = None,
    ) -> dict:
        return {'has_filter': filter is not None}

    with TestClient(app) as client:
        assert client.get('/p', params={'filter': 'depth > 1'}).json()['has_filter'] is True
