"""Runnable examples backing ``docs/core/negotiation.md``."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query, Response
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from pydantic import Field


# --8<-- [start:negotiate]
from gazebo.negotiation import HTML, JSON, negotiate

# ?f= wins; otherwise the Accept header; otherwise the first offered representation.
assert negotiate([JSON, HTML], f='html') is HTML
assert negotiate([JSON, HTML], accept='text/html;q=0.9, application/json;q=0.1') is HTML
assert negotiate([JSON, HTML]) is JSON
# --8<-- [end:negotiate]


# --8<-- [start:route]
from gazebo import Link, OmitNullModel
from gazebo.ext.fastapi import GazeboApp, Negotiate, Providers
from gazebo.negotiation import HTML, JSON, Representation, alternate_links

app = GazeboApp(Providers())


class Doc(OmitNullModel):
    id: str
    links: list[Link] = Field(default_factory=list)


@app.get('/collections/{cid}', response_model=Doc)
async def collection(
    cid: str,
    rep: Annotated[Representation, Negotiate([JSON, HTML])],
) -> Doc | Response:
    # self for the current representation, alternate links to the others
    links = [Link.self_link(type=rep.media_type), *alternate_links(rep, [JSON, HTML])]
    if rep.key == 'html':
        return HTMLResponse(f'<h1>{cid}</h1>')
    return Doc(id=cid, links=links)


# --8<-- [end:route]


# --8<-- [start:folded]
from pydantic import BaseModel

from gazebo.ext.fastapi import FormatEnum, GazeboApp, Providers
from gazebo.negotiation import HTML, JSON, Representation

# Map each format key to the Representation you serve for it (the enum is keys only).
REPS = {rep.key: rep for rep in (JSON, HTML)}


class DocFormat(FormatEnum):  # your closed ?f= key set — a real class, a usable field type
    json = 'json'
    html = 'html'


class DocQuery(BaseModel):  # fold ?f= into your own query model as a field
    f: DocFormat = DocFormat.json  # a real enum field: no type: ignore, native validation


folded_app = GazeboApp(Providers())


@folded_app.get('/report')
async def report(query: Annotated[DocQuery, Query()]) -> dict:
    # query.f is a validated ?f= key (no Accept at model-validation time). Map it to the
    # Representation you serve; an absent ?f= falls back to the field default (json).
    rep: Representation = REPS[query.f]
    return {'format': rep.key}


# --8<-- [end:folded]


with TestClient(folded_app) as client:
    assert client.get('/report?f=html').json() == {'format': 'html'}
    assert client.get('/report').json() == {'format': 'json'}  # absent -> first offered
    assert client.get('/report?f=xml').status_code == 400  # unknown -> 400 problem


with TestClient(app) as client:
    body = client.get('/collections/beds?f=json').json()
    assert body['id'] == 'beds'
    alt = next(link for link in body['links'] if link['rel'] == 'alternate')
    assert alt['type'] == 'text/html'
    assert 'f=html' in alt['href']

    html = client.get('/collections/beds?f=html')
    assert html.headers['content-type'].startswith('text/html')

    unknown = client.get('/collections/beds?f=xml')
    assert unknown.status_code == 400
