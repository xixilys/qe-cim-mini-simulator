#!/usr/bin/env python3
"""Small repo-owned JSON Schema subset validator.

This is not a full replacement for the external ``jsonschema`` package.  It is a
strict, stdlib-only validator for the subset used by the canonical DSE contract
schemas: object/array/scalar types, required/properties, enum, const, items,
minItems, additionalProperties, and numeric/string bounds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class ContractValidationError(ValueError):
    """Raised when a contract schema or instance is invalid."""


SUPPORTED_JSON_TYPES = frozenset({"object", "array", "string", "integer", "number", "boolean", "null"})


def _json_type_matches(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, Mapping)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return (isinstance(value, int | float) and not isinstance(value, bool))
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    raise ContractValidationError(f"unsupported JSON Schema type: {expected_type!r}")


def _as_types(type_decl: Any, path: str) -> tuple[str, ...]:
    if isinstance(type_decl, str):
        return (type_decl,)
    if isinstance(type_decl, list) and all(isinstance(item, str) for item in type_decl):
        return tuple(type_decl)
    raise ContractValidationError(f"{path}.type must be a string or list of strings")


def validate_schema_semantics(schema: Mapping[str, Any], *, path: str = "$") -> None:
    """Validate the JSON Schema subset used by this repository."""

    if not isinstance(schema, Mapping):
        raise ContractValidationError(f"{path} schema must be an object")
    schema_id = schema.get("$id")
    if path == "$" and not isinstance(schema_id, str):
        raise ContractValidationError("top-level schema must have string $id")
    type_decl = schema.get("type")
    schema_types: tuple[str, ...] = ()
    if type_decl is not None:
        schema_types = _as_types(type_decl, path)
        for schema_type in schema_types:
            if schema_type not in SUPPORTED_JSON_TYPES:
                raise ContractValidationError(
                    f"{path}.type contains unsupported JSON Schema type: {schema_type!r}"
                )
    properties = schema.get("properties", {})
    if properties:
        if not isinstance(properties, Mapping):
            raise ContractValidationError(f"{path}.properties must be an object")
        if schema_types and "object" not in schema_types:
            raise ContractValidationError(
                f"{path}.properties requires object type in {schema_types}"
            )
        for name, subschema in properties.items():
            if not isinstance(name, str):
                raise ContractValidationError(f"{path}.properties keys must be strings")
            validate_schema_semantics(subschema, path=f"{path}.properties.{name}")
    required = schema.get("required", [])
    if required:
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise ContractValidationError(f"{path}.required must be a list of strings")
        if len(set(required)) != len(required):
            raise ContractValidationError(f"{path}.required contains duplicate fields")
        if properties and any(item not in properties for item in required):
            missing = [item for item in required if item not in properties]
            raise ContractValidationError(
                f"{path}.required references undefined properties: {missing}"
            )
    enum = schema.get("enum")
    if enum is not None and (not isinstance(enum, list) or not enum):
        raise ContractValidationError(f"{path}.enum must be a non-empty list")
    if "const" in schema and enum is not None:
        raise ContractValidationError(f"{path} cannot specify both const and enum")
    items = schema.get("items")
    if items is not None:
        if schema_types and "array" not in schema_types:
            raise ContractValidationError(f"{path}.items requires array type")
        validate_schema_semantics(items, path=f"{path}.items")
    additional = schema.get("additionalProperties", True)
    if not isinstance(additional, bool):
        raise ContractValidationError(f"{path}.additionalProperties must be boolean")
    for key in ("minItems", "maxItems", "minLength", "maxLength"):
        if key in schema and (
            not isinstance(schema[key], int) or isinstance(schema[key], bool) or schema[key] < 0
        ):
            raise ContractValidationError(f"{path}.{key} must be a non-negative integer")
    for key in ("minimum", "maximum"):
        if key in schema and not isinstance(schema[key], int | float):
            raise ContractValidationError(f"{path}.{key} must be numeric")


def validate_instance(instance: Any, schema: Mapping[str, Any], *, path: str = "$") -> None:
    """Validate an instance against the repository JSON Schema subset."""

    type_decl = schema.get("type")
    if type_decl is not None:
        allowed_types = _as_types(type_decl, path)
        if not any(_json_type_matches(instance, schema_type) for schema_type in allowed_types):
            raise ContractValidationError(
                f"{path} expected type {allowed_types}, got {type(instance).__name__}"
            )
    if "const" in schema and instance != schema["const"]:
        raise ContractValidationError(f"{path} expected const {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        raise ContractValidationError(f"{path} expected one of {schema['enum']!r}")
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            raise ContractValidationError(f"{path} shorter than minLength")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            raise ContractValidationError(f"{path} longer than maxLength")
    if isinstance(instance, int | float) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            raise ContractValidationError(f"{path} below minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            raise ContractValidationError(f"{path} above maximum")
    if isinstance(instance, Mapping):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        missing = [name for name in required if name not in instance]
        if missing:
            raise ContractValidationError(f"{path} missing required fields: {missing}")
        additional = schema.get("additionalProperties", True)
        if additional is False:
            extras = sorted(set(instance) - set(properties))
            if extras:
                raise ContractValidationError(f"{path} has unexpected fields: {extras}")
        for name, subschema in properties.items():
            if name in instance:
                validate_instance(instance[name], subschema, path=f"{path}.{name}")
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            raise ContractValidationError(f"{path} has fewer than minItems")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            raise ContractValidationError(f"{path} has more than maxItems")
        if "items" in schema:
            for index, item in enumerate(instance):
                validate_instance(item, schema["items"], path=f"{path}[{index}]")


def validate_unique_schema_ids(schemas: Sequence[Mapping[str, Any]]) -> None:
    seen: dict[str, int] = {}
    for index, schema in enumerate(schemas):
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str):
            raise ContractValidationError(f"schema at index {index} missing string $id")
        if schema_id in seen:
            raise ContractValidationError(
                f"duplicate schema id {schema_id!r}: indexes {seen[schema_id]} and {index}"
            )
        seen[schema_id] = index
