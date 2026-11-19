#!/usr/bin/env python3
"""Exact finish-to-start CPM calculator for explicitly adapted schedule data."""

import argparse
import heapq
import json
import os
import re
import sys
import tempfile
from decimal import Clamped, Decimal, DecimalException, Inexact, InvalidOperation, MAX_EMAX, MAX_PREC, MIN_EMIN, Overflow, Underflow, localcontext


SCHEMA_VERSION = "schedule-baseline/v1"
ROLE_ORDER = ("equipment", "labor", "wait", "assay", "other")
MAX_CRITICAL_PATHS = 10000
DECIMAL_PATTERN = re.compile(
    r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z"
)


class ScheduleError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.error = {"code": code, "message": message}
        if details:
            self.error["details"] = details


def fail(code, message, details=None):
    raise ScheduleError(code, message, details)


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail("duplicate_json_key", "Duplicate JSON key: {!r}".format(key))
        result[key] = value
    return result


def reject_non_finite_json(value):
    fail("non_finite_json_number", "NaN and Infinity are not valid input numbers: {}".format(value))


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(
                handle,
                object_pairs_hook=reject_duplicate_keys,
                parse_constant=reject_non_finite_json,
            )
    except ScheduleError:
        raise
    except json.JSONDecodeError as exc:
        fail(
            "invalid_json",
            "Invalid JSON at line {}, column {}".format(exc.lineno, exc.colno),
            {"reason": exc.msg},
        )
    except UnicodeDecodeError as exc:
        fail("invalid_encoding", "Input must be UTF-8", {"reason": str(exc)})
    except RecursionError:
        fail("nesting_limit", "Input exceeds the JSON decoder's nesting limit")
    except OSError as exc:
        fail("input_io_error", "Cannot read input file: {}".format(exc))


def require_object(value, path):
    if not isinstance(value, dict):
        fail("invalid_type", "{} must be a JSON object".format(path))
    return value


def require_list(value, path):
    if not isinstance(value, list):
        fail("invalid_type", "{} must be a JSON array".format(path))
    return value


def require_string(container, key, path):
    if key not in container:
        fail("missing_field", "Missing required field {}.{}".format(path, key))
    value = container[key]
    if not isinstance(value, str) or not value:
        fail("invalid_string", "{}.{} must be a non-empty string".format(path, key))
    return value


def decimal_value(raw, path, negative_code=None):
    if not isinstance(raw, str) or DECIMAL_PATTERN.fullmatch(raw) is None:
        fail(
            "invalid_decimal_string",
            "{} must be a finite decimal string without a unit suffix".format(path),
        )
    value = Decimal(raw)
    if not value.is_finite():
        fail("invalid_decimal_string", "{} must be finite".format(path))
    if value < 0:
        fail(negative_code or "negative_decimal", "{} must be non-negative".format(path))
    return value


def decimal_text(value):
    if value is None:
        return None
    if value.is_zero():
        return "0"
    return str(value)


def validate_input(data):
    require_object(data, "input")
    if data.get("schema_version") != SCHEMA_VERSION:
        fail(
            "unsupported_schema_version",
            "schema_version must be {!r}".format(SCHEMA_VERSION),
        )

    model = {
        "case_id": require_string(data, "case_id", "input"),
        "plan_id": require_string(data, "plan_id", "input"),
        "time_unit": require_string(data, "time_unit", "input"),
        "source_id": None,
        "numeric_values": [],
    }
    if "source_id" in data:
        model["source_id"] = require_string(data, "source_id", "input")
    if "tasks" not in data:
        fail("missing_field", "Missing required field input.tasks")
    raw_tasks = require_list(data["tasks"], "input.tasks")
    if not raw_tasks:
        fail("empty_tasks", "At least one task is required; makespan is undefined for an empty project")

    tasks = []
    by_id = {}
    for index, raw_task in enumerate(raw_tasks):
        path = "input.tasks[{}]".format(index)
        require_object(raw_task, path)
        task_id = require_string(raw_task, "id", path)
        if task_id in by_id:
            fail("duplicate_task_id", "Duplicate task id: {!r}".format(task_id))
        if "duration" not in raw_task:
            fail("missing_field", "Missing required field {}.duration".format(path))
        if "predecessors" not in raw_task:
            fail(
                "missing_predecessors",
                "Missing required field {}.predecessors; use [] only when absence of incoming edges was explicitly verified".format(path),
            )
        duration = decimal_value(
            raw_task["duration"],
            "{}.duration".format(path),
            "negative_duration",
        )
        raw_predecessors = require_list(raw_task["predecessors"], "{}.predecessors".format(path))
        predecessors = []
        predecessor_set = set()
        for pred_index, predecessor in enumerate(raw_predecessors):
            if not isinstance(predecessor, str) or not predecessor:
                fail(
                    "invalid_predecessor",
                    "{}.predecessors[{}] must be a non-empty task id string".format(path, pred_index),
                )
            if predecessor in predecessor_set:
                fail(
                    "duplicate_predecessor",
                    "Task {!r} lists predecessor {!r} more than once".format(task_id, predecessor),
                )
            predecessor_set.add(predecessor)
            predecessors.append(predecessor)

        source_id = require_string(raw_task, "source_id", path)
        role = raw_task.get("role", "other")
        if role not in ROLE_ORDER:
            fail(
                "invalid_role",
                "{}.role must be one of {}".format(path, ", ".join(ROLE_ORDER)),
            )
        for unit_key in ("time_unit", "duration_unit", "unit"):
            if unit_key in raw_task and raw_task[unit_key] != model["time_unit"]:
                fail(
                    "unit_conversion_required",
                    "{}.{} differs from input.time_unit; convert it explicitly before scheduling".format(path, unit_key),
                )

        task = {
            "id": task_id,
            "duration": duration,
            "predecessors": predecessors,
            "role": role,
            "source_id": source_id,
            "input_index": index,
        }
        if "locator" in raw_task:
            task["locator"] = raw_task["locator"]
        tasks.append(task)
        by_id[task_id] = task
        model["numeric_values"].append(duration)

    for task in tasks:
        for predecessor in task["predecessors"]:
            if predecessor not in by_id:
                fail(
                    "unknown_predecessor",
                    "Task {!r} has unknown predecessor {!r}".format(task["id"], predecessor),
                    {"task_id": task["id"], "predecessor": predecessor},
                )

    limits = {}
    if "resource_limits" in data:
        raw_limits = require_object(data["resource_limits"], "input.resource_limits")
        for resource, raw_limit in raw_limits.items():
            path = "input.resource_limits[{!r}]".format(resource)
            if not resource:
                fail("invalid_resource", "Resource names must be non-empty strings")
            require_object(raw_limit, path)
            if "capacity" not in raw_limit:
                fail("missing_field", "Missing required field {}.capacity".format(path))
            capacity = decimal_value(
                raw_limit["capacity"],
                "{}.capacity".format(path),
                "negative_resource_capacity",
            )
            limits[resource] = {
                "capacity": capacity,
                "source_id": require_string(raw_limit, "source_id", path),
            }
            if "locator" in raw_limit:
                limits[resource]["locator"] = raw_limit["locator"]
            model["numeric_values"].append(capacity)

    demands = {}
    demand_sources = {}
    if "resource_demands" in data:
        raw_demands = require_object(data["resource_demands"], "input.resource_demands")
        for task_id, raw_task_demands in raw_demands.items():
            path = "input.resource_demands[{!r}]".format(task_id)
            if task_id not in by_id:
                fail("unknown_demand_task", "Resource demands reference unknown task {!r}".format(task_id))
            require_object(raw_task_demands, path)
            task_demands = {}
            task_sources = {}
            for resource, raw_demand in raw_task_demands.items():
                if not resource:
                    fail("invalid_resource", "Resource names must be non-empty strings")
                source = {"source_id": by_id[task_id]["source_id"], "source_scope": "inherited_task_source"}
                if isinstance(raw_demand, dict):
                    source = {"source_id": require_string(raw_demand, "source_id", path), "source_scope": "explicit_resource_demand"}
                    if "locator" in raw_demand:
                        source["locator"] = raw_demand["locator"]
                    raw_demand = raw_demand.get("value")
                demand = decimal_value(
                    raw_demand,
                    "{}[{!r}]".format(path, resource),
                    "negative_resource_demand",
                )
                task_demands[resource] = demand
                task_sources[resource] = source
                model["numeric_values"].append(demand)
            demands[task_id] = task_demands
            demand_sources[task_id] = task_sources

    deadline = None
    if "deadline" in data:
        deadline = decimal_value(data["deadline"], "input.deadline", "negative_deadline")
        model["numeric_values"].append(deadline)

    model.update(
        {
            "tasks": tasks,
            "by_id": by_id,
            "limits": limits,
            "demands": demands,
            "demand_sources": demand_sources,
            "limits_present": "resource_limits" in data,
            "demands_present": "resource_demands" in data,
            "deadline": deadline,
        }
    )
    return model


def stable_topological_order(model):
    tasks = model["tasks"]
    by_id = model["by_id"]
    indegree = {task["id"]: len(task["predecessors"]) for task in tasks}
    successors = {task["id"]: [] for task in tasks}
    for task in tasks:
        for predecessor in task["predecessors"]:
            successors[predecessor].append(task["id"])
    for task_id in successors:
        successors[task_id].sort(key=lambda item: by_id[item]["input_index"])

    ready = [
        (task["input_index"], task["id"])
        for task in tasks
        if indegree[task["id"]] == 0
    ]
    heapq.heapify(ready)
    order = []
    while ready:
        _, task_id = heapq.heappop(ready)
        order.append(task_id)
        for successor in successors[task_id]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                heapq.heappush(ready, (by_id[successor]["input_index"], successor))
    if len(order) != len(tasks):
        ordered_set = set(order)
        unresolved = [task["id"] for task in tasks if task["id"] not in ordered_set]
        fail(
            "dependency_cycle",
            "The task dependency graph contains a cycle",
            {"unresolved_task_ids": unresolved},
        )
    model["successors"] = successors
    return order


def exact_context(model):
    values = [value for value in model["numeric_values"] if not value.is_zero()]
    task_count = len(model["tasks"])
    if values:
        minimum_exponent = min(value.as_tuple().exponent for value in values)
        maximum_adjusted = max(value.adjusted() for value in values)
        carry_digits = len(str(max(1, task_count)))
        precision = max(28, maximum_adjusted - minimum_exponent + carry_digits + 3)
    else:
        precision = 28
    if precision > MAX_PREC:
        fail("arithmetic_too_large", "Exact decimal arithmetic exceeds the implementation precision limit")
    context = localcontext()
    return context, precision


def calculate_cpm(model, order):
    by_id = model["by_id"]
    zero = Decimal(0)
    earliest_start = {}
    earliest_finish = {}
    for task_id in order:
        predecessors = by_id[task_id]["predecessors"]
        earliest_start[task_id] = max(
            (earliest_finish[pred] for pred in predecessors),
            default=zero,
        )
        earliest_finish[task_id] = earliest_start[task_id] + by_id[task_id]["duration"]

    makespan = max(earliest_finish[task_id] for task_id in order)
    latest_finish = {}
    latest_start = {}
    for task_id in reversed(order):
        successors = model["successors"][task_id]
        latest_finish[task_id] = (
            min(latest_start[successor] for successor in successors)
            if successors
            else makespan
        )
        latest_start[task_id] = latest_finish[task_id] - by_id[task_id]["duration"]
    total_float = {
        task_id: latest_start[task_id] - earliest_start[task_id]
        for task_id in order
    }
    return {
        "ES": earliest_start,
        "EF": earliest_finish,
        "LS": latest_start,
        "LF": latest_finish,
        "float": total_float,
        "makespan": makespan,
    }


def critical_path_result(model, order, cpm):
    by_id = model["by_id"]
    zero_float = [task_id for task_id in order if cpm["float"][task_id].is_zero()]
    critical_set = set(zero_float)
    tight_successors = {task_id: [] for task_id in zero_float}
    tight_predecessors = {task_id: [] for task_id in zero_float}
    tight_edges = []
    for task_id in zero_float:
        for successor in model["successors"][task_id]:
            if successor in critical_set and cpm["ES"][successor] == cpm["EF"][task_id]:
                tight_successors[task_id].append(successor)
                tight_predecessors[successor].append(task_id)
                tight_edges.append({"predecessor": task_id, "successor": successor})

    starts = [
        task_id
        for task_id in zero_float
        if cpm["ES"][task_id].is_zero() and not tight_predecessors[task_id]
    ]
    path_counts = {}
    for task_id in reversed(zero_float):
        successors = tight_successors[task_id]
        if not successors:
            path_counts[task_id] = int(cpm["EF"][task_id] == cpm["makespan"])
        else:
            path_counts[task_id] = sum(path_counts[successor] for successor in successors)
    path_count = sum(path_counts[task_id] for task_id in starts)
    complete = path_count <= MAX_CRITICAL_PATHS
    paths = []
    if complete:
        for start in starts:
            stack = [(start, [start])]
            while stack:
                task_id, path = stack.pop()
                successors = tight_successors[task_id]
                if not successors:
                    if cpm["EF"][task_id] == cpm["makespan"]:
                        paths.append(path)
                    continue
                for successor in reversed(successors):
                    stack.append((successor, path + [successor]))

    if path_count == 1:
        status = "unique"
    elif path_count > 1:
        status = "multiple"
    else:
        status = "none"
    result = {
        "status": status,
        "path_count": str(path_count),
        "complete": complete,
        "paths": paths,
        "definition": "Source-to-sink paths using only zero-float tasks and tight finish-to-start edges",
        "evidence": {
            "zero_float_tasks": zero_float,
            "tight_finish_start_edges": tight_edges,
        },
    }
    if not complete:
        result["evidence_note"] = (
            "The exact path count and the complete zero-float tight-edge graph are provided; "
            "path expansion was omitted because it exceeds {} paths".format(MAX_CRITICAL_PATHS)
        )
    return result


def task_output(task, cpm):
    result = {
        "id": task["id"],
        "role": task["role"],
        "source_id": task["source_id"],
        "predecessors": task["predecessors"],
        "duration": decimal_text(task["duration"]),
        "ES": decimal_text(cpm["ES"][task["id"]]),
        "EF": decimal_text(cpm["EF"][task["id"]]),
        "LS": decimal_text(cpm["LS"][task["id"]]),
        "LF": decimal_text(cpm["LF"][task["id"]]),
        "float": decimal_text(cpm["float"][task["id"]]),
    }
    if "locator" in task:
        result["locator"] = task["locator"]
    return result


def demand_evidence(task, resource, model):
    source = model["demand_sources"][task["id"]][resource]
    evidence = {
        "task_id": task["id"],
        "demand": decimal_text(model["demands"][task["id"]][resource]),
        "source_id": source["source_id"],
        "source_scope": source["source_scope"],
    }
    if "locator" in source:
        evidence["locator"] = source["locator"]
    else:
        evidence["normalized_input_pointer"] = "/resource_demands/{}/{}".format(
            task["id"].replace("~", "~0").replace("/", "~1"),
            resource.replace("~", "~0").replace("/", "~1"),
        )
    return evidence


def interval_evidence(start, end, declared_demand, active, missing, resource, model, capacity=None):
    evidence = {
        "timepoint": decimal_text(start),
        "interval": {"start": decimal_text(start), "end": decimal_text(end)},
        "declared_demand": decimal_text(declared_demand),
        "active_demands": [
            demand_evidence(model["by_id"][task_id], resource, model)
            for task_id in active
        ],
        "missing_active_task_demands": missing,
        "incomplete_coverage": bool(missing),
    }
    if capacity is not None:
        evidence["declared_excess_over_capacity"] = decimal_text(declared_demand - capacity)
    return evidence


def resource_result(resource, model, order, cpm):
    limit = model["limits"].get(resource)
    capacity = limit["capacity"] if limit is not None else None
    positive_tasks = [task_id for task_id in order if model["by_id"][task_id]["duration"] > 0]
    missing_declarations = [
        task_id
        for task_id in positive_tasks
        if resource not in model["demands"].get(task_id, {})
    ]
    full_coverage = model["demands_present"] and not missing_declarations
    endpoints = sorted(
        {cpm["ES"][task_id] for task_id in order}
        | {cpm["EF"][task_id] for task_id in order}
    )
    zero = Decimal(0)
    maximum_declared = zero
    maximum_evidence = {
        "timepoint": "0",
        "interval": None,
        "declared_demand": "0",
        "active_demands": [],
        "missing_active_task_demands": [],
        "incomplete_coverage": bool(positive_tasks and not full_coverage),
    }
    atomic_overloads = []

    for start, end in zip(endpoints, endpoints[1:]):
        if not start < end:
            continue
        active = [
            task_id
            for task_id in positive_tasks
            if cpm["ES"][task_id] <= start < cpm["EF"][task_id]
        ]
        declared_active = [
            task_id
            for task_id in active
            if resource in model["demands"].get(task_id, {})
        ]
        missing_active = [task_id for task_id in active if task_id not in declared_active]
        declared_demand = sum(
            (model["demands"][task_id][resource] for task_id in declared_active),
            zero,
        )
        if declared_demand > maximum_declared:
            maximum_declared = declared_demand
            maximum_evidence = interval_evidence(
                start,
                end,
                declared_demand,
                declared_active,
                missing_active,
                resource,
                model,
            )
        if capacity is not None and declared_demand > capacity:
            evidence = interval_evidence(
                start,
                end,
                declared_demand,
                declared_active,
                missing_active,
                resource,
                model,
                capacity,
            )
            atomic_overloads.append(
                {
                    "start": start,
                    "end": end,
                    "declared_demand": declared_demand,
                    "evidence": [evidence],
                }
            )

    merged_overloads = []
    for interval in atomic_overloads:
        if merged_overloads and merged_overloads[-1]["end"] == interval["start"]:
            previous = merged_overloads[-1]
            previous["end"] = interval["end"]
            previous["declared_demand"] = max(
                previous["declared_demand"], interval["declared_demand"]
            )
            previous["evidence"].extend(interval["evidence"])
        else:
            merged_overloads.append(interval)

    overloads = []
    for interval in merged_overloads:
        overloads.append(
            {
                "start": decimal_text(interval["start"]),
                "end": decimal_text(interval["end"]),
                "capacity": decimal_text(capacity),
                "maximum_concurrent_demand": (
                    decimal_text(interval["declared_demand"]) if full_coverage else None
                ),
                "declared_maximum_concurrent_demand": decimal_text(interval["declared_demand"]),
                "maximum_declared_excess_over_capacity": decimal_text(
                    interval["declared_demand"] - capacity
                ),
                "bound": "exact" if full_coverage else "lower_bound",
                "evidence": interval["evidence"],
            }
        )

    reasons = []
    if capacity is None:
        reasons.append("missing_resource_limit")
    if not model["demands_present"]:
        reasons.append("missing_resource_demands")
    elif missing_declarations:
        reasons.append("incomplete_explicit_demand_coverage")
    if overloads:
        status = "overloaded_at_cpm_earliest_schedule"
    elif capacity is not None and full_coverage:
        status = "within_limits_at_cpm_earliest_schedule"
    else:
        status = "undetermined"

    result = {
        "resource": resource,
        "capacity": decimal_text(capacity),
        "comparison_status": status,
        "undetermined_reasons": reasons,
        "explicit_demand_coverage": "complete" if full_coverage else "incomplete",
        "missing_task_demands": missing_declarations,
        "maximum_concurrent_demand": decimal_text(maximum_declared) if full_coverage else None,
        "declared_maximum_concurrent_demand": decimal_text(maximum_declared),
        "maximum_bound": "exact" if full_coverage else "lower_bound",
        "maximum_evidence": maximum_evidence,
        "overload_intervals": overloads,
    }
    if limit is not None:
        result["limit_source_id"] = limit["source_id"]
        if "locator" in limit:
            result["limit_locator"] = limit["locator"]
    return result


def resource_analysis(model, order, cpm):
    resources = sorted(
        set(model["limits"])
        | {
            resource
            for task_demands in model["demands"].values()
            for resource in task_demands
        }
    )
    records = [resource_result(resource, model, order, cpm) for resource in resources]
    if any(record["comparison_status"] == "overloaded_at_cpm_earliest_schedule" for record in records):
        status = "overloaded_at_cpm_earliest_schedule"
    elif records and all(
        record["comparison_status"] == "within_limits_at_cpm_earliest_schedule"
        for record in records
    ):
        status = "within_limits_at_cpm_earliest_schedule"
    else:
        status = "undetermined"
    return {
        "status": status,
        "basis": "Fixed CPM earliest-start schedule with half-open task occupancy intervals [ES, EF)",
        "zero_demand_assumption": "None: omitted task-resource demands make an exact maximum undetermined",
        "resource_constrained_schedule_status": "undetermined",
        "note": (
            "Overload findings apply to the fixed CPM earliest-start schedule. "
            "No resource leveling, alternative schedule search, global feasibility, or optimality is claimed"
        ),
        "resources": records,
    }


def duration_sums(model):
    sums = {role: Decimal(0) for role in ROLE_ORDER}
    for task in model["tasks"]:
        sums[task["role"]] += task["duration"]
    return {
        "time_unit": model["time_unit"],
        "by_role": {role: decimal_text(sums[role]) for role in ROLE_ORDER},
        "method": "Plain per-role sums of task durations; overlapping task durations are counted repeatedly",
        "person_hours": None,
        "person_hours_status": "undetermined",
        "notes": [
            "Labor task-duration sum is not person-hours; explicit staffing per task is required",
            "Equipment task-duration sum is not equipment-hours without explicit equipment demand and compatible time units",
            "Wait, assay, equipment, labor, and other sums are not elapsed time; only makespan is the CPM elapsed duration",
        ],
    }


def calculate(model):
    order = stable_topological_order(model)
    context_manager, precision = exact_context(model)
    with context_manager as context:
        context.prec = precision
        context.Emax = MAX_EMAX
        context.Emin = MIN_EMIN
        context.traps[Inexact] = True
        context.traps[InvalidOperation] = True
        context.traps[Overflow] = True
        context.traps[Underflow] = True
        context.traps[Clamped] = True
        cpm = calculate_cpm(model, order)
        critical = critical_path_result(model, order, cpm)
        resources = resource_analysis(model, order, cpm)
        aggregates = duration_sums(model)
        margin = model["deadline"] - cpm["makespan"] if model["deadline"] is not None else None

    deadline = {
        "status": "computed" if margin is not None else "undetermined",
        "value": decimal_text(model["deadline"]),
        "margin": decimal_text(margin),
        "time_unit": model["time_unit"],
        "definition": "deadline - makespan; relative numeric values only, with no date or timezone interpretation",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": model["case_id"],
        "plan_id": model["plan_id"],
        "source_id": model["source_id"],
        "time_unit": model["time_unit"],
        "status": "success",
        "errors": [],
        "makespan": decimal_text(cpm["makespan"]),
        "topological_order": order,
        "tasks": [task_output(model["by_id"][task_id], cpm) for task_id in order],
        "critical_path": critical,
        "deadline": deadline,
        "duration_sums": aggregates,
        "resource_analysis": resources,
        "method": {
            "network": "Finish-to-start CPM; ES=max predecessor EF and EF=ES+duration",
            "schedule": "Earliest-start CPM baseline",
            "global_optimality": "not_assessed",
        },
    }


def safe_identifier(data, key):
    if isinstance(data, dict) and isinstance(data.get(key), str):
        return data[key]
    return None


def error_result(data, errors):
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": safe_identifier(data, "case_id"),
        "plan_id": safe_identifier(data, "plan_id"),
        "source_id": safe_identifier(data, "source_id"),
        "time_unit": safe_identifier(data, "time_unit"),
        "status": "error",
        "errors": errors,
        "makespan": None,
        "topological_order": [],
        "tasks": [],
        "critical_path": {
            "status": "undetermined",
            "path_count": None,
            "complete": False,
            "paths": [],
            "evidence": {"zero_float_tasks": [], "tight_finish_start_edges": []},
        },
        "deadline": {
            "status": "undetermined",
            "value": None,
            "margin": None,
            "time_unit": safe_identifier(data, "time_unit"),
            "definition": "deadline - makespan; relative numeric values only",
        },
        "duration_sums": None,
        "resource_analysis": {
            "status": "undetermined",
            "resource_constrained_schedule_status": "undetermined",
            "resources": [],
        },
    }


def atomic_write_json(path, result):
    destination = os.path.abspath(path)
    parent = os.path.dirname(destination) or os.curdir
    temporary_path = None
    try:
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".{}-".format(os.path.basename(destination)),
            suffix=".tmp",
            dir=parent,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Schedule baseline JSON input")
    parser.add_argument("--output", required=True, help="Atomically written JSON result")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    data = None
    status = 0
    try:
        data = load_json(args.input)
        model = validate_input(data)
        result = calculate(model)
    except ScheduleError as exc:
        result = error_result(data, [exc.error])
        status = 2
    except DecimalException as exc:
        error = {
            "code": "exact_arithmetic_error",
            "message": "Exact decimal arithmetic failed without falling back to floats: {}".format(exc),
        }
        result = error_result(data, [error])
        status = 2

    try:
        atomic_write_json(args.output, result)
    except OSError as exc:
        print("Cannot write output file atomically: {}".format(exc), file=sys.stderr)
        return 2
    return status


if __name__ == "__main__":
    sys.exit(main())
