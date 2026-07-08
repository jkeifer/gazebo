"""Runnable examples backing ``docs/core/context.md``."""

from __future__ import annotations

# --8<-- [start:protocol]
from collections.abc import Mapping, Sequence

from gazebo.context import RequestContext


class MyContext:
    """Anything structurally matching RequestContext can drive link resolution."""

    @property
    def base_url(self) -> str:
        return 'https://api.example.com/'

    @property
    def url(self) -> str:
        return 'https://api.example.com/plants'

    @property
    def query_params(self) -> Mapping[str, str]:
        return {}

    def url_for(self, name: str, /, **path: object) -> str:
        return f'https://api.example.com/{name}'

    def url_for_template(
        self,
        name: str,
        path: Mapping[str, object],
        template: Sequence[str],
        /,
    ) -> str:
        vars = '/'.join(f'{{{v}}}' for v in template)
        return f'https://api.example.com/{name}/{vars}'


assert isinstance(MyContext(), RequestContext)  # runtime-checkable: structural match
# --8<-- [end:protocol]


# --8<-- [start:resolve]
from gazebo.context import use_context
from gazebo.link import Link

link = Link.self_link()

# Under the framework glue this happens for you. To resolve manually, either bind
# the context for a block...
with use_context(MyContext()):
    inside = link.model_dump_json()

# ...or pass it to model_dump as the serialization context (the test escape hatch).
outside = link.model_dump(mode='json', context={'request': MyContext()})
# --8<-- [end:resolve]

assert 'https://api.example.com/plants' in inside
assert outside['href'] == 'https://api.example.com/plants'
