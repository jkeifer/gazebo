"""gazebo.di — a small, framework-agnostic, type-driven injection container.

Extraction-ready: depends only on the standard library, never on gazebo's OGC code
or any web framework.
"""

from __future__ import annotations

from gazebo.di.container import (
    CircularDependencyError,
    Container,
    DIError,
    ScopeMismatchError,
    ScopeState,
    UnresolvedDependencyError,
)
from gazebo.di.providers import (
    Binding,
    HasProvide,
    Key,
    Overrides,
    Providers,
    Qualify,
    Recipe,
    parse_annotation,
    resolve_annotation,
)

__all__ = [
    'Binding',
    'CircularDependencyError',
    'Container',
    'DIError',
    'HasProvide',
    'Key',
    'Overrides',
    'Providers',
    'Qualify',
    'Recipe',
    'ScopeMismatchError',
    'ScopeState',
    'UnresolvedDependencyError',
    'parse_annotation',
    'resolve_annotation',
]
