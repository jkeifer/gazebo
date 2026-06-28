# Assertions

> Helpers that check OGC response shapes and return the matched value — so a test
> reads as intent, and a failure shows pytest's full introspection.

OGC conformance is mostly about *shapes*: an error must be problem+json (the
content-type **and** the body), an envelope must carry the right links. Asserting
that by hand is repetitive and the failure messages are poor. These helpers do it in
one call, and — when you've [opted in](index.md#opting-in) so pytest rewrites their
assertions — a failure reports exactly what was present.

```python
--8<-- "tests/examples/testing.py:assertions"
```

## `assert_problem`

`assert_problem(response, *, status=..., type=...)` asserts the response is an
RFC 7807/9457 problem: the `content-type` starts with `application/problem+json`
*and* the body has `title`/`status`. With `status=` it also checks both the HTTP
status and `problem.status`; with `type=` it checks the problem `type` URI. It
returns the parsed problem body so you can assert on extension members (e.g. the
`errors` list, or the `parameter` a bad query param reports). `response` is any
object with `status_code`, `headers`, and `json()` — a Starlette/httpx `TestClient`
response.

## `assert_has_link`

`assert_has_link(body, rel, *, type=..., href_suffix=...)` asserts that an envelope
(a mapping with a `links` array) — or a bare links list — carries a link with the
given `rel`, optionally checking its media `type` and that its `href` ends with a
suffix. It returns the matched link. The failure message lists the rels that *were*
present, which is usually enough to see what went wrong.

## `find_link`

`find_link(body, rel)` is the non-asserting lookup: it returns the first matching
link or `None`. Use it when absence is a valid outcome (e.g. asserting there is *no*
`next` link on the last page).

## Reference

See [`gazebo.testing`](../reference.md#gazebo.testing).
</content>
