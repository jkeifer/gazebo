# Testing

> `gazebo.testing` — a pytest plugin for asserting the OGC-ness of a service
> declaratively: problem/link assertions, a pagination driver, and fixtures.
> Requires the `gazebo[test]` extra.

## What the plugin provides

Testing an OGC-style service means checking the same shapes over and over: errors
are problem+json, envelopes carry the right links, pagination follows `next` to the
end without looping. `gazebo.testing` packages those checks so each test states the
*intent* instead of re-walking the JSON. It gives you three kinds of thing:

- **Assertions** — [`assert_problem`](assertions.md), [`assert_has_link`](assertions.md),
  and the non-asserting [`find_link`](assertions.md). They check both content-type
  *and* document shape, and return the matched value for further assertions.
- **A pagination driver** — [`drive_pagination`](pagination.md) follows `next` links
  to exhaustion, accumulates the items, asserts the envelope invariants on *every*
  page, and guards against a runaway/looping link. GET and POST.
- **Fixtures** — opt-in [`gazebo_link_context`](fixtures.md) (contextvar isolation)
  and [`gazebo_overrides`](fixtures.md) (a fresh `Overrides`).

Everything is a plain importable function plus opt-in fixtures — nothing is autouse,
nothing runs unless you ask for it.

## Opting in

The helpers would work as ordinary functions, but registering `gazebo.testing` as a
pytest plugin buys one thing you can't get otherwise: **pytest rewrites the `assert`
statements inside the helpers**. A failed `assert_has_link` or `assert_problem` then
shows pytest's full introspection — the actual links present, the actual status — not
just a hand-written message string.

It does **not** auto-register (an entry-point plugin would import gazebo, and impose
its fixtures, on every downstream pytest session). Opt in with one line in your
top-level `conftest.py`:

```python
pytest_plugins = ['gazebo.testing']
```

That enables the fixtures and the assertion rewriting. (Confirm with
`pytest --fixtures | grep gazebo`.) The assertion *functions* are importable and
usable without opting in — you just miss the rewritten failure output.

!!! warning "Don't run tests under `-O`"
    The helpers assert with bare `assert`, so running pytest under `python -O` /
    `PYTHONOPTIMIZE` strips them and they silently become no-ops. Inherent to any
    assertion helper — keep assertions enabled when running tests.

## In this section

- [Assertions](assertions.md) — `assert_problem`, `assert_has_link`, `find_link`.
- [Pagination driver](pagination.md) — `drive_pagination` and its invariants.
- [Fixtures](fixtures.md) — `gazebo_link_context`, `gazebo_overrides`.

The [garden example](../example.md) uses all of these in its own test suite.

## Reference

See [`gazebo.testing`](../reference.md#gazebo.testing).
</content>
