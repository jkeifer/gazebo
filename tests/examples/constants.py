"""Runnable examples backing ``docs/core/constants.md``."""

from __future__ import annotations

# --8<-- [start:rels]
from gazebo.link import Link
from gazebo.rels import MediaType, Rel

# StrEnum members are plain strings, so they drop straight into a Link.
link = Link(
    href='https://api.example.com/items.geojson',
    rel=Rel.NEXT,
    type=MediaType.GEOJSON,
)
assert link.rel == 'next'
# --8<-- [end:rels]


# --8<-- [start:tags]
from gazebo.tags import Tag, tags_metadata

openapi_tags = tags_metadata(
    Tag(name='plants', description='Browse and create plants'),
)
# pass to FastAPI(openapi_tags=openapi_tags) to group endpoints in the docs UI
# --8<-- [end:tags]

assert openapi_tags == [{'name': 'plants', 'description': 'Browse and create plants'}]
