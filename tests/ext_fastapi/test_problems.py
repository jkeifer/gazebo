"""Problem responses: the 400/422 split, app-supplied resolvable types, cited parameters."""

from __future__ import annotations

from typing import Annotated

import pytest

from fastapi import Query
from fastapi.testclient import TestClient
from pydantic import BaseModel, model_validator

from gazebo.ext.fastapi import GazeboApp, Providers, install_problem_handlers
from gazebo.problems import ProblemType

from .support import make_app, params_app


def test_problem_response(client):
    r = client.get('/boom')
    assert r.status_code == 404
    assert r.headers['content-type'] == 'application/problem+json'
    assert r.json()['detail'] == 'nope'


def test_validation_error_is_problem(client):
    # a non-int `limit` fails FastAPI request validation; the glue maps that to a
    # problem+json response (not FastAPI's default {"detail": [...]} shape). A *query*
    # error is a 400 (OGC: malformed query param is a client error).
    r = client.get('/things?limit=nope', headers={'authorization': 'a'})
    assert r.status_code == 400
    assert r.headers['content-type'] == 'application/problem+json'
    body = r.json()
    assert body['status'] == 400
    assert body['title'] == 'Bad Request'
    # the field-level error list is carried as an RFC 9457 extension member
    assert body['errors']
    assert any(err['loc'] == ['query', 'limit'] for err in body['errors'])
    # the offending query parameter is cited, consistent with ParamError's problem
    assert body['parameter'] == 'limit'
    # unset optional members are omitted, not emitted as null (OGC omit-null)
    assert 'instance' not in body


class _IntBody(BaseModel):
    n: int


def test_body_validation_still_422_problem():
    app = GazeboApp(Providers())

    @app.post('/things')
    async def make(body: _IntBody) -> dict:
        return {'n': body.n}

    with TestClient(app) as client:
        r = client.post('/things', json={'n': 'nope'})
        # a bad request *body* stays a 422, now rendered as problem+json
        assert r.status_code == 422
        assert r.headers['content-type'] == 'application/problem+json'
        body = r.json()
        assert body['status'] == 422
        assert body['title'] == 'Unprocessable Entity'
        assert body['errors']
        # no query params were involved, so no parameter citation
        assert 'parameter' not in body


# --- app-supplied resolvable type for validation/param errors --------------


_QUERY_PROBLEM = ProblemType(
    type='/problems/malformed-query-parameter',
    title='Malformed query parameter',
    status=400,
)
_BODY_PROBLEM = ProblemType(
    type='/problems/unprocessable-body',
    title='Unprocessable body',
    status=422,
)


def test_query_problem_types_the_400(client):
    # With a query_problem supplied, a malformed query param 400 carries that resolvable
    # type/title but keeps its handler-computed status, detail, errors, and parameter.
    app = make_app()
    install_problem_handlers(app, query_problem=_QUERY_PROBLEM)
    with TestClient(app) as c:
        r = c.get('/things?limit=nope', headers={'authorization': 'a'})
        assert r.status_code == 400
        body = r.json()
        assert body['type'] == '/problems/malformed-query-parameter'
        assert body['title'] == 'Malformed query parameter'
        assert body['status'] == 400
        assert body['detail']
        assert body['errors']
        assert body['parameter'] == 'limit'


def test_query_problem_via_gazebo_app():
    # The same, threaded through GazeboApp's constructor.
    app = GazeboApp(Providers(), query_problem=_QUERY_PROBLEM, body_problem=_BODY_PROBLEM)

    @app.get('/things')
    async def things(limit: int = 10) -> dict:
        return {'limit': limit}

    with TestClient(app) as c:
        r = c.get('/things?limit=nope')
        assert r.json()['type'] == '/problems/malformed-query-parameter'


def test_body_problem_types_the_422():
    app = GazeboApp(Providers(), body_problem=_BODY_PROBLEM)

    @app.post('/things')
    async def make(body: _IntBody) -> dict:
        return {'n': body.n}

    with TestClient(app) as c:
        r = c.post('/things', json={'n': 'nope'})
        assert r.status_code == 422
        body = r.json()
        assert body['type'] == '/problems/unprocessable-body'
        assert body['title'] == 'Unprocessable body'
        assert body['status'] == 422
        assert body['errors']


def test_query_problem_types_the_param_error():
    # The ParamError path (a gazebo OGC param adapter) is typed by query_problem too.
    app = params_app()
    install_problem_handlers(app, query_problem=_QUERY_PROBLEM)
    with TestClient(app) as c:
        r = c.get('/search?bbox=1,2,3')
        assert r.status_code == 400
        body = r.json()
        assert body['type'] == '/problems/malformed-query-parameter'
        assert body['parameter'] == 'bbox'


def test_no_problem_types_stays_about_blank(client):
    # Back-compat: with nothing supplied, the malformed-param problem is typeless.
    r = client.get('/things?limit=nope', headers={'authorization': 'a'})
    assert r.json()['type'] == 'about:blank'


def test_wrong_status_problem_type_rejected():
    # A supplied type whose status contradicts the case it wires is rejected at install.
    with pytest.raises(ValueError, match='status 400'):
        GazeboApp(Providers(), query_problem=_BODY_PROBLEM)
    with pytest.raises(ValueError, match='status 422'):
        GazeboApp(Providers(), body_problem=_QUERY_PROBLEM)


# --- the cited `parameter` is derived from the right loc element ------------


class _LocQuery(BaseModel):
    # A folded query model whose validation errors span the three loc shapes: a scalar
    # field (`('query', 'zone')`), a list/repeatable param (`('query', 'sizes', <idx>)`),
    # and a model-level validator (`('query',)`).
    zone: int = 0
    sizes: list[int] = []

    @model_validator(mode='after')
    def _check(self) -> _LocQuery:
        if self.zone == 99:
            raise ValueError('zone 99 is reserved')
        return self


@pytest.fixture
def loc_client():
    app = GazeboApp(Providers())

    @app.get('/q')
    async def search(query: Annotated[_LocQuery, Query()]) -> dict:
        return {'zone': query.zone, 'sizes': query.sizes}

    with TestClient(app) as c:
        yield c


def test_scalar_field_error_cites_field_name(loc_client):
    r = loc_client.get('/q?zone=nope')
    assert r.status_code == 400
    body = r.json()
    assert any(err['loc'] == ['query', 'zone'] for err in body['errors'])
    assert body['parameter'] == 'zone'


def test_list_param_error_cites_name_not_index(loc_client):
    # A bad element in a repeatable param fails with `('query', 'sizes', <idx>)`; the cited
    # parameter must be the name `sizes`, not the list index (the last loc element).
    r = loc_client.get('/q?sizes=1&sizes=nope')
    assert r.status_code == 400
    body = r.json()
    # the failing error's loc really does end in an index, confirming the shape under test
    assert any(
        err['loc'][:2] == ['query', 'sizes'] and len(err['loc']) > 2 for err in body['errors']
    )
    assert body['parameter'] == 'sizes'


def test_model_validator_error_cites_no_parameter(loc_client):
    # A cross-field `@model_validator` error has loc `('query',)` — no single field. It must
    # stay a 400 (query-scoped) but fabricate no `parameter`/`parameters` member.
    r = loc_client.get('/q?zone=99')
    assert r.status_code == 400
    body = r.json()
    assert any(err['loc'] == ['query'] for err in body['errors'])
    assert 'parameter' not in body
    assert 'parameters' not in body
