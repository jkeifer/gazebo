"""Routers and endpoints.

Demonstrates: bare-type injection (``catalog``/``user``/``tenant``), an external
type via ``Annotated[Session, Inject]`` alongside a real request body, deferred
self/root/collection links, pagination links, RFC 7807 problems, hierarchical
landing pages (``LinkedRouter``), and a conformance declaration.
"""

from __future__ import annotations

from typing import Annotated

from gazebo.ext.fastapi import (
    BBoxParam,
    CrsParam,
    DatetimeParam,
    GazeboRouter,
    Inject,
    LinkedRouter,
)
from gazebo.link import Link
from gazebo.ogc import (
    Collection,
    Collections,
    Conformance,
    ConformanceDeclaration,
    Extent,
    SpatialExtent,
    TemporalExtent,
)
from gazebo.params import CRS84, BBox, DatetimeInterval
from gazebo.pagination import paginate
from gazebo.problems import ProblemException
from gazebo.rels import MediaType, Rel

from .models import Bed, BedCollection, Plant, PlantCollection, PlantCreate, to_bed, to_plant
from .resources import Catalog, Session, Tenant, User, all_beds, get_bed_row

CONFORMANCE = Conformance(
    Conformance.CORE,
    Conformance.LANDING_PAGE,
    Conformance.JSON,
    Conformance.OAS30,
    # The geospatial beds collection exercises OGC API Features core + GeoJSON.
    'http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core',
    'http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson',
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


# The OGC Features-style geospatial collection: garden beds as GeoJSON features,
# with bbox/datetime/crs filtering and Collection/Extent metadata.
collections_router = GazeboRouter(tags=['collections'])

BEDS_ALLOWED_CRS = [CRS84]


def build_beds_collection() -> Collection:
    """Collection metadata (id/title/extent/links) derived from the beds data."""
    rows = all_beds()
    # An empty store has no spatial/temporal extent to compute — omit it rather than
    # calling min()/max() over an empty sequence.
    extent: Extent | None = None
    if rows:
        lons = [r['lon'] for r in rows]
        lats = [r['lat'] for r in rows]
        first_planted = min(r['planted'] for r in rows)
        extent = Extent(
            spatial=SpatialExtent(bbox=[[min(lons), min(lats), max(lons), max(lats)]]),
            temporal=TemporalExtent(interval=[[first_planted, None]]),
        )
    return Collection(
        id='beds',
        title='Garden Beds',
        description='Planting beds as GeoJSON point features.',
        extent=extent,
        links=[
            Link.to_route('beds_collection', rel=Rel.SELF, type=MediaType.JSON),
            Link.to_route(
                'list_beds', rel=Rel.ITEMS, type=MediaType.GEOJSON, title='Bed features'
            ),
            Link.root_link(),
        ],
    )


@collections_router.get('', response_model=Collections, name='collections')
async def list_collections() -> Collections:
    return Collections(
        items=[build_beds_collection()],
        links=[Link.self_link(), Link.root_link()],
    )


@collections_router.get('/beds', response_model=Collection, name='beds_collection')
async def beds_collection() -> Collection:
    return build_beds_collection()


@collections_router.get('/beds/items', response_model=BedCollection, name='list_beds')
async def list_beds(
    bbox: Annotated[BBox | None, BBoxParam] = None,
    datetime: Annotated[DatetimeInterval | None, DatetimeParam] = None,
    crs: Annotated[str, CrsParam(allowed=BEDS_ALLOWED_CRS)] = CRS84,
) -> BedCollection:
    rows = all_beds()
    if bbox is not None:
        rows = [r for r in rows if bbox.contains(r['lon'], r['lat'])]
    if datetime is not None:
        rows = [r for r in rows if datetime.contains(r['planted'])]
    return BedCollection(
        items=[to_bed(r) for r in rows],
        links=[Link.self_link(type=MediaType.GEOJSON), Link.root_link()],
        number_matched=len(rows),
    )


@collections_router.get('/beds/items/{bed_id}', response_model=Bed, name='get_bed')
async def get_bed(bed_id: str) -> Bed:
    row = get_bed_row(bed_id)
    if row is None:
        raise ProblemException(
            404,
            detail=f'bed {bed_id!r} not found',
            instance=f'/collections/beds/items/{bed_id}',
        )
    return to_bed(row)


root_router.include_router(collections_router, prefix='/collections')
root_router.include_router(plants_router, prefix='/plants')
root_router.add_link(Rel.CONFORMANCE, 'conformance', title='Conformance')
root_router.add_link(Rel.ITEMS, 'list_plants', title='Plants')
root_router.add_link(Rel.DATA, 'collections', title='Collections')
