"""``Depends`` adapters for CQL2 ``filter`` and ``sortby`` query parameters.

Mirror the :mod:`gazebo.ext.fastapi.params` idiom: a ``XxxParam(config)`` factory returns
a ``Depends`` whose closure reads the query value and turns it into a typed, validated
:class:`~gazebo.filtering.Filter` / :class:`~gazebo.filtering.SortBy`, raising
:class:`~gazebo.params.ParamError` (-> 400 ``application/problem+json``) on bad input.

``FilterParam`` resolves the CQL2 engine once, at route-definition time: pass one
explicitly, or leave it unset to default to :class:`~gazebo.filtering.cql2.Cql2Engine`
(which needs the ``gazebo[cql2]`` extra). Property references are validated against the
collection's queryables; a filter naming a non-queryable field is a 400.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from fastapi import Depends, Query

from gazebo.filtering.engine import Filter, FilterEngine, FilterError, FilterLang
from gazebo.filtering.models import Queryables, Sortables, SortBy
from gazebo.filtering.queryables import validate_properties
from gazebo.params import CRS84, ParamError, validate_crs


def _default_engine() -> FilterEngine:
    try:
        from gazebo.filtering.cql2 import Cql2Engine
    except ImportError as exc:  # the extra is not installed and no engine was supplied
        raise RuntimeError(
            'FilterParam needs a CQL2 engine: install gazebo[cql2] or pass engine=...',
        ) from exc
    return Cql2Engine()


def _resolve_lang(value: str, explicit: str | None, *, lang_name: str) -> FilterLang:
    if explicit is not None:
        try:
            return FilterLang(explicit)
        except ValueError:
            raise ParamError(lang_name, f'unknown filter language {explicit!r}') from None
    # No explicit filter-lang: a value that starts with '{' is cql2-json, else cql2-text.
    return FilterLang.CQL2_JSON if value.lstrip().startswith('{') else FilterLang.CQL2_TEXT


def FilterParam(  # noqa: N802  (factory returning a Depends, named like one)
    queryables: Queryables,
    *,
    engine: FilterEngine | None = None,
    name: str = 'filter',
    lang_name: str = 'filter-lang',
    crs_name: str = 'filter-crs',
    crs_allowed: Sequence[str] = (CRS84,),
) -> Any:
    """Build a ``Depends`` resolving the OGC ``filter`` parameter into a :class:`Filter`.

    Drop it into a route as ``filter: Annotated[Filter | None, FilterParam(QUERYABLES)]``.
    An absent ``filter`` resolves to ``None``. ``filter-lang`` selects the encoding (else
    it is inferred); ``filter-crs`` is validated against ``crs_allowed``. A parse/validation
    failure, an unknown language, an unsupported CRS, or a reference to a non-queryable
    property each become a ``400`` problem.
    """
    resolved_engine = engine if engine is not None else _default_engine()
    allowed = tuple(crs_allowed)

    async def _filter_dep(
        value: str | None = Query(default=None, alias=name),
        lang_value: str | None = Query(default=None, alias=lang_name),
        crs_value: str | None = Query(default=None, alias=crs_name),
    ) -> Filter | None:
        if value is None:
            return None
        lang = _resolve_lang(value, lang_value, lang_name=lang_name)
        crs = validate_crs(crs_value, allowed, parameter=crs_name)
        try:
            compiled = resolved_engine.compile(value, lang)
            flt = Filter(compiled, lang, crs=crs)
            validate_properties(flt, queryables)
        except FilterError as exc:
            raise ParamError(name, str(exc)) from exc
        return flt

    return Depends(_filter_dep)


def SortByParam(  # noqa: N802  (factory returning a Depends, named like one)
    sortables: Sortables | Iterable[str],
    *,
    name: str = 'sortby',
) -> Any:
    """Build a ``Depends`` resolving the OGC/STAC ``sortby`` parameter into a :class:`SortBy`.

    ``sortables`` is the allow-list (a :class:`Sortables` resource or a set of field names);
    a term naming a field outside it — or malformed ``sortby`` syntax — is a ``400``
    problem. An absent ``sortby`` resolves to ``None``.
    """
    names = sortables.names if isinstance(sortables, Sortables) else set(sortables)

    async def _sortby_dep(
        value: str | None = Query(default=None, alias=name),
    ) -> SortBy | None:
        if value is None:
            return None
        return SortBy.parse(value, sortables=names)

    return Depends(_sortby_dep)


__all__ = ['FilterParam', 'SortByParam']
