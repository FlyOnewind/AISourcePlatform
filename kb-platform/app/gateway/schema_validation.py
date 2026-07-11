import hashlib
import json
import math
from collections.abc import Iterable
from copy import deepcopy
from typing import Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from app.gateway.errors import GatewayError


Direction = Literal["input", "output"]


def _schema_definition_error(
    *,
    path: Iterable[object] = (),
) -> GatewayError:
    safe_path = list(path)
    return GatewayError(
        "SCHEMA_DEFINITION_INVALID",
        "Schema definition is invalid",
        details={
            "path": safe_path,
            "schema_path": safe_path.copy(),
            "keyword": "json",
        },
    )


def _error_details(error: SchemaError | ValidationError) -> dict[str, object]:
    return {
        "path": list(error.absolute_path),
        "schema_path": list(error.absolute_schema_path),
        "keyword": error.validator,
    }


def _path_sort_key(
    path: Iterable[object],
) -> tuple[tuple[int, int | str, str], ...]:
    key: list[tuple[int, int | str, str]] = []
    for part in path:
        if isinstance(part, int) and not isinstance(part, bool):
            key.append((0, part, ""))
        else:
            key.append((1, type(part).__name__, str(part)))
    return tuple(key)


def _validation_error_sort_key(
    error: ValidationError,
) -> tuple[
    tuple[tuple[int, int | str, str], ...],
    tuple[tuple[int, int | str, str], ...],
]:
    return (
        _path_sort_key(error.absolute_path),
        _path_sort_key(error.absolute_schema_path),
    )


def _validate_json_value(
    value: object,
    *,
    path: tuple[object, ...] = (),
) -> None:
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, float):
        if math.isfinite(value):
            return
        raise _schema_definition_error(path=path)
    if type(value) is dict:
        for key, child in value.items():
            if not isinstance(key, str):
                raise _schema_definition_error(path=path)
            _validate_json_value(child, path=(*path, key))
        return
    if type(value) is list:
        for index, child in enumerate(value):
            _validate_json_value(child, path=(*path, index))
        return
    raise _schema_definition_error(path=path)


def _schema_snapshot(schema: dict[str, object]) -> dict[str, object]:
    try:
        return deepcopy(schema)
    except Exception as error:
        raise _schema_definition_error() from error


def _canonical_schema(schema: dict[str, object]) -> bytes:
    try:
        return json.dumps(
            schema,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise _schema_definition_error() from error


def _schema_fingerprint(canonical_schema: bytes) -> str:
    return hashlib.sha256(canonical_schema).hexdigest()


class SchemaValidatorCache:
    def __init__(self) -> None:
        self._validators: dict[tuple[str, str], Draft202012Validator] = {}

    def validate_schema(self, schema: dict[str, object]) -> None:
        schema_snapshot = _schema_snapshot(schema)
        _validate_json_value(schema_snapshot)
        _canonical_schema(schema_snapshot)
        try:
            Draft202012Validator.check_schema(schema_snapshot)
        except SchemaError as error:
            raise GatewayError(
                "SCHEMA_DEFINITION_INVALID",
                "Schema definition is invalid",
                details=_error_details(error),
            ) from error

    def validate(
        self,
        instance: object,
        schema: dict[str, object],
        cache_key: str,
        direction: Direction,
    ) -> None:
        if direction not in ("input", "output"):
            raise ValueError("direction must be 'input' or 'output'")

        schema_snapshot = _schema_snapshot(schema)
        _validate_json_value(schema_snapshot)
        canonical_schema = _canonical_schema(schema_snapshot)
        fingerprint = _schema_fingerprint(canonical_schema)
        internal_cache_key = (cache_key, fingerprint)
        validator = self._validators.get(internal_cache_key)
        if validator is None:
            try:
                Draft202012Validator.check_schema(schema_snapshot)
            except SchemaError as error:
                raise GatewayError(
                    "SCHEMA_DEFINITION_INVALID",
                    "Schema definition is invalid",
                    details=_error_details(error),
                ) from error
            validator = Draft202012Validator(schema_snapshot)
            self._validators[internal_cache_key] = validator

        errors = sorted(
            validator.iter_errors(instance),
            key=_validation_error_sort_key,
        )
        if not errors:
            return

        messages = {
            "input": "Input does not match the declared schema",
            "output": "Output does not match the declared schema",
        }
        raise GatewayError(
            f"SCHEMA_{direction.upper()}_INVALID",
            messages[direction],
            details=_error_details(errors[0]),
        )
