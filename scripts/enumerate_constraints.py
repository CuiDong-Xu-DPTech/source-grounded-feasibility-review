#!/usr/bin/env python3
"""Deterministic, exact finite-domain constraint review.

Usage:
    python3 enumerate_constraints.py INPUT.json --output RESULT.json
        [--audit AUDIT.jsonl] [--max-combinations 100000]
        [--deadline-seconds 60]

Only the Python standard library is used. Exit codes are 0 for a successful
run, 3 for a partial run, and 1 for a failed run or an output failure.
A successful run can still have an undetermined scientific judgment.
"""

import argparse
import ast
import decimal
import hashlib
import itertools
import json
import math
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


INPUT_SCHEMA = "finite-domain-review/v1"
RESULT_SCHEMA = "finite-domain-review-result/v1"
AUDIT_SCHEMA = "finite-domain-audit/v1"
PRECISION = 50
MAX_AST_DEPTH = 64
MAX_AST_NODES = 512
MAX_EXPRESSION_CHARS = 16384
MAX_ROUNDING_PLACES = 10000
MAX_WITNESSES = 64
NUMERIC_STRING = re.compile(
    r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z"
)
COMPARISON_OPERATORS = {
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Eq: "==",
    ast.NotEq: "!=",
}
BINARY_OPERATORS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}
UNARY_OPERATORS = {ast.UAdd: "+", ast.USub: "-", ast.Not: "not"}
FUNCTION_NAMES = {"ceil", "floor", "abs", "min", "max", "round_half_up"}


class InputError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class EvaluationFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Value:
    kind: str
    data: Any = None

    def output(self) -> Any:
        if self.kind == "unknown":
            return None
        if self.kind == "number":
            return str(self.data)
        return self.data

    def sort_key(self) -> Tuple[str, Any]:
        return self.kind, self.data


UNKNOWN = Value("unknown")
TRUE = Value("bool", True)
FALSE = Value("bool", False)


@dataclass
class Constraint:
    constraint_id: str
    expression: str
    hard: bool
    source_id: Optional[str]
    locator: Optional[str]
    code: Any = None
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def evidence_refs(self) -> List[Dict[str, Any]]:
        if self.source_id is None:
            return []
        ref = {"source_id": self.source_id}
        if self.locator is not None:
            ref["locator"] = self.locator
        return [ref]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "expression": self.expression,
            "hard": self.hard,
            "evidence_refs": self.evidence_refs(),
        }


@dataclass
class Parameter:
    name: str
    domain: List[Value]
    unit: Optional[str]
    source_id: Optional[str]
    locator: Optional[str]

    def evidence_refs(self) -> List[Dict[str, Any]]:
        if self.source_id is None:
            return []
        ref = {"source_id": self.source_id}
        if self.locator is not None:
            ref["locator"] = self.locator
        return [ref]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "parameter_id": self.name,
            "domain": [item.output() for item in self.domain],
            "unit": self.unit,
            "evidence_refs": self.evidence_refs(),
        }


@dataclass
class PreparedPlan:
    plan_id: str
    parameters: List[Parameter] = field(default_factory=list)
    constraints: List[Constraint] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    structural_ok: bool = True

    def parameter_snapshot(self) -> List[Dict[str, Any]]:
        return [parameter.snapshot() for parameter in self.parameters]

    def constraint_snapshot(self) -> List[Dict[str, Any]]:
        return [constraint.snapshot() for constraint in self.constraints]


class ExpressionCompiler:
    def __init__(self, expression: str, variables: Iterable[str]):
        self.expression = expression
        self.variables = set(variables)
        self.node_count = 0

    def compile(self) -> Any:
        if not self.expression or len(self.expression) > MAX_EXPRESSION_CHARS:
            raise InputError(
                "invalid_expression",
                "Expression must contain 1 to %d characters." % MAX_EXPRESSION_CHARS,
            )
        try:
            tree = ast.parse(self.expression, mode="eval")
        except (SyntaxError, ValueError, RecursionError) as exc:
            raise InputError("invalid_expression", "Expression cannot be parsed: %s" % exc)
        return self._compile_node(tree.body, 1)

    def _enter(self, depth: int) -> None:
        self.node_count += 1
        if self.node_count > MAX_AST_NODES:
            raise InputError(
                "expression_too_complex",
                "Expression exceeds the %d-node safety limit." % MAX_AST_NODES,
            )
        if depth > MAX_AST_DEPTH:
            raise InputError(
                "ast_too_deep",
                "Expression exceeds the %d-level safety limit." % MAX_AST_DEPTH,
            )

    def _compile_node(self, node: ast.AST, depth: int) -> Any:
        self._enter(depth)
        if isinstance(node, ast.Constant):
            value = node.value
            if value is None:
                return "constant", UNKNOWN
            if isinstance(value, bool):
                return "constant", TRUE if value else FALSE
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                literal = ast.get_source_segment(self.expression, node)
                if literal is None or not NUMERIC_STRING.fullmatch(literal.replace("_", "")):
                    raise InputError(
                        "unsupported_literal",
                        "Only exact decimal numeric literals are allowed.",
                    )
                try:
                    number = Decimal(literal.replace("_", ""))
                except decimal.DecimalException as exc:
                    raise InputError("unsupported_literal", str(exc))
                if not number.is_finite():
                    raise InputError("unsupported_literal", "Numeric literals must be finite.")
                return "constant", Value("number", number)
            if isinstance(value, str):
                return "constant", make_value(value)
            raise InputError(
                "unsafe_ast", "Literal type %s is not allowed." % type(value).__name__
            )
        if isinstance(node, ast.Name):
            if node.id in self.variables:
                return "variable", node.id
            aliases = {"null": UNKNOWN, "true": TRUE, "false": FALSE}
            if node.id in aliases:
                return "constant", aliases[node.id]
            raise InputError("unknown_variable", "Unknown variable: %s" % node.id)
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPERATORS:
            return (
                "binary",
                BINARY_OPERATORS[type(node.op)],
                self._compile_node(node.left, depth + 1),
                self._compile_node(node.right, depth + 1),
            )
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPERATORS:
            return (
                "unary",
                UNARY_OPERATORS[type(node.op)],
                self._compile_node(node.operand, depth + 1),
            )
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            return (
                "bool",
                "and" if isinstance(node.op, ast.And) else "or",
                tuple(self._compile_node(item, depth + 1) for item in node.values),
            )
        if isinstance(node, ast.Compare) and node.ops:
            operations = []
            for operator in node.ops:
                if type(operator) not in COMPARISON_OPERATORS:
                    raise InputError(
                        "unsafe_ast", "Comparison operator is not allowed."
                    )
                operations.append(COMPARISON_OPERATORS[type(operator)])
            return (
                "compare",
                self._compile_node(node.left, depth + 1),
                tuple(operations),
                tuple(self._compile_node(item, depth + 1) for item in node.comparators),
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in FUNCTION_NAMES
        ):
            name = node.func.id
            if node.keywords:
                raise InputError(
                    "invalid_function_signature", "Keyword arguments are not allowed."
                )
            expected_two = name == "round_half_up"
            if (expected_two and len(node.args) != 2) or (
                name in {"ceil", "floor", "abs"} and len(node.args) != 1
            ):
                raise InputError(
                    "invalid_function_signature", "Invalid argument count for %s." % name
                )
            if name in {"min", "max"} and not node.args:
                raise InputError(
                    "invalid_function_signature", "%s requires at least one argument." % name
                )
            return (
                "call",
                name,
                tuple(self._compile_node(item, depth + 1) for item in node.args),
            )
        raise InputError(
            "unsafe_ast", "AST node %s is not allowed." % type(node).__name__
        )


class AtomicFile:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        parent = os.path.dirname(self.path) or os.curdir
        os.makedirs(parent, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".%s." % os.path.basename(self.path), suffix=".tmp", dir=parent
        )
        self.temporary = temporary
        self.stream = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
        self.finished = False

    def write(self, text: str) -> None:
        self.stream.write(text)

    def finish(self) -> None:
        if not self.finished:
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.stream.close()
            self.finished = True

    def commit(self) -> None:
        self.finish()
        os.replace(self.temporary, self.path)

    def abort(self) -> None:
        try:
            if not self.finished:
                self.stream.close()
                self.finished = True
        finally:
            try:
                os.unlink(self.temporary)
            except FileNotFoundError:
                pass


class AuditWriter:
    def __init__(self, path: str):
        self.output = AtomicFile(path)

    def write(self, record: Dict[str, Any]) -> None:
        text = json.dumps(
            json_safe(record), ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        self.output.write(text + "\n")


class RuntimeErrors:
    def __init__(self):
        self.items: List[Dict[str, Any]] = []
        self.index: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}

    def add(
        self,
        constraint_id: str,
        code: str,
        message: str,
        first_combination: int,
    ) -> None:
        key = constraint_id, code, message, "evaluation"
        if key in self.index:
            self.index[key]["occurrences"] += 1
            return
        error = {
            "phase": "evaluation",
            "constraint_id": constraint_id,
            "code": code,
            "message": message,
            "first_combination_index": first_combination,
            "occurrences": 1,
        }
        self.index[key] = error
        self.items.append(error)


def make_value(raw: Any) -> Value:
    if raw is None:
        return UNKNOWN
    if isinstance(raw, bool):
        return TRUE if raw else FALSE
    if isinstance(raw, Decimal):
        if not raw.is_finite():
            raise InputError("invalid_domain_value", "Numbers must be finite.")
        return Value("number", raw)
    if isinstance(raw, int):
        return Value("number", Decimal(raw))
    if isinstance(raw, str):
        if NUMERIC_STRING.fullmatch(raw):
            try:
                number = Decimal(raw)
            except decimal.DecimalException as exc:
                raise InputError("invalid_domain_value", str(exc))
            if not number.is_finite():
                raise InputError("invalid_domain_value", "Numbers must be finite.")
            return Value("number", number)
        return Value("string", raw)
    raise InputError(
        "invalid_domain_value", "Domain values must be numbers, strings, booleans, or null."
    )


def json_safe(value: Any) -> Any:
    if isinstance(value, Value):
        return value.output()
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite decimal cannot be written")
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite float cannot be written")
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    raise TypeError("Unsupported output value: %s" % type(value).__name__)


def duplicate_checked_object(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError("duplicate_json_key", "Duplicate JSON key: %s" % key)
        result[key] = value
    return result


def reject_json_constant(token: str) -> None:
    raise InputError(
        "non_finite_json_number", "NaN and Infinity are not valid input numbers: %s" % token
    )


def read_input(path: str) -> Tuple[Dict[str, Any], str, bytes]:
    raw = open(path, "rb").read()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
        data = json.loads(
            text,
            parse_float=Decimal,
            parse_constant=reject_json_constant,
            object_pairs_hook=duplicate_checked_object,
        )
    except InputError as exc:
        exc.input_sha256 = digest
        raise
    except (UnicodeDecodeError, ValueError, RecursionError, decimal.DecimalException) as exc:
        failure = InputError("invalid_json", "Input is not strict UTF-8 JSON: %s" % exc)
        failure.input_sha256 = digest
        raise failure
    if not isinstance(data, dict):
        failure = InputError("invalid_input", "Top-level JSON value must be an object.")
        failure.input_sha256 = digest
        raise failure
    return data, digest, raw


def error_item(
    phase: str, code: str, message: str, **identifiers: Any
) -> Dict[str, Any]:
    item = {"phase": phase, "code": code, "message": message}
    item.update(identifiers)
    return item


def optional_text(
    raw: Dict[str, Any], key: str, errors: List[Dict[str, Any]], owner: Dict[str, Any]
) -> Optional[str]:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        errors.append(
            error_item(
                "input_validation",
                "invalid_%s" % key,
                "%s must be a non-empty string when present." % key,
                **owner
            )
        )
        return None
    return value


def prepare_plan(raw: Any, index: int) -> PreparedPlan:
    if not isinstance(raw, dict):
        return PreparedPlan(
            plan_id="plans[%d]" % index,
            structural_ok=False,
            errors=[
                error_item(
                    "input_validation", "invalid_plan", "Each plan must be an object."
                )
            ],
        )
    plan_id = raw.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        plan_id = "plans[%d]" % index
    prepared = PreparedPlan(plan_id=plan_id)
    if raw.get("plan_id") != plan_id:
        prepared.structural_ok = False
        prepared.errors.append(
            error_item(
                "input_validation",
                "invalid_plan_id",
                "plan_id must be a non-empty string.",
            )
        )

    raw_parameters = raw.get("parameters")
    if not isinstance(raw_parameters, dict):
        prepared.structural_ok = False
        prepared.errors.append(
            error_item(
                "input_validation",
                "invalid_parameters",
                "parameters must be an object.",
            )
        )
        raw_parameters = {}
    for name, specification in raw_parameters.items():
        owner = {"parameter_id": name}
        parameter_errors: List[Dict[str, Any]] = []
        if not isinstance(name, str) or not name:
            parameter_errors.append(
                error_item(
                    "input_validation",
                    "invalid_parameter_id",
                    "Parameter names must be non-empty strings.",
                )
            )
        if not isinstance(specification, dict):
            prepared.errors.append(
                error_item(
                    "input_validation",
                    "invalid_parameter",
                    "Parameter specification must be an object.",
                    **owner
                )
            )
            prepared.structural_ok = False
            continue
        if "domain" not in specification:
            parameter_errors.append(
                error_item(
                    "input_validation",
                    "missing_domain",
                    "Missing domain; the parameter is not treated as a free variable.",
                    **owner
                )
            )
            domain = []
        elif not isinstance(specification["domain"], list):
            parameter_errors.append(
                error_item(
                    "input_validation",
                    "invalid_domain",
                    "domain must be an array.",
                    **owner
                )
            )
            domain = []
        else:
            domain = []
            seen = set()
            for domain_index, raw_value in enumerate(specification["domain"]):
                try:
                    value = make_value(raw_value)
                except InputError as exc:
                    parameter_errors.append(
                        error_item(
                            "input_validation",
                            exc.code,
                            exc.message,
                            parameter_id=name,
                            domain_index=domain_index,
                        )
                    )
                    continue
                key = value.sort_key()
                if key not in seen:
                    seen.add(key)
                    domain.append(value)
        source_id = specification.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            parameter_errors.append(
                error_item(
                    "input_validation",
                    "missing_parameter_source_id",
                    "Parameter source_id must be a non-empty string.",
                    **owner
                )
            )
            source_id = None
        unit = specification.get("unit")
        if unit is not None and not isinstance(unit, str):
            parameter_errors.append(
                error_item(
                    "input_validation",
                    "invalid_unit",
                    "unit must be a string when present.",
                    **owner
                )
            )
            unit = None
        locator = optional_text(specification, "locator", parameter_errors, owner)
        prepared.parameters.append(
            Parameter(name, domain, unit, source_id, locator)
        )
        if parameter_errors:
            prepared.structural_ok = False
            prepared.errors.extend(parameter_errors)

    raw_constraints = raw.get("constraints")
    if not isinstance(raw_constraints, list):
        prepared.structural_ok = False
        prepared.errors.append(
            error_item(
                "input_validation",
                "invalid_constraints",
                "constraints must be an array.",
            )
        )
        raw_constraints = []
    variable_names = [parameter.name for parameter in prepared.parameters]
    seen_constraints = set()
    for constraint_index, specification in enumerate(raw_constraints):
        if not isinstance(specification, dict):
            prepared.structural_ok = False
            prepared.errors.append(
                error_item(
                    "input_validation",
                    "invalid_constraint",
                    "Constraint must be an object.",
                    constraint_index=constraint_index,
                )
            )
            continue
        constraint_id = specification.get("id")
        if not isinstance(constraint_id, str) or not constraint_id:
            prepared.structural_ok = False
            prepared.errors.append(
                error_item(
                    "input_validation",
                    "invalid_constraint_id",
                    "Constraint id must be a non-empty string.",
                    constraint_index=constraint_index,
                )
            )
            constraint_id = "constraints[%d]" % constraint_index
        if constraint_id in seen_constraints:
            prepared.structural_ok = False
            prepared.errors.append(
                error_item(
                    "input_validation",
                    "duplicate_constraint_id",
                    "Duplicate constraint id: %s" % constraint_id,
                    constraint_id=constraint_id,
                )
            )
        seen_constraints.add(constraint_id)
        owner = {"constraint_id": constraint_id}
        constraint_errors = []
        expression = specification.get("expression")
        if not isinstance(expression, str) or not expression:
            constraint_errors.append(
                error_item(
                    "constraint_validation",
                    "missing_expression",
                    "Constraint expression must be a non-empty string.",
                    **owner
                )
            )
            expression = ""
        source_id = specification.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            constraint_errors.append(
                error_item(
                    "constraint_validation",
                    "missing_constraint_source_id",
                    "Constraint source_id must be a non-empty string.",
                    **owner
                )
            )
            source_id = None
        hard = specification.get("hard", True)
        if not isinstance(hard, bool):
            constraint_errors.append(
                error_item(
                    "constraint_validation",
                    "invalid_hard_flag",
                    "hard must be a boolean; the invalid constraint cannot decide feasibility.",
                    **owner
                )
            )
            hard = True
        locator = optional_text(specification, "locator", constraint_errors, owner)
        constraint = Constraint(
            constraint_id, expression, hard, source_id, locator, errors=constraint_errors
        )
        if expression:
            try:
                constraint.code = ExpressionCompiler(expression, variable_names).compile()
            except InputError as exc:
                constraint.errors.append(
                    error_item("compilation", exc.code, exc.message, **owner)
                )
            except (RecursionError, MemoryError) as exc:
                constraint.errors.append(
                    error_item(
                        "compilation",
                        "unsafe_ast",
                        "Expression compilation failed safely: %s" % type(exc).__name__,
                        **owner
                    )
                )
        prepared.constraints.append(constraint)
        prepared.errors.extend(constraint.errors)
    return prepared


def require_number(value: Value, operation: str) -> Decimal:
    if value.kind != "number":
        raise EvaluationFailure(
            "type_error", "%s requires numeric operands, got %s." % (operation, value.kind)
        )
    return value.data


def require_boolean(value: Value, operation: str) -> bool:
    if value.kind != "bool":
        raise EvaluationFailure(
            "type_error", "%s requires boolean operands, got %s." % (operation, value.kind)
        )
    return value.data


def compare_values(operator: str, left: Value, right: Value) -> Value:
    if left.kind == "unknown" or right.kind == "unknown":
        return UNKNOWN
    if left.kind != right.kind:
        if operator == "==":
            return FALSE
        if operator == "!=":
            return TRUE
        raise EvaluationFailure(
            "type_error",
            "Ordered comparison requires matching types, got %s and %s."
            % (left.kind, right.kind),
        )
    try:
        if operator == "==":
            result = left.data == right.data
        elif operator == "!=":
            result = left.data != right.data
        elif operator == "<":
            result = left.data < right.data
        elif operator == "<=":
            result = left.data <= right.data
        elif operator == ">":
            result = left.data > right.data
        else:
            result = left.data >= right.data
    except (TypeError, decimal.DecimalException) as exc:
        raise EvaluationFailure("comparison_error", str(exc))
    return TRUE if result else FALSE


def decimal_failure(exc: decimal.DecimalException) -> EvaluationFailure:
    if isinstance(exc, decimal.DivisionByZero):
        code = "division_by_zero"
    elif isinstance(exc, decimal.Overflow):
        code = "overflow"
    elif isinstance(exc, decimal.Inexact):
        code = "inexact_arithmetic"
    elif isinstance(exc, decimal.InvalidOperation):
        code = "invalid_operation"
    else:
        code = "decimal_error"
    return EvaluationFailure(
        code, "%s: %s" % (code, type(exc).__name__)
    )


def evaluate_call(name: str, arguments: Sequence[Value]) -> Value:
    known = [item for item in arguments if item.kind != "unknown"]
    for value in known:
        require_number(value, name)
    if len(known) != len(arguments):
        return UNKNOWN
    values = [item.data for item in arguments]
    try:
        if name == "ceil":
            return Value("number", values[0].to_integral_value(rounding=decimal.ROUND_CEILING))
        if name == "floor":
            return Value("number", values[0].to_integral_value(rounding=decimal.ROUND_FLOOR))
        if name == "abs":
            return Value("number", values[0].copy_abs())
        if name == "min":
            return Value("number", min(values))
        if name == "max":
            return Value("number", max(values))
        number, places = values
        if places != places.to_integral_value() or abs(places) > MAX_ROUNDING_PLACES:
            raise EvaluationFailure(
                "invalid_rounding_places",
                "round_half_up places must be an integer with absolute value at most %d."
                % MAX_ROUNDING_PLACES,
            )
        exponent = Decimal(1).scaleb(-int(places))
        with decimal.localcontext() as context:
            context.prec = PRECISION
            context.traps[decimal.Inexact] = False
            context.traps[decimal.InvalidOperation] = True
            context.traps[decimal.DivisionByZero] = True
            context.traps[decimal.Overflow] = True
            rounded = number.quantize(exponent, rounding=decimal.ROUND_HALF_UP)
        return Value("number", rounded)
    except decimal.DecimalException as exc:
        raise decimal_failure(exc)


def evaluate(code: Any, assignment: Dict[str, Value]) -> Value:
    tag = code[0]
    if tag == "constant":
        return code[1]
    if tag == "variable":
        return assignment[code[1]]
    if tag == "unary":
        operand = evaluate(code[2], assignment)
        if code[1] == "not":
            if operand.kind == "unknown":
                return UNKNOWN
            return FALSE if require_boolean(operand, "not") else TRUE
        if operand.kind == "unknown":
            return UNKNOWN
        number = require_number(operand, "unary " + code[1])
        if code[1] == "+":
            return Value("number", number)
        return Value("number", -number)
    if tag == "binary":
        left = evaluate(code[2], assignment)
        right = evaluate(code[3], assignment)
        if left.kind == "unknown" or right.kind == "unknown":
            if code[1] == "/" and right.kind == "number" and right.data.is_zero():
                raise EvaluationFailure("division_by_zero", "Division by zero.")
            return UNKNOWN
        left_number = require_number(left, code[1])
        right_number = require_number(right, code[1])
        try:
            if code[1] == "+":
                result = left_number + right_number
            elif code[1] == "-":
                result = left_number - right_number
            elif code[1] == "*":
                result = left_number * right_number
            else:
                result = left_number / right_number
        except decimal.DecimalException as exc:
            raise decimal_failure(exc)
        return Value("number", result)
    if tag == "bool":
        operation = code[1]
        undetermined = False
        for child in code[2]:
            value = evaluate(child, assignment)
            if value.kind == "unknown":
                undetermined = True
                continue
            boolean = require_boolean(value, operation)
            if operation == "and" and not boolean:
                return FALSE
            if operation == "or" and boolean:
                return TRUE
        if undetermined:
            return UNKNOWN
        return TRUE if operation == "and" else FALSE
    if tag == "compare":
        left = evaluate(code[1], assignment)
        undetermined = False
        for operator, right_code in zip(code[2], code[3]):
            right = evaluate(right_code, assignment)
            result = compare_values(operator, left, right)
            if result.kind == "unknown":
                undetermined = True
            elif not result.data:
                return FALSE
            left = right
        return UNKNOWN if undetermined else TRUE
    if tag == "call":
        arguments = [evaluate(child, assignment) for child in code[2]]
        return evaluate_call(code[1], arguments)
    raise EvaluationFailure("internal_evaluation_error", "Unknown compiled instruction.")


def evaluate_constraint(
    constraint: Constraint, assignment: Dict[str, Value]
) -> Tuple[str, Optional[Dict[str, Any]]]:
    if constraint.errors:
        first = constraint.errors[0]
        return "error", {
            "code": first["code"],
            "message": first["message"],
            "phase": first["phase"],
        }
    try:
        with decimal.localcontext() as context:
            context.prec = PRECISION
            context.traps[decimal.Inexact] = True
            context.traps[decimal.InvalidOperation] = True
            context.traps[decimal.DivisionByZero] = True
            context.traps[decimal.Overflow] = True
            result = evaluate(constraint.code, assignment)
    except EvaluationFailure as exc:
        return "error", {"code": exc.code, "message": exc.message, "phase": "evaluation"}
    except decimal.DecimalException as exc:
        failure = decimal_failure(exc)
        return "error", {
            "code": failure.code,
            "message": failure.message,
            "phase": "evaluation",
        }
    except (ArithmeticError, TypeError, ValueError, RecursionError) as exc:
        return "error", {
            "code": "evaluation_error",
            "message": "%s: %s" % (type(exc).__name__, exc),
            "phase": "evaluation",
        }
    if result.kind == "unknown":
        return "UNKNOWN", None
    if result.kind != "bool":
        return "error", {
            "code": "non_boolean_constraint",
            "message": "Constraint result must be boolean, got %s." % result.kind,
            "phase": "evaluation",
        }
    return ("TRUE" if result.data else "FALSE"), None


def summarize_plan(
    complete: bool,
    timed_out: bool,
    limit_exceeded: bool,
    total: int,
    total_known: bool,
    feasible: int,
    undetermined: int,
    violated: int,
    hard_count: int,
) -> Dict[str, Any]:
    if not total_known:
        status, reason = "undetermined", "invalid_or_missing_domain"
        statement = "The declared domain could not be enumerated safely."
    elif not complete:
        status = "undetermined"
        if timed_out:
            reason = "deadline_exceeded"
        elif limit_exceeded:
            reason = "combination_limit_exceeded"
        else:
            reason = "incomplete_enumeration"
        statement = "Enumeration was incomplete; no exhaustive scientific judgment is available."
    elif total == 0:
        status, reason = "undetermined", "empty_domain_product"
        statement = "The domain product contains no assignments; this is not reported as an all-FALSE proof."
    elif feasible > 0:
        status, reason = "feasible", "satisfying_assignment_found"
        statement = "At least one fully enumerated assignment satisfies every hard constraint."
    elif undetermined == 0 and violated == total:
        status, reason = "infeasible", "exhaustive_all_false"
        statement = "Enumeration completed and every assignment is FALSE under the declared hard constraints."
    elif hard_count == 0:
        status, reason = "undetermined", "no_hard_constraints"
        statement = "No hard constraints were declared; the domain is not called feasible."
    else:
        status, reason = "undetermined", "unknown_or_error_prevents_conclusion"
        statement = "UNKNOWN or erroneous hard constraints prevent an exhaustive feasibility judgment."
    return {
        "status": status,
        "reason_code": reason,
        "statement": statement,
        "basis": "declared finite domains and hard constraints; soft constraints are reported separately",
        "ranking": None,
    }


def empty_plan_result(prepared: PreparedPlan, total_known: bool = False) -> Dict[str, Any]:
    return {
        "plan_id": prepared.plan_id,
        "run_status": "partial",
        "tested": 0,
        "total": 0,
        "total_known": total_known,
        "feasible_count": 0,
        "undetermined_count": 0,
        "violated_count": 0,
        "complete": False,
        "timed_out": False,
        "limit_exceeded": False,
        "errors": list(prepared.errors),
        "parameters": prepared.parameter_snapshot(),
        "constraints": prepared.constraint_snapshot(),
        "soft_constraint_statistics": [],
        "witnesses": [],
        "witnesses_truncated": False,
        "summary": summarize_plan(
            False, False, False, 0, total_known, 0, 0, 0, 0
        ),
    }


def run_plan(
    prepared: PreparedPlan,
    audit: Optional[AuditWriter],
    case_id: str,
    input_sha256: str,
    max_combinations: int,
    plan_deadline: float,
) -> Dict[str, Any]:
    if not prepared.structural_ok:
        return empty_plan_result(prepared)
    domains = [parameter.domain for parameter in prepared.parameters]
    total = 1
    for domain in domains:
        total *= len(domain)
    result = empty_plan_result(prepared, total_known=True)
    result["total"] = total
    result["run_status"] = "success"
    hard_count = sum(1 for constraint in prepared.constraints if constraint.hard)
    soft_statistics = {
        constraint.constraint_id: {
            "constraint_id": constraint.constraint_id,
            "evidence_refs": constraint.evidence_refs(),
            "TRUE": 0,
            "FALSE": 0,
            "UNKNOWN": 0,
            "error": 0,
        }
        for constraint in prepared.constraints
        if not constraint.hard
    }
    parameter_context = {
        parameter.name: {
            "unit": parameter.unit,
            "evidence_refs": parameter.evidence_refs(),
        }
        for parameter in prepared.parameters
    }
    runtime_errors = RuntimeErrors()
    early_witnesses: List[Dict[str, Any]] = []
    first_by_status: Dict[str, Dict[str, Any]] = {}
    witness_statuses = set()
    timed_out = False
    limit_exceeded = False
    tested = 0

    iterator = itertools.product(*domains)
    for raw_combination in iterator:
        if time.monotonic() >= plan_deadline:
            timed_out = True
            break
        if tested >= max_combinations:
            limit_exceeded = True
            break
        tested += 1
        assignment = dict(zip([item.name for item in prepared.parameters], raw_combination))
        assignment_output = {name: value.output() for name, value in assignment.items()}
        constraint_records = []
        hard_records = []
        for constraint in prepared.constraints:
            status, evaluation_error = evaluate_constraint(constraint, assignment)
            record = {
                "constraint_id": constraint.constraint_id,
                "hard": constraint.hard,
                "status": status,
                "error": evaluation_error,
                "evidence_refs": constraint.evidence_refs(),
            }
            constraint_records.append(record)
            if constraint.hard:
                hard_records.append(record)
            else:
                soft_statistics[constraint.constraint_id][status] += 1
            if evaluation_error is not None and not constraint.errors:
                runtime_errors.add(
                    constraint.constraint_id,
                    evaluation_error["code"],
                    evaluation_error["message"],
                    tested,
                )
        if not hard_records:
            combination_status = "undetermined"
        elif any(record["status"] == "error" for record in hard_records):
            combination_status = "undetermined"
        elif any(record["status"] == "FALSE" for record in hard_records):
            combination_status = "violated"
        elif any(record["status"] == "UNKNOWN" for record in hard_records):
            combination_status = "undetermined"
        else:
            combination_status = "feasible"
        result[combination_status + "_count"] += 1
        record = {
            "schema_version": AUDIT_SCHEMA,
            "case_id": case_id,
            "input_sha256": input_sha256,
            "plan_id": prepared.plan_id,
            "combination_index": tested,
            "assignment": assignment_output,
            "parameter_context": parameter_context,
            "status": combination_status,
            "constraints": constraint_records,
        }
        if audit is not None:
            audit.write(record)
        if len(early_witnesses) < MAX_WITNESSES:
            early_witnesses.append(record)
        if combination_status not in first_by_status:
            first_by_status[combination_status] = record
        witness_statuses.add(combination_status)

    complete = tested == total and not timed_out and not limit_exceeded
    if timed_out:
        prepared.errors.append(
            error_item(
                "enumeration",
                "deadline_exceeded",
                "Plan time slice expired; remaining assignments were not tested.",
                plan_id=prepared.plan_id,
            )
        )
    if limit_exceeded:
        prepared.errors.append(
            error_item(
                "enumeration",
                "combination_limit_exceeded",
                "The combination limit was reached; remaining assignments were not tested.",
                plan_id=prepared.plan_id,
                max_combinations=max_combinations,
            )
        )
    result["tested"] = tested
    result["complete"] = complete
    result["timed_out"] = timed_out
    result["limit_exceeded"] = limit_exceeded
    result["errors"] = list(prepared.errors) + runtime_errors.items
    result["run_status"] = "success" if complete and not result["errors"] else "partial"
    result["soft_constraint_statistics"] = list(soft_statistics.values())
    witnesses = []
    selected = set()
    for status in ("feasible", "violated", "undetermined"):
        if status in first_by_status:
            item = first_by_status[status]
            witnesses.append(item)
            selected.add(item["combination_index"])
    for item in early_witnesses:
        if len(witnesses) >= MAX_WITNESSES:
            break
        if item["combination_index"] not in selected:
            witnesses.append(item)
            selected.add(item["combination_index"])
    witnesses.sort(key=lambda item: item["combination_index"])
    result["witnesses"] = witnesses[:MAX_WITNESSES]
    result["witnesses_truncated"] = tested > len(result["witnesses"])
    result["summary"] = summarize_plan(
        complete,
        timed_out,
        limit_exceeded,
        total,
        True,
        result["feasible_count"],
        result["undetermined_count"],
        result["violated_count"],
        hard_count,
    )
    return result


def witness_for(plan_result: Dict[str, Any], status: str) -> Optional[Dict[str, Any]]:
    for witness in plan_result["witnesses"]:
        if witness["status"] == status:
            return witness
    return None


def build_version_changes(
    prepared_plans: Sequence[PreparedPlan], results: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    changes = []
    for index in range(1, len(prepared_plans)):
        before = prepared_plans[index - 1]
        after = prepared_plans[index]
        change = {
            "relationship": "adjacent_input_order",
            "from_plan_id": before.plan_id,
            "to_plan_id": after.plan_id,
            "ranking": None,
        }
        if not before.structural_ok or not after.structural_ok:
            change["status"] = "undetermined"
            change["reason_code"] = "invalid_version_declarations"
            changes.append(change)
            continue
        change["status"] = "success"
        parameter_changes = []
        old_parameters = {item.name: item.snapshot() for item in before.parameters}
        new_parameters = {item.name: item.snapshot() for item in after.parameters}
        for parameter_id in sorted(set(old_parameters) | set(new_parameters)):
            old = old_parameters.get(parameter_id)
            new = new_parameters.get(parameter_id)
            if old == new:
                continue
            if old is None:
                kind = "added"
            elif new is None:
                kind = "removed"
            else:
                kind = "changed"
            parameter_changes.append(
                {
                    "parameter_id": parameter_id,
                    "change": kind,
                    "from": old,
                    "to": new,
                }
            )
        constraint_changes = []
        old_constraints = {item.constraint_id: item.snapshot() for item in before.constraints}
        new_constraints = {item.constraint_id: item.snapshot() for item in after.constraints}
        for constraint_id in sorted(set(old_constraints) | set(new_constraints)):
            old = old_constraints.get(constraint_id)
            new = new_constraints.get(constraint_id)
            if old == new:
                continue
            if old is None:
                kind = "added"
            elif new is None:
                kind = "removed"
            else:
                kind = "changed"
            constraint_changes.append(
                {
                    "constraint_id": constraint_id,
                    "change": kind,
                    "from": old,
                    "to": new,
                }
            )
        change["parameter_changes"] = parameter_changes
        change["constraint_changes"] = constraint_changes
        change["witness_changes"] = {}
        for status in ("feasible", "violated", "undetermined"):
            change["witness_changes"][status] = {
                "from": witness_for(results[index - 1], status),
                "to": witness_for(results[index], status),
                "from_complete": results[index - 1]["complete"],
                "to_complete": results[index]["complete"],
            }
        changes.append(change)
    return changes


def validate_case(data: Dict[str, Any]) -> Tuple[str, List[Any]]:
    if data.get("schema_version") != INPUT_SCHEMA:
        raise InputError(
            "invalid_schema_version", "schema_version must be %s." % INPUT_SCHEMA
        )
    case_id = data.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        raise InputError("invalid_case_id", "case_id must be a non-empty string.")
    plans = data.get("plans")
    if not isinstance(plans, list) or not plans:
        raise InputError("invalid_plans", "plans must be a non-empty array.")
    plan_ids = set()
    for plan in plans:
        if isinstance(plan, dict):
            plan_id = plan.get("plan_id")
            if isinstance(plan_id, str) and plan_id:
                if plan_id in plan_ids:
                    raise InputError(
                        "duplicate_plan_id", "Duplicate plan id: %s" % plan_id
                    )
                plan_ids.add(plan_id)
    return case_id, plans


def execute_case(
    data: Dict[str, Any],
    input_sha256: str,
    audit: Optional[AuditWriter],
    max_combinations: int,
    deadline_seconds: float,
    started: float,
) -> Dict[str, Any]:
    case_id, raw_plans = validate_case(data)
    hard_deadline = started + deadline_seconds
    write_reserve = min(2.0, deadline_seconds * 0.1)
    enumeration_deadline = hard_deadline - write_reserve
    prepared_plans: List[PreparedPlan] = []
    results: List[Dict[str, Any]] = []
    for index, raw_plan in enumerate(raw_plans):
        now = time.monotonic()
        remaining_plans = len(raw_plans) - index
        remaining_time = max(0.0, enumeration_deadline - now)
        plan_deadline = min(enumeration_deadline, now + remaining_time / remaining_plans)
        prepared = prepare_plan(raw_plan, index)
        prepared_plans.append(prepared)
        if time.monotonic() >= enumeration_deadline and prepared.structural_ok:
            result = empty_plan_result(prepared, total_known=True)
            total = 1
            for parameter in prepared.parameters:
                total *= len(parameter.domain)
            result["total"] = total
            result["timed_out"] = True
            result["errors"].append(
                error_item(
                    "enumeration",
                    "deadline_exceeded",
                    "No enumeration time remained for this plan.",
                    plan_id=prepared.plan_id,
                )
            )
            result["summary"] = summarize_plan(
                False, True, False, total, True, 0, 0, 0, 0
            )
        else:
            try:
                result = run_plan(
                    prepared,
                    audit,
                    case_id,
                    input_sha256,
                    max_combinations,
                    plan_deadline,
                )
            except OSError:
                raise
            except Exception as exc:
                result = empty_plan_result(prepared)
                result["errors"].append(
                    error_item(
                        "enumeration",
                        "internal_plan_error",
                        "Plan failed without affecting other versions: %s: %s"
                        % (type(exc).__name__, exc),
                        plan_id=prepared.plan_id,
                    )
                )
                result["summary"] = summarize_plan(
                    False, False, False, 0, False, 0, 0, 0, 0
                )
        results.append(result)
    run_status = (
        "success"
        if all(result["run_status"] == "success" for result in results)
        else "partial"
    )
    return {
        "schema_version": RESULT_SCHEMA,
        "case_id": case_id,
        "input_sha256": input_sha256,
        "run": {
            "status": run_status,
            "max_combinations": max_combinations,
            "deadline_seconds": Decimal(str(deadline_seconds)),
            "decimal_precision": PRECISION,
            "write_reserve_seconds": Decimal(str(write_reserve)),
            "errors": [],
        },
        "plans": results,
        "version_changes": build_version_changes(prepared_plans, results),
        "comparison_policy": "Adjacent plans only, aligned by stable IDs; no target and no ranking.",
    }


def failed_result(
    case_id: Optional[str],
    input_sha256: str,
    max_combinations: int,
    deadline_seconds: float,
    failure: Exception,
) -> Dict[str, Any]:
    if isinstance(failure, InputError):
        code, message = failure.code, failure.message
    else:
        code = "run_failed"
        message = "%s: %s" % (type(failure).__name__, failure)
    return {
        "schema_version": RESULT_SCHEMA,
        "case_id": case_id,
        "input_sha256": input_sha256,
        "run": {
            "status": "failed",
            "max_combinations": max_combinations,
            "deadline_seconds": Decimal(str(deadline_seconds)),
            "decimal_precision": PRECISION,
            "errors": [error_item("run", code, message)],
        },
        "plans": [],
        "version_changes": [],
    }


def positive_integer(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer")
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def positive_finite_seconds(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a number")
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("must be finite and greater than zero")
    return value


def real_path(path: str) -> str:
    return os.path.realpath(os.path.abspath(path))


def main(argv: Optional[Sequence[str]] = None) -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit")
    parser.add_argument("--max-combinations", type=positive_integer, default=100000)
    parser.add_argument(
        "--deadline-seconds", type=positive_finite_seconds, default=60.0
    )
    args = parser.parse_args(argv)
    paths = [real_path(args.input), real_path(args.output)]
    if args.audit:
        paths.append(real_path(args.audit))
    if len(set(paths)) != len(paths):
        parser.error("input, output, and audit paths must be distinct")

    audit = None
    result_file = None
    digest = hashlib.sha256(b"").hexdigest()
    case_id = None
    try:
        data, digest, _ = read_input(args.input)
        if isinstance(data.get("case_id"), str):
            case_id = data["case_id"]
        if args.audit:
            audit = AuditWriter(args.audit)
        result = execute_case(
            data,
            digest,
            audit,
            args.max_combinations,
            args.deadline_seconds,
            started,
        )
    except Exception as exc:
        digest = getattr(exc, "input_sha256", digest)
        result = failed_result(
            case_id, digest, args.max_combinations, args.deadline_seconds, exc
        )

    try:
        if audit is not None:
            audit.output.finish()
        result_file = AtomicFile(args.output)
        result_text = json.dumps(
            json_safe(result), ensure_ascii=False, allow_nan=False, indent=2
        )
        result_file.write(result_text + "\n")
        result_file.finish()
        if audit is not None:
            audit.output.commit()
        result_file.commit()
    except Exception as exc:
        if audit is not None:
            audit.output.abort()
        if result_file is not None:
            result_file.abort()
        print("error: unable to write output: %s" % exc, file=sys.stderr)
        return 1

    status = result["run"]["status"]
    if status == "failed":
        for item in result["run"]["errors"]:
            print("error: %s: %s" % (item["code"], item["message"]), file=sys.stderr)
        return 1
    if status == "partial":
        print("partial: %s" % args.output, file=sys.stderr)
        return 3
    print("success: %s" % args.output, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
