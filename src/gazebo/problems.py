"""RFC 7807 / 9457 problem details.

The model is core (pydantic only); rendering it into an HTTP response lives in the
framework glue. Raise :class:`ProblemException` from anywhere; the glue's handler
turns it into an ``application/problem+json`` response.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from pydantic import BaseModel, ConfigDict


def _reason(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return 'Error'


class ProblemDetail(BaseModel):
    """An RFC 7807/9457 problem object. Extensions allowed."""

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

    @property
    def status(self) -> int:
        return self.problem.status
