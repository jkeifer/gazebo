from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from fastapi.testclient import TestClient

from gazebo.context import link_context
from gazebo.di import Overrides
from gazebo.ext.fastapi import GazeboApp, GazeboRouter
from gazebo.link import Link
from gazebo.pagination import paginate
from gazebo.testing import assert_has_link, assert_problem, drive_pagination, find_link

# --- stub response / client for the pure-function helpers ------------------


@dataclass
class _Resp:
    status_code: int
    _body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)
    text: str = ''

    def json(self) -> dict[str, Any]:
        return self._body


def test_find_link_accepts_body_or_list():
    body = {'links': [{'rel': 'self', 'href': '/x'}, {'rel': 'next', 'href': '/x?p=2'}]}
    nxt = find_link(body, 'next')
    assert nxt is not None
    assert nxt['href'] == '/x?p=2'
    selfl = find_link(body['links'], 'self')
    assert selfl is not None
    assert selfl['href'] == '/x'
    assert find_link(body, 'prev') is None


def test_assert_has_link_checks_type_and_suffix():
    geojson = 'application/geo+json'
    body = {'links': [{'rel': 'self', 'href': 'https://h/items/1', 'type': geojson}]}
    link = assert_has_link(body, 'self', type=geojson, href_suffix='/items/1')
    assert link['rel'] == 'self'
    with pytest.raises(AssertionError, match='no link with rel'):
        assert_has_link(body, 'next')
    with pytest.raises(AssertionError, match='type'):
        assert_has_link(body, 'self', type='application/json')


def test_find_link_handles_null_links():
    # a body whose `links` member is explicitly null must not crash the helper
    # (body.get('links', []) would return None and then iterate it -> TypeError).
    assert find_link({'links': None}, 'self') is None
    with pytest.raises(AssertionError, match='no link with rel'):
        assert_has_link({'links': None}, 'self')


def test_assert_problem_validates_content_type_and_shape():
    good = _Resp(
        404,
        {'title': 'Not Found', 'status': 404},
        headers={'content-type': 'application/problem+json'},
    )
    assert assert_problem(good, status=404)['status'] == 404
    plain = _Resp(404, {'detail': 'x'}, headers={'content-type': 'application/json'})
    with pytest.raises(AssertionError, match='problem'):
        assert_problem(plain)


def test_assert_problem_accepts_titleless_problem():
    # RFC 7807 makes `title` optional; a problem with only type/status/detail is valid.
    titleless = _Resp(
        400,
        {'type': 'about:blank', 'status': 400, 'detail': 'bad'},
        headers={'content-type': 'application/problem+json'},
    )
    assert assert_problem(titleless, status=400)['status'] == 400
    # but a problem+json body missing `status` is still rejected as malformed
    no_status = _Resp(400, {'title': 'Bad'}, headers={'content-type': 'application/problem+json'})
    with pytest.raises(AssertionError, match='status'):
        assert_problem(no_status)


# --- drive_pagination over a fake client -----------------------------------


class _FakeClient:
    """Serves three pages of items with chained `next` links."""

    def __init__(self) -> None:
        self.pages = {
            '/items': {
                'items': [1, 2],
                'numberReturned': 2,
                'links': [{'rel': 'next', 'href': '/items?p=2'}],
            },
            '/items?p=2': {
                'items': [3, 4],
                'numberReturned': 2,
                'links': [{'rel': 'next', 'href': '/items?p=3'}],
            },
            '/items?p=3': {'items': [5], 'numberReturned': 1, 'links': []},
        }

    def request(self, method: str, url: str, json: Any = None) -> _Resp:
        return _Resp(200, self.pages[url])


def test_drive_pagination_collects_all_items():
    items = drive_pagination(_FakeClient(), '/items', items_key='items', limit=2)
    assert items == [1, 2, 3, 4, 5]


def test_drive_pagination_post_carries_link_body():
    # POST-driven pagination: the `next` link's `body` member is sent on the next
    # request (per STAPI), and the method stays POST.
    calls: list[tuple[str, Any]] = []

    class _PostClient:
        # the next page is selected by the posted body, not the URL (which repeats)
        def request(self, method: str, url: str, json: Any = None) -> _Resp:
            calls.append((method, json))
            if json == {'token': 'p1'}:
                return _Resp(
                    200,
                    {
                        'items': [1, 2],
                        'links': [{'rel': 'next', 'href': '/search', 'body': {'token': 'p2'}}],
                    },
                )
            return _Resp(200, {'items': [3], 'links': []})

    items = drive_pagination(
        _PostClient(),
        '/search',
        items_key='items',
        method='POST',
        body={'token': 'p1'},
    )
    assert items == [1, 2, 3]
    assert calls[0] == ('POST', {'token': 'p1'})
    assert calls[1] == ('POST', {'token': 'p2'})  # body carried from the next link


def test_drive_pagination_forwards_request_kwargs():
    # an authenticated service passes headers (or any client option) through to
    # every request without wrapping the client
    seen_headers: list[Any] = []

    class _AuthClient(_FakeClient):
        def request(self, method: str, url: str, json: Any = None, **kwargs: Any) -> _Resp:
            seen_headers.append(kwargs.get('headers'))
            return super().request(method, url, json=json)

    items = drive_pagination(
        _AuthClient(),
        '/items',
        items_key='items',
        request_kwargs={'headers': {'authorization': 'Bearer x'}},
    )
    assert items == [1, 2, 3, 4, 5]
    # forwarded on every one of the three page requests
    assert seen_headers == [{'authorization': 'Bearer x'}] * 3


def test_drive_pagination_detects_loop():
    class _Looper:
        def request(self, method: str, url: str, json: Any = None) -> _Resp:
            return _Resp(200, {'items': [1], 'links': [{'rel': 'next', 'href': '/items'}]})

    with pytest.raises(AssertionError, match='loop'):
        drive_pagination(_Looper(), '/items', items_key='items')


def test_drive_pagination_flags_bad_count():
    class _BadCount:
        def request(self, method: str, url: str, json: Any = None) -> _Resp:
            return _Resp(200, {'items': [1, 2], 'numberReturned': 99, 'links': []})

    with pytest.raises(AssertionError, match='numberReturned'):
        drive_pagination(_BadCount(), '/items', items_key='items')


# --- integration: drive a real paginated app -------------------------------


def test_drive_pagination_against_real_app():
    from gazebo.collection import LinkedCollection
    from gazebo.ext.fastapi import Providers

    class Items(LinkedCollection[int]):
        pass

    router = GazeboRouter()

    @router.get('/items', response_model=Items)
    async def list_items(offset: int = 0):
        page = list(range(offset, min(offset + 2, 5)))
        nxt = str(offset + 2) if offset + 2 < 5 else None
        links = [Link.self_link(), *paginate(next_token=nxt, token_param='offset')]
        return Items(items=page, links=links)

    app = GazeboApp(Providers())
    app.include_router(router)

    with TestClient(app) as client:
        all_items = drive_pagination(client, '/items', items_key='items', limit=2)
    assert all_items == [0, 1, 2, 3, 4]


# --- the bundled fixtures --------------------------------------------------


def test_gazebo_overrides_fixture(gazebo_overrides):
    assert isinstance(gazebo_overrides, Overrides)


def test_link_context_isolation_fixture_resets(gazebo_link_context):
    # requesting the (opt-in) fixture guarantees no ambient context in this test
    assert link_context.get(None) is None
