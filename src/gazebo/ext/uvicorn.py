"""Uvicorn assembly for the ``serve`` command: an argv-boundary over uvicorn's CLI.

This sits above :mod:`gazebo.ext.cli` (the server-agnostic toolkit) and is the only
module here that imports ``uvicorn``. It treats uvicorn as a **CLI, not a library**: the
only execution-path coupling is uvicorn's documented command-line interface. Instead of
copying uvicorn's option params and delegating to its callback (three couplings to
uvicorn internals), :func:`serve` forwards documented argv to
``uvicorn.main.main(args=..., standalone_mode=False)`` and lets uvicorn do its own
parsing, defaults, ``UVICORN_*`` env vars, and value transforms.

Discoverability splits cleanly: ``serve --help`` documents *app configuration* (our
contribution via :class:`gazebo.ext.cli.SettingsGroup`), while ``serve --help-server``
prints uvicorn's own help. The ``--help-server`` path is a *display-only* coupling
(``uvicorn.main.get_help``) that fails soft — a broken help screen never stops a server.

Requires the ``gazebo[uvicorn]`` extra (which pulls in ``gazebo[cli]`` plus uvicorn
itself). The ``import uvicorn`` here resolves to the real package, mirroring
``ext/fastapi``'s ``import fastapi``.
"""

import json
import tempfile

from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

import click
import uvicorn

from pydantic_settings import BaseSettings

from gazebo.ext.cli import SettingsGroup, default_log_config

__all__ = ['serve', 'serve_command']


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


# --- the launch action -------------------------------------------------------


def serve(
    app: str | Any,
    *uvicorn_args: str,
    factory: bool = False,
    log_config: Any = None,
) -> None:
    """Launch ``app`` via uvicorn by forwarding documented CLI argv to its console entry
    point (``uvicorn.main.main(args=..., standalone_mode=False)``).

    ``uvicorn_args`` are exactly uvicorn's documented command-line arguments, so
    ``serve('pkg.mod:app', '--workers', '4')`` mirrors ``uvicorn pkg.mod:app --workers
    4``. Uvicorn does its own parsing, defaults, ``UVICORN_*`` env vars, and value
    transforms (``--header x:y`` splitting, ``--app-dir`` on ``sys.path``, ...). An
    unknown flag gets uvicorn's own error (with its "did you mean" suggestion): raised as
    a :class:`click.UsageError` when called outside a click context, and surfaced as a
    normal usage error when called inside one.

    Args:
        app: A ``'module:attr'`` import string or an importable (module-level) factory.
            Live app objects and lambdas are rejected — uvicorn re-imports by name.
        *uvicorn_args: Uvicorn CLI arguments, forwarded verbatim after the injected
            ``--factory`` / ``--log-config``. Since click is last-value-wins for
            single-value options, an explicit ``--log-config`` here overrides the
            injected default.
        factory: Force factory mode for a string ``app`` (auto-detected for callables).
        log_config: dictConfig loading for uvicorn. ``None`` injects
            :func:`gazebo.ext.cli.default_log_config`; a ``dict`` is written to a temp
            ``.json`` file whose path is passed (workers re-read it); a ``str``/``Path``
            is passed through as-is.
    """
    import_string, derived_factory = _resolve_app(app)
    use_factory = factory or derived_factory

    temp_path: str | None = None
    if log_config is None:
        log_config = default_log_config()
    if isinstance(log_config, dict):
        # workers re-read this file, so it must live for the whole run (unlinked after).
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as fh:
            json.dump(log_config, fh)
            temp_path = fh.name
        log_config_path = temp_path
    else:
        log_config_path = str(log_config)

    argv = [import_string]
    if use_factory:
        argv.append('--factory')
    argv += ['--log-config', log_config_path]
    argv += list(uvicorn_args)  # last, so an explicit operator --log-config wins

    try:
        uvicorn.main.main(args=argv, standalone_mode=False)  # type: ignore[attr-defined]
    finally:
        if temp_path is not None:
            with suppress(OSError):
                Path(temp_path).unlink()


# --- validation preflight ----------------------------------------------------


def _run_check(factory_path: str, classes: tuple[type[BaseSettings], ...]) -> None:
    """Validate settings resolution and that the app target imports, then exit. No
    server, no lifespan — the cheap, high-value preflight (CI / container check)."""
    import importlib

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


# --- the command -------------------------------------------------------------


def serve_command(
    app: str | Any,
    *,
    settings_group: SettingsGroup | None = None,
    name: str = 'serve',
    factory: bool = False,
    log_config: Any = None,
    uvicorn_args: Sequence[str] = (),
) -> click.Command:
    """Build a click ``serve`` command for ``app``.

    ``serve --help`` documents *your app's configuration* (one option per settings
    field); every uvicorn option is still accepted and forwarded verbatim to uvicorn (run
    ``serve --help-server`` to list them). Operator arguments on the command line follow
    the author's ``uvicorn_args`` defaults, so — being later — the operator can override
    them (``uvicorn_args=('--workers', '4')`` is a default an operator overrides with
    ``--workers 8``).

    Args:
        app: A ``'module:attr'`` import string or an importable (module-level)
            factory callable. Live app objects and lambdas are rejected because
            uvicorn workers re-import by name.
        settings_group: A :class:`gazebo.ext.cli.SettingsGroup` — one or more settings
            classes composed (and validated) into the command's options. Build it
            yourself so any per-group ``exclude``/``rename`` and its cross-group checks
            live in one place: ``settings_group=SettingsGroup(Settings)`` (or
            ``SettingsGroup(A) + SettingsGroup(B)``). A passed option sets its env var.
        name: The command name (default ``serve``).
        factory: Force factory mode for a string ``app`` (auto-detected for callables).
        log_config: dictConfig for uvicorn; defaults to
            :func:`gazebo.ext.cli.default_log_config`. Operators can still override it
            with ``--log-config`` on the command line.
        uvicorn_args: Author-supplied uvicorn CLI defaults, forwarded *before* operator
            arguments so an operator can override them at the command line.
    """
    import_string, derived_factory = _resolve_app(app)
    force_factory = factory or derived_factory

    group = settings_group if settings_group is not None else SettingsGroup()
    setting_opts = group.options
    classes = group.settings_classes

    check_opt = click.Option(
        ['--check'],
        is_flag=True,
        default=False,
        help='Validate settings and that the app imports, then exit (no server).',
    )

    def _show_server_help(ctx: click.Context, param: click.Parameter, value: bool) -> None:
        # eager (like --version): must work even if a required settings option is unset.
        if not value or ctx.resilient_parsing:
            return
        click.echo(uvicorn.main.get_help(click.Context(uvicorn.main)))  # type: ignore[attr-defined]
        ctx.exit()

    help_server_opt = click.Option(
        ['--help-server'],
        is_flag=True,
        is_eager=True,
        expose_value=False,
        callback=_show_server_help,
        help="Show uvicorn's own options (all are accepted and forwarded), then exit.",
    )

    def callback(**kwargs: Any) -> None:
        if kwargs.pop('check', False):
            _run_check(import_string, classes)
            return
        # settings options self-propagate to the env (expose_value=False), so they never
        # reach here; forwarded uvicorn args land in ctx.args (unknown options allowed).
        ctx = click.get_current_context()
        serve(
            import_string,
            *uvicorn_args,
            *ctx.args,
            factory=force_factory,
            log_config=log_config,
        )

    epilog = group.secrets_epilog
    forwarded = (
        'Any uvicorn option (--workers, --reload, --host, ...) is accepted and '
        'forwarded to uvicorn; run with --help-server to list them.'
    )
    epilog = f'{epilog}\n\n{forwarded}' if epilog else forwarded

    return click.Command(
        name,
        params=[check_opt, help_server_opt, *setting_opts],
        callback=callback,
        epilog=epilog,
        context_settings={'ignore_unknown_options': True, 'allow_extra_args': True},
        help='Run the server. Options here configure the app (each sets its env var); '
        'uvicorn options are accepted and forwarded — see --help-server.',
    )
