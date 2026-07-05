"""RFC 7807 / 9457 problem details.

The model is core (pydantic only); rendering it into an HTTP response lives in the
framework glue. Raise :class:`ProblemException` from anywhere; the glue's handler
turns it into an ``application/problem+json`` response.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from pydantic import ConfigDict

from gazebo.serialization import OmitNullModel


def _reason(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return 'Error'


class ProblemDetail(OmitNullModel):
    """An RFC 7807/9457 problem object. Extensions allowed.

    Absent optional members (``detail``, ``instance``, any ``None`` extension) are
    omitted on JSON serialization, per the OGC/RFC 7807 omit-null convention.
    """

    model_config = ConfigDict(extra='allow')

    type: str = 'about:blank'
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


class ProblemException(Exception):  # noqa: N818
    """Raise to produce a problem response. Carries a :class:`ProblemDetail`.

    Named like the familiar ``HTTPException`` (rather than ``...Error``): it's
    a control-flow signal to emit an HTTP response, not a programming error.
    """

    def __init__(
        self,
        status: int,
        title: str | None = None,
        *,
        detail: str | None = None,
        type: str = 'about:blank',
        instance: str | None = None,
        **extensions: Any,
    ) -> None:
        self.problem = ProblemDetail(
            type=type,
            title=title or _reason(status),
            status=status,
            detail=detail,
            instance=instance,
            **extensions,
        )
        super().__init__(self.problem.detail or self.problem.title)

    @classmethod
    def from_detail(cls, problem: ProblemDetail) -> ProblemException:
        """Wrap an already-built :class:`ProblemDetail` (no field re-assembly)."""
        exc = cls.__new__(cls)
        exc.problem = problem
        Exception.__init__(exc, problem.detail or problem.title)
        return exc

    @property
    def status(self) -> int:
        return self.problem.status


class ProblemType(OmitNullModel):
    """A documented, reusable kind of problem: a stable ``type`` URI plus defaults.

    Define these once and raise them by reference, so a service's error catalog lives
    in one place and its ``type`` URIs stop defaulting to ``about:blank`` and stay
    stable/linkable. The per-occurrence ``detail``/``instance`` (and any extension
    members) are supplied at the raise site::

        NOT_FOUND = ProblemType(
            type='https://errors.example/not-found', title='Resource not found', status=404,
        )
        raise NOT_FOUND.exception(detail='plant 5 not found', instance='/plants/5')
    """

    model_config = ConfigDict(frozen=True)

    type: str
    title: str
    status: int
    detail: str | None = None

    def problem(
        self,
        *,
        detail: str | None = None,
        instance: str | None = None,
        **extensions: Any,
    ) -> ProblemDetail:
        """Build a :class:`ProblemDetail` for one occurrence of this problem type."""
        return ProblemDetail(
            type=self.type,
            title=self.title,
            status=self.status,
            detail=detail if detail is not None else self.detail,
            instance=instance,
            **extensions,
        )

    def exception(
        self,
        *,
        detail: str | None = None,
        instance: str | None = None,
        **extensions: Any,
    ) -> ProblemException:
        """Build a :class:`ProblemException` to ``raise`` for this problem type."""
        return ProblemException.from_detail(
            self.problem(detail=detail, instance=instance, **extensions),
        )


class ProblemRegistry:
    """A catalog of :class:`ProblemType` instances, keyed by a short name.

    Register a service's problem kinds once, reference them by key, and serve the
    whole set from a catalog endpoint so the ``type`` URIs resolve to documentation.

    >>> problems = ProblemRegistry()
    >>> not_found = problems.define(
    ...     'not-found', type='https://errors.example/not-found',
    ...     title='Resource not found', status=404,
    ... )
    >>> raise problems['not-found'].exception(detail='plant 5 not found')
    """

    def __init__(self) -> None:
        self._types: dict[str, ProblemType] = {}

    def register(self, key: str, problem_type: ProblemType) -> ProblemType:
        """Add an already-built :class:`ProblemType` under ``key`` (returns it)."""
        if key in self._types:
            raise ValueError(f'problem type {key!r} is already registered')
        self._types[key] = problem_type
        return problem_type

    def define(
        self,
        key: str,
        *,
        type: str,
        title: str,
        status: int,
        detail: str | None = None,
    ) -> ProblemType:
        """Build and register a :class:`ProblemType` in one call (returns it)."""
        return self.register(
            key,
            ProblemType(type=type, title=title, status=status, detail=detail),
        )

    def __getitem__(self, key: str) -> ProblemType:
        return self._types[key]

    def get(self, key: str) -> ProblemType | None:
        return self._types.get(key)

    def catalog(self) -> dict[str, ProblemType]:
        """The full catalog (a copy), ready to serve from a ``/problems`` endpoint."""
        return dict(self._types)


__all__ = ['ProblemDetail', 'ProblemException', 'ProblemRegistry', 'ProblemType']
