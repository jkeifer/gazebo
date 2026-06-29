"""Request-side CQL2 filtering: queryables, sortables, and the engine seam.

Core layer: pydantic + stdlib only. gazebo owns the OGC plumbing around filtering — the
``filter``/``filter-lang``/``sortby`` parsing, the queryables/sortables resources derived
from a pydantic model, and validating that a filter only references queryable fields —
while delegating CQL2 parsing/evaluation to a pluggable :class:`FilterEngine`. The bundled
engine (:class:`~gazebo.filtering.cql2.Cql2Engine`, adapting cql2-rs) lives in
:mod:`gazebo.filtering.cql2` behind the ``gazebo[cql2]`` extra and is **not** imported
here, so this package never pulls in the CQL2 dependency. The FastAPI ``FilterParam`` /
``SortByParam`` adapters live in :mod:`gazebo.ext.fastapi`.
"""

from __future__ import annotations

from gazebo.filtering.engine import (
    Compiled,
    Filter,
    FilterEngine,
    FilterError,
    FilterLang,
)
from gazebo.filtering.models import (
    CONF_CQL2_JSON,
    CONF_CQL2_TEXT,
    CONF_FEATURES_FILTER,
    CONF_FILTER,
    CONF_QUERYABLES,
    CONF_SORTBY,
    REL_QUERYABLES,
    REL_SORTABLES,
    Direction,
    Queryables,
    Sort,
    Sortables,
    SortBy,
    filter_conformance_classes,
)
from gazebo.filtering.queryables import (
    queryables_from_model,
    sortables_from_model,
    validate_properties,
)

__all__ = [
    'CONF_CQL2_JSON',
    'CONF_CQL2_TEXT',
    'CONF_FEATURES_FILTER',
    'CONF_FILTER',
    'CONF_QUERYABLES',
    'CONF_SORTBY',
    'REL_QUERYABLES',
    'REL_SORTABLES',
    'Compiled',
    'Direction',
    'Filter',
    'FilterEngine',
    'FilterError',
    'FilterLang',
    'Queryables',
    'Sort',
    'SortBy',
    'Sortables',
    'filter_conformance_classes',
    'queryables_from_model',
    'sortables_from_model',
    'validate_properties',
]
