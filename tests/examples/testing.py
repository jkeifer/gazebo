"""Runnable examples backing the ``docs/testing/`` pages.

These call the helpers directly (they are plain functions); under pytest the same
module is registered as a plugin so its assertions are rewritten for richer output.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from gazebo.collection import LinkedCollection
from gazebo.ext.fastapi import GazeboApp, GazeboRouter, Providers
from gazebo.link import Link
from gazebo.pagination import paginate
from gazebo.problems import ProblemException


class Numbers(LinkedCollection[int]):
    pass


router = GazeboRouter()


@router.get('/numbers', response_model=Numbers)
async def numbers(offset: int = 0):
    page = list(range(offset, min(offset + 2, 5)))
    nxt = str(offset + 2) if offset + 2 < 5 else None
    links = [Link.self_link(), *paginate(next_token=nxt, token_param='offset')]
    return Numbers(items=page, links=links)


@router.get('/boom')
async def boom():
    raise ProblemException(404, detail='nope')


app = GazeboApp(Providers())
app.include_router(router)


with TestClient(app) as client:
    # --8<-- [start:pagination]
    from gazebo.testing import drive_pagination

    # Follow every `next` link, accumulating items to exhaustion. On each page it
    # asserts the envelope invariants — numberReturned == len(items), and (with
    # limit=) no page over the limit — and guards against a looping `next`.
    all_numbers = drive_pagination(client, '/numbers', items_key='items', limit=2)
    assert all_numbers == [0, 1, 2, 3, 4]
    # --8<-- [end:pagination]

    # --8<-- [start:assertions]
    from gazebo.testing import assert_has_link, assert_problem, find_link

    # assert_problem checks the content-type *and* the document shape, and returns
    # the parsed problem body for further assertions.
    problem = assert_problem(client.get('/boom'), status=404)
    assert problem['title'] == 'Not Found'

    body = client.get('/numbers').json()
    # assert_has_link checks an envelope (or a links list) carries a matching link,
    # optionally by `type` / `href_suffix`, and returns it.
    self_link = assert_has_link(body, 'self')
    assert self_link['rel'] == 'self'

    # find_link is the non-asserting lookup — the link, or None.
    assert find_link(body, 'next') is not None
    # --8<-- [end:assertions]
