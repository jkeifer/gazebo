"""CLI / serving glue: a self-documenting ``serve`` command builder over uvicorn.

This is the topmost, most optional layer — like ``ext/fastapi`` it sits above the
core and **must not be imported by it**. It imports ``click``, ``uvicorn``, and
``pydantic-settings`` and requires the ``gazebo[cli]`` extra.

``serve_command(app, settings=Settings)`` builds a click command that:

  * runs the app via uvicorn (host/port/workers/reload/... are uvicorn's own CLI
    options, composed in with full help);
  * generates one documented option per settings field, so ``--help`` shows every
    setting, its env var, default, and description — the self-documentation;
  * when a settings flag is *passed*, it simply sets that field's env var, so the
    value reaches the app and any uvicorn workers through the environment they
    already read. No serialization, no transport across the worker boundary.

Secrets are never accepted on the command line: model them as ``SecretStr`` and they
get no value flag, only a documented entry in ``--help`` (their env var), so they stay
out of shell history / ``ps``. Supply them via the settings class's ``secrets_dir``
(pydantic-settings reads ``/run/secrets``-style files) or env.
"""

import copy
import importlib
import json
import logging
import os

from collections.abc import Sequence
from enum import Enum
from types import UnionType
from typing import Any, Union, get_args, get_origin

import click
import uvicorn

from click.core import ParameterSource
from pydantic import SecretBytes, SecretStr
from pydantic_core import PydanticUndefined
from pydantic_settings import BaseSettings

__all__ = ['JsonFormatter', 'default_log_config', 'serve_command']


# --- default logging (the genuinely fiddly part) -----------------------------


class JsonFormatter(logging.Formatter):
    """Minimal structured formatter: one JSON object per line. The access logger's
    rendered line lands in ``message``; fully-structured access fields (status, path
    as separate keys) are a later enhancement if needed."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            'time': self.formatTime(record),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        rid = getattr(record, 'request_id', None)
        if rid is not None:
            data['request_id'] = rid
        if record.exc_info:
            data['exc'] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def default_log_config(
    level: str = 'INFO',
    *,
    json_logs: bool = False,
    request_id: bool = False,
) -> dict[str, Any]:
    """A complete dictConfig so uvicorn's loggers coexist with app loggers
    (``disable_existing_loggers=False``), error + access are formatted consistently,
    and it re-applies cleanly in every spawned worker. Pin it via
    ``serve_command(..., log_config=default_log_config())`` (the default).

    Args:
        level: Log level for uvicorn loggers and the root logger.
        json_logs: Emit one JSON object per line (for log aggregation) instead of
            the console format. Pin per environment, e.g.
            ``log_config=default_log_config(json_logs=True)``.
        request_id: Wire :class:`gazebo.context.RequestIdFilter` into the handlers so
            the per-request id (set via ``use_request_id``) appears in every line.
    """
    rid_token = '[%(request_id)s] ' if request_id else ''
    formatters: dict[str, dict[str, Any]]
    if json_logs:
        formatters = {
            'default': {'()': f'{__name__}.JsonFormatter'},
            'access': {'()': f'{__name__}.JsonFormatter'},
        }
    else:
        formatters = {
            'default': {
                '()': 'uvicorn.logging.DefaultFormatter',
                'format': f'%(levelprefix)s {rid_token}%(message)s',
                'use_colors': None,
            },
            'access': {
                '()': 'uvicorn.logging.AccessFormatter',
                'format': f'%(levelprefix)s {rid_token}%(client_addr)s - '
                '"%(request_line)s" %(status_code)s',
            },
        }
    filters = {'request_id': {'()': 'gazebo.context.RequestIdFilter'}} if request_id else {}
    handler_filters = ['request_id'] if request_id else []
    return {
        'version': 1,
        'disable_existing_loggers': False,
        'filters': filters,
        'formatters': formatters,
        'handlers': {
            'default': {
                'class': 'logging.StreamHandler',
                'formatter': 'default',
                'stream': 'ext://sys.stderr',
                'filters': handler_filters,
            },
            'access': {
                'class': 'logging.StreamHandler',
                'formatter': 'access',
                'stream': 'ext://sys.stdout',
                'filters': handler_filters,
            },
        },
        'loggers': {
            'uvicorn': {'handlers': ['default'], 'level': level, 'propagate': False},
            'uvicorn.error': {'level': level},
            'uvicorn.access': {'handlers': ['access'], 'level': level, 'propagate': False},
        },
        'root': {'handlers': ['default'], 'level': level},
    }


# --- app reference resolution ------------------------------------------------


def _resolve_app(app: str | Any) -> tuple[str, bool]:
    """``(import_string, is_factory)``. A str is used verbatim; a module-level
    factory has its string derived and ``factory=True`` forced. Lambdas, locals, and
    live app objects are rejected — workers re-import by string, so the target must
    be an importable name."""
    if isinstance(app, str):
        return app, False
    if callable(app):
        mod = getattr(app, '__module__', None)
        qn = getattr(app, '__qualname__', None)
        if not mod or not qn or '<locals>' in qn or '<lambda>' in qn:
            raise ValueError(
                f'app {app!r} has no import string (use a module-level def or a '
                "'module:attr' string; reload/workers re-import by name)",
            )
        return f'{mod}:{qn}', True
    raise TypeError("app must be a 'module:attr' string or an importable factory")


# --- settings option generation (the self-documentation) ---------------------


def _is_secret(anno: Any) -> bool:
    for arg in get_args(anno) or (anno,):
        if isinstance(arg, type) and issubclass(arg, (SecretStr, SecretBytes)):
            return True
    return False


def _unwrap_optional(anno: Any) -> Any:
    """``X | None`` / ``Optional[X]`` -> ``X`` (only for a single non-None arm), so an
    optional scalar gets the same flag its non-optional twin would."""
    if get_origin(anno) in (Union, UnionType):
        non_none = [a for a in get_args(anno) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return anno


def _settings_options(
    settings_cls: type[BaseSettings],
) -> list[tuple[click.Parameter, str, str]]:
    """One documented click.Option per non-secret field. Returns
    ``(option, dest, envvar)``. Flags are prefixed by the env_prefix (e.g.
    ``--app-host``) so they never collide with uvicorn's own options and read as
    'app config' vs 'server config' in --help. The option's only runtime effect is
    to set its env var when passed; everything else is for ``--help``.

    No type gating: a flag just writes a string to the env var, and pydantic
    deserializes it exactly as it does for env loading — so a flag can carry whatever
    an env var can (scalars directly; complex types as a JSON string)."""
    opts: list[tuple[click.Parameter, str, str]] = []
    prefix = settings_cls.model_config.get('env_prefix', '')
    case_sensitive = settings_cls.model_config.get('case_sensitive', False)
    group = prefix.rstrip('_').lower()
    for name, field in settings_cls.model_fields.items():
        anno = field.annotation
        if _is_secret(anno):
            continue  # never put a secret on the command line
        anno = _unwrap_optional(anno)
        envvar = prefix + name
        envvar = envvar if case_sensitive else envvar.upper()
        dest = f'{group}_{name}' if group else name
        dash = dest.replace('_', '-')
        default = field.default if field.default is not PydanticUndefined else None
        required = field.is_required()
        kw: dict[str, Any] = {
            'envvar': envvar,
            'show_envvar': True,
            'show_default': True,
            'help': field.description,
            # click reads `envvar`, so a required field is satisfied by the flag OR
            # the env var (not forced onto the command line) — shown in --help, errors
            # early only if neither is set. A required option must carry NO default: a
            # default (even None) suppresses click's required check.
            'required': required,
        }
        if not required:
            kw['default'] = default
        # Every field gets a flag (no type gating). The default is a plain string
        # flag: the value is written verbatim to the env var and pydantic deserializes
        # it exactly as for env loading — scalars (str/int/Path/UUID/...) directly,
        # complex types (list/dict/model) as JSON. Only bool and enum get a special
        # widget, for UX and self-documentation — not because of how they parse.
        decls = [f'--{dash}']
        if anno is bool:
            decls = [f'--{dash}/--no-{dash}']
        elif isinstance(anno, type) and issubclass(anno, Enum):
            kw['type'] = click.Choice([e.value for e in anno])
            if isinstance(default, Enum):
                kw['default'] = default.value
        opts.append((click.Option(decls, **kw), dest, envvar))
    return opts


# --- the command -------------------------------------------------------------

_RESERVED = {'app', 'factory'}


def _run_check(factory_path: str, classes: tuple[type[BaseSettings], ...]) -> None:
    """Validate settings resolution and that the app target imports, then exit. No
    server, no lifespan — the cheap, high-value preflight (CI / container check)."""
    problems: list[str] = []
    for cls in classes:
        try:
            cls()
        except Exception as exc:  # noqa: BLE001 - report any resolution/validation error
            problems.append(f'{cls.__name__}: {exc}')
    try:
        mod_name, _, attr = factory_path.partition(':')
        obj: Any = importlib.import_module(mod_name)
        for part in attr.split('.'):
            obj = getattr(obj, part)
    except Exception as exc:  # noqa: BLE001
        problems.append(f'app import ({factory_path}): {exc}')
    if problems:
        for problem in problems:
            click.echo(problem, err=True)
        raise SystemExit(1)
    click.echo('OK')


def _reject_unknown_uvicorn_kwargs(fixed: dict[str, Any]) -> None:
    """Fail fast if a pinned kwarg isn't a real uvicorn option (typo / wrong name)."""
    valid = {p.name for p in uvicorn.main.params} - _RESERVED  # type: ignore[attr-defined]
    unknown = set(fixed) - valid
    if unknown:
        raise ValueError(f'not uvicorn.run options: {sorted(unknown)}')


def _as_tuple(
    settings: type[BaseSettings] | Sequence[type[BaseSettings]] | None,
) -> tuple[type[BaseSettings], ...]:
    if settings is None:
        return ()
    if isinstance(settings, type):
        return (settings,)
    return tuple(settings)


def _require_env_prefix(cls: type[BaseSettings]) -> None:
    """Every settings group must declare a non-empty env_prefix. The prefix
    namespaces the group's CLI flags (so they can't collide with uvicorn's options
    or another group) and its env vars. Fail loudly at build time if it's missing."""
    if not cls.model_config.get('env_prefix'):
        raise ValueError(
            f'{cls.__name__} must set a non-empty env_prefix, e.g. '
            "model_config = SettingsConfigDict(env_prefix='APP_'). The prefix "
            'namespaces its CLI flags and env vars.',
        )


def _setting_options_and_routing(
    classes: tuple[type[BaseSettings], ...],
) -> tuple[list[click.Parameter], list[tuple[str, str]]]:
    """The combined settings option group plus the ``(dest -> envvar)`` routing the
    callback uses to write passed flags to the environment. Each class is its own
    group, namespaced by its required, distinct env_prefix."""
    options: list[click.Parameter] = []
    routing: list[tuple[str, str]] = []
    seen_prefixes: set[str] = set()
    for cls in classes:
        _require_env_prefix(cls)
        prefix = cls.model_config.get('env_prefix', '')
        if prefix in seen_prefixes:
            raise ValueError(
                f'duplicate env_prefix {prefix!r} across settings groups; '
                'each group needs a distinct prefix',
            )
        seen_prefixes.add(prefix)
        for option, dest, envvar in _settings_options(cls):
            options.append(option)
            routing.append((dest, envvar))
    return options, routing


def _secrets_epilog(classes: tuple[type[BaseSettings], ...]) -> str | None:
    """A ``--help`` section documenting secret fields as a configuration surface —
    their env vars, but no value-accepting flag, so secrets never land in shell
    history or ``ps``. Supply them via the environment or the class's secrets_dir."""
    rows: list[tuple[str, str]] = []
    for cls in classes:
        prefix = cls.model_config.get('env_prefix', '')
        case_sensitive = cls.model_config.get('case_sensitive', False)
        for name, field in cls.model_fields.items():
            if not _is_secret(field.annotation):
                continue
            envvar = prefix + name
            desc = field.description or ''
            if field.is_required():  # no flag to mark required, so say so here
                desc = f'{desc} (required)'.strip()
            rows.append((envvar if case_sensitive else envvar.upper(), desc))
    if not rows:
        return None
    width = max(len(envvar) for envvar, _ in rows)
    listing = '\n'.join(f'  {envvar.ljust(width)}  {desc}'.rstrip() for envvar, desc in rows)
    # the \b marks the listing as preformatted so click doesn't rewrap the columns
    return (
        'Secrets (set via the environment or a secrets file, never on the command '
        'line):\n\n\b\n' + listing
    )


def _uvicorn_passthrough_options(excluded: set[str]) -> list[click.Parameter]:
    """Copies of uvicorn's own CLI options (never the originals), with an env var
    annotated for documentation. Excludes the ones we pin or control."""
    options: list[click.Parameter] = []
    for param in uvicorn.main.params:  # type: ignore[attr-defined]
        if param.name in excluded:
            continue
        param = copy.copy(param)
        if getattr(param, 'envvar', None) is None and param.name:
            param.envvar = f'UVICORN_{param.name.upper()}'
            param.show_envvar = True  # type: ignore[attr-defined]
        options.append(param)
    return options


def _export_passed_settings(routing: list[tuple[str, str]], kwargs: dict[str, Any]) -> None:
    """For each settings flag the user actually passed, write its env var so the
    value reaches the app (and uvicorn workers) through the environment. Defaults and
    env-sourced values are left untouched, so the app's own resolution still wins.
    Settings keys are removed from ``kwargs`` so only uvicorn options remain."""
    ctx = click.get_current_context()
    for dest, envvar in routing:
        if ctx.get_parameter_source(dest) == ParameterSource.COMMANDLINE:
            os.environ[envvar] = str(kwargs[dest])
        kwargs.pop(dest, None)


def serve_command(
    app: str | Any,
    *,
    settings: type[BaseSettings] | Sequence[type[BaseSettings]] | None = None,
    name: str = 'serve',
    factory: bool = False,
    log_config: Any = None,
    **fixed: Any,
) -> click.Command:
    """Build a click ``serve`` command for ``app``.

    Args:
        app: A ``'module:attr'`` import string or an importable (module-level)
            factory callable. Live app objects and lambdas are rejected because
            uvicorn workers re-import by name.
        settings: A pydantic-settings class or a sequence of them. Each becomes a
            self-documenting option group, namespaced by its (required, distinct)
            ``env_prefix``; a passed flag sets the matching env var.
        name: The command name (default ``serve``).
        factory: Force factory mode for a string ``app`` (auto-detected for callables).
        log_config: dictConfig for uvicorn; defaults to :func:`default_log_config`.
        **fixed: uvicorn.run() kwargs pinned to constants and removed from the CLI.
    """
    factory_path, derived_factory = _resolve_app(app)
    force_factory = factory or derived_factory
    fixed.setdefault('log_config', log_config if log_config is not None else default_log_config())
    _reject_unknown_uvicorn_kwargs(fixed)

    classes = _as_tuple(settings)
    setting_opts, routing = _setting_options_and_routing(classes)
    uvicorn_opts = _uvicorn_passthrough_options(excluded=_RESERVED | set(fixed))
    check_opt = click.Option(
        ['--check'],
        is_flag=True,
        default=False,
        help='Validate settings and that the app imports, then exit (no server).',
    )

    def callback(**kwargs: Any) -> None:
        check = kwargs.pop('check', False)
        _export_passed_settings(routing, kwargs)
        if check:
            _run_check(factory_path, classes)
            return
        # delegate to uvicorn's own CLI callback so its value transforms run
        # (header split, app_dir -> sys.path, ...); we only pin app + factory.
        uvicorn.main.callback(  # type: ignore[misc]
            app=factory_path,
            factory=force_factory,
            **fixed,
            **kwargs,
        )

    return click.Command(
        name,
        params=[check_opt, *setting_opts, *uvicorn_opts],
        callback=callback,
        epilog=_secrets_epilog(classes),
        help='Run the server. Settings options set the matching env var; the rest '
        'are uvicorn options.',
    )
