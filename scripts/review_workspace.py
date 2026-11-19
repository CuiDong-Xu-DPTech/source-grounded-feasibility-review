#!/usr/bin/env python3
import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inspect_case as inspector
import validate_result as validator


def read_json(path):
    return inspector.load_strict_json_bytes(inspector.read_regular_file(path, "input"), "input")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False)
    temporary = handle.name
    try:
        with handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def scalar(record, names):
    for name in names:
        if name in record and not isinstance(record[name], (dict, list)):
            return record[name]
    return None


def source_entries(inspection, needed=()):
    records = []
    for entry in inspection["source_registry"]["sources"]:
        roles = set(entry.get("roles", []))
        if roles & {"case_reference", "case_argument"} or entry["source_id"] in needed:
            records.append({key: copy.deepcopy(entry[key]) for key in
                            ("source_id", "path", "bytes", "extension", "case_json_pointers", "roles")
                            if key in entry})
    return records


def collect_source_ids(value):
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "source_id" and isinstance(child, str):
                found.add(child)
            else:
                found.update(collect_source_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(collect_source_ids(child))
    return found


def prepare(args):
    case = read_json(args.case)
    inspection = inspect_input(args.case, args.task, args.resource_root, args.out)
    workspace = {
        "schema_version": "source-grounded-review-workspace/v1",
        "case_id": inspection["case_id"],
        "case_file": str(Path(args.case).resolve()),
        "inspection_file": str(args.out / "case_inspection.json"),
        "source_registry": source_entries(inspection),
        "plans": [],
        "overall_decision": "",
        "uncertainty": [],
        "change_records": [],
        "custom_change_comparison": False,
    }
    for index, plan in enumerate(case.get("plans", [])):
        if not isinstance(plan, dict):
            continue
        plan_id = scalar(plan, ("plan_id", "id"))
        version = scalar(plan, ("plan_version", "version", "version_id"))
        checks = []
        for r_index, rubric in enumerate(case.get("public_rubrics", [])):
            if not isinstance(rubric, dict):
                continue
            applies = rubric.get("applies_to", rubric.get("plans"))
            if isinstance(applies, list) and applies:
                if plan_id is not None and plan_id not in applies and version not in applies:
                    continue
            check = {
                "check_id": scalar(rubric, ("check_id", "rubric_id", "id")),
                "axis": rubric.get("axis"),
                "judgment": None,
                "observed_facts": None,
                "evidence": [],
                "uncertainty": None,
                "disposition": {"status": "not_reviewed"},
                "rubric_pointer": "/public_rubrics/%d" % r_index,
            }
            for key in ("requirement", "criterion", "hard", "hard_threshold_or_documentary_gate"):
                if key in rubric:
                    check[key] = copy.deepcopy(rubric[key])
            checks.append(check)
        workspace["plans"].append({
            "plan_id": plan_id,
            "plan_version": version,
            "plan_pointer": "/plans/%d" % index,
            "input_plan": copy.deepcopy(plan),
            "checks": checks,
        })
    supported = (
        inspection["case_id"] is not None
        and isinstance(inspection["output_contract"], dict)
        and isinstance(inspection["output_contract"].get("plan_reviews"), list)
        and any(plan["plan_id"] is not None for plan in workspace["plans"])
        and any(check["check_id"] is not None
                for plan in workspace["plans"] for check in plan["checks"])
    )
    workspace["support"] = {
        "supported": supported,
        "reason": "Auto assembly requires a literal output_contract with a plan_reviews array and explicit plan/check IDs. Other schemas require the normal evidence-ledger workflow, not inferred fields."
    }
    write_json(args.out / "review_workspace.json", workspace)
    if supported:
        initial = copy.deepcopy(inspection["output_contract"])
        initial.update({"case_id": inspection["case_id"], "plan_reviews": [], "status": "partial"})
        if isinstance(initial.get("sources"), list):
            initial["sources"] = copy.deepcopy(workspace["source_registry"])
        write_json(args.initial_result if args.initial_result else args.out / "initial_result.json", initial)
    print(json.dumps({"case_id": inspection["case_id"], "supported": supported,
                      "plans": len(workspace["plans"]), "workspace": str(args.out / "review_workspace.json")}, ensure_ascii=False))


def inspect_input(case_path, task_path, root, out):
    namespace = inspector.build_parser().parse_args([
        "--case", str(case_path), "--task", str(task_path), "--resource-root", str(root),
        "--output", str(out / "case_inspection.json"),
    ])
    return inspector.inspect(namespace)


def is_complete(check):
    if check.get("judgment") in (None, "", "pending", "not_reviewed"):
        return False
    facts = check.get("observed_facts")
    if facts is None or (isinstance(facts, (str, list, dict)) and not facts):
        return False
    disposition = check.get("disposition")
    if disposition is None:
        return False
    if isinstance(disposition, str) and not disposition.strip():
        return False
    if isinstance(disposition, dict) and disposition.get("status") in (None, "pending", "not_reviewed"):
        return False
    return True


def diff_records(workspace, case):
    source_id = next((entry["source_id"] for entry in workspace["source_registry"]
                      if "case_argument" in entry.get("roles", [])), None)
    if source_id is None:
        raise ValueError("Cannot bind candidate change records to the actual case file")
    records = []
    missing = object()

    def stored(value):
        return None if value is missing else copy.deepcopy(value)

    def difference_evidence(index, pointer):
        for candidate_index in (index, index + 1):
            location = "/plans/%d%s" % (candidate_index, pointer)
            try:
                validator.resolve_json_pointer(case, location)
            except (ValueError, KeyError):
                continue
            return {"source_id": source_id, "case_json_pointer": location}
        parent = "/plans/%d" % index
        validator.resolve_json_pointer(case, parent)
        return {
            "source_id": source_id, "case_json_pointer": parent,
            "unresolved_historical_input_pointer": "/plans/%d%s" % (index, pointer),
            "locator_scope": "The actual prior-plan root is resolvable. The nested path is retained only for the version comparison; it is not an existing case value or evidence that the removed field was supplied.",
        }

    def walk(index, pointer, before, after, left, right):
        if isinstance(before, dict) and isinstance(after, dict):
            for key in sorted(set(before) | set(after)):
                token = str(key).replace("~", "~0").replace("/", "~1")
                walk(index, pointer + "/" + token,
                     before[key] if key in before else missing,
                     after[key] if key in after else missing, left, right)
            return
        if before == after:
            return
        item = {
            "change_scope": "candidate_input_delta",
            "path": pointer, "from": stored(before), "to": stored(after),
            "from_present": before is not missing, "to_present": after is not missing,
            "from_plan_id": left.get("plan_id"), "to_plan_id": right.get("plan_id"),
            "evidence": [difference_evidence(index - 1, pointer)],
            "pointer_scope": "from_pointer/target_pointer describe the compared input sequence and may be absent with the field; evidence.case_json_pointer always resolves against the actual case.",
        }
        if before is not missing:
            item["from_pointer"] = "/plans/%d%s" % (index - 1, pointer)
        if after is not missing:
            item["target_pointer"] = "/plans/%d%s" % (index, pointer)
        records.append(item)

    for index, (left, right) in enumerate(zip(workspace["plans"], workspace["plans"][1:]), 1):
        walk(index, "", left["input_plan"], right["input_plan"], left, right)
    return records


def finalize(args):
    workspace = read_json(args.work / "review_workspace.json")
    case = read_json(args.case)
    if not workspace["support"]["supported"]:
        raise ValueError("This case is not supported for automatic contract assembly; use the ordinary workflow")
    if Path(workspace["case_file"]).resolve() != Path(args.case).resolve():
        raise ValueError("The workspace belongs to different case bytes or a different path; prepare it again")
    if case["case_id"] != workspace["case_id"]:
        raise ValueError("Case identity differs between workspace and actual input")
    inspection = read_json(workspace["inspection_file"])
    current_hash = "sha256:" + hashlib.sha256(inspector.read_regular_file(args.case, "case")).hexdigest()
    if inspection["case_file"]["source_id"] != current_hash:
        raise ValueError("Case bytes changed after this workspace was prepared; prepare it again and do not reuse old evidence hashes")
    complete = True
    for plan in workspace["plans"]:
        for check in plan["checks"]:
            if not is_complete(check):
                complete = False
                if not args.allow_partial:
                    raise ValueError("Unfinished or unjustified check: %s / %s" % (plan["plan_id"], check["check_id"]))
            if not check.get("evidence") and check.get("judgment") in ("met", "unmet"):
                raise ValueError("Judgment without supporting evidence: %s / %s" % (plan["plan_id"], check["check_id"]))
    if not workspace["overall_decision"]:
        complete = False
    plan_reviews = []
    for plan in workspace["plans"]:
        item = {"plan_pointer": plan["plan_pointer"]}
        if plan["plan_id"] is not None:
            item["plan_id"] = plan["plan_id"]
        if plan["plan_version"] is not None:
            item["plan_version"] = plan["plan_version"]
        item["checks"] = copy.deepcopy(plan["checks"])
        plan_reviews.append(item)
    result = copy.deepcopy(case["output_contract"])
    result.update({"case_id": workspace["case_id"], "plan_reviews": plan_reviews,
                   "overall_decision": workspace["overall_decision"], "status": "success" if complete else "partial"})
    needed = collect_source_ids(plan_reviews)
    current_inspection = read_json(workspace["inspection_file"])
    workspace["source_registry"] = source_entries(current_inspection, needed)
    for key in ("sources", "evidence_sources"):
        if key in result:
            result[key] = copy.deepcopy(workspace["source_registry"])
    if workspace.get("uncertainty") is not None:
        result["uncertainty"] = copy.deepcopy(workspace["uncertainty"])
    if workspace.get("change_records"):
        result["change_records"] = copy.deepcopy(workspace["change_records"])
    else:
        result["change_records"] = diff_records(workspace, case)
    if "uncertainty" in result and isinstance(result["uncertainty"], list) and not workspace["overall_decision"]:
        result["uncertainty"] = result["uncertainty"] + [{"code": "summary_pending", "detail": "The overall decision has not been provided."}]
    write_json(args.output, result)
    validation_code = None
    if args.validate:
        report = Path(args.work) / "validation-report.json"
        with report.open("w", encoding="utf-8") as handle:
            command = [sys.executable, str(Path(__file__).with_name("validate_result.py")),
                       "--case", str(Path(args.case).resolve()), "--result", str(Path(args.output).resolve()),
                       "--inspection", workspace["inspection_file"], "--summary"]
            if args.evidence:
                command.extend(["--evidence", str(Path(args.evidence).resolve())])
            process = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, text=True)
        validation_code = process.returncode
    status = "success" if complete and validation_code in (None, 0) else "partial"
    if status == "partial":
        result["status"] = "partial"
        write_json(args.output, result)
    if status == "partial" and not args.allow_partial:
        raise ValueError("Review is incomplete or failed validation; see %s" % args.output)
    print(json.dumps({"case_id": workspace["case_id"], "status": status,
                      "validation_returncode": validation_code, "result": args.output}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="Scaffold source-grounded review workspaces; never invent judgments")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--case", required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--resource-root", default="/input")
    p.add_argument("--initial-result")
    p.set_defaults(function=prepare)
    f = commands.add_parser("finalize")
    f.add_argument("--case", required=True)
    f.add_argument("--work", required=True, type=Path)
    f.add_argument("--output", required=True)
    f.add_argument("--validate", action="store_true")
    f.add_argument("--evidence")
    f.add_argument("--allow-partial", action="store_true")
    f.set_defaults(function=finalize)
    args = parser.parse_args()
    try:
        args.function(args)
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError, inspector.InspectionError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
