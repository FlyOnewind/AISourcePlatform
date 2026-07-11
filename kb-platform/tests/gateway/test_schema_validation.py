import pytest

import app.gateway.schema_validation as schema_validation
from app.gateway.errors import GatewayError
from app.gateway.schema_validation import SchemaValidatorCache


def test_missing_required_input_raises_input_error():
    cache = SchemaValidatorCache()

    with pytest.raises(GatewayError) as exc:
        cache.validate(
            {},
            {"type": "object", "required": ["product_id"]},
            "capability:1.0.0:input",
            "input",
        )

    assert exc.value.code == "SCHEMA_INPUT_INVALID"
    assert exc.value.retryable is False


def test_invalid_output_raises_output_error():
    cache = SchemaValidatorCache()

    with pytest.raises(GatewayError) as exc:
        cache.validate(
            {"count": "many"},
            {
                "type": "object",
                "properties": {"count": {"type": "integer"}},
            },
            "capability:1.0.0:output",
            "output",
        )

    assert exc.value.code == "SCHEMA_OUTPUT_INVALID"
    assert exc.value.retryable is False


def test_input_error_reports_paths_without_invalid_value():
    secret = "super-secret-customer-value"
    cache = SchemaValidatorCache()

    with pytest.raises(GatewayError) as exc:
        cache.validate(
            {"credentials": {"token": secret}},
            {
                "type": "object",
                "properties": {
                    "credentials": {
                        "type": "object",
                        "properties": {"token": {"type": "integer"}},
                    }
                },
            },
            "capability:1.0.0:input",
            "input",
        )

    error = exc.value
    assert error.details == {
        "path": ["credentials", "token"],
        "schema_path": ["properties", "credentials", "properties", "token", "type"],
        "keyword": "type",
    }
    serialized = error.to_dict()
    assert serialized == {
        "code": "SCHEMA_INPUT_INVALID",
        "message": "Input does not match the declared schema",
        "retryable": False,
        "details": error.details,
    }
    serialized_text = repr(serialized)
    assert secret not in str(error)
    assert secret not in serialized_text
    assert "instance" not in serialized_text
    assert "value" not in serialized_text


def test_invalid_schema_is_rejected_at_publish():
    with pytest.raises(GatewayError) as exc:
        SchemaValidatorCache().validate_schema({"type": "not-a-json-type"})

    assert exc.value.code == "SCHEMA_DEFINITION_INVALID"
    assert exc.value.retryable is False
    assert set(exc.value.details) == {"path", "schema_path", "keyword"}


def test_schema_with_non_json_object_is_rejected_at_publish():
    with pytest.raises(GatewayError) as exc:
        SchemaValidatorCache().validate_schema({"default": object()})

    assert exc.value.code == "SCHEMA_DEFINITION_INVALID"
    assert exc.value.details == {
        "path": ["default"],
        "schema_path": ["default"],
        "keyword": "json",
    }


def test_schema_with_nan_is_rejected_at_publish():
    with pytest.raises(GatewayError) as exc:
        SchemaValidatorCache().validate_schema({"enum": [float("nan")]})

    assert exc.value.code == "SCHEMA_DEFINITION_INVALID"
    assert exc.value.details == {
        "path": ["enum", 0],
        "schema_path": ["enum", 0],
        "keyword": "json",
    }


def test_schema_with_tuple_annotation_is_rejected_at_publish():
    with pytest.raises(GatewayError) as exc:
        SchemaValidatorCache().validate_schema({"default": ("draft",)})

    assert exc.value.code == "SCHEMA_DEFINITION_INVALID"
    assert exc.value.details == {
        "path": ["default"],
        "schema_path": ["default"],
        "keyword": "json",
    }


@pytest.mark.parametrize(
    "annotation",
    [
        {"draft"},
        type("CustomList", (list,), {})(["draft"]),
    ],
    ids=["set", "custom-list"],
)
def test_schema_with_non_json_container_is_rejected_at_publish(annotation):
    with pytest.raises(GatewayError) as exc:
        SchemaValidatorCache().validate_schema({"default": annotation})

    assert exc.value.code == "SCHEMA_DEFINITION_INVALID"
    assert exc.value.details == {
        "path": ["default"],
        "schema_path": ["default"],
        "keyword": "json",
    }


def test_draft_2020_12_prefix_items_is_accepted_and_enforced():
    schema = {
        "type": "array",
        "prefixItems": [{"type": "string"}, {"type": "integer"}],
    }
    cache = SchemaValidatorCache()

    cache.validate_schema(schema)
    cache.validate(["sku", 3], schema, "prefix-items", "input")
    with pytest.raises(GatewayError) as exc:
        cache.validate([3, "sku"], schema, "prefix-items-invalid", "input")

    assert exc.value.code == "SCHEMA_INPUT_INVALID"
    assert exc.value.details["path"] == [0]
    assert exc.value.details["keyword"] == "type"


def test_reusing_cache_key_reuses_compiled_validator():
    schema = {"type": "integer"}
    cache = SchemaValidatorCache()

    cache.validate(1, schema, "shared", "input")
    cache.validate(2, schema, "shared", "input")

    assert len(cache._validators) == 1


def test_same_cache_key_with_different_schema_uses_schema_fingerprint():
    cache = SchemaValidatorCache()

    cache.validate(1, {"type": "integer"}, "shared", "input")
    cache.validate("one", {"type": "string"}, "shared", "input")

    assert len(cache._validators) == 2


def test_non_string_schema_key_cannot_collide_with_string_key():
    cache = SchemaValidatorCache()
    non_string_key_schema = {
        "type": "object",
        "properties": {1: {"type": "integer"}},
    }
    string_key_schema = {
        "type": "object",
        "properties": {"1": {"type": "integer"}},
    }

    with pytest.raises(GatewayError) as definition_exc:
        cache.validate(
            {"1": "invalid"},
            non_string_key_schema,
            "key-collision",
            "input",
        )

    assert definition_exc.value.code == "SCHEMA_DEFINITION_INVALID"
    assert definition_exc.value.details == {
        "path": ["properties"],
        "schema_path": ["properties"],
        "keyword": "json",
    }

    with pytest.raises(GatewayError) as validation_exc:
        cache.validate(
            {"1": "invalid"},
            string_key_schema,
            "key-collision",
            "input",
        )

    assert validation_exc.value.code == "SCHEMA_INPUT_INVALID"


def test_tuple_schema_cannot_hit_cached_list_schema():
    cache = SchemaValidatorCache()
    list_schema = {
        "type": "object",
        "required": ["name"],
    }
    tuple_schema = {
        "type": "object",
        "required": ("name",),
    }

    cache.validate({"name": "Ada"}, list_schema, "container-collision", "input")

    with pytest.raises(GatewayError) as exc:
        cache.validate(
            {"name": "Ada"},
            tuple_schema,
            "container-collision",
            "input",
        )

    assert exc.value.code == "SCHEMA_DEFINITION_INVALID"
    assert exc.value.details == {
        "path": ["required"],
        "schema_path": ["required"],
        "keyword": "json",
    }


def test_mutating_caller_schema_does_not_corrupt_cached_validator():
    schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
    }
    fresh_original_schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
    }
    cache = SchemaValidatorCache()

    cache.validate({"count": 1}, schema, "mutable", "input")
    schema["properties"]["count"]["type"] = "string"  # type: ignore[index]

    cache.validate({"count": 2}, fresh_original_schema, "mutable", "input")


def test_schema_is_snapshotted_before_fingerprinting(monkeypatch):
    schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
    }
    canonical_schema = schema_validation._canonical_schema

    def canonicalize_while_caller_mutates(candidate: dict[str, object]) -> bytes:
        result = canonical_schema(candidate)
        schema["properties"]["count"]["type"] = "string"  # type: ignore[index]
        return result

    monkeypatch.setattr(
        schema_validation,
        "_canonical_schema",
        canonicalize_while_caller_mutates,
    )
    cache = SchemaValidatorCache()

    cache.validate({"count": 1}, schema, "snapshot-order", "input")

    validator = next(iter(cache._validators.values()))
    assert validator.schema["properties"]["count"]["type"] == "integer"


def test_multiple_validation_errors_are_sorted_deterministically():
    cache = SchemaValidatorCache()
    schema = {
        "type": "object",
        "properties": {
            "b": {"type": "integer"},
            "a": {"type": "integer"},
        },
    }

    with pytest.raises(GatewayError) as exc:
        cache.validate(
            {"b": "invalid-b", "a": "invalid-a"},
            schema,
            "deterministic",
            "input",
        )

    assert exc.value.details == {
        "path": ["a"],
        "schema_path": ["properties", "a", "type"],
        "keyword": "type",
    }


def test_multiple_array_errors_are_sorted_by_numeric_index():
    cache = SchemaValidatorCache()
    instance: list[object] = [0] * 11
    instance[2] = "invalid-two"
    instance[10] = "invalid-ten"

    with pytest.raises(GatewayError) as exc:
        cache.validate(
            instance,
            {"type": "array", "items": {"type": "integer"}},
            "numeric-order",
            "input",
        )

    assert exc.value.details["path"] == [2]


def test_invalid_direction_is_rejected_without_arbitrary_gateway_code():
    cache = SchemaValidatorCache()

    with pytest.raises(ValueError, match="direction must be 'input' or 'output'"):
        cache.validate(1, {"type": "integer"}, "direction", "sideways")  # type: ignore[arg-type]
