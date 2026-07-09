"""Conditional requests through the glue: ETag emission and 304 handling."""

from __future__ import annotations

from fastapi import Request, Response
from fastapi.testclient import TestClient

from gazebo.ext.fastapi import GazeboApp, Providers


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
