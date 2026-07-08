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
    # The clear message must surface rather than pydantic falling through a union
    # to an opaque "unknown type" error (regression: the whole point of the fix).
    with pytest.raises(PydanticSerializationError, match='no request context'):
        link.model_dump_json()


def test_callable_href_resolver_error_surfaces(ctx):
    from pydantic_core import PydanticSerializationError

    def boom(_c):
        raise RuntimeError('kaboom')

    link = Link(href=boom, rel='self')
    with use_context(ctx), pytest.raises(PydanticSerializationError, match='resolver raised'):
        link.model_dump_json()


def test_landing_page_deferred_link_error_surfaces():
    # Stand-in for the FastAPI response path (TypeAdapter.dump_json is what FastAPI
    # uses to serialize response models): a deferred link with no active context must
    # surface the clear message, not an opaque serialization error.
    from pydantic import TypeAdapter
    from pydantic_core import PydanticSerializationError

    from gazebo.ogc import LandingPage

    page = LandingPage(title='T', description='D', links=[Link.self_link()])
    with pytest.raises(PydanticSerializationError, match='no request context'):
        TypeAdapter(LandingPage).dump_json(page)


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


def test_to_route_plain_omits_templated(ctx):
    link = Link.to_route('plant', rel=Rel.ITEM, path={'id': 1})
    with use_context(ctx):
        data = json.loads(link.model_dump_json())
    assert 'templated' not in data


def test_to_route_path_template_leaves_var_and_sets_templated(ctx):
    link = Link.to_route('stats', rel=Rel.ITEM, template=['triplet'])
    with use_context(ctx):
        data = json.loads(link.model_dump_json())
    assert data['href'] == 'https://api.example.com/stats/{triplet}'
    assert data['templated'] is True


def test_to_route_query_template_appends_query_expression(ctx):
    link = Link.to_route('stats', rel=Rel.ITEM, query_template=['from', 'to'])
    with use_context(ctx):
        data = json.loads(link.model_dump_json())
    # url_for('stats') has no query, so a fresh {?...} expression is appended.
    assert data['href'] == 'https://api.example.com/stats{?from,to}'
    assert data['templated'] is True


def test_to_route_path_and_query_template_combined(ctx):
    link = Link.to_route(
        'stats',
        rel=Rel.ITEM,
        path={'kind': 'daily'},
        template=['triplet'],
        query_template=['from', 'to'],
    )
    with use_context(ctx):
        data = json.loads(link.model_dump_json())
    assert data['href'] == 'https://api.example.com/stats/daily/{triplet}{?from,to}'
    assert data['templated'] is True


def test_to_route_query_template_uses_ampersand_when_base_has_query(ctx):
    # When the resolved base already carries a query string, the form-query
    # continuation must use {&...} rather than {?...}. Resolve the route name to a
    # URL that already has a query (the FakeContext subclass supplies the rest of
    # the RequestContext surface).
    from tests.conftest import FakeContext

    class QueryBaseCtx(FakeContext):
        def url_for(self, name: str, /, **path: object) -> str:
            return 'https://api.example.com/stats?fixed=1'

    link = Link.to_route('stats', rel=Rel.ITEM, query_template=['from'])
    with use_context(QueryBaseCtx()):
        data = json.loads(link.model_dump_json())
    assert data['href'] == 'https://api.example.com/stats?fixed=1{&from}'
    assert data['templated'] is True


def test_templated_field_in_serialization_schema():
    props = Link.model_json_schema(mode='serialization')['properties']
    assert 'templated' in props
    assert props['templated'].get('type') == 'boolean' or 'anyOf' in props['templated']
