"""Runnable examples backing ``docs/core/ogc.md``."""

from __future__ import annotations

from collections.abc import Mapping


class _Ctx:
    base_url = 'https://api.example.com/'
    url = 'https://api.example.com/'
    query_params: Mapping[str, str] = {}

    def url_for(self, name: str, /, **path: object) -> str:
        return f'https://api.example.com/{name}'


# --8<-- [start:landing]
from gazebo.link import Link
from gazebo.ogc import LandingPage
from gazebo.rels import Rel

page = LandingPage(
    title='Gazebo Gardens',
    description='A plant catalog',
    links=[
        Link.self_link(),
        Link.to_route('conformance', rel=Rel.CONFORMANCE),
    ],
)
# --8<-- [end:landing]

dumped = page.model_dump(mode='json', context={'request': _Ctx()})
assert dumped['title'] == 'Gazebo Gardens'
assert {link['rel'] for link in dumped['links']} == {'self', 'conformance'}


# --8<-- [start:conformance]
from gazebo.ogc import Conformance

conformance = Conformance(Conformance.CORE, Conformance.JSON)
conformance.add(Conformance.LANDING_PAGE)
declaration = conformance.declaration()
# --8<-- [end:conformance]

assert Conformance.CORE in declaration.conforms_to
assert declaration.model_dump(by_alias=True)['conformsTo'] == conformance.uris
