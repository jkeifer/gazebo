"""Exception handlers that render errors as ``application/problem+json``.

Maps gazebo's :class:`~gazebo.problems.ProblemException`, FastAPI's request-body
validation error (422), and gazebo's :class:`~gazebo.params.ParamError` (a 400 for a
malformed query parameter) into RFC 7807/9457 problem responses.
"""

from __future__ import annotations

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
    problem = ProblemDetail(
        title='Unprocessable Entity',
        status=422,
        detail=f'request validation failed: {len(exc.errors())} error(s)',
        errors=jsonable_encoder(exc.errors()),  # type: ignore[call-arg]
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
