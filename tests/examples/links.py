"""Runnable examples backing ``docs/core/links.md``.

Regions between ``--8<--`` markers are included verbatim into the page; the asserts
below them run in CI (``tests/test_examples.py``) so the snippets can't go stale.
"""

from __future__ import annotations

from collections.abc import Mapping


class _Ctx:
    """A stand-in RequestContext so examples resolve without a live server."""

    base_url = 'https://api.example.com/'
    url = 'https://api.example.com/plants?limit=10'
    query_params: Mapping[str, str] = {}

    def url_for(self, name: str, /, **path: object) -> str:
        suffix = '/' + '/'.join(str(v) for v in path.values()) if path else ''
        return f'https://api.example.com/{name}{suffix}'


def _dump(link: object) -> dict:
    return link.model_dump(mode='json', context={'request': _Ctx()})  # type: ignore[attr-defined]


# --8<-- [start:self_link]
from gazebo.link import Link
from gazebo.rels import Rel

# Built in business logic with no request in hand: the href is a callable, and is
# resolved against the active request when the model is serialized to JSON.
link = Link(href=lambda ctx: ctx.url_for('plant', id=1), rel=Rel.ITEM)
# --8<-- [end:self_link]

assert _dump(link) == {'href': 'https://api.example.com/plant/1', 'rel': 'item'}


# --8<-- [start:factories]
from gazebo.link import Link
from gazebo.rels import Rel

links = [
    Link.self_link(),  # the current request URL
    Link.root_link(),  # url_for('landing')
    Link.to_route('plant', rel=Rel.ITEM, path={'id': 1}),  # url_for('plant', id=1)
]
# --8<-- [end:factories]

dumped = [_dump(link) for link in links]
assert dumped[0]['href'] == 'https://api.example.com/plants?limit=10'
assert dumped[1]['href'] == 'https://api.example.com/landing'
assert dumped[2]['href'] == 'https://api.example.com/plant/1'
