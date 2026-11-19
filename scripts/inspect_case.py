#!/usr/bin/env python3
"""Inspect a case without inferring a scientific schema or extracting PDFs."""

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from collections import Counter, deque


SCHEMA_MAX_NODES = 3000
SCHEMA_MAX_DEPTH = 32
SCHEMA_MAX_OBJECT_KEYS = 256
SCHEMA_STRING_SUMMARY = 160
RESOURCE_LIST_LIMIT = 512
SYMLINK_REPORT_LIMIT = 512
PATH_STRING_LIMIT = 4096
PATH_KEY_TERMS = (
    "path",
    "file",
    "material",
    "resource",
    "attachment",
    "document",
    "artifact",
    "source",
)
REVIEW_TERMS = ("plan", "version", "candidate")
SKIPPED_URI_RE = re.compile(r"^(?:https?|ftp|doi|arxiv|sha256):", re.IGNORECASE)
PATH_SUFFIX_RE = re.compile(r"\.[A-Za-z0-9]{1,16}$")


class InspectionError(Exception):
    pass


def pointer_escape(token):
    return str(token).replace("~", "~0").replace("/", "~1")


def child_pointer(pointer, token):
    return pointer + "/" + pointer_escape(token)


def pointer_tokens(pointer):
    if pointer == "":
        return []
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


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


def json_values_equal(left, right):
    pending = [(left, right)]
    while pending:
        a, b = pending.pop()
        if type(a) is not type(b):
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


def occurrence_status(occurrences):
    if not occurrences:
        return "missing", None
    first = occurrences[0]["value"]
    if all(json_values_equal(first, item["value"]) for item in occurrences[1:]):
        return ("unique" if len(occurrences) == 1 else "repeated_equal"), first
    return "conflict", None


def canonical_occurrence(case, occurrences, wanted_key):
    root_pointer = child_pointer("", wanted_key)
    root = [item for item in occurrences if item["pointer"] == root_pointer]
    if root and isinstance(case, dict) and wanted_key in case:
        value = case[wanted_key]
        differences = [
            item for item in occurrences
            if item["pointer"] != root_pointer and not json_values_equal(value, item["value"])
        ]
        return "root", value, root_pointer, differences
    status, value = occurrence_status(occurrences)
    pointer = occurrences[0]["pointer"] if status in ("unique", "repeated_equal") else None
    return status, value, pointer, []


def reject_constant(value):
    raise InspectionError("non-finite JSON number is forbidden: %s" % value)


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InspectionError("duplicate JSON object key: %r" % key)
        result[key] = value
    return result


def load_strict_json_bytes(data, label):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InspectionError("%s is not valid UTF-8: %s" % (label, exc))
    try:
        return json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except InspectionError:
        raise
    except json.JSONDecodeError as exc:
        raise InspectionError(
            "%s is not strict JSON at line %d column %d: %s"
            % (label, exc.lineno, exc.colno, exc.msg)
        )
    except RecursionError:
        raise InspectionError("%s exceeds the JSON decoder's nesting limit" % label)


def read_regular_file(path, label):
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise InspectionError("cannot stat %s %s: %s" % (label, path, exc))
    if stat.S_ISLNK(info.st_mode):
        raise InspectionError("%s must not be a symlink: %s" % (label, path))
    if not stat.S_ISREG(info.st_mode):
        raise InspectionError("%s is not a regular file: %s" % (label, path))
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise InspectionError("cannot read %s %s: %s" % (label, path, exc))


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


def atomic_write_json(path, value):
    destination = os.path.abspath(path)
    parent = os.path.dirname(destination) or os.curdir
    os.makedirs(parent, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=parent, prefix=".case_inspection.", delete=False
        ) as handle:
            temporary = handle.name
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        raise InspectionError("cannot atomically write inspection %s: %s" % (destination, exc))


def scalar_summary(value):
    if isinstance(value, str):
        compact = value.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
        return {
            "length": len(value),
            "preview": compact[:SCHEMA_STRING_SUMMARY],
            "preview_truncated": len(compact) > SCHEMA_STRING_SUMMARY,
        }
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)[:SCHEMA_STRING_SUMMARY]


def make_schema_outline(case):
    nodes = []
    queue = deque([(case, "", 0)])
    truncated = False
    while queue and len(nodes) < SCHEMA_MAX_NODES:
        value, pointer, depth = queue.popleft()
        kind = json_type(value)
        node = {"pointer": pointer, "type": kind, "depth": depth}
        if depth >= SCHEMA_MAX_DEPTH and isinstance(value, (dict, list)):
            node["children_truncated"] = True
            truncated = True
            nodes.append(node)
            continue
        if isinstance(value, dict):
            keys = list(value)
            node["keys"] = keys[:SCHEMA_MAX_OBJECT_KEYS]
            node["key_count"] = len(keys)
            if len(keys) > SCHEMA_MAX_OBJECT_KEYS:
                node["key_list_truncated"] = True
                truncated = True
            for key in keys:
                queue.append((value[key], child_pointer(pointer, key), depth + 1))
        elif isinstance(value, list):
            node["length"] = len(value)
            node["element_types"] = dict(sorted(Counter(json_type(item) for item in value).items()))
            for index, item in enumerate(value):
                queue.append((item, child_pointer(pointer, index), depth + 1))
        else:
            node["summary"] = scalar_summary(value)
        nodes.append(node)
    if queue:
        truncated = True
    return {
        "format": "flat_json_pointer_nodes_v1",
        "node_limit": SCHEMA_MAX_NODES,
        "depth_limit": SCHEMA_MAX_DEPTH,
        "object_key_list_limit": SCHEMA_MAX_OBJECT_KEYS,
        "nodes": nodes,
        "nodes_returned": len(nodes),
        "truncated": truncated,
        "note": "This is a bounded structural outline, not a formal schema.",
    }


def normalized_key(key):
    return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")


def is_reference_key(key):
    normalized = normalized_key(key)
    if not normalized:
        return False
    tokens = normalized.split("_")
    return any(term in tokens or normalized.endswith("_" + term) for term in PATH_KEY_TERMS)


def path_shaped(value):
    suffix = PATH_SUFFIX_RE.search(value)
    meaningful_extension = (
        suffix is not None and suffix.start() > 0
        and suffix.group()[1:2].isalpha() and not re.search(r"\s", value)
    )
    return "/" in value or "\\" in value or meaningful_extension


def reference_candidate(value, key_context):
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    normalized_key_name = normalized_key(key_context)
    if not stripped:
        return normalized_key_name == "path" or normalized_key_name.endswith("_path")
    if len(value) > PATH_STRING_LIMIT or "\x00" in value or "\n" in value or "\r" in value:
        return False
    if SKIPPED_URI_RE.match(stripped) or stripped.startswith("#"):
        return False
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", stripped):
        return False
    return path_shaped(stripped)


def candidate_files(raw_path, resource_root, case_directory):
    stripped = raw_path.strip()
    if not stripped:
        return []
    if os.path.isabs(stripped):
        candidates = [stripped]
    else:
        candidates = [os.path.join(resource_root, stripped), os.path.join(case_directory, stripped)]
    result = []
    seen = set()
    for candidate in candidates:
        absolute = os.path.abspath(candidate)
        if absolute not in seen:
            seen.add(absolute)
            result.append(absolute)
    return result


def regular_file_without_final_symlink(path):
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)


def descendant_has_symlink(root, path):
    try:
        common = os.path.commonpath([root, path])
    except ValueError:
        return False
    if common != root:
        return False
    relative = os.path.relpath(path, root)
    if relative == os.curdir:
        return False
    current = root
    for component in relative.split(os.sep):
        current = os.path.join(current, component)
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                return True
        except OSError:
            return False
    return False


def collect_case_review(case):
    case_ids = []
    contracts = []
    help_occurrences = []
    rubric_occurrences = []
    resource_lists = []
    resource_lists_truncated = False
    references = []
    stack = [(case, "", "")]
    while stack:
        value, pointer, key_context = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = child_pointer(pointer, key)
                stack.append((child, child_path, key))
                lowered = key.lower()
                if key == "case_id":
                    case_ids.append({"pointer": child_path, "value": child})
                if key == "output_contract":
                    contracts.append({"pointer": child_path, "value": child})
                if "help" in lowered:
                    help_occurrences.append({"pointer": child_path, "value": child})
                if "rubric" in lowered:
                    rubric_occurrences.append(
                        {
                            "pointer": child_path,
                            "value": child,
                            "item_count": len(child) if isinstance(child, list) else None,
                            "has_16_items": isinstance(child, list) and len(child) == 16,
                        }
                    )
        elif isinstance(value, list):
            path_terms = set()
            for token in pointer_tokens(pointer):
                lowered = token.lower()
                path_terms.update(term for term in REVIEW_TERMS if term in lowered)
            matches = []
            element_terms = set()
            for index, item in enumerate(value):
                stack.append((item, child_pointer(pointer, index), key_context))
                if isinstance(item, dict):
                    for key in item:
                        lowered = key.lower()
                        found = [term for term in REVIEW_TERMS if term in lowered]
                        if found and len(matches) < 64:
                            matches.append(
                                {
                                    "pointer": child_pointer(child_pointer(pointer, index), key),
                                    "terms": found,
                                }
                            )
                        element_terms.update(found)
            if path_terms or element_terms:
                if len(resource_lists) < RESOURCE_LIST_LIMIT:
                    resource_lists.append(
                        {
                            "pointer": pointer,
                            "length": len(value),
                            "path_terms": sorted(path_terms),
                            "element_key_terms": sorted(element_terms),
                            "matching_key_pointers": matches,
                            "review_only": True,
                        }
                    )
                else:
                    resource_lists_truncated = True
        elif isinstance(value, str) and reference_candidate(value, key_context):
            references.append({"pointer": pointer, "value": value, "key_context": key_context})
    case_ids.sort(key=lambda item: item["pointer"])
    contracts.sort(key=lambda item: item["pointer"])
    help_occurrences.sort(key=lambda item: item["pointer"])
    rubric_occurrences.sort(key=lambda item: item["pointer"])
    resource_lists.sort(key=lambda item: item["pointer"])
    references.sort(key=lambda item: item["pointer"])
    metadata_help = [
        item
        for item in help_occurrences
        if any(normalized_key(token) in ("metadata", "meta") for token in pointer_tokens(item["pointer"]))
    ]
    return {
        "case_id_occurrences": case_ids,
        "output_contract_occurrences": contracts,
        "help_occurrences": help_occurrences,
        "metadata_help_occurrences": metadata_help,
        "rubric_occurrences": rubric_occurrences,
        "resource_list_review_candidates": resource_lists,
        "resource_list_review_note": (
            "Name-based and direct-element-key matches are review locations only; "
            "they do not establish scientific meaning. The candidate list is capped at %d."
            % RESOURCE_LIST_LIMIT
        ),
        "resource_list_review_truncated": resource_lists_truncated,
        "reference_candidates": references,
    }


def inspect(args):
    case_path = os.path.abspath(args.case)
    task_path = os.path.abspath(args.task)
    resource_root = os.path.abspath(args.resource_root)
    case_bytes = read_regular_file(case_path, "case")
    case = load_strict_json_bytes(case_bytes, "case")
    if not isinstance(case, dict):
        raise InspectionError("case top level must be a JSON object; got %s" % json_type(case))

    review = collect_case_review(case)
    case_id_status, case_id, case_id_pointer, case_id_differences = canonical_occurrence(
        case, review["case_id_occurrences"], "case_id"
    )
    contract_status, contract, contract_pointer, contract_differences = canonical_occurrence(
        case, review["output_contract_occurrences"], "output_contract"
    )
    case_directory = os.path.dirname(case_path)
    sources = []
    by_path = {}
    diagnostics = []
    for item in case_id_differences:
        diagnostics.append(
            {
                "severity": "warning", "code": "nested_case_id_differs_from_root",
                "pointer": item["pointer"], "root_pointer": case_id_pointer,
                "root_value": case_id, "nested_value": item["value"],
                "message": "Root case_id remains canonical; this nested value is retained but is non-fatal.",
            }
        )
    for item in contract_differences:
        diagnostics.append(
            {
                "severity": "warning", "code": "nested_output_contract_differs_from_root",
                "pointer": item["pointer"], "root_pointer": contract_pointer,
                "nested_value": item["value"],
                "message": "Root output_contract remains canonical; this nested value is retained but is non-fatal.",
            }
        )
    missing_references = []
    skipped_symlinks = []
    symlink_count = 0

    def add_source(path, role, case_pointers=None, known_bytes=None):
        absolute = os.path.abspath(path)
        case_pointers = case_pointers or []
        if absolute in by_path:
            entry = sources[by_path[absolute]]
            if role not in entry["roles"]:
                entry["roles"].append(role)
            for pointer in case_pointers:
                if pointer not in entry["case_json_pointers"]:
                    entry["case_json_pointers"].append(pointer)
            return entry
        if not regular_file_without_final_symlink(absolute):
            raise OSError("not a regular non-symlink file")
        if descendant_has_symlink(resource_root, absolute):
            raise OSError("a path component below the resource root is a symlink")
        if known_bytes is None:
            source_id, size = sha256_file(absolute)
        else:
            source_id = "sha256:" + hashlib.sha256(known_bytes).hexdigest()
            size = len(known_bytes)
        extension = os.path.splitext(absolute)[1].lower()
        entry = {
            "source_id": source_id,
            "path": absolute,
            "bytes": size,
            "extension": extension,
            "case_json_pointers": sorted(set(case_pointers)),
            "roles": [role],
        }
        if extension == ".pdf":
            entry["content_extraction"] = {
                "status": "pending_real_extraction",
                "text_registered": False,
                "note": "PDF bytes were hashed but not decoded; no quote or page content is verified here.",
            }
        by_path[absolute] = len(sources)
        sources.append(entry)
        return entry

    case_entry = add_source(case_path, "case_argument", known_bytes=case_bytes)
    case_file = {
        "path": case_path,
        "source_id": case_entry["source_id"],
        "bytes": case_entry["bytes"],
    }

    inventory_truncated = False
    inventory_files_seen = 0
    if os.path.islink(resource_root):
        diagnostics.append(
            {"severity": "warning", "code": "resource_root_symlink", "path": resource_root,
             "message": "Resource root is a symlink and was not traversed."}
        )
    elif not os.path.isdir(resource_root):
        diagnostics.append(
            {"severity": "warning", "code": "resource_root_unavailable", "path": resource_root,
             "message": "Resource root is not an available directory; this is not proof that references do not exist."}
        )
    else:
        directories = [resource_root]
        while directories and not inventory_truncated:
            directory = directories.pop(0)
            try:
                entries = sorted(os.scandir(directory), key=lambda item: item.name)
            except OSError as exc:
                diagnostics.append(
                    {"severity": "warning", "code": "directory_read_failed", "path": directory,
                     "message": str(exc)}
                )
                continue
            for entry in entries:
                path = os.path.abspath(entry.path)
                try:
                    if entry.is_symlink():
                        symlink_count += 1
                        if len(skipped_symlinks) < SYMLINK_REPORT_LIMIT:
                            skipped_symlinks.append(path)
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        directories.append(path)
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    inventory_files_seen += 1
                    if inventory_files_seen > args.max_files:
                        inventory_truncated = True
                        break
                    try:
                        add_source(path, "resource_root_inventory")
                    except OSError as exc:
                        diagnostics.append(
                            {"severity": "warning", "code": "inventory_hash_failed", "path": path,
                             "message": str(exc)}
                        )
                except OSError as exc:
                    diagnostics.append(
                        {"severity": "warning", "code": "inventory_entry_failed", "path": path,
                         "message": str(exc)}
                    )

    task_registration = {"path": task_path, "registered": False}
    if regular_file_without_final_symlink(task_path) and not descendant_has_symlink(resource_root, task_path):
        try:
            entry = add_source(task_path, "task_argument")
            task_registration.update(
                {"registered": True, "source_id": entry["source_id"], "bytes": entry["bytes"]}
            )
        except OSError as exc:
            task_registration["reason"] = str(exc)
            diagnostics.append(
                {"severity": "warning", "code": "task_hash_failed", "path": task_path, "message": str(exc)}
            )
    else:
        task_registration["reason"] = "No regular non-symlink file at this path; no task source was registered."

    for reference in review["reference_candidates"]:
        raw_path = reference["value"]
        pointer = reference["pointer"]
        attempted = candidate_files(raw_path, resource_root, case_directory)
        existing = []
        for path in attempted:
            if regular_file_without_final_symlink(path) and not descendant_has_symlink(resource_root, path):
                existing.append(path)
        if not existing:
            missing_references.append(
                {
                    "case_json_pointer": pointer,
                    "reference": raw_path,
                    "attempted_paths": attempted,
                    "status": "unresolved_reference_candidate",
                    "message": (
                        "No readable regular non-symlink file was found at the attempted lexical paths. "
                        "This is not a finding that the referenced material does not exist."
                    ),
                }
            )
            continue
        if len(existing) > 1:
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "multiple_existing_reference_paths",
                    "case_json_pointer": pointer,
                    "paths": existing,
                    "message": "The same string resolved to multiple existing paths; the registry records all and retains ambiguity.",
                }
            )
        for path in existing:
            try:
                add_source(path, "case_reference", [pointer])
            except OSError as exc:
                diagnostics.append(
                    {"severity": "warning", "code": "case_reference_hash_failed", "path": path,
                     "case_json_pointer": pointer, "message": str(exc)}
                )

    sources.sort(key=lambda item: item["path"])
    for entry in sources:
        entry["case_json_pointers"].sort()
        entry["roles"].sort()
    rubric_16 = [item["pointer"] for item in review["rubric_occurrences"] if item["has_16_items"]]
    report = {
        "inspection_version": "1.0",
        "case_file": case_file,
        "resource_root": resource_root,
        "task_file": task_registration,
        "case_id": case_id,
        "case_id_status": case_id_status,
        "case_id_canonical_pointer": case_id_pointer,
        "case_id_occurrences": review["case_id_occurrences"],
        "output_contract": contract,
        "output_contract_status": contract_status,
        "output_contract_canonical_pointer": contract_pointer,
        "output_contract_occurrences": review["output_contract_occurrences"],
        "contract_note": (
            "Root case_id/output_contract are canonical when present. Nested differences are non-fatal diagnostics. "
            "Without root values, missing or conflicting fallback occurrences remain unresolved."
        ),
        "schema_outline": make_schema_outline(case),
        "resource_list_review_candidates": review["resource_list_review_candidates"],
        "resource_list_review_note": review["resource_list_review_note"],
        "resource_list_review_truncated": review["resource_list_review_truncated"],
        "help_occurrences": review["help_occurrences"],
        "metadata_help_occurrences": review["metadata_help_occurrences"],
        "rubric_occurrences": review["rubric_occurrences"],
        "sixteen_item_rubric_locations": rubric_16,
        "rubric_location_note": (
            "Only actual keys containing 'rubric' are reported. Sixteen-item flags describe list length; "
            "no location or official status is inferred when absent."
        ),
        "source_registry": {
            "source_id_format": "sha256:<64 lowercase hex digits>",
            "hash_input": "raw file bytes",
            "sources": sources,
            "file_count_limit": args.max_files,
            "inventory_files_seen": inventory_files_seen,
            "inventory_truncated": inventory_truncated,
            "inventory_symlinks_skipped": symlink_count,
            "skipped_symlink_paths": skipped_symlinks,
            "symlink_path_list_truncated": symlink_count > len(skipped_symlinks),
        },
        "reference_summary": {
            "candidates": len(review["reference_candidates"]),
            "unresolved_candidates": len(missing_references),
        },
        "missing_references": missing_references,
        "pdf_sources_pending_extraction": [
            item["source_id"] for item in sources if item["extension"] == ".pdf"
        ],
        "diagnostics": diagnostics,
    }
    atomic_write_json(args.output, report)
    return report


def build_parser():
    parser = argparse.ArgumentParser(
        description="Inspect strict case JSON, locate contracts, and hash real input files without PDF extraction."
    )
    parser.add_argument("--case", required=True, help="Path to case.json")
    parser.add_argument("--task", required=True, help="Path to task.md; registered only when it exists")
    parser.add_argument("--output", required=True, help="Atomic UTF-8 inspection JSON destination")
    parser.add_argument("--resource-root", default="/input", help="Inventory root (default: /input)")
    parser.add_argument(
        "--max-files", type=int, default=2000,
        help="Maximum regular files inventoried and hashed (default: 2000; references may add more)",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_files < 1:
        parser.error("--max-files must be at least 1")
    try:
        inspect(args)
        return 0
    except InspectionError as exc:
        print("inspect_case: error: %s" % exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print("inspect_case: filesystem error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
