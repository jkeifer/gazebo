from __future__ import annotations

import json

from pydantic import HttpUrl

from gazebo.context import use_context
from gazebo.ogc import Conformance, ConformanceDeclaration, LandingPage
from gazebo.pagination import paginate, with_query
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
