#!/usr/bin/env python3
"""Validate result structure, source integrity, and bounded evidence claims."""

import argparse
import hashlib
import json
import os
import re
import stat
import sys


SOURCE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
PLACEHOLDER_RE = re.compile(r"^(?:TBD|TODO)$", re.IGNORECASE)
ARRAY_INDEX_RE = re.compile(r"^(?:0|[1-9][0-9]*)$")
TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml",
    ".xml", ".html", ".htm", ".py", ".tex", ".log", ".rst", ".srt",
}
SCHEMA_TYPES = {"null", "boolean", "object", "array", "number", "integer", "string"}
SCHEMA_ANNOTATIONS = {
    "$schema", "$id", "$anchor", "$comment", "title", "description", "default",
    "examples", "deprecated", "readOnly", "writeOnly",
}
SCHEMA_CORE = {
    "type", "required", "properties", "enum", "items", "additionalItems",
    "additionalProperties",
}
SCHEMA_ADVANCED = {
    "$ref", "$defs", "definitions", "allOf", "anyOf", "oneOf", "not", "if",
    "then", "else", "dependentRequired", "dependentSchemas", "dependencies",
    "patternProperties", "propertyNames", "unevaluatedProperties", "const",
    "format", "pattern", "minLength", "maxLength", "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minItems",
    "maxItems", "uniqueItems", "contains", "minContains", "maxContains",
    "unevaluatedItems", "minProperties", "maxProperties", "contentEncoding",
    "contentMediaType", "contentSchema",
}
SCHEMA_STRONG_MARKERS = {
    "$schema", "properties", "required", "items", "$ref", "allOf", "anyOf",
    "oneOf", "not", "if", "then", "else", "const", "$defs", "definitions",
}
EVIDENCE_PATH_KEYS = ("path", "file_path", "source_path")
EVIDENCE_POINTER_KEYS = ("case_json_pointer", "json_pointer", "pointer", "source_pointer")
QUOTE_KEYS = ("short_quote", "quote")
EXTRACTION_PATH_KEYS = ("extraction_path", "extracted_text_path", "text_path")


class InputError(Exception):
    pass


class MachineArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError(message)


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.checked = {
            "strict_json": {},
            "case_id": {"checked": False},
            "output_contract": {"checked": False},
            "inspection_case_fingerprint": {"checked": False},
            "evidence": [],
            "evidence_map": {"provided": False, "checked": False},
            "exact_placeholders": {"checked": False, "findings": 0},
            "duplicate_identifiers": {"checked": False, "findings": 0},
        }

    def error(self, code, message, pointer=None, **details):
        item = {"code": code, "message": message}
        if pointer is not None:
            item["pointer"] = pointer
        item.update(details)
        self.errors.append(item)

    def warning(self, code, message, pointer=None, **details):
        item = {"code": code, "message": message}
        if pointer is not None:
            item["pointer"] = pointer
        item.update(details)
        self.warnings.append(item)

    def finish(self):
        return {
            "valid": not self.errors,
            "errors": self.errors,
            "warnings": self.warnings,
            "checked": self.checked,
        }


def pointer_escape(token):
    return str(token).replace("~", "~0").replace("/", "~1")


def child_pointer(pointer, token):
    return pointer + "/" + pointer_escape(token)


def json_type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def values_equal(left, right, schema_numeric=False):
    pending = [(left, right)]
    while pending:
        a, b = pending.pop()
        numeric = (
            schema_numeric
            and isinstance(a, (int, float)) and not isinstance(a, bool)
            and isinstance(b, (int, float)) and not isinstance(b, bool)
        )
        if not numeric and type(a) is not type(b):
            return False
        if isinstance(a, dict):
            if len(a) != len(b) or set(a) != set(b):
                return False
            pending.extend((a[key], b[key]) for key in a)
        elif isinstance(a, list):
            if len(a) != len(b):
                return False
            pending.extend(zip(a, b))
        elif a != b:
            return False
    return True


def reject_constant(value):
    raise InputError("non-finite JSON number is forbidden: %s" % value)


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError("duplicate JSON object key: %r" % key)
        result[key] = value
    return result


def load_strict_json(path, label):
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise InputError("cannot read %s %s: %s" % (label, path, exc))
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError("%s is not valid UTF-8: %s" % (label, exc))
    try:
        value = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except InputError:
        raise
    except json.JSONDecodeError as exc:
        raise InputError(
            "%s is not strict JSON at line %d column %d: %s"
            % (label, exc.lineno, exc.colno, exc.msg)
        )
    except RecursionError:
        raise InputError("%s exceeds the JSON decoder's nesting limit" % label)
    return value, raw


def normalize_whitespace(value):
    return " ".join(value.split())


def decode_pointer_token(token):
    if re.search(r"~(?![01])", token):
        raise ValueError("invalid RFC 6901 escape in token %r" % token)
    return token.replace("~1", "/").replace("~0", "~")


def resolve_json_pointer(document, pointer):
    if not isinstance(pointer, str):
        raise ValueError("JSON Pointer must be a string")
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError("RFC 6901 JSON Pointer must be empty or start with '/'")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = decode_pointer_token(raw_token)
        if isinstance(current, dict):
            if token not in current:
                raise KeyError("object member %r does not exist" % token)
            current = current[token]
        elif isinstance(current, list):
            if not ARRAY_INDEX_RE.match(token):
                raise KeyError("array index %r is invalid or non-existent" % token)
            index = int(token)
            if index >= len(current):
                raise KeyError("array index %d is out of range" % index)
            current = current[index]
        else:
            raise KeyError("cannot descend through %s with token %r" % (json_type(current), token))
    return current


def find_occurrences(document, wanted_key):
    found = []
    stack = [(document, "")]
    while stack:
        value, pointer = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                path = child_pointer(pointer, key)
                if key == wanted_key:
                    found.append({"pointer": path, "value": child})
                stack.append((child, path))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                stack.append((child, child_pointer(pointer, index)))
    found.sort(key=lambda item: item["pointer"])
    return found


def unique_occurrence_value(occurrences):
    if not occurrences:
        return "missing", None
    first = occurrences[0]["value"]
    if all(values_equal(first, item["value"]) for item in occurrences[1:]):
        return ("unique" if len(occurrences) == 1 else "repeated_equal"), first
    return "conflict", None


def canonical_occurrence(case, occurrences, wanted_key):
    root_pointer = child_pointer("", wanted_key)
    root = [item for item in occurrences if item["pointer"] == root_pointer]
    if root and isinstance(case, dict) and wanted_key in case:
        value = case[wanted_key]
        differences = [
            item for item in occurrences
            if item["pointer"] != root_pointer and not values_equal(value, item["value"])
        ]
        return "root", value, root_pointer, differences
    status, value = unique_occurrence_value(occurrences)
    pointer = occurrences[0]["pointer"] if status in ("unique", "repeated_equal") else None
    return status, value, pointer, []


def validate_inspection_fingerprint(inspection, case_raw, case_path, report):
    state = {"checked": False}
    report.checked["inspection_case_fingerprint"] = state
    if not isinstance(inspection, dict):
        report.error("invalid_inspection", "Inspection top level must be an object.")
        return
    case_file = inspection.get("case_file")
    if not isinstance(case_file, dict):
        report.warning(
            "inspection_case_fingerprint_unavailable",
            "Inspection has no usable case_file fingerprint; evidence registries cannot be tied to this case by fingerprint.",
        )
        state["status"] = "unavailable"
        return
    source_id = case_file.get("source_id")
    actual_id = "sha256:" + hashlib.sha256(case_raw).hexdigest()
    state.update(
        {
            "checked": True,
            "expected_source_id": source_id,
            "actual_source_id": actual_id,
            "inspection_path": case_file.get("path"),
            "case_path": os.path.abspath(case_path),
        }
    )
    if not isinstance(source_id, str) or not SOURCE_ID_RE.match(source_id):
        report.error("invalid_inspection_case_fingerprint", "Inspection case_file.source_id is missing or malformed.")
        state["status"] = "malformed"
        return
    if case_file.get("bytes") is not None and case_file.get("bytes") != len(case_raw):
        report.error(
            "inspection_case_size_mismatch",
            "Inspection case byte count differs from the current case file.",
            expected_bytes=case_file.get("bytes"), actual_bytes=len(case_raw),
        )
        state["status"] = "mismatch"
        return
    if source_id != actual_id:
        report.error(
            "inspection_case_hash_mismatch",
            "Inspection was not made from the current case bytes; rerun inspect_case.",
            expected_source_id=source_id, actual_source_id=actual_id,
        )
        state["status"] = "mismatch"
        return
    state["status"] = "matched"


def validate_case_id(case, result, report):
    occurrences = find_occurrences(case, "case_id")
    selection_status, expected, canonical_pointer, differences = canonical_occurrence(
        case, occurrences, "case_id"
    )
    state = {
        "checked": False,
        "status": selection_status,
        "selection": selection_status,
        "canonical_pointer": canonical_pointer,
        "case_occurrence_pointers": [item["pointer"] for item in occurrences],
    }
    report.checked["case_id"] = state
    for item in differences:
        report.warning(
            "nested_case_id_differs_from_root",
            "Root case_id is canonical; this different nested value is retained as a non-fatal diagnostic.",
            item["pointer"], root_pointer=canonical_pointer, root_value=expected,
            nested_value=item["value"],
        )
    if selection_status == "missing":
        report.error("case_id_missing_in_case", "No case_id occurs in the actual case; equality cannot be established.")
        return selection_status, expected
    if selection_status == "conflict":
        report.error(
            "case_id_conflict_in_case",
            "Without a root case_id, conflicting fallback occurrences remain ambiguous; no value is selected.",
            pointers=state["case_occurrence_pointers"],
        )
        return selection_status, expected
    if "case_id" not in result:
        report.error("case_id_missing_in_result", "Result must contain top-level case_id.", "/case_id")
        return selection_status, expected
    state["checked"] = True
    state["expected"] = expected
    state["actual"] = result["case_id"]
    if not values_equal(expected, result["case_id"]):
        report.error(
            "case_id_mismatch",
            "Result case_id does not exactly equal the canonical root/fallback identity (including JSON type).",
            "/case_id", expected=expected, actual=result["case_id"],
        )
        state["status"] = "mismatch"
    else:
        state["status"] = "matched"
    return selection_status, expected


def recognize_contract(contract):
    if isinstance(contract, bool):
        return "json_schema", "boolean_json_schema"
    if not isinstance(contract, dict) or not contract:
        return "unrecognized", "a non-empty object template or a JSON Schema object/boolean is required"
    keys = set(contract)
    if "$schema" in keys or keys & SCHEMA_STRONG_MARKERS:
        return "json_schema", "explicit_marker" if "$schema" in keys else "structural_keywords"
    schema_value_markers = keys & {"type", "enum", "additionalProperties", "additionalItems"}
    if schema_value_markers:
        if keys <= SCHEMA_CORE | SCHEMA_ANNOTATIONS | SCHEMA_ADVANCED:
            return "json_schema", "schema_only_keyword_inference"
        return "unrecognized", "schema-like keywords are mixed with possible template fields"
    return "field_template", "literal_template"


def template_value_type(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    return json_type(value)


def validate_template(contract, result, contract_pointer, report):
    state = {
        "checked": True,
        "kind": "field_template",
        "contract_pointer": contract_pointer,
        "semantics": (
            "Template object members are required recursively and null is a type wildcard. "
            "Empty arrays are type-only; a single object item is an inferred per-item template with warning; "
            "other array templates are type-only with warning. Array counts and domain semantics are not claimed."
        ),
        "array_modes": [],
    }
    if isinstance(contract, dict) and len(contract) == 1 and isinstance(next(iter(contract.values())), dict):
        report.warning(
            "template_wrapping_root_ambiguous",
            "The template has one object-valued root field. No wrapper is removed or inferred; validation is anchored at the result root.",
            contract_pointer,
        )
    pending = [(contract, result, "", contract_pointer)]
    fields_checked = 0
    while pending:
        template, instance, result_pointer, schema_pointer = pending.pop()
        if template is None:
            continue
        expected_type = template_value_type(template)
        if template_value_type(instance) != expected_type:
            report.error(
                "template_type_mismatch",
                "Template expected JSON value type %s, got %s."
                % (expected_type, template_value_type(instance)),
                result_pointer, contract_pointer=schema_pointer,
                expected_type=expected_type, actual_type=template_value_type(instance),
            )
            continue
        fields_checked += 1
        if isinstance(template, dict):
            for key, child in template.items():
                child_result_pointer = child_pointer(result_pointer, key)
                if key not in instance:
                    report.error(
                        "template_field_missing",
                        "Original output_contract field %r is missing at the same result path." % key,
                        child_result_pointer, contract_pointer=child_pointer(schema_pointer, key),
                    )
                    continue
                pending.append(
                    (child, instance[key], child_result_pointer, child_pointer(schema_pointer, key))
                )
        elif isinstance(template, list):
            mode = {
                "result_pointer": result_pointer,
                "contract_pointer": schema_pointer,
                "actual_length": len(instance),
            }
            if not template:
                mode["mode"] = "type_only_empty_template"
                state["array_modes"].append(mode)
                continue
            if len(template) == 1 and isinstance(template[0], dict):
                mode["mode"] = "inferred_object_item_template"
                state["array_modes"].append(mode)
                report.warning(
                    "item_template_inference",
                    "A single object array item is treated only as a per-item structural example. Array count, item identity, and domain semantics are not verified.",
                    result_pointer, contract_pointer=schema_pointer,
                    template_item_count=1, actual_item_count=len(instance),
                )
                for index, item in enumerate(instance):
                    pending.append(
                        (
                            template[0], item, child_pointer(result_pointer, index),
                            child_pointer(schema_pointer, 0),
                        )
                    )
                continue
            mode["mode"] = "type_only_unrecognized_array_template"
            state["array_modes"].append(mode)
            report.warning(
                "template_array_items_unverified",
                "This array template is not an empty type marker or recognizable single-object item example. Only the result array type is checked; no positional comparison or count validation is claimed.",
                result_pointer, contract_pointer=schema_pointer,
                template_item_count=len(template), actual_item_count=len(instance),
            )
    state["values_type_checked"] = fields_checked
    return state


def instance_matches_type(instance, expected):
    if expected == "null":
        return instance is None
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "object":
        return isinstance(instance, dict)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "integer":
        return (
            isinstance(instance, int) and not isinstance(instance, bool)
        ) or (isinstance(instance, float) and instance.is_integer())
    if expected == "string":
        return isinstance(instance, str)
    return False


def validate_json_schema(schema, result, contract_pointer, report, recognition):
    state = {
        "checked": True,
        "kind": "json_schema_common_core",
        "contract_pointer": contract_pointer,
        "recognition": recognition,
        "implemented": [
            "boolean schemas", "required", "type", "properties", "enum", "array items",
            "positional items/additionalItems", "additionalProperties",
        ],
        "unverified_keywords": [],
    }
    if recognition != "explicit_marker" and recognition != "boolean_json_schema":
        report.warning(
            "json_schema_style_inferred",
            "JSON Schema style was inferred from actual keywords, not assumed from a filename or external schema.",
            contract_pointer, recognition=recognition,
        )
    pending = [(schema, result, "", contract_pointer)]
    values_checked = 0
    while pending:
        current_schema, instance, result_pointer, schema_pointer = pending.pop()
        if isinstance(current_schema, bool):
            values_checked += 1
            if not current_schema:
                report.error(
                    "json_schema_false",
                    "A false JSON Schema rejects every instance.",
                    result_pointer, contract_pointer=schema_pointer,
                )
            continue
        if not isinstance(current_schema, dict):
            report.error(
                "invalid_json_schema",
                "Every schema or subschema used by the common-core validator must be an object or boolean.",
                result_pointer, contract_pointer=schema_pointer,
                actual_type=json_type(current_schema),
            )
            continue
        values_checked += 1
        advanced = sorted(set(current_schema) & SCHEMA_ADVANCED)
        if advanced:
            state["unverified_keywords"].extend(
                {"contract_pointer": child_pointer(schema_pointer, key), "keyword": key}
                for key in advanced
            )
            report.warning(
                "unverified_json_schema_keywords",
                "These JSON Schema keywords/applicators are explicitly NOT enforced by this common-core validator: %s."
                % ", ".join(advanced),
                schema_pointer, keywords=advanced,
            )
        if "type" in current_schema:
            declared = current_schema["type"]
            if isinstance(declared, str):
                types = [declared]
            elif isinstance(declared, list) and all(isinstance(item, str) for item in declared):
                types = declared
            else:
                report.error(
                    "invalid_json_schema_type",
                    "Schema type must be a string or list of strings.",
                    result_pointer, contract_pointer=child_pointer(schema_pointer, "type"),
                )
                types = []
            if not types or len(set(types)) != len(types) or any(item not in SCHEMA_TYPES for item in types):
                report.error(
                    "invalid_json_schema_type",
                    "Schema type contains an empty, duplicate, or unknown type declaration: %r." % declared,
                    result_pointer, contract_pointer=child_pointer(schema_pointer, "type"),
                )
            elif not any(instance_matches_type(instance, item) for item in types):
                report.error(
                    "json_schema_type_mismatch",
                    "Instance does not match schema type %s." % ", ".join(types),
                    result_pointer, contract_pointer=child_pointer(schema_pointer, "type"),
                    expected_type=declared, actual_type=json_type(instance),
                )
        if "enum" in current_schema:
            choices = current_schema["enum"]
            if not isinstance(choices, list):
                report.error(
                    "invalid_json_schema_enum",
                    "Schema enum must be an array.",
                    result_pointer, contract_pointer=child_pointer(schema_pointer, "enum"),
                )
            elif not any(values_equal(instance, choice, schema_numeric=True) for choice in choices):
                report.error(
                    "json_schema_enum_mismatch",
                    "Instance is not one of the schema enum values.",
                    result_pointer, contract_pointer=child_pointer(schema_pointer, "enum"),
                    allowed=choices,
                )
        required = current_schema.get("required")
        if "required" in current_schema:
            if (
                not isinstance(required, list)
                or not all(isinstance(item, str) for item in required)
                or len(set(required)) != len(required)
            ):
                report.error(
                    "invalid_json_schema_required",
                    "Schema required must be an array of unique strings.",
                    result_pointer, contract_pointer=child_pointer(schema_pointer, "required"),
                )
                required = []
            if isinstance(instance, dict):
                for key in required:
                    if key not in instance:
                        report.error(
                            "json_schema_required_missing",
                            "Required object member %r is missing." % key,
                            child_pointer(result_pointer, key),
                            contract_pointer=child_pointer(schema_pointer, "required"),
                        )
        properties = current_schema.get("properties")
        if "properties" in current_schema and not isinstance(properties, dict):
            report.error(
                "invalid_json_schema_properties",
                "Schema properties must be an object.",
                result_pointer, contract_pointer=child_pointer(schema_pointer, "properties"),
            )
            properties = {}
        if isinstance(instance, dict) and isinstance(properties, dict):
            for key, subschema in properties.items():
                if key in instance:
                    pending.append(
                        (
                            subschema, instance[key], child_pointer(result_pointer, key),
                            child_pointer(child_pointer(schema_pointer, "properties"), key),
                        )
                    )
        if "additionalProperties" in current_schema:
            additional = current_schema["additionalProperties"]
            if not isinstance(additional, (dict, bool)):
                report.error(
                    "invalid_json_schema_additional_properties",
                    "additionalProperties must be an object or boolean in this validator.",
                    result_pointer, contract_pointer=child_pointer(schema_pointer, "additionalProperties"),
                )
            elif isinstance(instance, dict):
                if "patternProperties" in current_schema:
                    report.warning(
                        "additional_properties_not_enforced_with_pattern_properties",
                        "patternProperties is unverified; additionalProperties is not enforced here because their interaction cannot be decided safely.",
                        child_pointer(schema_pointer, "additionalProperties"),
                    )
                else:
                    known = set(properties) if isinstance(properties, dict) else set()
                    for key, value in instance.items():
                        if key in known:
                            continue
                        child_result_pointer = child_pointer(result_pointer, key)
                        if additional is False:
                            report.error(
                                "json_schema_additional_property",
                                "additionalProperties=false rejects member %r." % key,
                                child_result_pointer,
                                contract_pointer=child_pointer(schema_pointer, "additionalProperties"),
                            )
                        elif isinstance(additional, dict):
                            pending.append(
                                (
                                    additional, value, child_result_pointer,
                                    child_pointer(schema_pointer, "additionalProperties"),
                                )
                            )
        if "items" in current_schema:
            items = current_schema["items"]
            if not isinstance(items, (dict, list, bool)):
                report.error(
                    "invalid_json_schema_items",
                    "items must be a schema object, boolean, or positional schema array.",
                    result_pointer, contract_pointer=child_pointer(schema_pointer, "items"),
                )
                items = None
            if isinstance(instance, list) and items is not None:
                if isinstance(items, (dict, bool)):
                    for index, value in enumerate(instance):
                        pending.append(
                            (
                                items, value, child_pointer(result_pointer, index),
                                child_pointer(schema_pointer, "items"),
                            )
                        )
                else:
                    for index, subschema in enumerate(items):
                        if index < len(instance):
                            pending.append(
                                (
                                    subschema, instance[index], child_pointer(result_pointer, index),
                                    child_pointer(child_pointer(schema_pointer, "items"), index),
                                )
                            )
                    if len(instance) > len(items):
                        additional_items = current_schema.get("additionalItems", True)
                        if not isinstance(additional_items, (dict, bool)):
                            report.error(
                                "invalid_json_schema_additional_items",
                                "additionalItems must be a schema object or boolean.",
                                result_pointer, contract_pointer=child_pointer(schema_pointer, "additionalItems"),
                            )
                        elif additional_items is False:
                            for index in range(len(items), len(instance)):
                                report.error(
                                    "json_schema_additional_item",
                                    "additionalItems=false rejects array index %d." % index,
                                    child_pointer(result_pointer, index),
                                    contract_pointer=child_pointer(schema_pointer, "additionalItems"),
                                )
                        elif isinstance(additional_items, dict):
                            for index in range(len(items), len(instance)):
                                pending.append(
                                    (
                                        additional_items, instance[index], child_pointer(result_pointer, index),
                                        child_pointer(schema_pointer, "additionalItems"),
                                    )
                                )
        elif "additionalItems" in current_schema:
            report.warning(
                "additional_items_without_positional_items",
                "additionalItems is ignored when items is not a positional schema array.",
                child_pointer(schema_pointer, "additionalItems"),
            )
    state["values_checked"] = values_checked
    return state


def validate_output_contract(case, result, report):
    occurrences = find_occurrences(case, "output_contract")
    status, contract, contract_pointer, differences = canonical_occurrence(
        case, occurrences, "output_contract"
    )
    base = {
        "status": status,
        "selection": status,
        "canonical_pointer": contract_pointer,
        "occurrence_pointers": [item["pointer"] for item in occurrences],
        "checked": False,
    }
    report.checked["output_contract"] = base
    for item in differences:
        report.warning(
            "nested_output_contract_differs_from_root",
            "Root output_contract is canonical; this nested value is retained as a non-fatal diagnostic.",
            item["pointer"], root_pointer=contract_pointer, nested_value=item["value"],
        )
    if status == "missing":
        report.warning(
            "output_contract_missing_in_case",
            "No output_contract occurs in the case. No contract is invented and no contract check is claimed.",
        )
        base["status"] = "unavailable"
        return
    if status == "conflict":
        report.error(
            "output_contract_conflict_in_case",
            "Without a root output_contract, conflicting fallback occurrences remain ambiguous; no contract pass is claimed.",
            pointers=base["occurrence_pointers"],
        )
        return
    kind, recognition = recognize_contract(contract)
    base["recognition"] = recognition
    base["contract_pointer"] = contract_pointer
    if kind == "field_template":
        report.checked["output_contract"] = validate_template(contract, result, contract_pointer, report)
        base.update(
            checked=True, kind="field_template",
            values_type_checked=report.checked["output_contract"]["values_type_checked"],
        )
        report.checked["output_contract"]["occurrence_pointers"] = base["occurrence_pointers"]
        report.checked["output_contract"]["recognition"] = recognition
        report.checked["output_contract"]["selection"] = status
        report.checked["output_contract"]["status"] = status
        report.checked["output_contract"]["canonical_pointer"] = contract_pointer
    elif kind == "json_schema":
        report.checked["output_contract"] = validate_json_schema(
            contract, result, contract_pointer, report, recognition
        )
        report.checked["output_contract"]["occurrence_pointers"] = base["occurrence_pointers"]
    else:
        report.error(
            "output_contract_unrecognized",
            "The original output_contract cannot be recognized without guessing: %s." % recognition,
            contract_pointer,
        )
        base["status"] = "unrecognized"


def scalar_identity(value):
    return (json_type(value), json.dumps(value, ensure_ascii=False, allow_nan=False))


def empty_review_scope():
    return {"values": {}, "invalid": set(), "conflict": False}


def review_scope_category(key, key_context):
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    if normalized in ("plan_id", "candidate_id"):
        return normalized
    if normalized in ("plan_version", "plan_version_id"):
        return "plan_version"
    if normalized in ("candidate_version", "candidate_version_id"):
        return "candidate_version"
    context = key_context.lower()
    if normalized in ("version", "version_id"):
        if "plan" in context:
            return "plan_version"
        if "candidate" in context:
            return "candidate_version"
    return None


def extract_review_scope(item, key_context):
    scope = empty_review_scope()
    if not isinstance(item, dict):
        return scope
    for key, child in item.items():
        category = review_scope_category(key, key_context)
        if category is None:
            continue
        if child is None or isinstance(child, (dict, list)) or (isinstance(child, str) and not child.strip()):
            scope["invalid"].add(category)
        else:
            scope["values"][category] = scalar_identity(child)
    return scope


def merge_review_scope(inherited, current):
    merged = {
        "values": dict(inherited["values"]),
        "invalid": set(inherited["invalid"]) | set(current["invalid"]),
        "conflict": inherited["conflict"] or current["conflict"],
    }
    for category, identity in current["values"].items():
        if category in merged["values"] and merged["values"][category] != identity:
            merged["conflict"] = True
        else:
            merged["values"][category] = identity
    return merged


def validate_placeholders_and_ids(result, report):
    placeholder_count = 0
    duplicate_count = 0
    unresolved_scope_count = 0
    stack = [(result, "", "", empty_review_scope())]
    while stack:
        value, pointer, key_context, inherited_scope = stack.pop()
        if isinstance(value, str) and PLACEHOLDER_RE.match(value.strip()):
            report.error(
                "exact_placeholder_present",
                "Exact placeholder %r is not a completed value." % value.strip(),
                pointer,
            )
            placeholder_count += 1
        if isinstance(value, dict):
            current_scope = merge_review_scope(
                inherited_scope, extract_review_scope(value, key_context)
            )
            for key, child in value.items():
                stack.append((child, child_pointer(pointer, key), key, current_scope))
        elif isinstance(value, list):
            item_scopes = [
                merge_review_scope(inherited_scope, extract_review_scope(item, key_context))
                for item in value
            ]
            for index, child in enumerate(value):
                stack.append((child, child_pointer(pointer, index), key_context, item_scopes[index]))
            if value and all(isinstance(item, dict) for item in value):
                signatures = {frozenset(scope["values"]) for scope in item_scopes}
                scope_consistent = (
                    all(not scope["invalid"] and not scope["conflict"] for scope in item_scopes)
                    and len(signatures) == 1
                    and any(scope["values"] for scope in item_scopes)
                )
                seen = {}
                unresolved_seen = {}
                context = key_context.lower()
                for index, item in enumerate(value):
                    scope_identity = tuple(sorted(item_scopes[index]["values"].items()))
                    for key, child in item.items():
                        normalized = key.lower().replace("-", "_").replace(" ", "_")
                        is_check_id = normalized == "check_id" or (
                            normalized == "id" and "check" in context
                        )
                        is_version = normalized in ("version", "plan_version") and any(
                            term in context for term in ("plan", "candidate", "version")
                        )
                        if not (is_check_id or is_version) or child is None:
                            continue
                        if isinstance(child, (dict, list)) or (isinstance(child, str) and not child.strip()):
                            continue
                        category = "check_id" if is_check_id else "version"
                        item_pointer = child_pointer(child_pointer(pointer, index), key)
                        identifier_key = (category, key, scalar_identity(child))
                        if not scope_consistent:
                            if identifier_key in unresolved_seen:
                                report.warning(
                                    "duplicate_identifier_scope_unresolved",
                                    "Repeated identifier has missing, inconsistent, or conflicting plan/version/candidate scope; it is not classified as same-scope or cross-scope duplication.",
                                    item_pointer, first_pointer=unresolved_seen[identifier_key],
                                    value=child, category=category,
                                )
                                unresolved_scope_count += 1
                            else:
                                unresolved_seen[identifier_key] = item_pointer
                            continue
                        dedupe_key = identifier_key + (scope_identity,)
                        if dedupe_key in seen:
                            report.error(
                                "duplicate_%s" % category,
                                "Duplicate %s value within the same identifiable plan/version/candidate scope." % category,
                                item_pointer, first_pointer=seen[dedupe_key], value=child,
                                scope=[list(entry) for entry in scope_identity],
                            )
                            duplicate_count += 1
                        else:
                            seen[dedupe_key] = item_pointer
    report.checked["exact_placeholders"] = {"checked": True, "findings": placeholder_count}
    report.checked["duplicate_identifiers"] = {
        "checked": True, "findings": duplicate_count,
        "scope_unresolved": unresolved_scope_count,
    }


def sha256_file(path):
    digest = hashlib.sha256()
    total = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
    return "sha256:" + digest.hexdigest(), total


class SourceRegistry:
    def __init__(self, inspection, case_path, report):
        self.report = report
        self.case_path = os.path.abspath(case_path)
        self.case_directory = os.path.dirname(self.case_path)
        self.resource_root = None
        self.by_path = {}
        self.by_id = {}
        self.by_case_pointer = {}
        self.entries = []
        self.available = False
        if not isinstance(inspection, dict):
            report.error("invalid_source_registry", "Inspection must be an object to provide a source registry.")
            return
        root = inspection.get("resource_root")
        if isinstance(root, str) and root:
            self.resource_root = os.path.abspath(root)
        else:
            report.warning(
                "resource_root_unavailable_in_inspection",
                "Relative evidence paths can only be resolved against the case directory unless an entry already has an absolute registered path.",
            )
        registry = inspection.get("source_registry")
        raw_entries = registry.get("sources") if isinstance(registry, dict) else None
        if not isinstance(raw_entries, list):
            report.error("invalid_source_registry", "Inspection source_registry.sources must be an array.")
            return
        for index, entry in enumerate(raw_entries):
            pointer = "/source_registry%s" % child_pointer("/sources", index)
            if not isinstance(entry, dict):
                report.error("invalid_source_registry_entry", "Registry entry must be an object.", pointer)
                continue
            source_id = entry.get("source_id")
            path = entry.get("path")
            if not isinstance(source_id, str) or not SOURCE_ID_RE.match(source_id):
                report.error("invalid_source_id_in_registry", "Registry source_id is missing or malformed.", pointer)
                continue
            if not isinstance(path, str) or not path:
                report.error("invalid_source_path_in_registry", "Registry path is missing or not a string.", pointer)
                continue
            normalized = dict(entry)
            normalized["path"] = os.path.abspath(path)
            if not isinstance(normalized.get("extension"), str):
                normalized["extension"] = os.path.splitext(path)[1].lower()
            normalized["case_json_pointers"] = (
                entry.get("case_json_pointers") if isinstance(entry.get("case_json_pointers"), list) else []
            )
            self.by_path.setdefault(normalized["path"], {})[source_id] = normalized
            self.by_id.setdefault(source_id, {})[normalized["path"]] = normalized
            for case_pointer in normalized["case_json_pointers"]:
                if isinstance(case_pointer, str):
                    self.by_case_pointer.setdefault(case_pointer, {})[normalized["path"]] = normalized
            self.entries.append(normalized)
        for path, variants in self.by_path.items():
            if len(variants) > 1:
                report.error(
                    "conflicting_registry_path",
                    "One registered path has conflicting source_id values; no entry is selected.",
                    path=path, source_ids=sorted(variants),
                )
        self.available = True
        if not self.by_path:
            report.warning(
                "no_registered_sources",
                "The inspection registry has no usable sources; evidence can only remain partial, never source-satisfied.",
            )

    def unique_path_entry(self, path):
        variants = self.by_path.get(path, {})
        if len(variants) == 1:
            return next(iter(variants.values()))
        return None

    def resolve_path(self, raw_path, evidence_pointer):
        if not isinstance(raw_path, str) or not raw_path:
            self.report.error(
                "invalid_evidence_path", "Evidence path must be a non-empty string.", evidence_pointer,
                actual_type=json_type(raw_path),
            )
            return None
        if os.path.isabs(raw_path):
            candidates = [os.path.abspath(raw_path)]
        else:
            candidates = []
            if self.resource_root:
                candidates.append(os.path.abspath(os.path.join(self.resource_root, raw_path)))
            candidates.append(os.path.abspath(os.path.join(self.case_directory, raw_path)))
        registered = []
        for candidate in dict.fromkeys(candidates):
            if candidate in self.by_path:
                registered.append(candidate)
        if len(registered) != 1:
            if len(registered) > 1:
                self.report.error(
                    "ambiguous_evidence_path",
                    "Relative evidence path resolves to multiple registered files; no file is selected.",
                    evidence_pointer, path=raw_path, candidates=registered,
                )
            else:
                self.report.error(
                    "evidence_path_not_registered",
                    "Evidence path does not resolve exactly to an inspection registry path; suffix matching is not used.",
                    evidence_pointer, path=raw_path, attempted_paths=candidates,
                )
            return None
        entry = self.unique_path_entry(registered[0])
        if entry is None:
            self.report.error(
                "ambiguous_registry_entry", "Registered path has conflicting hashes.", evidence_pointer,
                path=registered[0],
            )
        return entry

    def entry_for_source_id(self, source_id, evidence_pointer):
        paths = self.by_id.get(source_id, {})
        if not paths:
            self.report.error(
                "unknown_evidence_source_id",
                "Evidence source_id is not present in the inspection registry.",
                evidence_pointer, source_id=source_id,
            )
            return None
        if len(paths) == 1:
            return next(iter(paths.values()))
        self.report.warning(
            "source_id_has_multiple_paths",
            "Source_id identifies multiple same-hash paths; evidence must supply path for unique path/locator and quote checks.",
            evidence_pointer, source_id=source_id, paths=sorted(paths),
        )
        return None

    def entry_for_case_pointer(self, case_pointer):
        paths = self.by_case_pointer.get(case_pointer, {})
        if len(paths) == 1:
            return next(iter(paths.values()))
        return None

    def check_hash(self, entry, claimed_source_id, evidence_pointer):
        path = entry["path"]
        registered_id = entry["source_id"]
        try:
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise OSError("not a regular non-symlink file")
            actual_id, actual_size = sha256_file(path)
        except OSError as exc:
            self.report.error(
                "evidence_source_unreadable",
                "Evidence source file cannot be re-read for byte verification: %s." % exc,
                evidence_pointer, path=path,
            )
            return False
        ok = True
        if claimed_source_id is not None and claimed_source_id != registered_id:
            self.report.error(
                "evidence_path_source_id_mismatch",
                "Evidence source_id and path belong to different registry entries.",
                evidence_pointer, path=path, claimed_source_id=claimed_source_id,
                registered_source_id=registered_id,
            )
            ok = False
        if actual_id != registered_id:
            self.report.error(
                "evidence_source_hash_mismatch",
                "Current file bytes do not match the inspection source_id; the evidence hash check fails.",
                evidence_pointer, path=path, registered_source_id=registered_id,
                actual_source_id=actual_id,
            )
            ok = False
        if claimed_source_id is not None and actual_id != claimed_source_id:
            self.report.error(
                "evidence_claimed_hash_mismatch",
                "Current file bytes do not match the source_id claimed by this evidence item.",
                evidence_pointer, path=path, claimed_source_id=claimed_source_id,
                actual_source_id=actual_id,
            )
            ok = False
        registered_bytes = entry.get("bytes")
        if registered_bytes is not None and registered_bytes != actual_size:
            self.report.error(
                "evidence_source_size_mismatch",
                "Current file size differs from inspection registration.",
                evidence_pointer, path=path, registered_bytes=registered_bytes,
                actual_bytes=actual_size,
            )
            ok = False
        return ok


def alias_value(item, names, kind, evidence_pointer, report):
    present = [(key, item[key]) for key in names if key in item and item[key] is not None]
    if not present:
        return None, None
    first_key, first_value = present[0]
    for key, value in present[1:]:
        if not values_equal(first_value, value):
            report.error(
                "conflicting_evidence_%s" % kind,
                "Conflicting alias fields for evidence %s; no value is selected." % kind,
                evidence_pointer, fields=[name for name, _ in present],
            )
            return first_key, None
    return first_key, first_value


def read_text_source(entry, evidence_pointer, report):
    path = entry["path"]
    extension = entry.get("extension")
    if not isinstance(extension, str):
        extension = os.path.splitext(path)[1].lower()
    if extension.lower() not in TEXT_EXTENSIONS:
        report.warning(
            "source_text_not_available",
            "Source text is unavailable because the registered file is not a supported text type; no quote check is claimed.",
            evidence_pointer, path=path, extension=extension,
        )
        return None
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
        return raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        report.warning(
            "source_text_decode_failed",
            "Source text is unavailable as strict UTF-8: %s." % exc,
            evidence_pointer, path=path,
        )
        return None


def provided_pdf_text(item, evidence_pointer, registry, report):
    texts = []
    direct = item.get("extracted_text")
    if isinstance(direct, str):
        texts.append(("provided extracted_text", direct))
    elif direct is not None:
        report.warning(
            "invalid_provided_extraction",
            "extracted_text is present but not a string; it is not used.",
            child_pointer(evidence_pointer, "extracted_text"),
        )
    provided = item.get("provided_extraction")
    if isinstance(provided, dict) and isinstance(provided.get("text"), str):
        texts.append(("provided_extraction.text", provided["text"]))
    extraction_paths = []
    for key in EXTRACTION_PATH_KEYS:
        value = item.get(key)
        if isinstance(value, str):
            extraction_paths.append((key, value))
        elif value is not None:
            report.warning(
                "invalid_extraction_path",
                "Extraction path is not a string and is not used.",
                child_pointer(evidence_pointer, key),
            )
    if isinstance(provided, dict) and isinstance(provided.get("path"), str):
        extraction_paths.append(("provided_extraction.path", provided["path"]))
    for key, raw_path in extraction_paths:
        candidates = [os.path.abspath(raw_path)] if os.path.isabs(raw_path) else []
        if not candidates:
            if registry.resource_root:
                candidates.append(os.path.abspath(os.path.join(registry.resource_root, raw_path)))
            candidates.append(os.path.abspath(os.path.join(registry.case_directory, raw_path)))
        existing = []
        for path in candidates:
            try:
                if stat.S_ISREG(os.lstat(path).st_mode) and not stat.S_ISLNK(os.lstat(path).st_mode):
                    existing.append(path)
            except OSError:
                pass
        if len(existing) != 1:
            report.warning(
                "provided_extraction_unavailable",
                "Provided extraction text path is missing or ambiguous; PDF content remains unverified.",
                child_pointer(evidence_pointer, key), attempted_paths=candidates,
            )
            continue
        try:
            with open(existing[0], "rb") as handle:
                texts.append((key, handle.read().decode("utf-8")))
        except (OSError, UnicodeDecodeError) as exc:
            report.warning(
                "provided_extraction_decode_failed",
                "Provided extraction is not readable strict UTF-8: %s." % exc,
                child_pointer(evidence_pointer, key),
            )
    return texts


def resolve_evidence_pointer(pointer_key, pointer_value, path_entry, case, case_path, registry, evidence_pointer, report):
    if pointer_value is None:
        return {"status": "absent", "value": None, "document": None}
    if not isinstance(pointer_value, str):
        report.error(
            "invalid_evidence_json_pointer",
            "Evidence JSON Pointer must be a string.",
            child_pointer(evidence_pointer, pointer_key), actual_type=json_type(pointer_value),
        )
        return {"status": "invalid", "value": None, "document": None}
    document = case
    document_path = os.path.abspath(case_path)
    if pointer_key == "source_pointer" and path_entry is None:
        report.error(
            "evidence_source_pointer_requires_path",
            "source_pointer requires a uniquely resolved source path; it is not silently reinterpreted as a case pointer.",
            child_pointer(evidence_pointer, pointer_key),
        )
        return {"status": "invalid", "value": None, "document": None}
    if (
        pointer_key == "source_pointer"
        and path_entry is not None
        and os.path.splitext(path_entry["path"])[1].lower() != ".json"
    ):
        report.error(
            "evidence_source_pointer_requires_json",
            "source_pointer is resolved only against JSON documents; non-JSON/PDF bytes are never decoded as JSON.",
            child_pointer(evidence_pointer, pointer_key), path=path_entry["path"],
        )
        return {"status": "invalid", "value": None, "document": None}
    if pointer_key in ("source_pointer",) or (
        pointer_key in ("json_pointer", "pointer")
        and path_entry is not None
        and os.path.splitext(path_entry["path"])[1].lower() == ".json"
        and os.path.abspath(path_entry["path"]) != os.path.abspath(case_path)
    ):
        try:
            with open(path_entry["path"], "rb") as handle:
                raw = handle.read()
            document = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=reject_duplicate_keys,
                parse_constant=reject_constant,
            )
            document_path = path_entry["path"]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, InputError, RecursionError) as exc:
            report.error(
                "evidence_pointed_json_invalid",
                "Pointed JSON source cannot be parsed as strict UTF-8 JSON: %s." % exc,
                child_pointer(evidence_pointer, pointer_key), path=path_entry["path"],
            )
            return {"status": "invalid", "value": None, "document": None}
    try:
        value = resolve_json_pointer(document, pointer_value)
        return {
            "status": "resolved", "value": value, "document": document,
            "document_path": document_path, "pointer": pointer_value,
        }
    except (ValueError, KeyError) as exc:
        report.error(
            "evidence_json_pointer_unresolved",
            "RFC 6901 pointer does not resolve to an existing actual input value: %s." % exc,
            child_pointer(evidence_pointer, pointer_key), source_document=document_path,
            json_pointer=pointer_value,
        )
        return {"status": "invalid", "value": None, "document": document}


def is_evidence_key(key):
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return (
        "evidence" in normalized or "citation" in normalized
        or normalized in ("sources", "source_references", "supporting_sources")
    )


def validate_evidence_item(item, evidence_pointer, case, case_path, registry, report):
    state = {
        "result_pointer": evidence_pointer,
        "source_id_status": "absent",
        "path_status": "absent",
        "json_pointer_status": "absent",
        "hash_status": "not_applicable",
        "quote_status": "not_applicable",
        "locator_content_status": "not_checked",
    }
    report.checked["evidence"].append(state)
    source_key = "source_id" if "source_id" in item and item["source_id"] is not None else None
    claimed_source_id = item.get("source_id") if source_key else None
    if claimed_source_id is not None and not isinstance(claimed_source_id, str):
        report.error(
            "invalid_evidence_source_id", "Evidence source_id must be a string.",
            child_pointer(evidence_pointer, "source_id"), actual_type=json_type(claimed_source_id),
        )
        claimed_source_id = None
        state["source_id_status"] = "invalid"
    elif claimed_source_id is not None:
        if not SOURCE_ID_RE.match(claimed_source_id):
            report.error(
                "invalid_evidence_source_id", "Evidence source_id does not have sha256:<64 lowercase hex> format.",
                child_pointer(evidence_pointer, "source_id"), source_id=claimed_source_id,
            )
            state["source_id_status"] = "invalid"
            claimed_source_id = None
        else:
            state["source_id_status"] = "present"
    path_key, raw_path = alias_value(item, EVIDENCE_PATH_KEYS, "path", evidence_pointer, report)
    pointer_key, source_pointer = alias_value(item, EVIDENCE_POINTER_KEYS, "json_pointer", evidence_pointer, report)
    quote_key, quote = alias_value(item, QUOTE_KEYS, "quote", evidence_pointer, report)
    path_entry = registry.resolve_path(raw_path, child_pointer(evidence_pointer, path_key)) if path_key else None
    if path_key:
        state["path"] = raw_path
        state["path_status"] = "registered" if path_entry is not None else "unresolved"
    id_entry = registry.entry_for_source_id(claimed_source_id, child_pointer(evidence_pointer, "source_id")) if claimed_source_id else None
    if id_entry is not None:
        state["source_id_status"] = "registered"
    elif claimed_source_id is not None and state["source_id_status"] == "present":
        state["source_id_status"] = "unresolved_or_ambiguous"
    if path_entry is not None and id_entry is not None and path_entry["path"] != id_entry["path"]:
        report.error(
            "evidence_source_path_disagreement",
            "Evidence path and uniquely resolved source_id select different files.",
            evidence_pointer, path=path_entry["path"], source_id_path=id_entry["path"],
        )
    entry = path_entry or id_entry
    if entry is None and pointer_key in ("case_json_pointer", "json_pointer", "pointer") and isinstance(source_pointer, str):
        inferred = registry.entry_for_case_pointer(source_pointer)
        if inferred is not None:
            entry = inferred
            state["path_status"] = "inferred_from_unique_case_pointer_registration"
            state["path"] = inferred["path"]
    if entry is not None:
        state["registered_path"] = entry["path"]
        state["registered_source_id"] = entry["source_id"]
        state["hash_status"] = "matched" if registry.check_hash(
            entry, claimed_source_id, evidence_pointer
        ) else "mismatch_or_unreadable"
    pointed = resolve_evidence_pointer(
        pointer_key, source_pointer, entry, case, case_path, registry, evidence_pointer, report
    ) if pointer_key else {"status": "absent", "value": None}
    if pointer_key:
        state["json_pointer"] = source_pointer
        state["json_pointer_status"] = pointed["status"]
    has_quote = quote is not None
    if quote is not None and not isinstance(quote, str):
        report.error(
            "invalid_short_quote", "A short quote must be a string when present.",
            child_pointer(evidence_pointer, quote_key), actual_type=json_type(quote),
        )
        state["quote_status"] = "invalid"
        return state
    has_locator = "locator" in item and item["locator"] is not None
    if entry is None and pointed["status"] != "resolved":
        if has_quote or has_locator:
            report.warning(
                "evidence_source_unavailable_partial",
                "No unique registered source or resolvable input pointer is available. Evidence remains partial; no quote or locator satisfaction is claimed.",
                evidence_pointer,
            )
            if has_quote:
                state["quote_status"] = "partial_no_source_text"
            if has_locator:
                state["locator_content_status"] = "partial_no_source"
        return state
    extension = entry.get("extension", "") if entry else ""
    is_pdf = extension.lower() == ".pdf"
    if is_pdf and (has_quote or has_locator):
        report.warning(
            "pdf_content_not_independently_verified",
            "PDF bytes can be hash-checked, but page/span text and locator semantics require real extraction; raw PDF content is not declared verified.",
            evidence_pointer, path=entry["path"],
        )
        state["locator_content_status"] = "pdf_requires_real_extraction" if has_locator else "not_checked"
    if not has_quote:
        return state
    if not quote.strip():
        report.warning(
            "empty_short_quote", "An empty/whitespace quote cannot verify source text.",
            child_pointer(evidence_pointer, quote_key),
        )
        state["quote_status"] = "partial_empty_quote"
        return state
    texts = []
    if pointed["status"] == "resolved" and isinstance(pointed.get("value"), str):
        texts.append(("JSON Pointer target", pointed["value"], False))
    if entry is not None and state["hash_status"] == "matched" and not is_pdf:
        text = read_text_source(entry, evidence_pointer, report)
        if text is not None:
            texts.append(("registered input text", text, False))
    if is_pdf:
        texts.extend((label, text, True) for label, text, in provided_pdf_text(item, evidence_pointer, registry, report))
    if not texts:
        report.warning(
            "short_quote_text_unavailable",
            "No corresponding case-pointer text, supported input text, or provided PDF extraction is available; quote remains unverified/partial.",
            child_pointer(evidence_pointer, quote_key),
        )
        state["quote_status"] = "partial_no_source_text"
        return state
    normalized_quote = normalize_whitespace(quote)
    matched = [label for label, text, _ in texts if normalized_quote in normalize_whitespace(text)]
    if not matched:
        report.error(
            "short_quote_mismatch",
            "Whitespace-normalized short quote is not a substring of any available declared source text.",
            child_pointer(evidence_pointer, quote_key), available_texts=[label for label, _, _ in texts],
            normalized_quote=normalized_quote,
        )
        state["quote_status"] = "mismatch"
        return state
    direct_matches = [label for label, text, derived in texts if not derived and label in matched]
    if direct_matches:
        state["quote_status"] = "matched_whitespace_normalized"
        state["quote_matched_texts"] = direct_matches
    else:
        report.warning(
            "quote_matched_provided_extraction_only",
            "Quote matches supplied extraction text, not independently decoded PDF content; this is not raw-source quote verification.",
            child_pointer(evidence_pointer, quote_key), matched_texts=matched,
        )
        state["quote_status"] = "matched_provided_extraction_unverified_against_pdf"
    return state


def scan_evidence(document, label, case, case_path, registry, report):
    stack = [(document, "", "", False)]
    while stack:
        value, pointer, key_context, inherited_context = stack.pop()
        current_context = inherited_context or is_evidence_key(key_context)
        if isinstance(value, dict):
            has_locator_field = any(key in value for key in EVIDENCE_PATH_KEYS + EVIDENCE_POINTER_KEYS)
            has_quote = any(key in value for key in QUOTE_KEYS)
            recognizable = (
                ("source_id" in value and value["source_id"] is not None)
                or (has_quote and has_locator_field)
                or (current_context and (has_locator_field or has_quote))
            )
            if recognizable:
                item_pointer = pointer if label == "result" else label + pointer
                validate_evidence_item(value, item_pointer, case, case_path, registry, report)
            for key, child in value.items():
                stack.append((child, child_pointer(pointer, key), key, current_context))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                stack.append((child, child_pointer(pointer, index), key_context, current_context))


def validate_evidence_map(evidence_map, case_id_status, case_id, result, case, case_path, registry, report):
    state = {"provided": True, "checked": True, "result_pointers_checked": 0}
    report.checked["evidence_map"] = state
    if not isinstance(evidence_map, dict):
        report.error("invalid_evidence_map", "evidence_map top level must be an object when provided.")
        state["checked"] = False
        return
    if "case_id" not in evidence_map:
        report.warning(
            "evidence_map_case_id_missing",
            "evidence_map has no top-level case_id; map-to-case identity remains partially checked.",
        )
        state["case_id_status"] = "missing"
    elif case_id_status in ("root", "unique", "repeated_equal"):
        state["case_id_status"] = "checked"
        if not values_equal(evidence_map["case_id"], case_id) or not values_equal(evidence_map["case_id"], result.get("case_id")):
            report.error(
                "evidence_map_case_id_mismatch",
                "evidence_map case_id must equal both actual case and result case_id.",
                "/case_id", expected=case_id, actual=evidence_map["case_id"],
            )
            state["case_id_status"] = "mismatch"
        else:
            state["case_id_status"] = "matched"
    else:
        report.warning(
            "evidence_map_case_id_not_comparable",
            "Actual case_id is not uniquely available, so evidence_map case_id cannot be confirmed.",
        )
        state["case_id_status"] = "unverifiable"
    found = []
    stack = [(evidence_map, "")]
    while stack:
        value, pointer = stack.pop()
        if isinstance(value, dict):
            if "result_pointer" in value:
                found.append((pointer, value["result_pointer"]))
            for key, child in value.items():
                stack.append((child, child_pointer(pointer, key)))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                stack.append((child, child_pointer(pointer, index)))
    if not found:
        report.warning(
            "evidence_map_result_pointers_missing",
            "No result_pointer fields occur in evidence_map; map-to-result linkage is partial.",
        )
    for pointer, result_pointer in found:
        field_pointer = child_pointer(pointer, "result_pointer")
        if not isinstance(result_pointer, str):
            report.error(
                "invalid_evidence_map_result_pointer", "result_pointer must be a string.",
                field_pointer, actual_type=json_type(result_pointer),
            )
            continue
        try:
            target = resolve_json_pointer(result, result_pointer)
        except (ValueError, KeyError) as exc:
            report.error(
                "evidence_map_result_pointer_unresolved",
                "result_pointer does not resolve into the actual result: %s." % exc,
                field_pointer, result_pointer=result_pointer,
            )
            continue
        state["result_pointers_checked"] += 1
        state.setdefault("resolved_result_pointers", []).append(
            {"map_pointer": field_pointer, "result_pointer": result_pointer, "target_type": json_type(target)}
        )
    state["result_pointer_occurrences"] = len(found)
    scan_evidence(evidence_map, "evidence_map", case, case_path, registry, report)


def run(args, report):
    case, case_raw = load_strict_json(args.case, "case")
    report.checked["strict_json"]["case"] = "passed"
    result, _ = load_strict_json(args.result, "result")
    report.checked["strict_json"]["result"] = "passed"
    inspection, _ = load_strict_json(args.inspection, "inspection")
    report.checked["strict_json"]["inspection"] = "passed"
    if not isinstance(case, dict):
        report.error("case_not_object", "Case top level must be an object.", actual_type=json_type(case))
    if not isinstance(result, dict):
        report.error("result_not_object", "Result top level must be a strict JSON object.", actual_type=json_type(result))
    if not isinstance(inspection, dict):
        report.error("inspection_not_object", "Inspection top level must be an object.", actual_type=json_type(inspection))
    if not isinstance(case, dict) or not isinstance(result, dict) or not isinstance(inspection, dict):
        return
    validate_inspection_fingerprint(inspection, case_raw, args.case, report)
    case_id_status, case_id = validate_case_id(case, result, report)
    validate_output_contract(case, result, report)
    validate_placeholders_and_ids(result, report)
    registry = SourceRegistry(inspection, args.case, report)
    if registry.available:
        scan_evidence(result, "result", case, args.case, registry, report)
    if args.evidence:
        evidence_map, _ = load_strict_json(args.evidence, "evidence_map")
        report.checked["strict_json"]["evidence_map"] = "passed"
        if registry.available:
            validate_evidence_map(
                evidence_map, case_id_status, case_id, result, case, args.case, registry, report
            )
        else:
            report.checked["evidence_map"] = {"provided": True, "checked": False}


def build_parser():
    parser = MachineArgumentParser(
        description="Validate result JSON against actual case contracts and inspection-registered evidence."
    )
    parser.add_argument("--case", required=True, help="Actual input case.json")
    parser.add_argument("--result", required=True, help="Result JSON to validate")
    parser.add_argument("--inspection", required=True, help="Inspection produced by inspect_case.py")
    parser.add_argument("--evidence", help="Optional evidence_map.json")
    return parser


def main(argv=None):
    report = Report()
    try:
        args = build_parser().parse_args(argv)
        run(args, report)
    except InputError as exc:
        report.error("input_error", str(exc))
    except OSError as exc:
        report.error("filesystem_error", str(exc))
    output = report.finish()
    try:
        text = json.dumps(output, ensure_ascii=False, allow_nan=False, indent=2)
    except (TypeError, ValueError, RecursionError) as exc:
        output = {
            "valid": False,
            "errors": [{"code": "diagnostic_serialization_error", "message": str(exc)}],
            "warnings": [],
            "checked": {},
        }
        text = json.dumps(output, ensure_ascii=False, indent=2)
    print(text)
    return 0 if output["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
