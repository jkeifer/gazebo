from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from gazebo.ext.fastapi import Overrides
from gazebo.testing import assert_has_link, assert_problem, drive_pagination

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
    # assert_problem (from gazebo.testing) checks the content-type *and* the shape.
    assert_problem(client.get('/plants'), status=401)


def test_list_plants(client):
    body = client.get('/plants?limit=2', headers=AUTH).json()
    assert body['numberReturned'] == 2
    assert body['numberMatched'] == 3
    assert_has_link(body, 'next')
    assert_has_link(body['plants'][0], 'self')


def test_pagination_follows_next(client):
    # drive_pagination follows `next` to exhaustion, checking envelope invariants
    # on every page (numberReturned == len(items), each page <= limit) and guarding
    # against a runaway/looping `next` link.
    plants = drive_pagination(
        client, '/plants?limit=2', items_key='plants', limit=2, request_kwargs={'headers': AUTH}
    )
    assert len(plants) == 3


def test_get_plant_self_link_resolves_path_param(client):
    body = client.get('/plants/1', headers=AUTH).json()
    self_link = next(link for link in body['links'] if link['rel'] == 'self')
    # The path param is bound into the deferred href, not leaked as a link field.
    assert self_link['href'].endswith('/plants/1')
    assert 'path' not in self_link


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


def test_cors_enabled(client):
    # the garden app enables permissive CORS so a browser can call it cross-origin.
    r = client.get('/plants', headers={**AUTH, 'origin': 'http://browser.test'})
    assert r.headers['access-control-allow-origin'] == '*'


# --- OGC Features: the geospatial beds collection --------------------------


def test_collections_envelope(client):
    body = client.get('/collections').json()
    assert [c['id'] for c in body['collections']] == ['beds']


def test_collection_metadata_has_extent(client):
    body = client.get('/collections/beds').json()
    assert body['itemType'] == 'feature'
    assert body['extent']['spatial']['bbox']  # spatial extent present
    assert body['extent']['temporal']['interval']  # temporal extent present


def test_empty_store_collection_omits_extent(client):
    # an empty store has no extent to compute: the endpoints must still serve 200
    # with the extent omitted, not 500 on min() of an empty sequence
    from garden import resources

    resources._BEDS.clear()
    listing = client.get('/collections')
    assert listing.status_code == 200
    beds = client.get('/collections/beds')
    assert beds.status_code == 200
    assert 'extent' not in beds.json()


def test_beds_items_is_feature_collection(client):
    body = client.get('/collections/beds/items').json()
    assert body['type'] == 'FeatureCollection'
    assert body['numberReturned'] == 3
    assert body['features'][0]['geometry']['type'] == 'Point'
    # deferred GeoJSON media-type self link resolves
    self_link = next(link for link in body['features'][0]['links'] if link['rel'] == 'self')
    assert self_link['href'].endswith('/collections/beds/items/roses')


def test_beds_bbox_filter(client):
    # a box over western Europe keeps only the Herb Spiral (lon 2.35, lat 48.85)
    body = client.get('/collections/beds/items?bbox=-10,40,20,55').json()
    assert [f['id'] for f in body['features']] == ['herbs']


def test_beds_datetime_filter(client):
    body = client.get('/collections/beds/items?datetime=2021-01-01T00:00:00Z/..').json()
    assert sorted(f['id'] for f in body['features']) == ['herbs', 'roses']


def test_beds_date_only_datetime_is_handled(client):
    # a valid date-only value (no time/offset) must not 500 against tz-aware data
    r = client.get('/collections/beds/items?datetime=2021-01-01/..')
    assert r.status_code == 200
    assert sorted(f['id'] for f in r.json()['features']) == ['herbs', 'roses']


def test_beds_bad_bbox_is_400_problem(client):
    r = client.get('/collections/beds/items?bbox=1,2,3')
    assert r.status_code == 400
    assert r.headers['content-type'] == 'application/problem+json'
    assert r.json()['parameter'] == 'bbox'


def test_beds_disallowed_crs_is_400_problem(client):
    r = client.get('/collections/beds/items?crs=http://example.com/crs/nope')
    assert r.status_code == 400
    assert r.json()['parameter'] == 'crs'


def test_missing_bed_is_404_problem(client):
    r = client.get('/collections/beds/items/nope')
    assert r.status_code == 404
    assert r.json()['detail'].startswith('bed')


def test_override_seam():
    overrides = Overrides().set(Settings, Settings(replica_dsn='memory://test'))
    with TestClient(create_app(overrides=overrides)) as c:
        assert c.get('/plants', headers=AUTH).status_code == 200
