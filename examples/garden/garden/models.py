"""Response/request models: a plant, the plant collection, and a create body."""

from __future__ import annotations

from pydantic import BaseModel, Field

from gazebo.collection import LinkedCollection
from gazebo.ext.fastapi import link_to
from gazebo.link import Link
from gazebo.rels import MediaType, Rel


class Plant(BaseModel):
    id: str
    name: str
    links: list[Link] = Field(default_factory=list)


class PlantCollection(LinkedCollection[Plant], items_alias='plants'):
    """Items serialize under ``plants``; adds ``numberReturned``/``numberMatched``."""


class PlantCreate(BaseModel):
    name: str


def to_plant(row: dict) -> Plant:
    """Build a Plant with deferred self/collection links (resolved at serialization)."""
    return Plant(
        id=row['id'],
        name=row['name'],
        links=[
            # link_to resolves the route by its endpoint name; path params supplied here.
            link_to('get_plant', rel=Rel.SELF, type=MediaType.JSON, path={'plant_id': row['id']}),
            Link.to_route('list_plants', rel=Rel.COLLECTION, type=MediaType.JSON),
            Link.root_link(),
        ],
    )
