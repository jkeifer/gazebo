"""Pytest helpers for testing the OGC-ness of a gazebo service, declaratively.

A pytest plugin you **opt into** — add ``pytest_plugins = ['gazebo.testing']`` to your
top-level ``conftest.py`` (it does not auto-register, so it never imposes its fixtures
on an unrelated downstream suite). Opting in also enables pytest's assertion rewriting
for these helpers, so a failed ``assert_has_link`` / ``assert_problem`` gets full
introspection, not just the message. Importing it requires ``pytest`` (the
``gazebo[test]`` extra).

What you get:

- :func:`assert_has_link` / :func:`assert_problem` — envelope and problem+json
  assertions with descriptive failures.
- :func:`drive_pagination` — follow ``next`` links to exhaustion, checking the
  envelope invariants on every page, with a loop guard. Works with gazebo's
  resolved (deferred) links directly, and with GET or POST ``next`` links.
- opt-in fixtures: ``gazebo_link_context`` (isolate the link-context contextvar for
  a test) and ``gazebo_overrides`` (a fresh ``Overrides``).

Note: the assertion helpers use bare ``assert``, so a test run under ``python -O``
(``PYTHONOPTIMIZE``) strips them and they become no-ops — don't optimize your tests.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import pytest

from gazebo.context import link_context

__all__ = [
    'assert_has_link',
    'assert_problem',
    'drive_pagination',
    'find_link',
]


def find_link(body: Mapping[str, Any] | Sequence[Any], rel: str) -> dict[str, Any] | None:
    """Return the first link in ``body`` with relation ``rel``, or ``None``.

    ``body`` may be a serialized model (a mapping with a ``links`` array) or the
    links list itself.
    """
    links = (body.get('links') or []) if isinstance(body, Mapping) else body
    return next((link for link in links if link.get('rel') == rel), None)


def assert_has_link(
    body: Mapping[str, Any] | Sequence[Any],
    rel: str,
    *,
    type: str | None = None,
    href_suffix: str | None = None,
) -> dict[str, Any]:
    """Assert ``body`` carries a link with ``rel`` (and optionally ``type``/href).

    Returns the matched link so callers can make further assertions.
    """
    links = list((body.get('links') or []) if isinstance(body, Mapping) else body)
    link = find_link(links, rel)
    assert link is not None, (
        f'no link with rel={rel!r}; present rels: {[link_.get("rel") for link_ in links]}'
    )
    if type is not None:
        assert link.get('type') == type, (
            f'link rel={rel!r} has type {link.get("type")!r}, expected {type!r}'
        )
    if href_suffix is not None:
        href = link.get('href', '')
        assert href.endswith(href_suffix), (
            f'link rel={rel!r} href {href!r} does not end with {href_suffix!r}'
        )
    return link


def assert_problem(
    response: Any,
    *,
    status: int | None = None,
    type: str | None = None,
) -> dict[str, Any]:
    """Assert ``response`` is an RFC 7807/9457 problem (content-type *and* shape).

    ``response`` is any object with ``status_code``, ``headers``, and ``json()``
    (an httpx / Starlette ``TestClient`` response). Returns the parsed body.
    """
    content_type = response.headers.get('content-type', '')
    assert content_type.startswith('application/problem+json'), (
        f'content-type {content_type!r} is not application/problem+json'
    )
    body = response.json()
    # RFC 7807/9457 make `title` (and every other member) OPTIONAL; the content-type
    # above is the authoritative signal. We still require `status` as a light shape
    # check — gazebo always emits it and it's what most callers assert against.
    assert 'status' in body, f'not a problem document (missing "status"): {body!r}'
    if status is not None:
        assert response.status_code == status, f'HTTP status {response.status_code} != {status}'
        assert body['status'] == status, f'problem.status {body["status"]} != {status}'
    if type is not None:
        assert body.get('type') == type, f'problem.type {body.get("type")!r} != {type!r}'
    return body


def drive_pagination(
    client: Any,
    url: str,
    *,
    items_key: str,
    method: str = 'GET',
    body: Any = None,
    rel: str = 'next',
    limit: int | None = None,
    max_pages: int = 1000,
    request_kwargs: Mapping[str, Any] | None = None,
) -> list[Any]:
    """Follow ``rel`` (``next`` by default) links to exhaustion; return all items.

    Asserts the envelope invariants on *every* page — ``numberReturned`` matches the
    item count, and (if ``limit`` is given) no page exceeds it — and guards against a
    runaway/looping ``next`` link. For POST-driven pagination, a ``body`` member on
    the ``next`` link is carried into the next request (per STAPI).

    ``request_kwargs`` is forwarded to every ``client.request`` call, so an
    authenticated service can pass ``request_kwargs={'headers': {...}}`` without
    wrapping the client.
    """
    extra = dict(request_kwargs or {})
    seen: set[str] = set()
    collected: list[Any] = []
    pages = 0

    while url:
        # POST pagination legitimately reposts the same URL with a different body,
        # so the loop marker must include the body in that case.
        marker = f'{method} {url} {body!r}' if method == 'POST' else url
        assert marker not in seen, f'pagination loop: revisited {url}'
        seen.add(marker)
        pages += 1
        assert pages <= max_pages, f'pagination exceeded max_pages={max_pages} (runaway next?)'

        response = client.request(method, url, json=body, **extra)
        assert response.status_code == 200, response.text
        page = response.json()

        assert items_key in page, f'page has no {items_key!r} key: {sorted(page)}'
        items = page[items_key]
        if limit is not None:
            assert len(items) <= limit, f'page {pages} has {len(items)} items > limit {limit}'
        if 'numberReturned' in page:
            assert page['numberReturned'] == len(items), (
                f'page {pages}: numberReturned={page["numberReturned"]} but {len(items)} items'
            )
        collected.extend(items)

        nxt = find_link(page, rel)
        url = nxt['href'] if nxt else ''
        if nxt is not None and method == 'POST':
            body = nxt.get('body', body)

    return collected


# --- fixtures --------------------------------------------------------------


@pytest.fixture
def gazebo_link_context() -> Iterator[None]:
    """Isolate the link-context contextvar for a test, so a leak can't bleed.

    Opt in by requesting this fixture. It is deliberately **not** autouse: this
    plugin auto-registers wherever gazebo and pytest are installed, and forcing an
    autouse fixture onto every unrelated test in a downstream suite would be too
    intrusive. Make it autouse in your own ``conftest.py`` if you want that::

        @pytest.fixture(autouse=True)
        def _isolate(gazebo_link_context): ...
    """
    token = link_context.set(None)
    try:
        yield
    finally:
        link_context.reset(token)


@pytest.fixture
def gazebo_overrides() -> Any:
    """A fresh :class:`~gazebo.di.Overrides` to populate and pass to an app factory."""
    from gazebo.di import Overrides

    return Overrides()
