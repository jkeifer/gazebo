"""Runnable examples backing ``docs/core/collections.md``."""

from __future__ import annotations

from collections.abc import Mapping


class _Ctx:
    base_url = 'https://api.example.com/'
    url = 'https://api.example.com/plants?limit=10'
    query_params: Mapping[str, str] = {}

    def url_for(self, name: str, /, **path: object) -> str:
        return f'https://api.example.com/{name}'


# --8<-- [start:collection]
from gazebo.collection import LinkedCollection
from gazebo.link import Link


class FeatureCollection(LinkedCollection[dict], items_alias='features'):
    pass


collection = FeatureCollection(
    items=[{'id': 1}, {'id': 2}],
    links=[Link.self_link()],
    number_matched=42,
)
# --8<-- [end:collection]


# --8<-- [start:pagination]
from gazebo.pagination import paginate

# next/prev links that, at serialization, rewrite only the pagination query params
# of the current request URL and preserve everything else.
collection.links.extend(paginate(next_token='abc', limit=10))
# --8<-- [end:pagination]

dumped = collection.model_dump(mode='json', by_alias=True, context={'request': _Ctx()})
assert dumped['numberReturned'] == 2
assert dumped['numberMatched'] == 42
assert [item['id'] for item in dumped['features']] == [1, 2]
assert any('token=abc' in link['href'] for link in dumped['links'])


# --8<-- [start:cursor]
from gazebo.pagination import decode_cursor, encode_cursor, paginate

# Wrap an arbitrary token payload in one opaque, URL-safe cursor instead of
# hand-rolling a token format. encode/decode round-trip; a malformed cursor raises a
# ParamError (which the FastAPI glue renders as a 400 problem).
cursor = encode_cursor({'offset': 20})
assert decode_cursor(cursor) == {'offset': 20}

# paginate() also emits first/last/self when asked (token_param renames the param).
cursor_links = paginate(next_token=cursor, first=True, self_=True, token_param='cursor', limit=10)
# --8<-- [end:cursor]

assert {link.rel for link in cursor_links} >= {'next', 'first', 'self'}


# --8<-- [start:offset]
from gazebo.pagination import paginate_offset

# Offset/limit pagination: say where you are (and the total, if known) and the
# self/first/prev/next/last links are derived from the page position.
offset_links = paginate_offset(offset=20, limit=10, total=55)
# --8<-- [end:offset]

assert {link.rel for link in offset_links} == {'self', 'first', 'prev', 'next', 'last'}


# --8<-- [start:post]
# POST pagination for a *stateless* server: the token rides in the request body (merged
# with the original criteria) rather than the query, so each `next` re-states the whole
# search. Any Link member (here `type`) can be set on every emitted link.
post_links = paginate(
    next_token='page-2',
    method='POST',
    body={'filter': {'collection': 'plants'}},
    type='application/json',
)
next_link = post_links[0]
# --8<-- [end:post]

assert next_link.method == 'POST'
assert next_link.body == {'filter': {'collection': 'plants'}, 'token': 'page-2'}


# --8<-- [start:omit_null]
from gazebo import OmitNullModel


class Style(OmitNullModel):
    name: str
    description: str | None = None


# an unset optional member is omitted on the wire, not emitted as null
basic = Style(name='basic').model_dump_json()
# --8<-- [end:omit_null]

import json

assert json.loads(basic) == {'name': 'basic'}  # no "description": null
