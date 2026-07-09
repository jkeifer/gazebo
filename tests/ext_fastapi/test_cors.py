"""CORS wiring: the CorsConfig contract, permissive/allowlist modes, error responses."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gazebo.ext.fastapi import CorsConfig, GazeboApp, Providers
from gazebo.problems import ProblemException


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
