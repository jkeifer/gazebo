"""Bare-type injection: signature rewriting, the route guard, and hint resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from fastapi.testclient import TestClient

from gazebo.ext.fastapi import GazeboApp, GazeboRouter, Providers

from .support import Ping

if TYPE_CHECKING:
    # A name visible to the type checkers but absent at runtime — exactly the shape
    # of an import guarded by ``if TYPE_CHECKING:`` that trips up ``get_type_hints``.
    TypeOnlyName = int


def test_bare_type_injection(client):
    r = client.get('/things?limit=2', headers={'authorization': 'alice'})
    assert r.status_code == 200
    body = r.json()
    assert body['things'] == [
        {'id': 0, 'owner': 'alice', 'dsn': 'real'},
        {'id': 1, 'owner': 'alice', 'dsn': 'real'},
    ]
    assert body['numberReturned'] == 2


def test_injected_params_absent_from_openapi(client):
    schema = client.get('/openapi.json').json()
    params = schema['paths']['/things']['get'].get('parameters', [])
    names = {p['name'] for p in params}
    assert 'limit' in names
    assert 'session' not in names
    assert 'user' not in names


def test_plain_router_injectable_fails_loudly():
    # Declaring an injectable-typed route on a plain APIRouter (instead of a
    # GazeboRouter) must fail loudly at startup, not silently treat it as a body.
    from fastapi import APIRouter

    plain = APIRouter()

    @plain.get('/oops')
    async def oops(ping: Ping):
        return {'ok': True}

    app = GazeboApp(Providers().request(Ping))
    app.include_router(plain)
    with pytest.raises(RuntimeError, match='look injectable'), TestClient(app):
        pass


def test_injection_survives_unresolvable_sibling_hint():
    # The headline of per-parameter resolution: a name importable only under
    # TYPE_CHECKING makes that one annotation unresolvable, but the injectable param
    # next to it must still be rewritten (it used to be silently skipped, then 500'd
    # as a request body). A warning still names the unresolvable parameter.
    import inspect

    from gazebo.ext.fastapi.injection import inject_signature

    async def handler(value: TypeOnlyName, ping: Ping):  # type: ignore[name-defined]
        return {'ok': ping.ok}

    with pytest.warns(UserWarning, match='could not resolve the type hint for .*value'):
        inject_signature(handler)

    params = inspect.signature(handler).parameters
    # `ping` was wired into a Depends despite `value` being unresolvable...
    assert type(params['ping'].default).__name__ == 'Depends'
    # ...while `value` is left untouched for FastAPI to handle.
    assert params['value'].default is inspect.Parameter.empty


def test_injection_warning_fires_once_on_reregistration():
    # include_router re-invokes inject_signature on the same endpoint; the warning
    # must fire at most once, not once per registration.
    import warnings

    from gazebo.ext.fastapi.injection import inject_signature

    async def handler(value: TypeOnlyName):  # type: ignore[name-defined]
        return {'ok': True}

    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter('always')
        inject_signature(handler)
        inject_signature(handler)
    matching = [r for r in records if 'could not resolve' in str(r.message)]
    assert len(matching) == 1


def test_unresolvable_hints_do_not_crash_startup():
    # The startup route guard must not let the unresolved hint escape as a cryptic
    # crash — the decoration-time warning already covers it.
    gr = GazeboRouter()

    with pytest.warns(UserWarning, match='could not resolve'):

        @gr.get('/typecheck-only')
        async def route(value: TypeOnlyName):  # type: ignore[name-defined]
            return {'ok': True}

    app = GazeboApp(Providers())
    app.include_router(gr)
    # Entering the context runs the lifespan, where _validate_routes inspects every
    # route; the unresolved hint must not crash startup.
    with TestClient(app):
        pass
