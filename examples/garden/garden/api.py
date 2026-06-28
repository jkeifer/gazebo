"""Routers and endpoints.

Demonstrates: bare-type injection (``catalog``/``user``/``tenant``), an external
type via ``Annotated[Session, Inject]`` alongside a real request body, deferred
self/root/collection links, pagination links, RFC 7807 problems, hierarchical
landing pages (``LinkedRouter``), and a conformance declaration.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Query, Request, Response
from fastapi.responses import HTMLResponse

from gazebo.caching import etag_for
from gazebo.ext.fastapi import (
    BBoxParam,
    CrsParam,
    DatetimeParam,
    GazeboRouter,
    Inject,
    LinkedRouter,
    Negotiate,
    not_modified,
    set_cache_headers,
    set_link_header,
)
from gazebo.negotiation import HTML, JSON, Representation, alternate_links
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
from gazebo.params import CRS84, BBox, DatetimeInterval, ParamError
from gazebo.pagination import (
    decode_cursor,
    encode_cursor,
    last_page_offset,
    paginate,
    paginate_offset,
)
from gazebo.problems import ProblemException
from gazebo.rels import MediaType, Rel

from .models import (
    Bed,
    BedCollection,
    Plant,
    PlantCollection,
    PlantCreate,
    PlantSearch,
    to_bed,
    to_plant,
)
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


def _offset_from_cursor(cursor: str | None) -> int:
    """Decode the opaque page cursor into a validated, non-negative offset.

    The cursor is opaque but *not trusted* (see ``decode_cursor``): a crafted cursor
    could carry a missing, non-integer, or negative ``offset``, so validate it and
    surface a bad one as a ``400`` problem rather than letting it 500.
    """
    if not cursor:
        return 0
    offset = decode_cursor(cursor).get('offset', 0)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ParamError('cursor', 'cursor offset must be a non-negative integer')
    return offset


@plants_router.get('', response_model=PlantCollection, name='list_plants')
async def list_plants(
    catalog: Catalog,
    user: User,
    tenant: Tenant,
    response: Response,
    limit: int = Query(10, ge=1, le=10_000),
    cursor: str | None = None,
) -> PlantCollection:
    # Opaque cursor pagination: the page offset is wrapped in a base64-JSON cursor, so
    # clients treat it as a token. A malformed cursor decodes to a 400 problem.
    offset = _offset_from_cursor(cursor)
    total = catalog.read.count(tenant.id)
    rows = catalog.read.list(tenant.id, limit, offset)
    last_offset = last_page_offset(total, limit)
    links = [
        Link.root_link(),
        *paginate(
            next_token=encode_cursor({'offset': offset + limit})
            if offset + limit < total
            else None,
            prev_token=encode_cursor({'offset': max(0, offset - limit)}) if offset else None,
            first=offset > 0,
            last_token=encode_cursor({'offset': last_offset}) if last_offset > offset else None,
            self_=True,
            token_param='cursor',
            limit=limit,
        ),
    ]
    # Mirror the navigational links into an RFC 8288 Link: header so crawlers and
    # non-JSON clients can follow self/next/prev/... without parsing the body.
    set_link_header(response, links)
    return PlantCollection(items=[to_plant(r) for r in rows], links=links, number_matched=total)


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


@plants_router.post('/search', response_model=PlantCollection, name='search_plants')
async def search_plants(
    body: PlantSearch,
    catalog: Catalog,
    user: User,
    tenant: Tenant,
) -> PlantCollection:
    # A stateless POST search: the pagination links travel as method=POST with a body
    # that re-states the whole search (criteria + the advanced offset), since the
    # server keeps no per-query state. `base` is the current request body; paginate
    # overrides only the offset token per link.
    rows = catalog.read.list(tenant.id, 1000, 0)
    if body.name:
        rows = [r for r in rows if body.name.lower() in r['name'].lower()]
    total = len(rows)
    page = rows[body.offset : body.offset + body.limit]
    base: dict = {'offset': body.offset, 'limit': body.limit}
    if body.name:
        base['name'] = body.name
    links = [
        Link.root_link(),
        *paginate(
            next_token=str(body.offset + body.limit) if body.offset + body.limit < total else None,
            prev_token=str(max(0, body.offset - body.limit)) if body.offset else None,
            limit=body.limit,
            first=body.offset > 0,
            self_=True,
            method='POST',
            body=base,
            token_param='offset',
        ),
    ]
    return PlantCollection(items=[to_plant(r) for r in page], links=links, number_matched=total)


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
async def list_collections(response: Response) -> Collections:
    links = [Link.self_link(), Link.root_link()]
    set_link_header(response, links)
    return Collections(items=[build_beds_collection()], links=links)


@collections_router.get('/beds', response_model=Collection, name='beds_collection')
async def beds_collection(
    rep: Annotated[Representation, Negotiate([JSON, HTML])],
) -> Collection | Response:
    # Content negotiation: ?f=json|html (then the Accept header) picks the
    # representation; gazebo adds the `alternate` link to the other one. HTML rendering
    # is the app's job — gazebo ships no templating opinion.
    coll = build_beds_collection()
    coll.links.extend(alternate_links(rep, [JSON, HTML]))
    if rep.key == 'html':
        return HTMLResponse(f'<h1>{coll.title}</h1>\n<p>{coll.description}</p>')
    return coll


@collections_router.get('/beds/items', response_model=BedCollection, name='list_beds')
async def list_beds(
    response: Response,
    bbox: Annotated[BBox | None, BBoxParam] = None,
    datetime: Annotated[DatetimeInterval | None, DatetimeParam] = None,
    crs: Annotated[str, CrsParam(allowed=BEDS_ALLOWED_CRS)] = CRS84,
    limit: int = Query(10, ge=1, le=10_000),
    offset: int = Query(0, ge=0),
) -> BedCollection:
    rows = all_beds()
    if bbox is not None:
        rows = [r for r in rows if bbox.contains(r['lon'], r['lat'])]
    if datetime is not None:
        rows = [r for r in rows if datetime.contains(r['planted'])]
    total = len(rows)
    page = rows[offset : offset + limit]
    # self is the geo+json representation; paginate_offset derives first/prev/next/last.
    links = [
        Link.self_link(type=MediaType.GEOJSON),
        Link.root_link(),
        *paginate_offset(offset=offset, limit=limit, total=total, self_=False),
    ]
    set_link_header(response, links)
    return BedCollection(items=[to_bed(r) for r in page], links=links, number_matched=total)


@collections_router.get('/beds/items/{bed_id}', response_model=Bed, name='get_bed')
async def get_bed(bed_id: str, request: Request, response: Response) -> Bed | Response:
    row = get_bed_row(bed_id)
    if row is None:
        raise ProblemException(
            404,
            detail=f'bed {bed_id!r} not found',
            instance=f'/collections/beds/items/{bed_id}',
        )
    # Conditional GET: a weak ETag over the row data lets a client revalidate cheaply
    # (If-None-Match -> 304) without us re-sending the feature.
    etag = etag_for(row)
    if (cached := not_modified(request, etag=etag, cache_control='max-age=300')) is not None:
        return cached
    set_cache_headers(response, etag=etag, cache_control='max-age=300')
    return to_bed(row)


root_router.include_router(collections_router, prefix='/collections')
root_router.include_router(plants_router, prefix='/plants')
root_router.add_link(Rel.CONFORMANCE, 'conformance', title='Conformance')
root_router.add_link(Rel.ITEMS, 'list_plants', title='Plants')
root_router.add_link(Rel.DATA, 'collections', title='Collections')
