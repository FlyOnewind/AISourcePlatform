import hashlib
import json
from collections.abc import Iterable
from typing import Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from app.gateway.errors import GatewayError


Direction = Literal["input", "output"]


def _error_details(error: SchemaError | ValidationError) -> dict[str, object]:
    return {
        "path": list(error.absolute_path),
        "schema_path": list(error.absolute_schema_path),
        "keyword": error.validator,
    }


def _path_sort_key(path: Iterable[object]) -> tuple[tuple[str, str], ...]:
    return tuple((type(part).__name__, str(part)) for part in path)


def _validation_error_sort_key(
    error: ValidationError,
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    return (
        _path_sort_key(error.absolute_path),
        _path_sort_key(error.absolute_schema_path),
    )


def _schema_fingerprint(schema: dict[str, object]) -> str:
    try:
        canonical_schema = json.dumps(
            schema,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise GatewayError(
            "SCHEMA_DEFINITION_INVALID",
            "Schema definition is invalid",
        ) from error
    return hashlib.sha256(canonical_schema).hexdigest()


class SchemaValidatorCache:
    def __init__(self) -> None:
        self._validators: dict[tuple[str, str], Draft202012Validator] = {}

    def validate_schema(self, schema: dict[str, object]) -> None:
        try:
            Draft202012Validator.check_schema(schema)
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

        fingerprint = _schema_fingerprint(schema)
        internal_cache_key = (cache_key, fingerprint)
        validator = self._validators.get(internal_cache_key)
        if validator is None:
            self.validate_schema(schema)
            validator = Draft202012Validator(schema)
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
