# Fixtures

> Two opt-in pytest fixtures. They are deliberately not autouse — the plugin
> auto-registers wherever gazebo and pytest are installed, and an autouse fixture
> would intrude on every unrelated test downstream.

## `gazebo_link_context`

Link hrefs resolve through the `link_context` contextvar (set per request by the
framework glue). A test that publishes a context manually — or one whose app leaks
one — could let that bleed into the next test. Request `gazebo_link_context` to
isolate it: the contextvar is reset around the test, so each test starts clean and
nothing leaks out.

```python
def test_links(gazebo_link_context):
    ...  # link_context is guaranteed unset at the start, and restored after
```

It is intentionally **not** autouse. If you want every test in your suite isolated,
make it autouse in your own `conftest.py` — an explicit, local choice rather than
one this plugin imposes on you:

```python
import pytest

@pytest.fixture(autouse=True)
def _isolate_link_context(gazebo_link_context):
    pass
```

## `gazebo_overrides`

`gazebo_overrides` yields a fresh [`Overrides`](../di/qualifiers-overrides.md#overrides)
to populate and pass into your app factory — substituting a binding (a fake database,
fixed settings) by parameter, never by mutating a global:

```python
def test_with_fake_db(gazebo_overrides):
    gazebo_overrides.set(Database, FakeDatabase())
    app = create_app(overrides=gazebo_overrides)
    with TestClient(app) as client:
        ...
```

## Reference

See [`gazebo.testing`](../reference.md#gazebo.testing).
</content>
