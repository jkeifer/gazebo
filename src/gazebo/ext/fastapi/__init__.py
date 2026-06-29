"""FastAPI glue.

Turns a central :class:`~gazebo.di.Providers` registry into a working app:
``GazeboApp`` enters the app scope in its lifespan, opens a request scope per
request (publishing the link ``RequestContext``), and resolves bound types injected
into routes. Routes opt into bare-type injection by being declared on a
``GazeboRouter`` (or directly on the app): any parameter whose type carries a
``__provide__`` recipe, or is marked ``Annotated[T, Inject]``, is resolved from the
per-request DI scope.

This is the only part of gazebo that imports ``fastapi`` (the ``gazebo[fastapi]``
extra). It is organized as a package — one module per concern (injection, OGC param
adapters, CORS, response helpers, routers, app wiring) — but the public surface is
flat: import everything straight from ``gazebo.ext.fastapi``.
"""

from __future__ import annotations

from gazebo.caching import etag_for
from gazebo.di import Overrides, Providers
from gazebo.ext.fastapi.app import GazeboApp, forward_lifespans, upgrade
from gazebo.ext.fastapi.context import RequestContextAdapter
from gazebo.ext.fastapi.cors import Cors, CorsConfig
from gazebo.ext.fastapi.filtering import FilterParam, SortByParam
from gazebo.ext.fastapi.injection import Inject, inject_signature
from gazebo.ext.fastapi.params import BBoxParam, CrsParam, DatetimeParam, Negotiate
from gazebo.ext.fastapi.problems import (
    param_exception_handler,
    problem_exception_handler,
    validation_exception_handler,
)
from gazebo.ext.fastapi.responses import not_modified, set_cache_headers, set_link_header
from gazebo.ext.fastapi.routers import GazeboRouter, LinkedRouter, RootRouter

__all__ = [
    'BBoxParam',
    'Cors',
    'CorsConfig',
    'CrsParam',
    'DatetimeParam',
    'FilterParam',
    'GazeboApp',
    'GazeboRouter',
    'Inject',
    'LinkedRouter',
    'Negotiate',
    'Overrides',
    'Providers',
    'RequestContextAdapter',
    'RootRouter',
    'SortByParam',
    'etag_for',
    'forward_lifespans',
    'inject_signature',
    'not_modified',
    'param_exception_handler',
    'problem_exception_handler',
    'set_cache_headers',
    'set_link_header',
    'upgrade',
    'validation_exception_handler',
]
