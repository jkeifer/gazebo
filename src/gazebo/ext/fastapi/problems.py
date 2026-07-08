"""Exception handlers that render errors as ``application/problem+json``.

Maps gazebo's :class:`~gazebo.problems.ProblemException`, FastAPI's request-body
validation error (422), and gazebo's :class:`~gazebo.params.ParamError` (a 400 for a
malformed query parameter) into RFC 7807/9457 problem responses.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError

from gazebo.params import ParamError
from gazebo.problems import ProblemDetail, ProblemException
from gazebo.rels import MediaType


def _problem_response(problem: ProblemDetail) -> Response:
    return Response(
        content=problem.model_dump_json(),
        status_code=problem.status,
        media_type=MediaType.PROBLEM,
    )


async def problem_exception_handler(request: Request, exc: ProblemException) -> Response:
    return _problem_response(exc.problem)


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> Response:
    errors = exc.errors()
    # OGC treats a malformed *query* parameter as a client error (400), while a bad request
    # body (or path) is a 422. A folded gazebo query field (BBoxQuery/DatetimeQuery/...)
    # fails here with a `('query', <name>)` loc, so any query-scoped error tips the whole
    # response to 400 to preserve those OGC param semantics.
    query_errors = [err for err in errors if err.get('loc') and err['loc'][0] == 'query']
    status = 400 if query_errors else 422
    parameters = sorted({str(err['loc'][-1]) for err in query_errors})
    # Cite the offending query parameter name(s) as an RFC 9457 extension member, consistent
    # with ParamError's problem: a single one as `parameter`, several as `parameters`.
    extensions: dict[str, Any] = {'errors': jsonable_encoder(errors)}
    if len(parameters) == 1:
        extensions['parameter'] = parameters[0]
    elif len(parameters) > 1:
        extensions['parameters'] = parameters
    problem = ProblemDetail(
        title='Bad Request' if status == 400 else 'Unprocessable Entity',
        status=status,
        detail=f'request validation failed: {len(errors)} error(s)',
        **extensions,
    )
    return _problem_response(problem)


async def param_exception_handler(request: Request, exc: ParamError) -> Response:
    problem = ProblemDetail(
        title='Bad Request',
        status=400,
        detail=exc.detail,
        parameter=exc.parameter,  # type: ignore[call-arg]  # RFC 9457 extension member
    )
    return _problem_response(problem)


__all__ = [
    'param_exception_handler',
    'problem_exception_handler',
    'validation_exception_handler',
]
