"""Routers and endpoints.

Demonstrates: bare-type injection (``catalog``/``user``/``tenant``), an external
type via ``Annotated[Session, Inject]`` alongside a real request body, deferred
self/root/collection links, pagination links, RFC 7807 problems, hierarchical
landing pages (``LinkedRouter``), and a conformance declaration.
"""

from __future__ import annotations

from typing import Annotated

from gazebo.ext.fastapi import GazeboRouter, Inject, LinkedRouter
from gazebo.link import Link
from gazebo.ogc import Conformance, ConformanceDeclaration
from gazebo.pagination import paginate
from gazebo.problems import ProblemException
from gazebo.rels import Rel

from .models import Plant, PlantCollection, PlantCreate, to_plant
from .resources import Catalog, Session, Tenant, User

CONFORMANCE = Conformance(
    Conformance.CORE,
    Conformance.LANDING_PAGE,
    Conformance.JSON,
    Conformance.OAS30,
)

plants_router = GazeboRouter(tags=['plants'])


@plants_router.get('', response_model=PlantCollection, name='list_plants')
async def list_plants(
    catalog: Catalog,
    user: User,
    tenant: Tenant,
    limit: int = 10,
    token: str | None = None,
) -> PlantCollection:
    offset = int(token) if token and token.isdigit() else 0
    rows = catalog.read.list(tenant.id, limit + 1, offset)
    has_more = len(rows) > limit
    rows = rows[:limit]
    links = [
        Link.self_link(),
        Link.root_link(),
        *paginate(
            next_token=str(offset + limit) if has_more else None,
            prev_token=str(max(0, offset - limit)) if offset else None,
            limit=limit,
        ),
    ]
    return PlantCollection(
        items=[to_plant(r) for r in rows],
        links=links,
        number_matched=catalog.read.count(tenant.id),
    )


@plants_router.get('/{plant_id}', response_model=Plant, name='get_plant')
async def get_plant(plant_id: str, catalog: Catalog, user: User, tenant: Tenant) -> Plant:
    row = catalog.read.get(tenant.id, plant_id)
    if row is None:
        raise ProblemException(
            404,
            detail=f'plant {plant_id!r} not found',
            instance=f'/plants/{plant_id}',
        )
    return to_plant(row)


@plants_router.post('', response_model=Plant, status_code=201, name='create_plant')
async def create_plant(
    body: PlantCreate,
    session: Annotated[Session, Inject],
    user: User,
    tenant: Tenant,
) -> Plant:
    return to_plant(session.create_plant(tenant.id, body.name))


root_router = LinkedRouter(
    title='Gazebo Gardens',
    description='A tiny OGC-style plant catalog built with gazebo.',
    landing_name='landing',
)


@root_router.get('/conformance', response_model=ConformanceDeclaration, name='conformance')
async def conformance() -> ConformanceDeclaration:
    return CONFORMANCE.declaration()


collections_router = LinkedRouter(
    rel=Rel.DATA,
    title='Collections',
    description='Collections offered by this service.',
    landing_name='collections',
)
collections_router.add_link(Rel.ITEMS, 'list_plants', title='Plants')

root_router.include_router(collections_router, prefix='/collections')
root_router.include_router(plants_router, prefix='/plants')
root_router.add_link(Rel.CONFORMANCE, 'conformance', title='Conformance')
root_router.add_link(Rel.ITEMS, 'list_plants', title='Plants')
