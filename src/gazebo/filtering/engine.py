"""The filtering engine seam: the Protocol gazebo's filtering plumbing talks to.

Core layer: stdlib + typing only — no web framework and no CQL2 implementation. gazebo
parses the *request* (the ``filter``/``sortby`` params) and validates property references
against a collection's queryables; an *engine* compiles and evaluates the filter
*expression* itself. This split keeps the core free of the CQL2 dependency: the bundled
engine (:mod:`gazebo.filtering.cql2`, behind the ``gazebo[cql2]`` extra) adapts cql2-rs,
and a user may supply their own by implementing :class:`FilterEngine`.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from gazebo.params import CRS84


class FilterLang(StrEnum):
    """The CQL2 encodings gazebo understands as ``filter-lang`` values."""

    CQL2_TEXT = 'cql2-text'
    CQL2_JSON = 'cql2-json'


class FilterError(Exception):
    """A filter failed to compile, validate, or referenced a non-queryable property.

    Framework-agnostic: the FastAPI glue maps it to a ``400 application/problem+json`` by
    re-raising it as a :class:`~gazebo.params.ParamError` for the ``filter`` parameter.
    Raising or catching it directly is appropriate anywhere a filter is compiled outside a
    request (business logic, tests).
    """


@runtime_checkable
class Compiled(Protocol):
    """An engine's parsed and validated filter expression.

    ``matches`` contract: returns ``True``/``False``; a referenced property that is absent
    or null evaluates to *unknown*, so the item does **not** match — SQL ``WHERE`` / CQL2
    three-valued logic. Property names may be dotted paths (``site.coord.lat``) that
    traverse nested mappings. ``properties`` returns every referenced property name (dotted
    where nested), which gazebo checks against the collection's queryables.
    """

    def properties(self) -> set[str]: ...

    def matches(self, item: Mapping[str, Any]) -> bool: ...


@runtime_checkable
class FilterEngine(Protocol):
    """Compiles a raw filter value into a :class:`Compiled` expression.

    Implementations must parse **and** validate (some CQL2 parsers accept malformed text
    leniently), raising :class:`FilterError` on any failure.
    """

    def compile(self, raw: str | Mapping[str, Any], lang: FilterLang) -> Compiled: ...


class Filter:
    """A compiled, validated filter ready to evaluate — what a route parameter receives.

    Holds the engine-native :class:`Compiled` expression (reachable as ``compiled`` for
    engine-specific features such as SQL translation) plus the resolved ``lang`` and
    ``crs``. :meth:`matches` is the in-memory convenience; it inherits the engine's
    null-handling contract, so it is safe to use directly in a list comprehension over
    sparse data.
    """

    def __init__(self, compiled: Compiled, lang: FilterLang, *, crs: str = CRS84) -> None:
        self.compiled = compiled
        self.lang = lang
        self.crs = crs

    def matches(self, item: Mapping[str, Any]) -> bool:
        return self.compiled.matches(item)

    def properties(self) -> set[str]:
        return self.compiled.properties()


__all__ = ['Compiled', 'Filter', 'FilterEngine', 'FilterError', 'FilterLang']
