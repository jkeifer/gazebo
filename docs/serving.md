# Serving (CLI)

> A self-documenting `serve` command: run your app with uvicorn, and let `--help`
> show every setting and the env var that configures it.

Most projects hand-roll a CLI that calls `uvicorn.run(...)`, plus some way for
operators to discover how the app is configured. `serve_command` packages both: it
composes uvicorn's own options (so `--workers`, `--reload`, `--host`, `--env-file`
all work) and generates one documented option per settings field, so `--help`
*becomes* the configuration reference.

It requires the `gazebo[cli]` extra (`click`, `uvicorn`, `pydantic-settings`).

## Building a serve command

Point it at an importable app factory and your `pydantic-settings` class, then add
the result to your `click` group:

```python
--8<-- "tests/examples/serving.py:serve"
```

`yourcli serve --help` now lists `--app-greeting` — with its env var
(`APP_GREETING`), default, and description — alongside uvicorn's options.

## How settings reach the app

A settings flag's only job is to **set its env var**; the app (and every uvicorn
worker) reads configuration from the environment as usual, so nothing is serialized
across the worker boundary. Settings flags are prefixed by the class's `env_prefix`
(required), so they never collide with uvicorn's options and read as *app config*
vs *server config* in `--help`. For multiple groups, pass `settings=[A, B]`; each
needs a distinct `env_prefix`.

Secrets are never placed on the command line: model them as `SecretStr` (they get
no flag) and supply them via the settings class's `secrets_dir` (Docker/k8s
`/run/secrets`) and/or env.

The app target must be an importable `'module:attr'` string or a module-level
factory — uvicorn's `--workers`/`--reload` re-import it by name, so live app objects
and lambdas are rejected.

## Validation and logging

`yourcli serve --check` validates settings (including required secrets) and that the
app imports, then exits — handy for CI and container preflight. `default_log_config()`
is pinned by default; pass `json_logs=True` for one-JSON-object-per-line output, or
`request_id=True` to thread gazebo's request id into every line.

## Reference

See [`gazebo.ext.cli`](reference.md#gazebo.ext.cli).
