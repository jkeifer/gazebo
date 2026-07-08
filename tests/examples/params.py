"""Runnable examples backing ``docs/core/params.md``."""

from __future__ import annotations

from datetime import datetime, UTC

from fastapi.testclient import TestClient


# --8<-- [start:parse]
from gazebo.params import BBox, DatetimeInterval

box = BBox.parse('-10,-20,10,20')  # minx,miny,maxx,maxy (6 values for 3D)

interval = DatetimeInterval.parse('2020-01-01T00:00:00Z/..')  # open-ended
assert interval.contains(datetime(2025, 1, 1, tzinfo=UTC))
# --8<-- [end:parse]

assert (box.minx, box.maxy) == (-10, 20)


# --8<-- [start:route]
from typing import Annotated

from gazebo.ext.fastapi import BBoxParam, CrsParam, DatetimeParam, GazeboApp, Providers
from gazebo.params import CRS84, BBox, DatetimeInterval

app = GazeboApp(Providers())


@app.get('/items')
async def items(
    bbox: Annotated[BBox | None, BBoxParam] = None,
    datetime: Annotated[DatetimeInterval | None, DatetimeParam] = None,
    crs: Annotated[str, CrsParam(allowed=[CRS84])] = CRS84,
) -> dict:
    # bbox/datetime are already parsed-and-validated (or None); crs is allow-listed.
    return {'count': 0, 'crs': crs}


# A malformed value never reaches the body: it becomes a 400 problem+json.
# --8<-- [end:route]


with TestClient(app) as client:
    ok = client.get('/items?bbox=-1,-2,3,4&datetime=2020-01-01T00:00:00Z')
    assert ok.status_code == 200

    bad = client.get('/items?bbox=1,2,3')  # wrong number of coordinates
    assert bad.status_code == 400
    assert bad.headers['content-type'] == 'application/problem+json'
    assert bad.json()['parameter'] == 'bbox'


# --8<-- [start:folded]
from typing import Annotated

from fastapi import Query
from pydantic import BaseModel

from gazebo.ext.fastapi import BBoxQuery, CrsEnum, DatetimeQuery, GazeboApp, Providers
from gazebo.params import CRS84, BBox, DatetimeInterval


class BedCrs(CrsEnum):  # your closed CRS set — a real class, so it's a usable field type
    CRS84 = CRS84
    WEB_MERCATOR = 'http://www.opengis.net/def/crs/EPSG/0/3857'


class BedQuery(BaseModel):  # your own query model — fold OGC fields in as fields
    bbox: BBoxQuery = None
    datetime: DatetimeQuery = None
    crs: BedCrs = BedCrs.CRS84  # a real enum field: no type: ignore, native validation
    limit: int = 10


folded_app = GazeboApp(Providers())


@folded_app.get('/beds')
async def beds(query: Annotated[BedQuery, Query()]) -> dict:
    # FastAPI explodes the model into individual, documented query params; each OGC
    # field arrives already parsed (bbox: BBox | None, datetime: DatetimeInterval | None).
    assert query.bbox is None or isinstance(query.bbox, BBox)
    return {'crs': query.crs, 'limit': query.limit}


# A malformed folded field is still a 400 problem+json — OGC's client-error semantics.
# --8<-- [end:folded]


with TestClient(folded_app) as client:
    ok = client.get('/beds?bbox=-1,-2,3,4&limit=5')
    assert ok.status_code == 200
    assert ok.json() == {'crs': CRS84, 'limit': 5}

    bad = client.get('/beds?bbox=1,2,3')
    assert bad.status_code == 400
    assert bad.json()['parameter'] == 'bbox'
