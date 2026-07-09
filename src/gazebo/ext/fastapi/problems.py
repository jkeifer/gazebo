"""Exception handlers that render errors as ``application/problem+json``.

Maps gazebo's :class:`~gazebo.problems.ProblemException`, FastAPI's request-body
validation error (422), and gazebo's :class:`~gazebo.params.ParamError` (a 400 for a
malformed query parameter) into RFC 7807/9457 problem responses.

The validation/param problems default to a typeless ``about:blank``: the resolvable
``type`` URI for a malformed parameter is service-relative (it lives in the service's own
``/problems`` catalog), so gazebo has none to emit. A service that does own such a catalog
passes its :class:`~gazebo.problems.ProblemType` to :func:`install_problem_handlers` (or to
``GazeboApp``/``upgrade``) to give those framework errors a resolvable ``type`` too.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError

from gazebo.params import ParamError
from gazebo.problems import ProblemDetail, ProblemException, ProblemType
from gazebo.rels import MediaType


def _problem_response(problem: ProblemDetail) -> Response:
    return Response(
        content=problem.model_dump_json(),
        status_code=problem.status,
        media_type=MediaType.PROBLEM,
    )


def _problem_detail(
    problem_type: ProblemType | None,
    *,
    default_title: str,
    status: int,
    detail: str | None,
    **extensions: Any,
) -> ProblemDetail:
    """Build a :class:`ProblemDetail`, drawing ``type``/``title`` from a supplied type.

    ``status`` is authoritative (the handler computes it); a ``ProblemType`` only sources
    ``type``/``title``. With no type, the result is the typeless ``about:blank`` problem.
    """
    if problem_type is not None:
        return ProblemDetail(
            type=problem_type.type,
            title=problem_type.title,
            status=status,
            detail=detail,
            **extensions,
        )
    return ProblemDetail(title=default_title, status=status, detail=detail, **extensions)


def _validation_problem(
    exc: RequestValidationError,
    *,
    query_problem: ProblemType | None = None,
    body_problem: ProblemType | None = None,
) -> ProblemDetail:
    errors = exc.errors()
    # OGC treats a malformed *query* parameter as a client error (400), while a bad request
    # body (or path) is a 422. A folded gazebo query field (BBoxQuery/DatetimeQuery/...)
    # fails here with a `('query', <name>)` loc, so any query-scoped error tips the whole
    # response to 400 to preserve those OGC param semantics.
    query_errors = [err for err in errors if err.get('loc') and err['loc'][0] == 'query']
    status = 400 if query_errors else 422
    # The parameter name is the loc element right *after* the 'query' scope marker (`loc[1]`),
    # never the last: a list/repeatable param appends the element index (`('query', name, 0)`),
    # so `loc[-1]` would be that index, and a model/root `@model_validator` error has no field
    # at all (`loc == ('query',)`), so `loc[-1]` would be the scope marker itself. Skip the
    # fieldless case so a cross-field error doesn't fabricate a parameter name (it still tips
    # the status to 400 via `query_errors`). pydantic puts the alias at `loc[1]` when set.
    parameters = sorted({str(err['loc'][1]) for err in query_errors if len(err['loc']) > 1})
    # Cite the offending query parameter name(s) as an RFC 9457 extension member, consistent
    # with ParamError's problem: a single one as `parameter`, several as `parameters`.
    extensions: dict[str, Any] = {'errors': jsonable_encoder(errors)}
    if len(parameters) == 1:
        extensions['parameter'] = parameters[0]
    elif len(parameters) > 1:
        extensions['parameters'] = parameters
    problem_type, default_title = (
        (query_problem, 'Bad Request') if status == 400 else (body_problem, 'Unprocessable Entity')
    )
    return _problem_detail(
        problem_type,
        default_title=default_title,
        status=status,
        detail=f'request validation failed: {len(errors)} error(s)',
        **extensions,
    )


def _param_problem(
    exc: ParamError,
    *,
    query_problem: ProblemType | None = None,
) -> ProblemDetail:
    return _problem_detail(
        query_problem,
        default_title='Bad Request',
        status=400,
        detail=exc.detail,
        parameter=exc.parameter,  # RFC 9457 extension member
    )


async def problem_exception_handler(request: Request, exc: ProblemException) -> Response:
    return _problem_response(exc.problem)


def install_problem_handlers(
    app: FastAPI,
    *,
    query_problem: ProblemType | None = None,
    body_problem: ProblemType | None = None,
) -> None:
    """Register gazebo's problem exception handlers on ``app``.

    Handles :class:`~gazebo.problems.ProblemException`, FastAPI's
    :class:`RequestValidationError` (a 400 for a malformed query parameter, else 422), and
    gazebo's :class:`~gazebo.params.ParamError` (a 400).

    The validation/param problems are typeless (``about:blank``) unless a
    :class:`~gazebo.problems.ProblemType` is supplied to give those framework errors a
    resolvable ``type``/``title`` from the service's own catalog:

    - ``query_problem`` — the 400 case (malformed query parameter); must have ``status == 400``.
    - ``body_problem`` — the 422 case (bad request body/path); must have ``status == 422``.

    The handler stays authoritative for the response ``status``, the ``detail``, and the
    ``errors``/``parameter``/``parameters`` extension members; a supplied type only sets
    ``type``/``title``.
    """
    if query_problem is not None and query_problem.status != 400:
        raise ValueError(f'query_problem must have status 400, got {query_problem.status}')
    if body_problem is not None and body_problem.status != 422:
        raise ValueError(f'body_problem must have status 422, got {body_problem.status}')

    async def on_validation_error(request: Request, exc: RequestValidationError) -> Response:
        return _problem_response(
            _validation_problem(exc, query_problem=query_problem, body_problem=body_problem),
        )

    async def on_param_error(request: Request, exc: ParamError) -> Response:
        return _problem_response(_param_problem(exc, query_problem=query_problem))

    app.add_exception_handler(ProblemException, problem_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, on_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(ParamError, on_param_error)  # type: ignore[arg-type]


__all__ = [
    'install_problem_handlers',
    'problem_exception_handler',
]
