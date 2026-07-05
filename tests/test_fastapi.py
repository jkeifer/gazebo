from __future__ import annotations

import asyncio

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal

import httpx2 as httpx
import pytest

from fastapi import Request, Response
from fastapi.testclient import TestClient
from pydantic import BaseModel

from gazebo.asgi import trust_all
from gazebo.collection import LinkedCollection
from gazebo.context import RequestContext
from gazebo.di import Key
from gazebo.ext.fastapi import (
    BBoxParam,
    CorsConfig,
    CrsParam,
    DatetimeParam,
    FilterParam,
    GazeboApp,
    GazeboRouter,
    Inject,
    LinkedRouter,
    Negotiate,
    Overrides,
    Providers,
    RootRouter,
    SortByParam,
    forward_lifespans,
    set_link_header,
    upgrade,
)
from gazebo.filtering import Filter, SortBy, queryables_from_model, sortables_from_model
from gazebo.filtering.cql2 import Cql2Engine
from gazebo.link import Link
from gazebo.negotiation import HTML, JSON, Representation
from gazebo.params import CRS84, BBox, DatetimeInterval
from gazebo.problems import ProblemException
from gazebo.rels import Rel

if TYPE_CHECKING:
    # A name visible to the type checkers but absent at runtime — exactly the shape
    # of an import guarded by ``if TYPE_CHECKING:`` that trips up ``get_type_hints``.
    TypeOnlyName = int

TORN: list[str] = []


@dataclass
class Settings:
    dsn: str = 'real'

    @classmethod
    def __provide__(cls) -> Settings:
        return cls()


class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @classmethod
    @asynccontextmanager
    async def __provide__(cls, settings: Settings) -> AsyncIterator[Database]:
        try:
            yield cls(settings.dsn)
        finally:
            TORN.append('db')

    async def __health__(self) -> bool:
        return True


class Session:
    """External-style type: provided by a standalone function, injected via Inject."""

    def __init__(self, db: Database) -> None:
        self.db = db


@asynccontextmanager
async def provide_session(database: Database) -> AsyncIterator[Session]:
    try:
        yield Session(database)
    finally:
        TORN.append('session')


@dataclass
class User:
    name: str

    @classmethod
    async def __provide__(cls, request: Request, session: Annotated[Session, Inject]) -> User:
        return cls(request.headers.get('authorization', 'anon'))


@dataclass
class Ping:
    ok: bool = True

    @classmethod
    async def __provide__(cls) -> Ping:
        return cls()


class ThingCollection(LinkedCollection[dict], items_alias='things'):
    pass


def build_router() -> GazeboRouter:
    router = GazeboRouter()

    @router.get('/things', response_model=ThingCollection)
    async def list_things(session: Annotated[Session, Inject], user: User, limit: int = 10):
        items = [{'id': i, 'owner': user.name, 'dsn': session.db.dsn} for i in range(limit)]
        return ThingCollection(items=items, links=[Link.self_link(), Link.root_link()])

    @router.get('/boom')
    async def boom():
        raise ProblemException(404, detail='nope', instance='/boom')

    return router


def make_app(overrides: Overrides | None = None) -> GazeboApp:
    providers = Providers()
    providers.app(Settings).app(Database)
    providers.request(Session, provide_session).request(User)
    app = GazeboApp(providers, overrides=overrides, trust=trust_all)
    app.include_router(build_router())

    @app.get('/', name='landing')
    async def landing():
        return {'ok': True}

    return app


@pytest.fixture
def client():
    TORN.clear()
    with TestClient(make_app()) as c:
        yield c


def test_bare_type_injection(client):
    r = client.get('/things?limit=2', headers={'authorization': 'alice'})
    assert r.status_code == 200
    body = r.json()
    assert body['things'] == [
        {'id': 0, 'owner': 'alice', 'dsn': 'real'},
        {'id': 1, 'owner': 'alice', 'dsn': 'real'},
    ]
    assert body['numberReturned'] == 2


def test_links_resolved_in_response(client):
    body = client.get('/things?limit=1', headers={'authorization': 'a'}).json()
    rels = {link['rel']: link['href'] for link in body['links']}
    assert rels['self'].endswith('/things?limit=1')
    assert rels['root'].endswith('/')


def test_problem_response(client):
    r = client.get('/boom')
    assert r.status_code == 404
    assert r.headers['content-type'] == 'application/problem+json'
    assert r.json()['detail'] == 'nope'


def test_validation_error_is_problem(client):
    # a non-int `limit` fails FastAPI request validation; the glue maps that to a
    # problem+json 422 (not FastAPI's default {"detail": [...]} shape).
    r = client.get('/things?limit=nope', headers={'authorization': 'a'})
    assert r.status_code == 422
    assert r.headers['content-type'] == 'application/problem+json'
    body = r.json()
    assert body['status'] == 422
    assert body['title'] == 'Unprocessable Entity'
    # the field-level error list is carried as an RFC 9457 extension member
    assert body['errors']
    assert any(err['loc'] == ['query', 'limit'] for err in body['errors'])
    # unset optional members are omitted, not emitted as null (OGC omit-null)
    assert 'instance' not in body


def test_health(client):
    body = client.get('/health').json()
    assert body['status'] == 'healthy'
    assert body['checks'].get('Database') == 'ok'


def test_proxy_headers_make_links_https(client):
    body = client.get(
        '/things?limit=1',
        headers={
            'authorization': 'b',
            'x-forwarded-proto': 'https',
            'x-forwarded-host': 'api.public.com',
            'x-forwarded-prefix': '/v1',
        },
    ).json()
    rels = {link['rel']: link['href'] for link in body['links']}
    assert rels['self'].startswith('https://api.public.com/')
    assert rels['root'] == 'https://api.public.com/v1/'


def test_teardown_order(client):
    client.get('/things?limit=1', headers={'authorization': 'a'})
    # request-scoped session torn down before app-scoped db at shutdown
    assert 'session' in TORN


def test_overrides():
    with TestClient(make_app(Overrides().set(Settings, Settings(dsn='TEST')))) as client:
        body = client.get('/things?limit=1', headers={'authorization': 'x'}).json()
        assert body['things'][0]['dsn'] == 'TEST'


def test_injected_params_absent_from_openapi(client):
    schema = client.get('/openapi.json').json()
    params = schema['paths']['/things']['get'].get('parameters', [])
    names = {p['name'] for p in params}
    assert 'limit' in names
    assert 'session' not in names
    assert 'user' not in names


def test_plain_router_injectable_fails_loudly():
    # Declaring an injectable-typed route on a plain APIRouter (instead of a
    # GazeboRouter) must fail loudly at startup, not silently treat it as a body.
    from fastapi import APIRouter

    plain = APIRouter()

    @plain.get('/oops')
    async def oops(ping: Ping):
        return {'ok': True}

    app = GazeboApp(Providers().request(Ping))
    app.include_router(plain)
    with pytest.raises(RuntimeError, match='look injectable'), TestClient(app):
        pass


def test_injection_survives_unresolvable_sibling_hint():
    # The headline of per-parameter resolution: a name importable only under
    # TYPE_CHECKING makes that one annotation unresolvable, but the injectable param
    # next to it must still be rewritten (it used to be silently skipped, then 500'd
    # as a request body). A warning still names the unresolvable parameter.
    import inspect

    from gazebo.ext.fastapi.injection import inject_signature

    async def handler(value: TypeOnlyName, ping: Ping):  # type: ignore[name-defined]
        return {'ok': ping.ok}

    with pytest.warns(UserWarning, match='could not resolve the type hint for .*value'):
        inject_signature(handler)

    params = inspect.signature(handler).parameters
    # `ping` was wired into a Depends despite `value` being unresolvable...
    assert type(params['ping'].default).__name__ == 'Depends'
    # ...while `value` is left untouched for FastAPI to handle.
    assert params['value'].default is inspect.Parameter.empty


def test_injection_warning_fires_once_on_reregistration():
    # include_router re-invokes inject_signature on the same endpoint; the warning
    # must fire at most once, not once per registration.
    import warnings

    from gazebo.ext.fastapi.injection import inject_signature

    async def handler(value: TypeOnlyName):  # type: ignore[name-defined]
        return {'ok': True}

    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter('always')
        inject_signature(handler)
        inject_signature(handler)
    matching = [r for r in records if 'could not resolve' in str(r.message)]
    assert len(matching) == 1


def test_unresolvable_hints_do_not_crash_startup():
    # The startup route guard must not let the unresolved hint escape as a cryptic
    # crash — the decoration-time warning already covers it.
    gr = GazeboRouter()

    with pytest.warns(UserWarning, match='could not resolve'):

        @gr.get('/typecheck-only')
        async def route(value: TypeOnlyName):  # type: ignore[name-defined]
            return {'ok': True}

    app = GazeboApp(Providers())
    app.include_router(gr)
    # Entering the context runs the lifespan, where _validate_routes inspects every
    # route; the unresolved hint must not crash startup.
    with TestClient(app):
        pass


def test_upgrade_existing_app():
    from fastapi import FastAPI

    gr = GazeboRouter()

    @gr.get('/ping')
    async def ping_route(ping: Ping):
        return {'ok': ping.ok}

    app = FastAPI(title='pre-existing')
    app.include_router(gr)
    upgrade(app, Providers().request(Ping))  # gazebo-ify an app we didn't construct
    with TestClient(app) as client:
        assert client.get('/ping').json() == {'ok': True}
        assert client.get('/health').status_code == 200


def test_upgrade_does_not_mutate_callers_providers():
    from fastapi import FastAPI

    providers = Providers().request(Ping)
    assert Key(RequestContext) not in providers.bindings  # type: ignore[type-abstract]

    app = FastAPI(title='pre-existing')
    upgrade(app, providers)

    # upgrade() must layer in the default RequestContext binding on its own copy,
    # never write it back into the caller-owned registry.
    assert Key(RequestContext) not in providers.bindings  # type: ignore[type-abstract]
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200


def test_forward_lifespans_mount():
    from fastapi import FastAPI

    sub = GazeboApp(Providers().request(Ping))
    subr = GazeboRouter()

    @subr.get('/ping')
    async def ping_route(ping: Ping):
        return {'ok': ping.ok}

    sub.include_router(subr)

    root = FastAPI(lifespan=forward_lifespans(sub))
    root.mount('/api', sub)
    with TestClient(root) as client:
        assert client.get('/api/ping').json() == {'ok': True}


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


def _cors_app(cors) -> GazeboApp:
    app = GazeboApp(Providers(), cors=cors)

    @app.get('/ping')
    async def ping():
        return {'ok': True}

    return app


def test_cors_config_fields_are_middleware_kwargs():
    # CorsConfig.apply() splats asdict(self) straight into CORSMiddleware, so every
    # field name MUST be a CORSMiddleware parameter — otherwise apply() raises
    # TypeError at app startup. (CORSMiddleware may carry extra params CorsConfig
    # deliberately doesn't expose, e.g. allow_private_network; those just take the
    # middleware default, so the guard is a subset, not equality.)
    import inspect

    from dataclasses import fields

    from starlette.middleware.cors import CORSMiddleware

    mw_params = set(inspect.signature(CORSMiddleware).parameters)
    unknown = {f.name for f in fields(CorsConfig)} - mw_params
    assert not unknown, f'CorsConfig fields not accepted by CORSMiddleware: {unknown}'


def test_no_cors_by_default(client):
    # the default fixture app sets no cors; no CORS headers should appear.
    r = client.get('/things', headers={'authorization': 'a', 'origin': 'http://x.test'})
    assert 'access-control-allow-origin' not in r.headers


def test_cors_true_is_permissive():
    with TestClient(_cors_app(True)) as client:
        r = client.get('/ping', headers={'origin': 'http://anywhere.test'})
        assert r.headers['access-control-allow-origin'] == '*'
        # a preflight is answered without reaching the route
        pre = client.options(
            '/ping',
            headers={
                'origin': 'http://anywhere.test',
                'access-control-request-method': 'GET',
            },
        )
        assert pre.status_code == 200
        assert pre.headers['access-control-allow-origin'] == '*'


def test_cors_origin_allowlist():
    with TestClient(_cors_app(['http://good.test'])) as client:
        ok = client.get('/ping', headers={'origin': 'http://good.test'})
        assert ok.headers['access-control-allow-origin'] == 'http://good.test'
        # a disallowed origin gets no allow-origin header echoed back
        bad = client.get('/ping', headers={'origin': 'http://evil.test'})
        assert 'access-control-allow-origin' not in bad.headers


def test_cors_config_credentials():
    config = CorsConfig(allow_origins=['http://app.test'], allow_credentials=True)
    with TestClient(_cors_app(config)) as client:
        r = client.get('/ping', headers={'origin': 'http://app.test'})
        assert r.headers['access-control-allow-origin'] == 'http://app.test'
        assert r.headers['access-control-allow-credentials'] == 'true'


def test_cors_headers_on_problem_response():
    # CORS is outermost, so even a problem+json error carries the allow-origin header.
    app = _cors_app(True)

    @app.get('/boom')
    async def boom():
        raise ProblemException(404, detail='nope')

    with TestClient(app) as client:
        r = client.get('/boom', headers={'origin': 'http://anywhere.test'})
        assert r.status_code == 404
        assert r.headers['content-type'] == 'application/problem+json'
        assert r.headers['access-control-allow-origin'] == '*'


def _params_app() -> GazeboApp:
    app = GazeboApp(Providers())

    @app.get('/search')
    async def search(
        bbox: Annotated[BBox | None, BBoxParam] = None,
        datetime: Annotated[DatetimeInterval | None, DatetimeParam] = None,
        crs: Annotated[str, CrsParam(allowed=[CRS84])] = CRS84,
    ) -> dict:
        return {
            'bbox': None if bbox is None else [bbox.minx, bbox.miny, bbox.maxx, bbox.maxy],
            'has_datetime': datetime is not None,
            'crs': crs,
        }

    return app


@pytest.fixture
def params_client():
    with TestClient(_params_app()) as c:
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


# --- Link: response header via set_link_header helper ---------------------


def test_set_link_header_from_model_links():
    # No link_header middleware: the helper alone sets the header.
    app = GazeboApp(Providers())

    @app.get('/things', response_model=ThingCollection)
    async def things(response: Response) -> ThingCollection:
        coll = ThingCollection(
            items=[{'id': 1}],
            links=[
                Link.self_link(),
                Link(href=lambda ctx: ctx.url + '?page=2', rel=Rel.NEXT),
                Link(href='https://x/detail/1', rel=Rel.ITEM),  # non-nav, filtered out
            ],
        )
        set_link_header(response, coll.links)
        return coll

    with TestClient(app) as client:
        header = client.get('/things').headers['link']
        assert 'rel="self"' in header
        assert 'rel="next"' in header
        assert 'http://testserver/things' in header  # deferred href resolved in-endpoint
        assert 'rel="item"' not in header


def test_set_link_header_accepts_a_plain_link_list():
    # Not tied to an envelope: a bare list of Links works (and on a non-model response).
    app = GazeboApp(Providers())

    @app.get('/x')
    async def x(response: Response) -> dict:
        set_link_header(
            response,
            [Link.self_link(), Link(href='https://x/next', rel=Rel.NEXT)],
        )
        return {'ok': True}

    with TestClient(app) as client:
        header = client.get('/x').headers['link']
        assert 'rel="self"' in header
        assert 'rel="next"' in header


def test_set_link_header_respects_rels_filter():
    app = GazeboApp(Providers())

    @app.get('/x')
    async def x(response: Response) -> dict:
        set_link_header(
            response,
            [Link.self_link(), Link(href='https://x/next', rel=Rel.NEXT)],
            rels=['next'],
        )
        return {'ok': True}

    with TestClient(app) as client:
        header = client.get('/x').headers['link']
        assert 'rel="next"' in header
        assert 'rel="self"' not in header


def test_set_link_header_sets_nothing_when_no_nav_links():
    app = GazeboApp(Providers())

    @app.get('/x')
    async def x(response: Response) -> dict:
        set_link_header(response, [Link(href='https://x/i/1', rel=Rel.ITEM)])  # non-nav only
        return {'ok': True}

    with TestClient(app) as client:
        assert 'link' not in client.get('/x').headers


# --- conditional requests / caching (#6) ----------------------------------


def _caching_app():
    from gazebo.ext.fastapi import etag_for, not_modified, set_cache_headers

    app = GazeboApp(Providers())
    data = {'value': 1}

    @app.get('/thing')
    async def thing(request: Request, response: Response):
        etag = etag_for(data)
        nm = not_modified(request, etag=etag, cache_control='max-age=60')
        if nm is not None:
            return nm
        set_cache_headers(response, etag=etag, cache_control='max-age=60')
        return data

    return app, data


def test_etag_set_on_first_response():
    app, _ = _caching_app()
    with TestClient(app) as client:
        resp = client.get('/thing')
        assert resp.status_code == 200
        assert resp.headers['etag'].startswith('W/"')
        assert resp.headers['cache-control'] == 'max-age=60'


def test_conditional_get_returns_304():
    app, _ = _caching_app()
    with TestClient(app) as client:
        etag = client.get('/thing').headers['etag']
        again = client.get('/thing', headers={'if-none-match': etag})
        assert again.status_code == 304
        assert again.headers['etag'] == etag
        # the 304 refreshes cache freshness directives (RFC 9111 §4.3.4)
        assert again.headers['cache-control'] == 'max-age=60'
        assert again.content == b''


def test_changed_resource_is_not_304():
    app, data = _caching_app()
    with TestClient(app) as client:
        etag = client.get('/thing').headers['etag']
        data['value'] = 2  # resource changed -> old etag no longer matches
        again = client.get('/thing', headers={'if-none-match': etag})
        assert again.status_code == 200
        assert again.headers['etag'] != etag


# --- content negotiation (#4) ---------------------------------------------


def _negotiation_app():
    app = GazeboApp(Providers())

    @app.get('/res')
    async def res(rep: Annotated[Representation, Negotiate([JSON, HTML])]) -> dict:
        return {'format': rep.key, 'media_type': rep.media_type}

    return app


def test_negotiate_f_param_wins():
    with TestClient(_negotiation_app()) as client:
        assert client.get('/res?f=html').json()['format'] == 'html'
        # f beats a conflicting Accept
        r = client.get('/res?f=json', headers={'accept': 'text/html'})
        assert r.json()['format'] == 'json'


def test_negotiate_accept_header():
    with TestClient(_negotiation_app()) as client:
        r = client.get('/res', headers={'accept': 'text/html'})
        assert r.json()['format'] == 'html'


def test_negotiate_default_is_first():
    with TestClient(_negotiation_app()) as client:
        # TestClient sends Accept: */* by default -> first offered (json)
        assert client.get('/res').json()['format'] == 'json'


def test_negotiate_unknown_f_is_400_problem():
    with TestClient(_negotiation_app()) as client:
        r = client.get('/res?f=xml')
        assert r.status_code == 400
        assert r.headers['content-type'] == 'application/problem+json'
        assert r.json()['parameter'] == 'f'


def test_negotiate_unacceptable_is_406_problem():
    with TestClient(_negotiation_app()) as client:
        r = client.get('/res', headers={'accept': 'application/xml'})
        assert r.status_code == 406
        assert r.headers['content-type'] == 'application/problem+json'


# --- CQL2 filtering + sortby (#9) -----------------------------------------


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


# --- body-reading recipes share the request body with the endpoint --------


async def _asgi_request(app, method, path, *, json=None, timeout=5.0):
    # Drive the app via an in-process ASGI transport with an explicit timeout so a
    # regression that re-introduces the body-read deadlock fails the suite instead of
    # hanging it (TestClient has no server-side hang protection). We enter the lifespan
    # ourselves because ASGITransport does not run it.
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            return await asyncio.wait_for(client.request(method, path, json=json), timeout)


class _Audit:
    """A request-scoped recipe that reads the raw request body."""

    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    @classmethod
    async def __provide__(cls, request: Request) -> _Audit:
        return cls(await request.body())


class _Item(BaseModel):
    name: str


async def test_body_reading_recipe_and_body_endpoint_do_not_deadlock():
    # A recipe reading the body AND an endpoint parsing the body consume the same ASGI
    # receive channel; without a replayable receive the second reader blocks forever.
    router = GazeboRouter()

    @router.post('/items')
    async def create(item: _Item, audit: _Audit) -> dict:
        return {'name': item.name, 'audit_len': len(audit.raw)}

    app = GazeboApp(Providers().request(_Audit))
    app.include_router(router)

    resp = await _asgi_request(app, 'POST', '/items', json={'name': 'widget'})
    assert resp.status_code == 200
    body = resp.json()
    assert body['name'] == 'widget'
    assert body['audit_len'] > 0


async def test_body_reading_recipe_without_body_endpoint():
    # The recipe reads the body even though the endpoint does not parse one.
    router = GazeboRouter()

    @router.post('/audit')
    async def audit_only(audit: _Audit) -> dict:
        return {'audit_len': len(audit.raw)}

    app = GazeboApp(Providers().request(_Audit))
    app.include_router(router)

    resp = await _asgi_request(app, 'POST', '/audit', json={'hello': 'world'})
    assert resp.status_code == 200
    assert resp.json()['audit_len'] > 0


async def test_ordinary_body_endpoint_without_recipe_still_works():
    # Regression: the replay wrapper must not disturb the plain case (endpoint parses a
    # body, no body-reading recipe).
    router = GazeboRouter()

    @router.post('/plain')
    async def plain(item: _Item) -> dict:
        return {'name': item.name}

    app = GazeboApp(Providers())
    app.include_router(router)

    resp = await _asgi_request(app, 'POST', '/plain', json={'name': 'plain'})
    assert resp.status_code == 200
    assert resp.json() == {'name': 'plain'}


# --- duplicate route names fail loudly ------------------------------------


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


# --- health status code reflects readiness --------------------------------


class _Unhealthy:
    @classmethod
    def __provide__(cls) -> _Unhealthy:
        return cls()

    async def __health__(self) -> bool:
        return False


class _Erroring:
    @classmethod
    def __provide__(cls) -> _Erroring:
        return cls()

    def __health__(self) -> bool:
        raise RuntimeError('probe blew up')


def test_health_healthy_is_200(client):
    r = client.get('/health')
    assert r.status_code == 200
    assert r.json()['status'] == 'healthy'


def test_health_unhealthy_resource_is_503():
    app = GazeboApp(Providers().app(_Unhealthy))
    with TestClient(app) as client:
        r = client.get('/health')
        assert r.status_code == 503
        body = r.json()
        assert body['status'] == 'unhealthy'
        assert body['checks'][str(Key(_Unhealthy))] == 'fail'


def test_health_erroring_probe_is_503():
    app = GazeboApp(Providers().app(_Erroring))
    with TestClient(app) as client:
        r = client.get('/health')
        assert r.status_code == 503
        assert r.json()['checks'][str(Key(_Erroring))] == 'error'
