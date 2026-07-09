"""The ``set_link_header`` response helper: nav-link filtering and deferred resolution."""

from __future__ import annotations

from fastapi import Response
from fastapi.testclient import TestClient

from gazebo.ext.fastapi import GazeboApp, Providers, set_link_header
from gazebo.link import Link
from gazebo.rels import Rel

from .support import ThingCollection


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
