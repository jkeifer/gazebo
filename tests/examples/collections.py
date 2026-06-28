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
