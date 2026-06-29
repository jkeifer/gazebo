"""Runnable examples backing ``docs/core/filtering.md``."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi.testclient import TestClient


# --8<-- [start:queryables]
from datetime import date

from pydantic import BaseModel

from gazebo.filtering import queryables_from_model, sortables_from_model


class Coord(BaseModel):
    lat: float
    lon: float


class BedProps(BaseModel):
    name: str
    sun: Literal['full', 'part', 'shade']
    planted: date
    location: Coord | None = None


# The queryables resource *is* a JSON Schema — derived from the model you already wrote.
# Nested models flatten to dotted accessors, so `location.lat` is filterable.
queryables = queryables_from_model(BedProps, id='beds')
assert queryables.names == {'name', 'sun', 'planted', 'location.lat', 'location.lon'}

# Sortables are the scalar subset (no arrays/geometry to order by).
sortables = sortables_from_model(BedProps)
# --8<-- [end:queryables]

assert 'location.lat' in sortables.names


# --8<-- [start:route]
from gazebo.ext.fastapi import FilterParam, GazeboApp, Providers, SortByParam
from gazebo.filtering import Filter, SortBy

BED_QUERYABLES = queryables_from_model(BedProps, id='beds')
BED_SORTABLES = sortables_from_model(BedProps)

app = GazeboApp(Providers())

_BEDS = [
    {'name': 'roses', 'sun': 'full', 'planted': '2021-04-01'},
    {'name': 'ferns', 'sun': 'shade', 'planted': '2020-06-01'},
]


@app.get('/items')
async def items(
    filter: Annotated[Filter | None, FilterParam(BED_QUERYABLES)] = None,
    sortby: Annotated[SortBy | None, SortByParam(BED_SORTABLES)] = None,
) -> dict:
    rows = [r for r in _BEDS if filter is None or filter.matches(r)]
    if sortby is not None:
        rows = sortby.apply(rows)
    return {'names': [r['name'] for r in rows]}


# `?filter=sun = 'full'` is parsed, validated against the queryables, and evaluated;
# a malformed filter or a non-queryable property becomes a 400 problem+json.
# --8<-- [end:route]


with TestClient(app) as client:
    assert client.get("/items?filter=sun = 'full'").json()['names'] == ['roses']
    assert client.get('/items?sortby=-planted').json()['names'] == ['roses', 'ferns']

    bad = client.get("/items?filter=color = 'red'")  # color is not queryable
    assert bad.status_code == 400
    assert bad.headers['content-type'] == 'application/problem+json'
    assert bad.json()['parameter'] == 'filter'
