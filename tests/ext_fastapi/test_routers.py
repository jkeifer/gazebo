"""Router link resolution, the RootRouter/LinkedRouter hierarchy, and route-name checks."""

from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from gazebo.asgi import trust_all
from gazebo.ext.fastapi import GazeboApp, LinkedRouter, Providers, RootRouter
from gazebo.rels import Rel


def test_links_resolved_in_response(client):
    body = client.get('/things?limit=1', headers={'authorization': 'a'}).json()
    rels = {link['rel']: link['href'] for link in body['links']}
    assert rels['self'].endswith('/things?limit=1')
    assert rels['root'].endswith('/')


def test_templated_link_resolved_proxy_correct(client):
    # The adapter resolves through the real router (preserving proxy scheme/host),
    # leaving the path var as {triplet} and appending the {?from,to} query template.
    body = client.get('/templated', headers={'x-forwarded-proto': 'https'}).json()
    link = body['links'][0]
    assert link['href'].endswith('/stats/{triplet}/date-range{?from,to}')
    assert link['href'].startswith('https://')
    assert link['templated'] is True


def test_templated_field_in_openapi_link_schema(client):
    schema = client.get('/openapi.json').json()
    link_schema = schema['components']['schemas']['Link']
    assert 'templated' in link_schema['properties']


def test_bad_template_var_fails_loudly(client):
    # A template var that is not a real route parameter must not silently produce a
    # bogus URL; url_for rejects it and the failure surfaces (500, not 200).
    with pytest.raises(Exception):  # noqa: B017,PT011
        client.get('/bad-template')


def test_linked_router_hierarchy():
    root = LinkedRouter(title='API', landing_name='landing')
    things = LinkedRouter(rel=Rel.CHILD, title='Things', landing_name='things_landing')

    @things.get('/list')
    async def listing():
        return {'ok': True}

    root.include_router(things, prefix='/things')

    providers = Providers()
    app = GazeboApp(providers, trust=trust_all)
    app.include_router(root)

    with TestClient(app) as client:
        home = client.get('/').json()
        rels = {link['rel'] for link in home['links']}
        assert 'self' in rels
        assert 'root' in rels
        assert Rel.CHILD in rels
        child = client.get('/things').json()
        child_rels = {link['rel'] for link in child['links']}
        assert 'self' in child_rels


def _root_app(*, conformance=None, **app_kwargs) -> GazeboApp:
    app = GazeboApp(Providers(), trust=trust_all, **app_kwargs)
    app.include_router(RootRouter(landing_name='landing', conformance=conformance))
    return app


def test_root_router_landing_has_service_and_conformance_links():
    app = _root_app(title='Demo', description='A demo service.')
    with TestClient(app) as client:
        home = client.get('/').json()
        # title/description fall back to the app's (RootRouter set neither).
        assert home['title'] == 'Demo'
        assert home['description'] == 'A demo service.'
        links = {link['rel']: link['href'] for link in home['links']}
        assert links['service-desc'].endswith('/openapi.json')
        assert links['service-doc'].endswith('/docs')
        assert links['conformance'].endswith('/conformance')


def test_root_router_conformance_baseline_from_app_plus_extras():
    app = _root_app(conformance=['https://example.com/conf/features'])
    with TestClient(app) as client:
        conforms = client.get('/conformance').json()['conformsTo']
    assert 'https://example.com/conf/features' in conforms
    # Derived baseline: core/landing-page/json, plus oas30 because OpenAPI is exposed.
    assert {
        'http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/core',
        'http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/landing-page',
        'http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/json',
        'http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/oas30',
    } <= set(conforms)


def test_root_router_omits_service_links_and_oas30_when_openapi_disabled():
    app = _root_app(openapi_url=None)
    with TestClient(app) as client:
        rels = {link['rel'] for link in client.get('/').json()['links']}
        conforms = client.get('/conformance').json()['conformsTo']
    # No OpenAPI document -> no service-desc/service-doc and no oas30 conformance class.
    assert 'service-desc' not in rels
    assert 'service-doc' not in rels
    assert 'http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/oas30' not in conforms


def test_duplicate_route_names_fail_loudly():
    # Two LinkedRouters both keeping the default landing_name='landing' register a
    # duplicate route name; url_for would resolve a child link to the parent. Startup
    # must fail loudly instead.
    root = LinkedRouter(landing_name='landing')
    child = LinkedRouter(rel=Rel.CHILD, landing_name='landing')
    root.include_router(child, prefix='/child')

    app = GazeboApp(Providers())
    app.include_router(root)

    with pytest.raises(RuntimeError, match="'landing'"), TestClient(app):
        pass


def test_distinct_route_names_boot():
    root = LinkedRouter(landing_name='landing')
    child = LinkedRouter(rel=Rel.CHILD, landing_name='child_landing')
    root.include_router(child, prefix='/child')

    app = GazeboApp(Providers())
    app.include_router(root)

    with TestClient(app) as client:
        assert client.get('/').status_code == 200
        assert client.get('/child').status_code == 200
