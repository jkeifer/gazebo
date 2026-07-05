from __future__ import annotations

import json

import pytest

from gazebo.context import use_context
from gazebo.link import Link
from gazebo.pagination import decode_cursor, encode_cursor, paginate, paginate_offset
from gazebo.params import ParamError
from gazebo.rels import MediaType, Rel


def _hrefs(links: list[Link], ctx) -> dict[str, str]:
    with use_context(ctx):
        return {link.rel: json.loads(link.model_dump_json())['href'] for link in links}


# --- paginate() additions --------------------------------------------------


def test_paginate_backwards_compatible_order():
    # the legacy call still yields exactly [next, prev] in that order
    rels = [link.rel for link in paginate(next_token='n', prev_token='p', limit=5)]
    assert rels == [Rel.NEXT, Rel.PREV]


def test_paginate_first_link_drops_token(ctx):
    ctx.url = 'https://api.example.com/things?limit=10&token=abc'
    links = paginate(next_token='n', limit=10, first=True)
    hrefs = _hrefs(links, ctx)
    assert Rel.FIRST in hrefs
    assert 'token=' not in hrefs[Rel.FIRST]
    assert 'limit=10' in hrefs[Rel.FIRST]


def test_paginate_next_preserves_existing_limit_when_absent(ctx):
    # no `limit=` passed to paginate(): the current URL's limit must survive
    ctx.url = 'https://api.example.com/things?limit=10&token=a'
    links = paginate(next_token='b')
    hrefs = _hrefs(links, ctx)
    assert 'limit=10' in hrefs[Rel.NEXT]
    assert 'token=b' in hrefs[Rel.NEXT]


def test_paginate_next_explicit_limit_overrides(ctx):
    ctx.url = 'https://api.example.com/things?limit=10&token=a'
    links = paginate(next_token='b', limit=25)
    hrefs = _hrefs(links, ctx)
    assert 'limit=25' in hrefs[Rel.NEXT]
    assert 'limit=10' not in hrefs[Rel.NEXT]


def test_paginate_first_link_no_limit_keeps_url_limit(ctx):
    ctx.url = 'https://api.example.com/things?limit=10&token=abc'
    links = paginate(next_token='n', first=True)
    hrefs = _hrefs(links, ctx)
    assert Rel.FIRST in hrefs
    assert 'token=' not in hrefs[Rel.FIRST]
    assert 'limit=10' in hrefs[Rel.FIRST]


def test_post_pagination_no_limit_omits_limit_key():
    body = {'filter': 'x'}
    links = paginate(next_token='n', method='POST', body=body)
    nxt = links[0]
    assert nxt.body == {'filter': 'x', 'token': 'n'}
    assert 'limit' not in nxt.body


def test_paginate_last_and_self(ctx):
    links = paginate(last_token='z', self_=True, limit=5)
    rels = [link.rel for link in links]
    assert Rel.LAST in rels
    assert Rel.SELF in rels
    hrefs = _hrefs(links, ctx)
    assert 'token=z' in hrefs[Rel.LAST]
    assert hrefs[Rel.SELF] == ctx.url


# --- paginate_offset() -----------------------------------------------------


def test_offset_first_page_no_prev(ctx):
    ctx.url = 'https://api.example.com/items?offset=0&limit=10'
    links = paginate_offset(offset=0, limit=10, total=25)
    rels = {link.rel for link in links}
    assert Rel.PREV not in rels
    assert Rel.FIRST not in rels  # already on the first page
    assert {Rel.SELF, Rel.NEXT, Rel.LAST} <= rels


def test_offset_middle_page_has_all(ctx):
    ctx.url = 'https://api.example.com/items?offset=10&limit=10'
    links = paginate_offset(offset=10, limit=10, total=25)
    hrefs = _hrefs(links, ctx)
    assert 'offset=0' in hrefs[Rel.FIRST]
    assert 'offset=0' in hrefs[Rel.PREV]
    assert 'offset=20' in hrefs[Rel.NEXT]
    assert 'offset=20' in hrefs[Rel.LAST]  # last page starts at 20 for total=25,limit=10


def test_offset_last_page_no_next(ctx):
    ctx.url = 'https://api.example.com/items?offset=20&limit=10'
    links = paginate_offset(offset=20, limit=10, total=25)
    rels = {link.rel for link in links}
    assert Rel.NEXT not in rels
    assert Rel.LAST not in rels  # already on the last page


def test_offset_unknown_total_always_offers_next(ctx):
    ctx.url = 'https://api.example.com/items?offset=30&limit=10'
    links = paginate_offset(offset=30, limit=10, total=None)
    rels = {link.rel for link in links}
    assert Rel.NEXT in rels
    assert Rel.LAST not in rels  # unknown total -> no last


def test_offset_rejects_bad_limit():
    with pytest.raises(ValueError, match='limit must be positive'):
        paginate_offset(offset=0, limit=0)


def test_offset_rejects_negative_offset():
    with pytest.raises(ValueError, match='offset must not be negative'):
        paginate_offset(offset=-1, limit=10)


# --- POST-body pagination + Link passthrough -------------------------------


def test_post_pagination_carries_token_in_body(ctx):
    ctx.url = 'https://api.example.com/search'
    body = {'filter': {'eo:cloud_cover': {'lt': 10}}}
    links = paginate(next_token='abc', limit=20, method='POST', body=body)
    nxt = links[0]
    assert nxt.method == 'POST'
    # the original search criteria are preserved (stateless server) and the token added
    assert nxt.body == {'filter': {'eo:cloud_cover': {'lt': 10}}, 'token': 'abc', 'limit': 20}
    # href stays the current URL — the token rides in the body, not the query
    assert _hrefs(links, ctx)[Rel.NEXT] == 'https://api.example.com/search'


def test_post_pagination_does_not_mutate_caller_body():
    body = {'filter': 'x'}
    paginate(next_token='n', method='POST', body=body)
    assert body == {'filter': 'x'}  # each link gets its own copy


def test_post_first_link_drops_token_from_body():
    links = paginate(first=True, method='POST', body={'q': 'roses', 'token': 'stale'})
    first = links[0]
    assert first.rel == Rel.FIRST
    assert first.body is not None
    assert 'token' not in first.body


def test_paginate_passthrough_link_fields():
    links = paginate(next_token='n', type=MediaType.GEOJSON, title='Next page', headers={'X': 'y'})
    nxt = links[0]
    assert nxt.type == MediaType.GEOJSON
    assert nxt.title == 'Next page'
    assert nxt.headers == {'X': 'y'}


def test_offset_post_pagination(ctx):
    ctx.url = 'https://api.example.com/search'
    links = paginate_offset(offset=10, limit=10, total=30, method='POST', body={'q': 'x'})
    nxt = next(link for link in links if link.rel == Rel.NEXT)
    assert nxt.method == 'POST'
    assert nxt.body == {'q': 'x', 'offset': 20, 'limit': 10}


# --- cursor helpers --------------------------------------------------------


def test_cursor_round_trips():
    payload = {'after_id': 42, 'sort': 'name'}
    token = encode_cursor(payload)
    assert decode_cursor(token) == payload


def test_cursor_is_url_safe_and_unpadded():
    token = encode_cursor({'k': 'v' * 20})
    assert '=' not in token
    assert '/' not in token
    assert '+' not in token


def test_decode_bad_cursor_is_param_error():
    with pytest.raises(ParamError) as exc:
        decode_cursor('!!!not-base64!!!', parameter='token')
    assert exc.value.parameter == 'token'


def test_decode_non_object_cursor_is_param_error():
    token = encode_cursor({'ok': 1})
    # a cursor that decodes to a JSON array, not an object
    import base64

    array = base64.urlsafe_b64encode(b'[1,2,3]').rstrip(b'=').decode()
    with pytest.raises(ParamError, match='must encode an object'):
        decode_cursor(array)
    assert decode_cursor(token) == {'ok': 1}
