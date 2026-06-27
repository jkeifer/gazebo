# Problems

> RFC 7807 / 9457 problem responses: a typed `ProblemDetail` model and a
> `ProblemException` you can raise from anywhere.

## The model

`ProblemDetail` is a plain pydantic model with the RFC 7807 members: `type` (a URI
identifying the problem kind, default `about:blank`), `title`, `status`, `detail`,
and `instance`. It allows extras (`extra='allow'`), so you can attach extension
members — an `errors` list, a `trace_id` — and they serialize alongside the
standard ones. Being core, it's pydantic-only: constructing one never touches
HTTP; rendering it into a response is the framework glue's job.

## Raising a problem

Most of the time you don't build a `ProblemDetail` by hand — you raise a
`ProblemException(status, title=..., detail=..., **extensions)` and let the glue
render it. The name mirrors the familiar `HTTPException`: it's a
control-flow signal to emit a response, not a programming error. `title` defaults
to the HTTP status phrase, so `ProblemException(404)` is already a valid problem.
Raise it anywhere a request is being handled — a route, or a DI recipe (e.g. an
auth dependency that raises `401` when a token is missing).

```python
--8<-- "tests/examples/problems.py:raise"
```

## How it becomes a response

`ProblemDetail` is pure pydantic — turning it into an HTTP response is the
framework glue's job. Under [`GazeboApp` / `upgrade()`](../fastapi/app.md#problem-validation-responses)
two handlers are registered automatically: one renders any `ProblemException` you
raise as `application/problem+json`, and one maps FastAPI's request-validation
failures to a `422` problem so *bad input you never wrote a handler for* still
comes back as problem+json rather than FastAPI's default `{"detail": [...]}`
shape. That uniformity is a soft requirement for OGC conformance. See
[GazeboApp & upgrade](../fastapi/app.md#problem-validation-responses) for the
worked example. On non-ASGI frameworks, render `ProblemDetail` yourself.

## Reference

See [`gazebo.problems`](../reference.md#gazebo.problems).
