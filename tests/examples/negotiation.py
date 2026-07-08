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


class DocFormat(FormatEnum):  # your closed ?f= set — a real class, a usable field type
    json = 'json', 'application/json'  # each member is (?f= key, media type)
    html = 'html', 'text/html'


class DocQuery(BaseModel):  # fold ?f= into your own query model as a field
    f: DocFormat = DocFormat.json  # a real enum field: no type: ignore, native validation


folded_app = GazeboApp(Providers())


@folded_app.get('/report')
async def report(query: Annotated[DocQuery, Query()]) -> dict:
    # query.f is a validated ?f= key (no Accept at model-validation time). The member
    # carries its media type — `.representation` needs no external {key: rep} map; an
    # absent ?f= falls back to the field default (json).
    return {'format': query.f.representation.key}


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


# --8<-- [start:folded_accept]
from gazebo.ext.fastapi import FormatEnum, GazeboApp, Providers
from gazebo.negotiation import negotiate


class ReportFormat(FormatEnum):
    json = 'json', 'application/json'
    html = 'html', 'text/html'


class ReportQuery(BaseModel):
    # Optional field: an absent ?f= leaves it None, so the handler can negotiate on Accept.
    f: ReportFormat | None = None


neg_app = GazeboApp(Providers())


@neg_app.get('/report')
async def negotiated_report(query: Annotated[ReportQuery, Query()]) -> dict:
    # One line for the full OGC order: ?f= wins, then the request's Accept (read ambiently
    # from the context — no header wrangling), then the default. Member order is
    # server-preferred; an unsatisfiable Accept raises a 406, an unknown ?f= a 400.
    rep = negotiate(
        ReportFormat.representations(),
        f=query.f,
        default=ReportFormat.json.representation,
    )
    return {'format': rep.key}


# --8<-- [end:folded_accept]


with TestClient(neg_app) as client:
    # ?f= still wins over Accept
    got = client.get('/report?f=json', headers={'accept': 'text/html'})
    assert got.json() == {'format': 'json'}
    # an absent ?f= now negotiates on the Accept header
    got = client.get('/report', headers={'accept': 'text/html'})
    assert got.json() == {'format': 'html'}
    # an unknown ?f= key is still a 400 — the enum field validates it
    assert client.get('/report?f=xml').status_code == 400
    # an Accept listing nothing on offer, with ?f= absent, is a 406 problem
    assert client.get('/report', headers={'accept': 'application/xml'}).status_code == 406
