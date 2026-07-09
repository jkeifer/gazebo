"""The per-request RequestContext adapter: exposed headers and ambient Accept."""

from __future__ import annotations

from fastapi import Request
from fastapi.testclient import TestClient

from gazebo.context import RequestContext
from gazebo.ext.fastapi import GazeboApp, Providers


def test_request_context_adapter_exposes_headers():
    app = GazeboApp(Providers())
    seen: dict[str, str] = {}

    @app.get('/whoami')
    async def whoami(request: Request) -> dict:
        from gazebo.context import link_context

        ctx = link_context.get(None)
        assert ctx is not None
        assert isinstance(ctx, RequestContext)  # structural + runtime-checkable
        seen['accept'] = ctx.headers.get('accept', '')
        # Starlette Headers are case-insensitive.
        seen['accept_upper'] = ctx.headers.get('ACCEPT', '')
        return {'ok': True}

    with TestClient(app) as client:
        client.get('/whoami', headers={'Accept': 'text/html'})
    assert seen['accept'] == 'text/html'
    assert seen['accept_upper'] == 'text/html'


def test_negotiate_uses_ambient_accept_in_a_live_request():
    from gazebo.negotiation import HTML, JSON, negotiate

    app = GazeboApp(Providers())

    @app.get('/pick')
    async def pick() -> dict:
        # No explicit accept passed: negotiate() falls back to the live request's
        # Accept via the ambient RequestContext published by the request-scope middleware.
        rep = negotiate([JSON, HTML])
        return {'format': rep.key}

    with TestClient(app) as client:
        assert client.get('/pick', headers={'Accept': 'text/html'}).json() == {'format': 'html'}
        assert client.get('/pick', headers={'Accept': 'application/json'}).json() == {
            'format': 'json',
        }
        # No Accept header -> default (first offered).
        assert client.get('/pick').json() == {'format': 'json'}
