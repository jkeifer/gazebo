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
