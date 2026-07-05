from __future__ import annotations

import json

from datetime import UTC, datetime

from pydantic import HttpUrl

from gazebo.collection import LinkedCollection
from gazebo.context import use_context, with_query
from gazebo.ogc import (
    Collection,
    Collections,
    Conformance,
    ConformanceDeclaration,
    Extent,
    LandingPage,
    SpatialExtent,
    TemporalExtent,
)
from gazebo.pagination import paginate
from gazebo.params import CRS84
from gazebo.problems import ProblemDetail, ProblemException
from gazebo.rels import Rel
from gazebo.tags import Tag, TagDocs, tags_metadata


def test_with_query_replaces_and_preserves(ctx):
    ctx.url = 'https://api.example.com/things?limit=10&token=abc&filter=x'
    out = with_query(ctx, token='next', limit=10)
    assert 'filter=x' in out
    assert 'token=next' in out
    assert 'token=abc' not in out


def test_with_query_removes_on_none(ctx):
    ctx.url = 'https://api.example.com/things?token=abc'
    out = with_query(ctx, token=None)
    assert 'token' not in out


def test_with_query_preserves_repeated_params(ctx):
    ctx.url = 'https://api.example.com/things?tag=a&tag=b&token=abc'
    out = with_query(ctx, token='next')
    assert 'tag=a' in out
    assert 'tag=b' in out
    assert 'token=next' in out


def test_with_query_override_collapses_repeated_param(ctx):
    ctx.url = 'https://api.example.com/things?token=a&token=b'
    out = with_query(ctx, token='next')
    assert out.count('token=') == 1
    assert 'token=next' in out


def test_with_query_none_removes_repeated_param(ctx):
    ctx.url = 'https://api.example.com/things?token=a&token=b&limit=5'
    out = with_query(ctx, token=None)
    assert 'token' not in out
    assert 'limit=5' in out


def test_paginate_next_prev(ctx):
    links = paginate(next_token='n', prev_token='p', limit=5)
    rels = [link.rel for link in links]
    assert rels == [Rel.NEXT, Rel.PREV]
    with use_context(ctx):
        nxt = json.loads(links[0].model_dump_json())['href']
    assert 'token=n' in nxt
    assert 'limit=5' in nxt


def test_paginate_only_next():
    assert len(paginate(next_token='n')) == 1
    assert paginate() == []


def test_problem_detail_defaults():
    p = ProblemDetail(title='Bad', status=400)
    assert p.type == 'about:blank'
    assert p.detail is None


def test_problem_exception_reason_phrase():
    exc = ProblemException(404)
    assert exc.problem.title == 'Not Found'
    assert exc.status == 404


def test_problem_exception_extensions():
    exc = ProblemException(422, detail='bad', errors=[{'loc': 'x'}])
    data = json.loads(exc.problem.model_dump_json())
    assert data['errors'] == [{'loc': 'x'}]


def test_conformance_registry_dedupes():
    c = Conformance(Conformance.CORE)
    c.add(Conformance.CORE, Conformance.JSON)
    assert c.uris == [Conformance.CORE, Conformance.JSON]


def test_conformance_declaration_alias():
    decl = Conformance(Conformance.CORE).declaration()
    assert isinstance(decl, ConformanceDeclaration)
    data = json.loads(decl.model_dump_json(by_alias=True))
    assert data == {'conformsTo': [Conformance.CORE]}


def test_landing_page(ctx):
    page = LandingPage(title='T', description='D')
    data = json.loads(page.model_dump_json())
    assert data['title'] == 'T'
    assert data['links'] == []


def test_collection_aliases_and_defaults():
    coll = Collection(id='plants', title='Plants')
    data = json.loads(coll.model_dump_json(by_alias=True))
    assert data['itemType'] == 'feature'  # serialization alias
    assert data['crs'] == [CRS84]  # defaults to CRS84
    assert data['id'] == 'plants'
    # an unset extent is omitted, not emitted as null (OGC optional member)
    assert 'extent' not in data


def test_extent_omits_unset_member():
    # only spatial is set: the absent temporal must be omitted, not null
    data = json.loads(Extent(spatial=SpatialExtent()).model_dump_json(by_alias=True))
    assert 'spatial' in data
    assert 'temporal' not in data


def test_extent_serializes_temporal_null_as_open():
    extent = Extent(
        spatial=SpatialExtent(bbox=[[-10, -10, 10, 10]]),
        temporal=TemporalExtent(
            interval=[[datetime(2020, 1, 1, tzinfo=UTC), None]],
        ),
    )
    data = json.loads(extent.model_dump_json(by_alias=True))
    assert data['spatial']['crs'] == CRS84
    assert data['temporal']['interval'][0][0] == '2020-01-01T00:00:00Z'
    assert data['temporal']['interval'][0][1] is None  # open end


def test_collections_envelope_alias():
    envelope = Collections(items=[Collection(id='a'), Collection(id='b')])
    data = json.loads(envelope.model_dump_json(by_alias=True))
    assert [c['id'] for c in data['collections']] == ['a', 'b']
    # the /collections envelope omits numberReturned (not defined by OGC there)
    assert 'numberReturned' not in data


def test_linked_collection_number_returned_toggle():
    class Plain(LinkedCollection[int]):
        pass

    class NoCount(LinkedCollection[int], number_returned=False):
        pass

    assert json.loads(Plain(items=[1, 2]).model_dump_json(by_alias=True))['numberReturned'] == 2
    assert 'numberReturned' not in json.loads(NoCount(items=[1, 2]).model_dump_json(by_alias=True))
    # the toggle also omits the count under the python field name (by_alias=False),
    # where the computed member serializes as `number_returned`, not `numberReturned`.
    assert 'number_returned' not in NoCount(items=[1, 2]).model_dump()
    assert 'numberReturned' not in NoCount(items=[1, 2]).model_dump(mode='json')
    assert Plain(items=[1, 2]).model_dump()['number_returned'] == 2
    # numberMatched still works independently
    matched = NoCount(items=[1], number_matched=5).model_dump_json(by_alias=True)
    assert json.loads(matched)['numberMatched'] == 5


def test_tags_metadata_json_native():
    meta = tags_metadata(
        Tag(
            name='root',
            description='r',
            external_docs=TagDocs(description='d', url=HttpUrl('https://x.example.com')),
        ),
    )
    assert meta[0]['externalDocs']['url'] == 'https://x.example.com/'
    assert isinstance(meta[0]['externalDocs']['url'], str)
