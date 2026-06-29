"""The bundled CQL2 engine, adapting cql2-rs (the ``gazebo[cql2]`` extra).

This is the only module that imports ``cql2``; importing it requires the extra. It is
*not* imported by :mod:`gazebo.filtering` at package import, so the core stays free of the
dependency. gazebo ships exactly one engine but keeps :class:`~gazebo.filtering.engine`'s
``FilterEngine`` Protocol open, so a user who prefers another CQL2 implementation can
supply their own without gazebo bundling or testing a second one.

Two cql2-rs behaviors shape this adapter:

- Its text parser is **lenient** — malformed text can parse to a stray property reference
  rather than raising — so :meth:`Cql2Engine.compile` always calls ``validate()``.
- ``matches`` **raises** (rather than returning ``False``) when a referenced property is
  absent or null. To get SQL ``WHERE`` semantics without depending on that error message,
  :meth:`Cql2Compiled.matches` evaluates via ``reduce`` and treats only a literal ``True``
  as a match (an "unknown" comparison stays a partial expression — see the method).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import cql2

from gazebo.filtering.engine import Compiled, FilterError, FilterLang


def referenced_properties(node: Any) -> set[str]:
    """Collect every ``{'property': <name>}`` reference anywhere in a cql2-json node.

    cql2-json *is* a serialized AST; property references — including the dotted paths used
    for nested fields — appear uniformly as ``{'property': <name>}``, at any depth and
    inside every operator (comparison, logical, spatial, temporal, array, function).
    """
    found: set[str] = set()
    if isinstance(node, dict):
        name = node.get('property')
        if isinstance(name, str):
            found.add(name)
        for value in node.values():
            found |= referenced_properties(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            found |= referenced_properties(item)
    return found


class Cql2Compiled:
    """A validated :class:`cql2.Expr`, adapting it to the :class:`Compiled` Protocol."""

    def __init__(self, expr: cql2.Expr) -> None:
        self.native = expr
        """The underlying :class:`cql2.Expr` — for engine-specific features (``to_sql``)."""

    def properties(self) -> set[str]:
        return referenced_properties(self.native.to_json())

    def matches(self, item: Mapping[str, Any]) -> bool:
        # Reduce (rather than match()) so missing/null properties don't raise: an
        # expression that resolves collapses to a literal ``True``/``False``, while one
        # left "unknown" (an absent/null/type-mismatched property) stays a partial
        # expression. Only a literal ``True`` matches — SQL ``WHERE`` / CQL2 three-valued
        # logic — and this reads cql2-rs's documented API, not its error message.
        reduced: object = self.native.reduce(dict(item)).to_json()
        return reduced is True


class Cql2Engine:
    """A :class:`~gazebo.filtering.engine.FilterEngine` backed by cql2-rs."""

    def compile(self, raw: str | Mapping[str, Any], lang: FilterLang) -> Compiled:
        try:
            if isinstance(raw, str):
                expr = (
                    cql2.parse_json(raw) if lang is FilterLang.CQL2_JSON else cql2.parse_text(raw)
                )
            else:
                expr = cql2.Expr(dict(raw))
            expr.validate()  # REQUIRED: the text parser accepts malformed input leniently
        except Exception as exc:
            raise FilterError(f'invalid {lang.value} filter: {exc}') from exc
        return Cql2Compiled(expr)


__all__ = ['Cql2Compiled', 'Cql2Engine', 'referenced_properties']
