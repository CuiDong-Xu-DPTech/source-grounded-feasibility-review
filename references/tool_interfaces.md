# Helper interfaces and validation limits

All helpers require Python 3.9 or newer and only the standard library. Use `/skills/weekly-skill/scripts` at evaluation time. No installation command or network access is required. Helpers process actual agent-collected evidence; they are not scientific evaluators and do not rewrite result prose or judgments.

## `inspect_case.py`

```bash
python3 /skills/weekly-skill/scripts/inspect_case.py \
  --case /input/case.json --task /input/task.md \
  --output /app/work/case_inspection.json
```

This reports input case/output-contract locations, structural outlines, candidate-like arrays to inspect, existing and missing material references, and a registry of actual files with byte-level SHA-256 source IDs. Re-read the actual data before assigning meanings. A key containing “plan” may be a background example; a PDF suffix does not establish its contents. Inspection is not PDF extraction or semantic validation.

An input/encoding error must be shown and resolved honestly. Do not silently repair the source JSON and use that repaired data as the original. A source ID changes when file bytes change; retain the original and any derived extraction as separate entities.

## `enumerate_constraints.py`

```bash
python3 /skills/weekly-skill/scripts/enumerate_constraints.py INPUT.json \
  --output RESULT.json --audit AUDIT.jsonl
# Defaults: --max-combinations 100000 --deadline-seconds 60
```

The agent must first create a semantic adapter with this explicit intermediate form:

```json
{
  "schema_version": "finite-domain-review/v1",
  "case_id": "actual-case-id",
  "plans": [
    {
      "plan_id": "actual-version-id",
      "parameters": {
        "x": {
          "domain": ["0.1", "0.2"],
          "unit": "case-declared-unit",
          "source_id": "sha256:actual-content-digest",
          "locator": "/actual/json/pointer"
        }
      },
      "constraints": [
        {
          "id": "actual-constraint-id",
          "expression": "ceil(x * 10) <= 2",
          "hard": true,
          "source_id": "sha256:actual-content-digest",
          "locator": "/actual/constraint/pointer"
        }
      ]
    }
  ]
}
```

`domain` and `source_id` are mandatory for each parameter; `expression`, `id`, and `source_id` are mandatory for every constraint. Constants can be single-value domains. Preserve original plan/parameter IDs or keep an explicit lossless mapping. Never turn an absent domain into an unrestricted variable. Only perform unit conversion explicitly in the adapter, with cited conversion factors and preserved original values.

The expression language supports numbers, strings, boolean/null, parameter names, parentheses, `+ - * /`, comparisons, `and`, `or`, `not`, and whitelisted `ceil`, `floor`, `abs`, `min`, `max`, `round_half_up`. It does not run Python or allow attribute access, imports, subscripting or arbitrary calls. Use an explicit rounding function only when its semantics are appropriate to the declared quantity. A mathematically exact but nonterminating Decimal result is an arithmetic error, not an approximation.

`null` propagates unknowns. Comparisons or arithmetic involving it return unknown. Kleene logic means `false and unknown = false`, `true or unknown = true`, and `not unknown = unknown`. It does **not** turn null into a chosen finite-domain value.

Hard constraints govern the matching combinations. Soft constraints are reported separately. Only a complete enumeration with every assignment hard-false establishes infeasibility for the declared hard constraints. Even an exhaustive satisfying set only establishes that restricted result, not overall scientific feasibility. No hard constraint means there is no demonstrated feasible set. Unknowns/errors, incomplete domains, timeouts and max-combination truncation must not be converted into “no feasible solution”.

The file result is for calculations; the JSONL audit retains combination-by-combination assignment/constraint traces. Values are emitted as strings to avoid binary floating-point ambiguity. Use the actual result fields and completeness flags, linked back to source IDs, when filling the case's required output. Version changes retain the original identifiers. No objective means no automatic ranking.

## `schedule_baseline.py`

Use one input per actual plan when genuine finish-to-start dependencies and durations are supplied:

```json
{
  "schema_version": "schedule-baseline/v1",
  "case_id": "actual-case-id",
  "plan_id": "actual-plan-id",
  "time_unit": "case-declared-unit",
  "tasks": [
    {
      "id": "actual-step-id",
      "duration": "1.5",
      "predecessors": [],
      "role": "equipment",
      "source_id": "sha256:actual-content-digest",
      "locator": "/actual/task/pointer"
    },
    {
      "id": "actual-next-step",
      "duration": "2",
      "predecessors": ["actual-step-id"],
      "role": "wait",
      "source_id": "sha256:actual-content-digest",
      "locator": "/actual/next-task/pointer"
    }
  ]
}
```

Run:

```bash
python3 /skills/weekly-skill/scripts/schedule_baseline.py INPUT.json \
  --output RESULT.json
```

An empty predecessor list is an explicit adapter assertion that the actual evidence has no incoming dependency. A missing dependency list is not proof that a task can parallelize. Roles must be grounded: `equipment`, `labor`, `wait`, `assay`, or `other`; do not apply them just to make missing time estimates look complete.

Optional `resource_limits` and `resource_demands` represent explicit numeric quantities in a consistent unit. Each limit has `capacity` and `source_id`, and may have the original `locator`. Prefer giving each demand its own evidence, especially when it comes from a different document than task timing:

```json
"resource_demands": {
  "actual-step-id": {
    "instrument-slots": {
      "value": "1",
      "source_id": "sha256:actual-content-digest",
      "locator": "/resource_contract/demands/actual-step-id/instrument-slots"
    }
  }
}
```

A decimal-string demand (`"instrument-slots": "1"`) remains supported: it inherits the task-level source ID with `source_scope=inherited_task_source` and receives a `normalized_input_pointer` for recalculation, not the unrelated duration locator. That pointer addresses the normalized adapter input, not necessarily the original case. Use the object form whenever the actual resource document, file, or JSON Pointer differs. Supplying `locator` on a resource limit similarly produces `limit_locator` in the result.

The helper checks the resource exposure of the derived baseline, using half-open activity intervals so one task ending when another starts does not double count. CPM results are only a finish-to-start network baseline: they do not establish a resource-constrained optimum, reservation, working calendar, shipping time, future timezone rule, or production feasibility. Unprovided constraints remain undetermined.

## `validate_result.py`

```bash
python3 /skills/weekly-skill/scripts/validate_result.py \
  --case /input/case.json \
  --result /app/output/result.json \
  --inspection /app/work/case_inspection.json
```

If an allowed supplemental evidence map is used, pass `--evidence /app/output/evidence_map.json` as well. Its `result_pointer` must resolve to the relevant result entry.

This checks strict input JSON, real case identity, original field/template or common JSON Schema requirements, source IDs and byte hashes, JSON Pointers, some exact text quotes, link targets, obvious placeholders, and detected duplicate identifiers. It can report warnings where a PDF has not been text-extracted or advanced schema keywords are not supported. Read its actual error list; a nonzero exit requires correction or a truthful retained partial result.

A successful run does **not** certify scientific correctness, complete seven-axis/rubric coverage, PDF quote accuracy without extracted text, expert approval, or equivalence between a computed schedule and a real booking. Perform those semantic checks separately against the actual case. Never resolve a failed source check by inventing a citation or copying an expected hash into the result.

## Maintenance and package constraints

The intermediate formats are `finite-domain-review/v1` and `schedule-baseline/v1`; real case formats are discovered at runtime rather than replaced with these. Update related documentation when changing any interface. The helpers are deterministic given the same normalized inputs and options; re-run and compare semantic results rather than prose timestamps or runtime IDs. Do not add formal-case answers, precomputed case outputs, binary-only dependencies or symlinks to this Skill. Keep resources within the organizer's UTF-8 text/file-count/size limits.
