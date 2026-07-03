# Serving (CLI)

> A self-documenting `serve` command: `--help` is your app's configuration reference;
> every uvicorn option is still accepted and forwarded — `--help-server` lists them.

Most projects hand-roll a CLI that calls `uvicorn.run(...)`, plus some way for operators
to discover how the app is configured. `serve_command` packages both, and splits the help
cleanly: `serve --help` documents *your app's* settings (one option per field, with its
env var, default, and description — the configuration reference), while every uvicorn flag
(`--workers`, `--reload`, `--host`, `--env-file`, ...) is still accepted and **forwarded
verbatim to uvicorn**. Run `serve --help-server` to see uvicorn's own options.

Under the hood this treats uvicorn as a **CLI, not a library**: `serve` forwards
documented argv to uvicorn's console entry point, so uvicorn does its own parsing,
defaults, `UVICORN_*` env vars, and value transforms — the only coupling is uvicorn's
documented command-line interface.

`serve_command` lives in [`gazebo.ext.uvicorn`](reference.md#gazebo.ext.uvicorn); the
server-agnostic building blocks are in [`gazebo.ext.cli`](reference.md#gazebo.ext.cli).
`gazebo.ext.cli` requires the `gazebo[cli]` extra (`click`, `pydantic-settings`);
`gazebo.ext.uvicorn` requires the `gazebo[uvicorn]` extra (`gazebo[cli]` plus `uvicorn`).

## Building a serve command

Point it at an importable app factory and your `pydantic-settings` class, then add the
result to your `click` group:

```python
--8<-- "tests/examples/serving.py:serve"
```

`yourcli serve --help` now lists `--app-greeting` — with its env var (`APP_GREETING`),
default, and description — as your app's configuration reference. `yourcli serve
--workers 4 --reload` still works: those flags fall through to uvicorn.

## How settings reach the app

A settings flag's only job is to **set its env var**; the app (and every uvicorn worker)
reads configuration from the environment as usual, so nothing is serialized across the
worker boundary. Settings flags are prefixed by the class's `env_prefix` (required), so
they never collide with uvicorn's options and read as *app config* vs *server config*. For
multiple groups, pass `settings=[A, B]`; each needs a distinct `env_prefix`.

A field with no default is **required**: marked `[required]` in `--help` and enforced at
parse time. Because click reads the env var, it's satisfied by the flag *or* its env var —
not forced onto the command line — so the env/file workflow still works. (A required
secret, having no flag, is instead marked `(required)` in the Secrets section and enforced
by pydantic / `serve --check`.)

Secrets are never accepted on the command line: model them as `SecretStr`. They get no
value flag — but they're still listed in `--help` (their env var) as a documented
configuration surface, so they're discoverable without ever landing in shell history.
Supply them via the settings class's `secrets_dir` (Docker/k8s `/run/secrets`) or env.

The app target must be an importable `'module:attr'` string or a module-level factory —
uvicorn's `--workers`/`--reload` re-import it by name, so live app objects and lambdas are
rejected.

## Composing your own command

`gazebo.ext.cli` imports no server, so its pieces compose atop **any** server (granian,
hypercorn, ...), not just uvicorn: `settings_options(Settings)` returns the documented
`click` options for a settings group, and `secrets_epilog(Settings)` renders the `--help`
section for secret fields. When you *do* target uvicorn,
[`serve(app, *uvicorn_args, ...)`](reference.md#gazebo.ext.uvicorn.serve) is the launch
action — it forwards uvicorn's documented CLI argv.

Settings options are **self-propagating**: each carries a callback that writes its env var
when passed (and only when passed — env/default values are left for the app to resolve).
They're `expose_value=False`, so they act purely by side effect and never appear in your
callback's signature. With `ignore_unknown_options` / `allow_extra_args`, every uvicorn
flag falls through to `ctx.args`, which you forward straight to `serve`:

```python
--8<-- "tests/examples/serving.py:compose"
```

Compose several groups by concatenating lists (`[*settings_options(A),
*settings_options(B)]`).

**Overriding an argument** falls out of composition:

- *Rename a settings flag* — `settings_options(Settings, rename={'greeting':
  '--message'})`. The env var is unchanged, so the renamed flag still propagates to the
  same field; handy for unifying names across a larger CLI. (A renamed `bool` becomes the
  usual `--x/--no-x` toggle automatically.)
- *Pin a setting* — `settings_options(Settings, exclude={'log_level'})` drops its flag;
  set its env var yourself, or let the app's own default stand.
- *Author server defaults* — pass `uvicorn_args=('--workers', '4')` to `serve_command` (or
  place your own args before `*ctx.args` when hand-rolling). They're forwarded *before*
  the operator's arguments, so — click being last-value-wins — an operator's `--workers 8`
  on the command line overrides your default.

## Validation and logging

`yourcli serve --check` validates settings (including required secrets) and that the app
imports, then exits — handy for CI and container preflight. `default_log_config()` is
injected by default; pass `json_logs=True` for one-JSON-object-per-line output, or
`request_id=True` to thread gazebo's request id into every line. Operators can always
override it with `--log-config`, since that flag is forwarded to uvicorn like any other.

## Reference

See [`gazebo.ext.cli`](reference.md#gazebo.ext.cli) (the server-agnostic toolkit) and
[`gazebo.ext.uvicorn`](reference.md#gazebo.ext.uvicorn) (the uvicorn serve command).
