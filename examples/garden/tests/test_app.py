from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from gazebo.ext.fastapi import Overrides

from garden.app import create_app
from garden.resources import Settings, reset_store

AUTH = {'authorization': 'Bearer alice'}


@pytest.fixture(autouse=True)
def _reset_store():
    reset_store()


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def test_landing(client):
    body = client.get('/').json()
    rels = {link['rel'] for link in body['links']}
    assert {'self', 'root', 'conformance', 'items', 'data'} <= rels
    assert body['title'] == 'Gazebo Gardens'


def test_conformance(client):
    body = client.get('/conformance').json()
    assert 'http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/core' in body['conformsTo']


def test_auth_required_returns_problem(client):
    r = client.get('/plants')
    assert r.status_code == 401
    assert r.headers['content-type'] == 'application/problem+json'


def test_list_plants(client):
    body = client.get('/plants?limit=2', headers=AUTH).json()
    assert body['numberReturned'] == 2
    assert body['numberMatched'] == 3
    assert 'next' in {link['rel'] for link in body['links']}
    assert any(link['rel'] == 'self' for link in body['plants'][0]['links'])


def test_pagination_follows_next(client):
    page1 = client.get('/plants?limit=2', headers=AUTH).json()
    next_href = next(link['href'] for link in page1['links'] if link['rel'] == 'next')
    page2 = client.get(next_href, headers=AUTH).json()
    assert page2['numberReturned'] == 1


def test_get_missing_plant_is_404_problem(client):
    r = client.get('/plants/999', headers=AUTH)
    assert r.status_code == 404
    assert r.json()['detail'].startswith('plant')


def test_bad_body_is_422_problem(client):
    # missing required `name` -> FastAPI request validation fails -> problem+json,
    # not FastAPI's default error shape.
    r = client.post('/plants', json={}, headers=AUTH)
    assert r.status_code == 422
    assert r.headers['content-type'] == 'application/problem+json'
    body = r.json()
    assert body['status'] == 422
    assert body['errors']


def test_create_plant(client):
    created = client.post('/plants', json={'name': 'Cactus'}, headers=AUTH)
    assert created.status_code == 201
    assert created.json()['name'] == 'Cactus'
    names = [p['name'] for p in client.get('/plants?limit=10', headers=AUTH).json()['plants']]
    assert 'Cactus' in names


def test_tenant_isolation(client):
    body = client.get('/plants', headers={**AUTH, 'x-tenant': 'acme'}).json()
    assert body['numberMatched'] == 1
    assert body['plants'][0]['name'] == 'Bonsai'


def test_proxy_headers_make_links_https(client):
    body = client.get(
        '/plants?limit=1',
        headers={
            **AUTH,
            'x-forwarded-proto': 'https',
            'x-forwarded-host': 'garden.example.com',
        },
    ).json()
    self_href = next(link['href'] for link in body['links'] if link['rel'] == 'self')
    assert self_href.startswith('https://garden.example.com/')


def test_health(client):
    assert client.get('/health').json()['status'] == 'healthy'


def test_override_seam():
    overrides = Overrides().set(Settings, Settings(replica_dsn='memory://test'))
    with TestClient(create_app(overrides=overrides)) as c:
        assert c.get('/plants', headers=AUTH).status_code == 200
