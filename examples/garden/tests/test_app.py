from __future__ import annotations

import os

import pytest

from click.testing import CliRunner
from fastapi.testclient import TestClient

from gazebo.ext.fastapi import Overrides
from gazebo.testing import assert_has_link, assert_problem, drive_pagination

from garden.app import create_app, main
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
    # RootRouter adds service-desc/service-doc (to the OpenAPI doc + docs UI) alongside
    # the hierarchical/conformance links.
    assert {'self', 'root', 'conformance', 'items', 'data', 'service-desc', 'service-doc'} <= rels
    # title/description fall back to the app's (the RootRouter sets neither).
    assert body['title'] == 'Gazebo Gardens'


def test_landing_service_desc_points_at_openapi(client):
    links = {link['rel']: link['href'] for link in client.get('/').json()['links']}
    assert links['service-desc'].endswith('/openapi.json')
    assert links['service-doc'].endswith('/docs')


def test_conformance(client):
    conforms = client.get('/conformance').json()['conformsTo']
    # The baseline is derived from the running app: core/landing-page/json, plus oas30
    # because the app exposes an OpenAPI document.
    assert 'http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/core' in conforms
    assert 'http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/oas30' in conforms


def test_problems_catalog(client):
    catalog = client.get('/problems').json()
    assert catalog['plant-not-found']['status'] == 404
    assert catalog['plant-not-found']['type'].endswith('/plant-not-found')


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


def test_plants_cursor_pagination_links(client):
    from gazebo.pagination import encode_cursor

    # a middle page (offset 1 of 3) carries the full set of navigational links
    cursor = encode_cursor({'offset': 1})
    body = client.get(f'/plants?limit=1&cursor={cursor}', headers=AUTH).json()
    rels = {link['rel'] for link in body['links']}
    assert {'self', 'first', 'prev', 'next', 'last'} <= rels
    # the next/first links carry an opaque cursor, not a raw offset
    nxt = next(link for link in body['links'] if link['rel'] == 'next')
    assert 'cursor=' in nxt['href'] and 'offset=' not in nxt['href']


def test_pagination_preserves_other_query_params(client):
    # every non-paging query param -- repeated ones included -- survives into the
    # next link, so page two runs the same query as page one
    body = client.get('/plants?limit=1&tag=a&tag=b', headers=AUTH).json()
    nxt = next(link for link in body['links'] if link['rel'] == 'next')
    assert 'tag=a' in nxt['href']
    assert 'tag=b' in nxt['href']


def test_plants_malformed_cursor_is_problem(client):
    # a bad cursor decodes to a ParamError -> 400 problem+json, not a 500
    resp = client.get('/plants?cursor=%21%21not-base64', headers=AUTH)
    assert_problem(resp, status=400)


def test_plants_cursor_with_bad_offset_is_problem(client):
    from gazebo.pagination import encode_cursor

    # a well-formed but untrusted cursor carrying a non-integer offset is a client
    # error (400), not a 500 from int()/division on garbage.
    cursor = encode_cursor({'offset': 'not-a-number'})
    assert_problem(client.get(f'/plants?cursor={cursor}', headers=AUTH), status=400)
    negative = encode_cursor({'offset': -5})
    assert_problem(client.get(f'/plants?cursor={negative}', headers=AUTH), status=400)


def test_plants_limit_zero_is_validation_problem(client):
    # an out-of-range limit is rejected at the boundary (422), never a divide-by-zero 500
    assert_problem(client.get('/plants?limit=0', headers=AUTH), status=422)


def test_beds_offset_pagination(client):
    beds = drive_pagination(
        client, '/collections/beds/items?limit=1', items_key='features', limit=1
    )
    assert len(beds) == 3


def test_beds_out_of_range_paging_is_validation_problem(client):
    # bad limit/offset are rejected (422) before reaching paginate_offset's ValueError
    assert_problem(client.get('/collections/beds/items?limit=0'), status=422)
    assert_problem(client.get('/collections/beds/items?offset=-1'), status=422)


def test_beds_queryables_and_sortables(client):
    q = client.get('/collections/beds/queryables').json()
    assert q['$schema'].startswith('https://json-schema.org/')
    assert set(q['properties']) == {'name', 'planted'}
    s = client.get('/collections/beds/sortables').json()
    assert set(s['properties']) == {'name', 'planted'}
    # the collection advertises both as links
    rels = {link['rel'] for link in client.get('/collections/beds').json()['links']}
    assert {'http://www.opengis.net/def/rel/ogc/1.0/queryables'} <= rels


def test_beds_cql2_text_filter(client):
    body = client.get("/collections/beds/items?filter=name = 'Rose Bed'").json()
    assert [f['properties']['name'] for f in body['features']] == ['Rose Bed']


def test_beds_cql2_temporal_filter(client):
    # planted is advertised as a date-time queryable; cql2 compares it to a TIMESTAMP
    url = "/collections/beds/items?filter=planted >= TIMESTAMP('2021-06-01T00:00:00Z')"
    names = {f['properties']['name'] for f in client.get(url).json()['features']}
    assert names == {'Herb Spiral'}  # only the 2022 bed


def test_beds_sortby(client):
    body = client.get('/collections/beds/items?sortby=-planted').json()
    names = [f['properties']['name'] for f in body['features']]
    assert names == ['Herb Spiral', 'Rose Bed', 'Orchard']  # 2022, 2021, 2020


def test_beds_bad_filter_is_400_problem(client):
    assert_problem(client.get('/collections/beds/items?filter=%3F%3F nope %3F%3F'), status=400)


def test_beds_unknown_filter_property_is_400_problem(client):
    # `color` is not a queryable -> rejected before evaluation
    assert_problem(client.get("/collections/beds/items?filter=color = 'red'"), status=400)


def test_beds_non_sortable_field_is_400_problem(client):
    assert_problem(client.get('/collections/beds/items?sortby=color'), status=400)


def test_beds_conformance_advertises_cql2(client):
    conforms = client.get('/conformance').json()['conformsTo']
    assert 'http://www.opengis.net/spec/cql2/1.0/conf/cql2-text' in conforms


def test_post_search_limit_zero_is_validation_problem(client):
    # limit=0 would otherwise emit a self-referential next link (infinite paging loop)
    resp = client.post('/plants/search', json={'limit': 0}, headers=AUTH)
    assert_problem(resp, status=422)


def test_post_search_pagination_is_stateless(client):
    # the POST-search next link carries method=POST and a body that re-states the
    # search; drive_pagination follows it by reposting that body.
    first = client.post('/plants/search', json={'limit': 1}, headers=AUTH).json()
    nxt = next(link for link in first['links'] if link['rel'] == 'next')
    assert nxt['method'] == 'POST'
    assert nxt['body']['offset'] == '1'

    plants = drive_pagination(
        client,
        '/plants/search',
        items_key='plants',
        method='POST',
        body={'limit': 1},
        limit=1,
        request_kwargs={'headers': AUTH},
    )
    assert len(plants) == 3


def test_post_search_name_filter(client):
    body = client.post('/plants/search', json={'name': 'a'}, headers=AUTH).json()
    # only plants whose name contains 'a' come back (case-insensitive)
    assert all('a' in p['name'].lower() for p in body['plants'])


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
    # The problem carries the registered type's stable URI, not the about:blank default.
    assert r.json()['type'].endswith('/plant-not-found')


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


def test_beds_collection_negotiates_html(client):
    # ?f=html selects the HTML representation; the JSON one carries an alternate link.
    html = client.get('/collections/beds?f=html')
    assert html.status_code == 200
    assert html.headers['content-type'].startswith('text/html')
    assert '<h1>Garden Beds</h1>' in html.text

    js = client.get('/collections/beds?f=json').json()
    alt = next(link for link in js['links'] if link['rel'] == 'alternate')
    assert alt['type'] == 'text/html'
    assert 'f=html' in alt['href']


def test_beds_collection_accept_header_html(client):
    html = client.get('/collections/beds', headers={'accept': 'text/html'})
    assert html.headers['content-type'].startswith('text/html')


def test_beds_collection_unknown_format_is_400(client):
    r = client.get('/collections/beds?f=xml')
    assert_problem(r, status=400)


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


def test_serve_help_uses_renamed_replica_flag():
    # `garden serve` renames the replica-dsn field's flag to `--replica` (via
    # serve_command's rename=), but it still documents/targets GARDEN_REPLICA_DSN.
    result = CliRunner().invoke(main, ['serve', '--help'])
    assert result.exit_code == 0, result.output
    assert '--replica ' in result.output
    assert '--garden-replica-dsn' not in result.output  # the prefixed default is gone
    assert 'GARDEN_REPLICA_DSN' in result.output  # env var (and thus the field) unchanged


def test_serve_renamed_flag_writes_original_env_var(monkeypatch):
    monkeypatch.delenv('GARDEN_REPLICA_DSN', raising=False)
    # --check validates settings then exits without a server; the renamed option's
    # callback still propagates its value to the field's (unchanged) env var.
    result = CliRunner().invoke(main, ['serve', '--replica', 'memory://cli', '--check'])
    assert result.exit_code == 0, result.output
    assert os.environ['GARDEN_REPLICA_DSN'] == 'memory://cli'


def test_link_header_mirrors_nav_links(client):
    # set_link_header mirrors the navigational body links as an RFC 8288 header.
    resp = client.get('/plants', headers=AUTH)
    header = resp.headers['link']
    assert 'rel="self"' in header
    assert 'rel="root"' in header


def test_bed_conditional_get(client):
    first = client.get('/collections/beds/items/roses')
    assert first.status_code == 200
    etag = first.headers['etag']
    assert first.headers['cache-control'] == 'max-age=300'
    # a revalidation with the same etag short-circuits to 304, which still refreshes
    # the cache's freshness directives (RFC 9111 §4.3.4)
    again = client.get('/collections/beds/items/roses', headers={'if-none-match': etag})
    assert again.status_code == 304
    assert again.headers['cache-control'] == 'max-age=300'
