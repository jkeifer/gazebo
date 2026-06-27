"""Runnable examples backing ``docs/getting-started.md``."""

from __future__ import annotations


# --8<-- [start:app]
from dataclasses import dataclass

from gazebo.collection import LinkedCollection
from gazebo.ext.fastapi import GazeboApp, GazeboRouter, Overrides, Providers
from gazebo.link import Link


@dataclass
class Settings:
    greeting: str = 'hello'

    @classmethod
    def __provide__(cls) -> Settings:
        return cls()


class Things(LinkedCollection[dict], items_alias='things'):
    pass


router = GazeboRouter()


@router.get('/things', response_model=Things)
async def list_things(settings: Settings, limit: int = 10) -> Things:
    items = [{'id': i, 'greeting': settings.greeting} for i in range(limit)]
    return Things(items=items, links=[Link.self_link(), Link.root_link()])


def create_app(overrides: Overrides | None = None) -> GazeboApp:
    providers = Providers().app(Settings)
    app = GazeboApp(providers, overrides=overrides)
    app.include_router(router)

    @app.get('/', name='landing')
    async def landing() -> dict:
        return {'service': 'things'}

    return app


app = create_app()
# --8<-- [end:app]


# --8<-- [start:test]
from fastapi.testclient import TestClient


def test_things() -> None:
    overrides = Overrides().set(Settings, Settings(greeting='hi'))
    with TestClient(create_app(overrides)) as client:
        body = client.get('/things?limit=2').json()
        assert body['numberReturned'] == 2
        assert body['things'][0]['greeting'] == 'hi'


# --8<-- [end:test]


test_things()
