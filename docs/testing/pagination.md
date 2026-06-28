# Pagination driver

> `drive_pagination` follows `next` links to exhaustion, accumulates the items, and
> checks the envelope invariants on every page — so a pagination test is one call.

Verifying pagination by hand means a loop that follows `next`, accumulates items,
and re-checks the envelope each time — easy to write subtly wrong, and easy to hang
on a server whose `next` never terminates. `drive_pagination` is that loop, done
once and correctly. It is **deferred-link aware**: it reads gazebo's already-resolved
link hrefs straight from the response, the same ones a real client would follow.

```python
--8<-- "tests/examples/testing.py:pagination"
```

## What it checks

On *every* page (not just the final total) it asserts:

- the page contains the `items_key` you named;
- if the body has `numberReturned`, it equals the number of items on that page;
- if you pass `limit=`, no page exceeds it.

It also guards against a **runaway or looping `next`**: revisiting a request it has
already made raises immediately (rather than hanging), and `max_pages` is a hard
backstop. It returns the accumulated items, so the *content* assertions (ordering,
the full set) stay in your test rather than being baked into the driver.

## The client

The first argument is any object with a `request(method, url, json=...)` method — a
Starlette/httpx `TestClient`. For an authenticated service, pass `request_kwargs`;
it is forwarded to every request, so you hand the `TestClient` in directly rather
than wrapping it:

```python
drive_pagination(client, '/plants', items_key='plants',
                 request_kwargs={'headers': {'authorization': 'Bearer ...'}})
```

## GET and POST pagination

By default it issues GET requests and follows the `next` link's `href`. For
POST-driven pagination (as in STAPI), pass `method='POST'` and an initial `body`; a
`body` member on the `next` link is then carried into the following request. Because
POST pagination legitimately reposts the *same* URL with a different body, the loop
guard keys on the body too in that mode, so it won't mistake progress for a loop.

Other knobs: `rel=` follows a relation other than `next`; `max_pages=` caps the
walk.

## Reference

See [`gazebo.testing`](../reference.md#gazebo.testing).
</content>
