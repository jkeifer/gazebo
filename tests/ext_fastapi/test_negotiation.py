"""The Negotiate ``Depends`` adapter: ``?f=`` precedence, Accept, 400/406 problems."""

from __future__ import annotations

from typing import Annotated

from fastapi.testclient import TestClient

from gazebo.ext.fastapi import GazeboApp, Negotiate, Providers
from gazebo.negotiation import HTML, JSON, Representation


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
