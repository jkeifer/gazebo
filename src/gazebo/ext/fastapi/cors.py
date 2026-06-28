"""CORS policy as a small config, installable on any FastAPI app.

``CorsConfig`` mirrors Starlette's ``CORSMiddleware`` field-for-field so the config
*is* the keyword set, and ``Cors`` is the loose argument the app constructors accept
(``True`` for permissive, a list of origins, or a full config).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware


@dataclass(frozen=True, slots=True)
class CorsConfig:
    """A CORS policy for a gazebo app, mirroring Starlette's ``CORSMiddleware``.

    The permissive defaults (``allow_origins=['*']`` with credentials off) are what
    ``cors=True`` selects — fine for local development, but tighten ``allow_origins``
    for anything browser-facing in production. ``allow_origins=['*']`` with
    ``allow_credentials=True`` is rejected by browsers, so credentials default off.
    """

    allow_origins: Sequence[str] = ('*',)
    allow_methods: Sequence[str] = ('*',)
    allow_headers: Sequence[str] = ('*',)
    allow_credentials: bool = False
    allow_origin_regex: str | None = None
    expose_headers: Sequence[str] = field(default_factory=tuple)
    max_age: int = 600

    @classmethod
    def resolve(cls, cors: Cors) -> CorsConfig | None:
        """Normalize a loose ``cors=`` argument into a config (``None`` means off).

        ``None``/``False`` → off, ``True`` → permissive defaults, a string or list →
        an allow-list of origins, a :class:`CorsConfig` → itself.
        """
        if cors is None or cors is False:
            return None
        if cors is True:
            return cls()
        if isinstance(cors, CorsConfig):
            return cors
        origins = (cors,) if isinstance(cors, str) else tuple(cors)
        return cls(allow_origins=origins)

    def apply(self, app: FastAPI) -> None:
        """Install this policy on ``app`` as a ``CORSMiddleware`` layer.

        The field names mirror ``CORSMiddleware``'s parameters one-for-one, so the
        config *is* the keyword set — ``asdict`` keeps the two in sync with no
        hand-maintained mapping. Call it last in ``upgrade`` so CORS ends up the
        outermost middleware (headers ride on every response, including problems).
        """
        app.add_middleware(CORSMiddleware, **asdict(self))


type Cors = bool | str | Sequence[str] | CorsConfig | None
"""How to configure CORS: ``None``/``False`` off, ``True`` permissive, a list of
allowed origins, or a full :class:`CorsConfig`."""


__all__ = ['Cors', 'CorsConfig']
