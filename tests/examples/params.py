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
