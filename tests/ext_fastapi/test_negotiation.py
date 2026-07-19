"""The Negotiate ``Depends`` adapter: ``?f=`` precedence, Accept, 400/406 problems."""

from __future__ import annotations

from typing import Annotated

from fastapi.testclient import TestClient
from pydantic import BaseModel

from gazebo.ext.fastapi import GazeboApp, GazeboRouter, Negotiate, Providers
from gazebo.negotiation import CSV, HTML, JSON, Representation


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


# --- OpenAPI auto-fold of negotiated media types ---------------------------


class _Doc(BaseModel):
    id: str


def _folded_app():
    app = GazeboApp(Providers())
    router = GazeboRouter()

    @router.get('/doc', response_model=_Doc)
    async def doc(rep: Annotated[Representation, Negotiate([JSON, CSV])]) -> _Doc:
        return _Doc(id='x')

    @router.get('/plain', response_model=_Doc)
    async def plain() -> _Doc:
        return _Doc(id='y')

    @router.get(
        '/custom',
        response_model=_Doc,
        responses={200: {'content': {'text/csv': {'schema': {'type': 'array'}}}}},
    )
    async def custom(rep: Annotated[Representation, Negotiate([JSON, CSV])]) -> _Doc:
        return _Doc(id='z')

    app.include_router(router)
    return app


def _content(app, path):
    schema = app.openapi()
    return schema['paths'][path]['get']['responses']['200']['content']


def test_autofold_documents_extra_media_types():
    app = _folded_app()
    content = _content(app, '/doc')
    # the negotiated CSV media type is documented as a string schema
    assert content['text/csv']['schema'] == {'type': 'string'}
    # and application/json still carries the response_model's $ref (not a string)
    assert '$ref' in content['application/json']['schema']


def test_autofold_noop_without_negotiate():
    app = _folded_app()
    content = _content(app, '/plain')
    assert 'text/csv' not in content
    assert '$ref' in content['application/json']['schema']


def test_autofold_does_not_clobber_user_responses():
    app = _folded_app()
    content = _content(app, '/custom')
    # user-supplied text/csv schema is preserved, not overwritten by the derived default
    assert content['text/csv']['schema'] == {'type': 'array'}
    assert '$ref' in content['application/json']['schema']
