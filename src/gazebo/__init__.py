"""gazebo — helpers for building OGC-style REST APIs."""

from __future__ import annotations

from gazebo.__version__ import __version__
from gazebo.collection import LinkedCollection
from gazebo.context import (
    RequestContext,
    link_context,
    resolve_context,
    use_context,
)
from gazebo.link import Link, Url, UrlResolver
from gazebo.rels import MediaType, Rel

__all__ = [
    'Link',
    'LinkedCollection',
    'MediaType',
    'Rel',
    'RequestContext',
    'Url',
    'UrlResolver',
    '__version__',
    'link_context',
    'resolve_context',
    'use_context',
]
