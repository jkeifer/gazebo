from __future__ import annotations

import json

import pytest

from gazebo.context import use_context
from gazebo.link import Link
from gazebo.rels import MediaType, Rel


def test_static_href_round_trips():
    link = Link(href='https://example.com/a', rel=Rel.DESCRIBEDBY, title='t')
    data = json.loads(link.model_dump_json())
    assert data['href'] == 'https://example.com/a'
    assert data['rel'] == 'describedby'
    assert data['title'] == 't'


def test_serialization_schema_is_not_opaque():
    # the null-dropping model_serializer must not collapse the OpenAPI schema to an
    # opaque object; the real fields are reconstructed for serialization schemas.
    props = Link.model_json_schema(mode='serialization')['properties']
    assert {'href', 'rel', 'type', 'title'} <= set(props)


def test_none_fields_dropped_on_json():
    link = Link(href='https://example.com/a', rel='self')
    data = json.loads(link.model_dump_json())
    assert 'title' not in data
    assert 'method' not in data
    assert set(data) == {'href', 'rel'}


def test_callable_href_resolves_from_context(ctx):
    link = Link(href=lambda c: c.url, rel=Rel.SELF, type=MediaType.JSON)
    with use_context(ctx):
        data = json.loads(link.model_dump_json())
    assert data['href'] == ctx.url


def test_callable_href_without_context_raises():
    from pydantic_core import PydanticSerializationError

    link = Link(href=lambda c: c.url, rel='self')
    with pytest.raises(PydanticSerializationError):
        link.model_dump_json()


def test_self_and_root_factories(ctx):
    with use_context(ctx):
        self_data = json.loads(Link.self_link().model_dump_json())
        root_data = json.loads(Link.root_link(landing='landing').model_dump_json())
    assert self_data['href'] == ctx.url
    assert self_data['rel'] == 'self'
    assert root_data['href'] == 'https://api.example.com/landing'
    assert root_data['rel'] == 'root'


def test_context_via_serialization_context(ctx):
    link = Link(href=lambda c: c.url, rel='self')
    data = json.loads(link.model_dump_json(context={'request': ctx}))
    assert data['href'] == ctx.url


def test_to_route_with_path_resolves_and_does_not_leak(ctx):
    link = Link.to_route('plant', rel=Rel.ITEM, path={'id': 1})
    with use_context(ctx):
        data = json.loads(link.model_dump_json())
    assert data['href'] == 'https://api.example.com/plant/1'
    # ``path`` is a resolver input, not a stored link field.
    assert 'path' not in data


def test_to_route_with_path_is_idempotent_across_dumps(ctx):
    # Regression: the resolver must not mutate captured path params, or a
    # second serialization would drop them and produce a wrong URL.
    link = Link.to_route('plant', rel=Rel.ITEM, path={'id': 1})
    with use_context(ctx):
        first = json.loads(link.model_dump_json())
        second = json.loads(link.model_dump_json())
    assert first == second
    assert second['href'] == 'https://api.example.com/plant/1'
