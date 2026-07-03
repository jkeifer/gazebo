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

A field with no default is **required**: marked `[required]` in `--help` and enforced
at parse time. Because click reads the env var, it's satisfied by the flag *or* its
env var — not forced onto the command line — so the env/file workflow still works. (A
required secret, having no flag, is instead marked `(required)` in the Secrets section
and enforced by pydantic / `serve --check`.)

Secrets are never accepted on the command line: model them as `SecretStr`. They get
no value flag — but they're still listed in `--help` (their env var) as a documented
configuration surface, so they're discoverable without ever landing in shell history.
Supply them via the settings class's `secrets_dir` (Docker/k8s `/run/secrets`) or env.

The app target must be an importable `'module:attr'` string or a module-level
factory — uvicorn's `--workers`/`--reload` re-import it by name, so live app objects
and lambdas are rejected.

## Composing your own command

`serve_command` is the batteries-included assembly; its three pieces are exposed so a
custom CLI doesn't have to route through it: `settings_options(Settings)` returns the
documented `click` options for a settings group, `uvicorn_options()` returns copies of
uvicorn's own options (with `app`/`factory` always excluded — you supply those), and
`serve(app, ...)` is the launch action, delegating to uvicorn's own callback so its
value transforms still run.

Settings options are **self-propagating**: each carries a callback that writes its env
var when passed (and only when passed — env/default values are left for the app to
resolve). They're `expose_value=False`, so they act purely by side effect and never
appear in your callback's signature — which means the callback only ever sees uvicorn's
options and can forward them straight to `serve`:

```python
--8<-- "tests/examples/serving.py:compose"
```

Compose several groups by concatenating lists (`[*settings_options(A),
*settings_options(B)]`).

**Overriding an argument** falls out of composition:

- *Rename a settings flag* — `settings_options(Settings, rename={'greeting':
  '--message'})`. The env var is unchanged, so the renamed flag still propagates to the
  same field; handy for unifying names across a larger CLI. (A renamed `bool` becomes
  the usual `--x/--no-x` toggle automatically.)
- *Pin a uvicorn option* — `uvicorn_options(exclude={'workers'})` drops its flag; pass
  the constant to `serve(app, workers=4, ...)` (this is exactly what `serve_command`'s
  `**fixed` does).
- *Pin a setting* — `settings_options(Settings, exclude={'log_level'})` drops its flag;
  set its env var yourself, or let the app's own default stand.

## Validation and logging

`yourcli serve --check` validates settings (including required secrets) and that the
app imports, then exits — handy for CI and container preflight. `default_log_config()`
is pinned by default; pass `json_logs=True` for one-JSON-object-per-line output, or
`request_id=True` to thread gazebo's request id into every line.

## Reference

See [`gazebo.ext.cli`](reference.md#gazebo.ext.cli).
