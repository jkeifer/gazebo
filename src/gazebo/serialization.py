"""Shared serialization helpers (pure pydantic + pydantic-core; no gazebo imports).

OGC omits absent members rather than emitting ``null``. gazebo gets that with a JSON
``@model_serializer`` that drops null fields — but a model with a ``@model_serializer``
makes pydantic treat the *serialized* shape as opaque: its serialization JSON schema —
and therefore FastAPI's OpenAPI response schema — collapses to
``{"additionalProperties": true}``. The two halves must travel together, so
:class:`OmitNullModel` bundles them: subclass it and absent optional members are
omitted on the wire while the documented response schema stays honest. Models with
richer serializers (e.g. :class:`~gazebo.collection.LinkedCollection`) reuse the
pieces directly — :func:`drop_none` for the wire shape and
:func:`faithful_serialization_schema` from their own ``__get_pydantic_json_schema__``.

Why not pydantic's native ``exclude_none``? It is a dump-*time* flag, not a model
property — there is no model-level "always omit none" in pydantic. Relying on it would
push the responsibility onto each caller (``model_dump(exclude_none=True)``) or, under
the framework glue, onto per-route ``response_model_exclude_none=True`` — easy to
forget and inert for non-FastAPI users. Baking omission into the model keeps the
behavior self-contained and correct regardless of how the model is serialized.
"""

from __future__ import annotations

from typing import Any

from pydantic import (
    BaseModel,
    GetJsonSchemaHandler,
    SerializerFunctionWrapHandler,
    model_serializer,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema


def drop_none(data: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is ``None`` — OGC omits absent members on the wire."""
    return {k: v for k, v in data.items() if v is not None}


def strip_model_serializers(schema: Any) -> Any:
    """Deep-copy a core schema with model-level *function* serializers removed.

    Only the ``serialization`` entry attached to a ``model`` node — pydantic's
    representation of a ``@model_serializer`` — is dropped, since that is what
    opacifies the output shape. Field-level serializers (``PlainSerializer`` and
    friends, which sit on the field's own node) and computed-field schemas are
    preserved, so the reconstructed schema still reflects each field's real
    serialized type rather than its pre-serialization one.
    """
    if isinstance(schema, dict):
        is_model = schema.get('type') == 'model'
        return {
            key: strip_model_serializers(value)
            for key, value in schema.items()
            if not (
                is_model
                and key == 'serialization'
                and isinstance(value, dict)
                and str(value.get('type', '')).startswith('function')
            )
        }
    if isinstance(schema, list):
        return [strip_model_serializers(item) for item in schema]
    return schema


def faithful_serialization_schema(
    core_schema: CoreSchema,
    handler: GetJsonSchemaHandler,
) -> JsonSchemaValue:
    """A serialization JSON schema reflecting the real fields, not an opaque object.

    Call from ``__get_pydantic_json_schema__`` on any model whose ``@model_serializer``
    would otherwise opacify its serialization schema. Validation schemas (request
    bodies) are unaffected and returned as-is.
    """
    json_schema = handler(core_schema)
    if handler.mode == 'serialization' and 'properties' not in json_schema:
        json_schema = handler(strip_model_serializers(core_schema))
    return json_schema


class OmitNullModel(BaseModel):
    """A pydantic model that omits null fields on JSON serialization, OGC-style.

    Subclass it for any model whose absent optional members should be omitted on
    the wire rather than emitted as ``null``. It bundles the two halves that have to
    travel together: a JSON-mode ``@model_serializer`` that drops ``None`` values,
    and a ``__get_pydantic_json_schema__`` that reconstructs the real field shape so
    the serializer does not opacify the OpenAPI response schema.
    """

    @model_serializer(mode='wrap', when_used='json')
    def _omit_null(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return drop_none(handler(self))

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        return faithful_serialization_schema(core_schema, handler)
