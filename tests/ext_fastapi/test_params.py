"""The OGC ``Depends`` param adapters: parsing, the 400 problem path, and OpenAPI docs."""

from __future__ import annotations

from typing import Annotated

import pytest

from fastapi.testclient import TestClient

from gazebo.ext.fastapi import (
    BBoxParam,
    CrsParam,
    DatetimeParam,
    GazeboApp,
    Negotiate,
    Providers,
)
from gazebo.negotiation import HTML, JSON, Representation
from gazebo.params import CRS84, BBox, DatetimeInterval

from .support import openapi_params, params_app


@pytest.fixture
def params_client():
    with TestClient(params_app()) as c:
        yield c


def test_param_adapters_parse(params_client):
    r = params_client.get('/search?bbox=-1,-2,3,4&datetime=2020-01-01T00:00:00Z')
    assert r.status_code == 200
    body = r.json()
    assert body['bbox'] == [-1, -2, 3, 4]
    assert body['has_datetime'] is True
    assert body['crs'] == CRS84


def test_param_adapters_absent_are_none(params_client):
    body = params_client.get('/search').json()
    assert body['bbox'] is None
    assert body['has_datetime'] is False


def test_bad_bbox_is_400_problem(params_client):
    r = params_client.get('/search?bbox=1,2,3')
    assert r.status_code == 400
    assert r.headers['content-type'] == 'application/problem+json'
    body = r.json()
    assert body['parameter'] == 'bbox'
    assert body['status'] == 400


def test_bad_datetime_is_400_problem(params_client):
    r = params_client.get('/search?datetime=not-a-date')
    assert r.status_code == 400
    assert r.json()['parameter'] == 'datetime'


def test_disallowed_crs_is_400_problem(params_client):
    r = params_client.get('/search?crs=http://example.com/crs/nope')
    assert r.status_code == 400
    assert r.json()['parameter'] == 'crs'


# module-level so get_type_hints can resolve them inside the route annotations below
EPSG3857 = 'http://www.opengis.net/def/crs/EPSG/0/3857'


def test_crs_absent_defaults_to_crs84_when_allowed():
    app = GazeboApp(Providers())

    @app.get('/q')
    async def q(crs: Annotated[str, CrsParam(allowed=[CRS84, EPSG3857])]) -> dict:
        return {'crs': crs}

    with TestClient(app) as client:
        # CRS84 is allowed, so an absent crs defaults to it (the OGC default CRS)
        assert client.get('/q').json()['crs'] == CRS84


def test_crs_required_when_no_default_and_no_crs84():
    app = GazeboApp(Providers())

    @app.get('/q2')
    async def q2(crs: Annotated[str, CrsParam(allowed=[EPSG3857])]) -> dict:
        return {'crs': crs}

    with TestClient(app) as client:
        # no default and CRS84 not allowed -> there's no safe default -> crs is required
        absent = client.get('/q2')
        assert absent.status_code == 400
        assert absent.json()['parameter'] == 'crs'
        # supplying an allowed value still works
        assert client.get('/q2', params={'crs': EPSG3857}).json()['crs'] == EPSG3857


def test_crs_explicit_default_when_no_crs84():
    app = GazeboApp(Providers())

    @app.get('/q3')
    async def q3(crs: Annotated[str, CrsParam(allowed=[EPSG3857], default=EPSG3857)]) -> dict:
        return {'crs': crs}

    with TestClient(app) as client:
        assert client.get('/q3').json()['crs'] == EPSG3857


def test_crs_default_outside_allowed_raises_at_construction():
    with pytest.raises(ValueError, match='not in allowed'):
        CrsParam(allowed=[CRS84], default='http://example.com/crs/nope')


def test_depends_adapters_are_documented_in_openapi():
    app = GazeboApp(Providers())

    @app.get('/search')
    async def search(
        bbox: Annotated[BBox | None, BBoxParam] = None,
        datetime: Annotated[DatetimeInterval | None, DatetimeParam] = None,
        crs: Annotated[str, CrsParam(allowed=[CRS84])] = CRS84,
        rep: Annotated[Representation, Negotiate([JSON, HTML])] = JSON,
    ) -> dict:
        return {}

    with TestClient(app) as client:
        params = openapi_params(client.get('/openapi.json').json(), '/search')

    assert 'A bounding box' in params['bbox']['description']
    assert params['bbox']['examples']  # openapi_examples on bbox
    assert 'RFC 3339' in params['datetime']['description']
    assert params['datetime']['examples']
    # crs and f carry their closed set as an enum
    assert params['crs']['schema']['enum'] == [CRS84]
    assert 'coordinate reference system' in params['crs']['description']
    assert params['f']['schema']['enum'] == ['json', 'html']
    assert 'output format' in params['f']['description']
