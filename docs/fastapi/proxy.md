# Proxy, context & health

> Make generated URLs correct behind a load balancer, and surface readiness — the
> operational edges of a gazebo app.

## Proxy-aware URLs

Behind a TLS-terminating load balancer the app sees plain `http` and an internal
host, so generated URLs come out wrong. `ProxyHeadersMiddleware` reads
`X-Forwarded-Proto`, `-Host`, and `-Prefix` and applies them to the ASGI scope, so
`ctx.url`, `url_for`, and every deferred link come out with the right scheme,
host, and root path. It supersedes uvicorn's `--proxy-headers` (which doesn't set
the scheme) and is pure ASGI, so it works under any ASGI framework. `GazeboApp`
installs it for you.

## Trust policies

Forwarded headers are client-supplied and trivially spoofed, so they're applied
**only when the request is trusted** — and the default is to trust nothing. Pick a
policy and pass it as `GazeboApp(..., trust=...)`:

- `trust_all` / `trust_none` — the extremes;
- `TrustedClient(*hosts)` — trust an allowlist of immediate client hosts (loopback
  included by default);
- `SharedSecret(secret, header=...)` — trust requests carrying a matching secret
  header (proxy-chain auth);
- `all_of(...)` / `any_of(...)` — combine policies, e.g. require both a known host
  *and* the secret.

```python
--8<-- "tests/examples/proxy.py:trust"
```

## Request context middleware (no GazeboApp)

`GazeboApp` publishes the link [`RequestContext`](../core/context.md) for you via
its request scope. If you're running gazebo's models under a *different* ASGI
stack, `ContextMiddleware(app, factory)` does just that one job: it builds a
`RequestContext` from the ASGI scope (your `factory`) and binds it for the
request. This is the escape hatch for using deferred links without `GazeboApp`.

## Request id & logging

Pair a small middleware that calls `use_request_id(...)` with the
[`RequestIdFilter`](../core/context.md#request-id-logging-opt-in) on your log
handler, and every log line for a request is tagged with its id. It's opt-in —
gazebo doesn't impose a logging config:

```python
--8<-- "tests/examples/proxy.py:request_id"
```

## Health

`GazeboApp` mounts `GET /health` (rename via `health_path=`, or `None` to
disable). It probes each app-scoped resource exposing a
[`__health__()`](../di/scopes.md#health-checks) and returns a per-resource and
aggregate status — a readiness check assembled from the resources you already
built, with nothing extra to maintain.

## Reference

See [`gazebo.asgi`](../reference.md#gazebo.asgi) and
[`gazebo.context`](../reference.md#gazebo.context).
