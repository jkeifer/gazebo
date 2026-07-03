"""Server-agnostic CLI toolkit: self-documenting settings options for a serve command.

This is a topmost, optional layer — like ``ext/fastapi`` it sits above the core and
**must not be imported by it**. It imports ``click`` and ``pydantic-settings`` only
(never a web server); :mod:`gazebo.ext.uvicorn` builds the batteries-included uvicorn
``serve`` command on top of these pieces, but you can compose the same pieces atop any
server (granian, hypercorn, ...) with no uvicorn dependency. Requires the ``gazebo[cli]``
extra.

The building blocks:

  * :func:`settings_options` — one documented, self-propagating ``click.Option`` per
    settings field, so ``--help`` shows every setting, its env var, default, and
    description (the self-documentation), and a passed option writes its env var so the
    value reaches the app (and any server workers) through the environment they already
    read. No serialization, no transport across the worker boundary.
  * :func:`secrets_epilog` — the ``--help`` epilog documenting secret fields (their env
    var, requiredness) without accepting them as flags, so a composed command can
    document secrets without ever putting them on the command line.
  * :func:`default_log_config` — a complete dictConfig that survives worker spawn.

A settings option is *self-propagating* — it carries a callback that writes its env var
when passed — so you can drop it onto your own ``click`` command (renamed, reordered,
alongside your own options) and it still reaches the app with no export step of your own.

Secrets are never accepted on the command line: model them as ``SecretStr`` and they get
no value flag, only a documented entry in ``--help`` (their env var) via
:func:`secrets_epilog`, so they stay out of shell history / ``ps``. Supply them via the
settings class's ``secrets_dir`` (pydantic-settings reads ``/run/secrets``-style files)
or env.
"""

import json
import logging
import os

from collections.abc import Collection, Mapping, Sequence
from enum import Enum
from types import UnionType
from typing import Any, Union, get_args, get_origin

import click

from click.core import ParameterSource
from pydantic import SecretBytes, SecretStr
from pydantic_core import PydanticUndefined
from pydantic_settings import BaseSettings

__all__ = [
    'JsonFormatter',
    'default_log_config',
    'secrets_epilog',
    'settings_options',
]


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
    """A complete dictConfig so a server's loggers coexist with app loggers
    (``disable_existing_loggers=False``), error + access are formatted consistently,
    and it re-applies cleanly in every spawned worker.

    The console (non-``json_logs``) format names ``uvicorn.logging.DefaultFormatter`` /
    ``AccessFormatter`` as ``()`` dictConfig strings; these are *lazy string references*
    resolved by ``logging.config`` at config time, not imports here — but they do assume
    uvicorn is installed when the config is applied. The ``json_logs`` mode uses only
    :class:`JsonFormatter` and has no uvicorn dependency at all.

    Args:
        level: Log level for the server loggers and the root logger.
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


def _propagate_to_env(ctx: click.Context, param: click.Parameter, value: Any) -> Any:
    """Option callback: when the value came from the command line, write it to the
    field's env var so it reaches the app (and every server worker) through the
    environment they already read. Env- and default-sourced values are left untouched,
    so the app's own resolution still wins. This is what makes a settings option
    self-contained — compose it onto any command and it propagates itself, with no
    separate export step."""
    if (
        param.name
        and param.envvar
        and ctx.get_parameter_source(param.name) == ParameterSource.COMMANDLINE
    ):
        os.environ[str(param.envvar)] = str(value)
    return value


def _require_env_prefix(cls: type[BaseSettings]) -> None:
    """Every settings group must declare a non-empty env_prefix. The prefix
    namespaces the group's CLI flags (so they can't collide with the server's options
    or another group) and its env vars. Fail loudly at build time if it's missing."""
    if not cls.model_config.get('env_prefix'):
        raise ValueError(
            f'{cls.__name__} must set a non-empty env_prefix, e.g. '
            "model_config = SettingsConfigDict(env_prefix='APP_'). The prefix "
            'namespaces its CLI flags and env vars.',
        )


def settings_options(
    settings_cls: type[BaseSettings],
    *,
    exclude: Collection[str] = (),
    rename: Mapping[str, str] | None = None,
) -> list[click.Parameter]:
    """One self-documenting, self-propagating ``click.Option`` per non-secret field.

    Each option is prefixed by the class's (required) ``env_prefix`` (e.g.
    ``--app-host``) so it namespaces cleanly against the server's own options and other
    settings groups, carries its env var for ``--help``, and — via a callback — writes
    that env var when passed, so the value reaches the app with no export step of your
    own. Options are ``expose_value=False``: they act purely by side effect, so they
    don't appear in the command callback's signature.

    Compose the lists from several classes to expose more than one group on one command
    (``[*settings_options(A), *settings_options(B)]``); each class needs a distinct
    ``env_prefix``. This is the presentation half of ``serve_command``, exposed so a
    custom CLI can attach these options to its own command.

    Args:
        settings_cls: The ``pydantic-settings`` class to document.
        exclude: Field names to omit. Use this to drop a field you pin to a constant —
            set its env var yourself (or leave the app's default to stand) instead.
        rename: ``{field_name: decl}`` to give a field a different flag, e.g.
            ``{'greeting': '--message'}``, to unify names across a larger CLI. The env
            var is unchanged, so the renamed option still propagates to the same field.
            A renamed ``bool`` becomes the usual toggle automatically (``'--x'`` ->
            ``--x/--no-x``); give the full ``'--x/--no-x'`` form to control both names.

    No type gating: an option just writes a string to the env var, and pydantic
    deserializes it exactly as it does for env loading — so an option can carry whatever
    an env var can (scalars directly; complex types as a JSON string). Secret fields
    (``SecretStr``/``SecretBytes``) get no option, so a secret never lands on the
    command line."""
    _require_env_prefix(settings_cls)
    rename = rename or {}
    opts: list[click.Parameter] = []
    prefix = settings_cls.model_config.get('env_prefix', '')
    case_sensitive = settings_cls.model_config.get('case_sensitive', False)
    group = prefix.rstrip('_').lower()
    for name, field in settings_cls.model_fields.items():
        if name in exclude:
            continue
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
            # the option acts by side effect only (write env var on the command line);
            # nothing downstream needs its value, so keep it out of the callback kwargs.
            'expose_value': False,
            'callback': _propagate_to_env,
            # click reads `envvar`, so a required field is satisfied by the option OR
            # the env var (not forced onto the command line) — shown in --help, errors
            # early only if neither is set. A required option must carry NO default: a
            # default (even None) suppresses click's required check.
            'required': required,
        }
        if not required:
            kw['default'] = default
        if isinstance(anno, type) and issubclass(anno, Enum):
            kw['type'] = click.Choice([e.value for e in anno])
            if isinstance(default, Enum):
                kw['default'] = default.value
        # Every field gets an option (no type gating). The default is a plain string
        # option: the value is written verbatim to the env var and pydantic deserializes
        # it exactly as for env loading — scalars (str/int/Path/UUID/...) directly,
        # complex types (list/dict/model) as JSON. Only bool and enum get a special
        # widget, for UX and self-documentation — not because of how they parse.
        if name in rename:
            decl = rename[name]
            if anno is bool and '/' not in decl:
                decl = f'{decl}/--no-{decl.lstrip("-")}'  # same toggle a bool always gets
            decls = [decl]
        elif anno is bool:
            decls = [f'--{dash}/--no-{dash}']
        else:
            decls = [f'--{dash}']
        opts.append(click.Option(decls, **kw))
    return opts


def secrets_epilog(
    settings: type[BaseSettings] | Sequence[type[BaseSettings]],
) -> str | None:
    """Render a ``--help`` epilog documenting secret fields as a configuration surface —
    their env vars, but no value-accepting flag, so secrets never land in shell history
    or ``ps``. Supply them via the environment or the class's ``secrets_dir``.

    Returns ``None`` when no class declares a secret field, so a composed command can use
    it directly as its ``epilog`` regardless.

    Args:
        settings: A single ``pydantic-settings`` class or a sequence of them. A required
            secret is marked ``(required)`` since it has no flag to carry the marker.
    """
    classes = (settings,) if isinstance(settings, type) else tuple(settings)
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
