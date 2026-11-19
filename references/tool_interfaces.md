# Helper interfaces and validation limits

All helpers require Python 3.9 or newer and only the standard library. Use `/skills/weekly-skill/scripts` at evaluation time. No installation command or network access is required. Helpers process actual agent-collected evidence; they are not scientific evaluators and do not rewrite result prose or judgments.

## `inspect_case.py`

```bash
python3 /skills/weekly-skill/scripts/inspect_case.py \
  --case /input/case.json --task /input/task.md \
  --output /app/work/case_inspection.json
```

This reports input case/output-contract locations, structural outlines, candidate-like arrays to inspect, existing and missing material references, and a registry of actual files with byte-level SHA-256 source IDs. Re-read the actual data before assigning meanings. A key containing “plan” may be a background example; a PDF suffix does not establish its contents. Inspection is not PDF extraction or semantic validation.

After generating referenced extraction artifacts, refresh that registry with every real derived-file location:

```bash
python3 /skills/weekly-skill/scripts/inspect_case.py \
  --case /input/case.json --task /input/task.md \
  --output /app/work/case_inspection.json \
  --additional-resource-root /app/work
```

`--additional-resource-root` can be repeated. It leaves original case-relative path resolution unchanged and preserves the primary case fingerprint. Each additional file receives its own independent byte-level ID. Original-root files are searched before additional roots and case-directory files for relative references; ambiguity is explicit, never resolved by a convenient basename.

By default use the exact hash from the current inspection's `case_file.source_id` for facts established in `case.json`, together with an RFC 6901 pointer to the relevant plan/parameter/contract field. An explicit case citation rule can instead require an exact declared scenario/contract source ID. The validator permits that alternative only for `scenario_scope.source_id`, `scenario_id`/`scenario_source_id` inside that scope, or `contract_id` inside `resource_price_booking_contracts`, with an exact resolvable JSON Pointer inside the declaration's permitted scope; it then resolves the alias to the real current case-file entry and verifies those bytes. No other scheme, copied name, synthetic registry alias, prefix collision, absent pointer or out-of-scope pointer is accepted. Keep the case file itself registered so byte identity remains auditable. Do not turn this exception into a global replacement of original-paper hashes, independent extraction-file hashes or case-structure provenance. `fact_id` and `evidence_id` remain complementary indices rather than replacements for actual source identity.

For PDF evidence, the outer `evidence.source_id` still identifies the original PDF. `provided_extraction.path` identifies the actual extraction text artifact (JSON with a top-level string or object-valued `text` field, or plain UTF-8 text) and `provided_extraction.source_id`, when present, identifies that artifact's own bytes. `derived_from_source_id` identifies the parent PDF. Do not reuse the PDF hash for derived text or omit byte registration when using a text-file path. The provider flags an extraction whose parent/source relationship is mismatched or whose content/hash fails. Plain notes are not decoded PDF evidence.

An input/encoding error must be shown and resolved honestly. Do not silently repair the source JSON and use that repaired data as the original. A source ID changes when file bytes change; retain the original and any derived extraction as separate entities.

## `review_workspace.py` — optional contract-preserving accelerator

When the case has a literal output template with a top-level `plan_reviews` array and explicit plan/check identifiers, use the shared scaffold instead of writing a per-case generator. It calls `inspect_case.py`, hashes the actual inputs, preserves the original literal field types, inserts candidate/rubric rows with null judgments, and supports applicable-plan filtering. It does not invent scientific judgments or map unsupported JSON Schema contracts to invented fields.

```bash
python3 /skills/weekly-skill/scripts/review_workspace.py prepare \
  --case /input/case.json --task /input/task.md --out /app/work \
  --resource-root /input --initial-result /app/output/result.json
```

For an unsupported schema or absent plan identifiers, it prints `supported: false` and emits `review_workspace.json` with a reason, not an `initial_result.json`; use the ordinary workflow. For a supported case, `initial_result` is an atomic, contract-compatible partial checkpoint; the printed support flag remains authoritative.

`review_workspace.json` contains source IDs/paths, candidate plan/version IDs and pointers, original candidate data, and pending checks containing `check_id`, `axis`, `judgment`, `observed_facts`, `evidence`, `uncertainty`, `disposition` and `rubric_pointer`. Review the actual papers and contracts; fill only evidence-grounded edits, and never repurpose an unfilled null judgment as a scientific conclusion. Replace `disposition.status` from `not_reviewed` to the appropriate completed state only when its observation and required next action have been addressed. A missing scientific approval does not make the workflow incomplete; its gate must remain explicit.

After verified extraction and arithmetic, make a concise `overall_decision` and supply actual uncertainties and changes, then run:

```bash
python3 /skills/weekly-skill/scripts/review_workspace.py finalize \
  --case /input/case.json --work /app/work --output /app/output/result.json \
  --validate --allow-partial
# Append --evidence /app/output/evidence_map.json only if a real map was created.
```

Completion requires a nonempty observation and disposition as well as judgment. `met`/`unmet` require supporting evidence, and a completed review requires a brief overall decision. Missing fields or names, validation errors, pending rows, or changes to source bytes fail honestly unless `--allow-partial` deliberately permits a partial artifact. `status: success` only records the completed requested review; it does not mean an experiment is approved. Recheck source IDs using the latest inspection, including derived artifacts. Generation and validation **do not assert scientific correctness**; assess that separately with actual source evidence.

Unless the agent supplies its own change records, `finalize` compares consecutive input candidates and preserves object, scalar and list changes. `from_present`/`to_present` distinguish a missing field from an explicit JSON `null`; `from_pointer`/`target_pointer` describe the input comparison and can be absent with the field. `evidence.case_json_pointer` must resolve against the actual case, preferring the earlier candidate's existing value. If that nested value is absent in that candidate, use the other existing value or a real parent-plan pointer; preserve the former path only as `unresolved_historical_input_pointer` with its non-resolving scope, never as a fabricated citation. Check the generated evidence against the case's explicit scenario-namespace contract before delivery. Defaults do not infer scientific meaning, acceptance, or equivalence between versions.

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

This checks strict input JSON, real case identity, original field/template or common JSON Schema requirements, source IDs and byte hashes, JSON Pointers, some exact text quotes, link targets, obvious placeholders, and detected duplicate identifiers. It can report warnings where a PDF has not been text-extracted or advanced schema keywords are not supported. Lint also detects repeated leading-zero decimals in observation fields, inconsistent plan-linked JSON Pointers, and a foreign candidate ID inside a disposition; the last is suppressed only for explicit comparison/change-record contexts. These are scoped review warnings, not automatic text fixes or a proof of scientific error/correctness. A shared source registry without a plan/check parent is not automatically assigned to a candidate. Read the actual error list; a nonzero exit requires correction or a truthful retained partial result.

For large reports, append `--summary` to produce compact machine-readable diagnostics: all errors, warning counts/categories/examples, case identity and evidence/check coverage. Full diagnostics remain the default and preserve the original JSON shape. Comparison-only typesetting matching can handle NFKC form, discretionary U+00AD soft hyphens and alphabetic line-ending hyphens, with either keep-dash or drop-dash handling. It records `matched_typesetting_normalized` instead of silently claiming a literal/raw-page match. Never delete numeric bibliography markers (for example `[56]` or `[37,38,49]`) or scientific values to force a quote match; select a genuine continuous substring instead. Bad numbers, text, units and noncontiguous fragments still fail.

A successful run does **not** certify scientific correctness, complete seven-axis/rubric coverage, PDF quote accuracy without extracted text, expert approval, or equivalence between a computed schedule and a real booking. Perform those semantic checks separately against the actual case. Never resolve a failed source check by inventing a citation or copying an expected hash into the result.

## Compact, decision-ready result shape

The actual case contract always overrides these illustrative fields. For each parent plan/version, keep one array of checks. Each check normally needs an ID and axis, judgment, concise source-bound observation, evidence and (if adverse/unknown) a specific disposition. Do not copy the original criterion or repeat identical gate/action prose for every entry:

```json
{
  "plan_id": "actual-plan-id",
  "plan_version": "actual-version-or-null",
  "checks": [
    {
      "check_id": "actual-rubric-id",
      "axis": "actual-axis",
      "judgment": "unmet",
      "observed": "The actual changed fact and why it fails this specific constraint",
      "evidence": [
        {"source_id": "sha256:original-file-hash", "locator": {"kind":"pdf_page", "page": 11}}
      ],
      "gate_id": "shared-only-if-the-exact-same-missing-item-and-action-applies",
      "recheck": "The document/measurement/re-enumeration needed to close the gate"
    }
  ]
}
```

Shared gate definitions belong once in the allowed source/uncertainty/change-record structure or evidence map. Give a concrete missing item, authority/role (if actually supplied), start/precondition gate and pass criterion; do not replace them with repeated generic advice. Full domain/witness audits and rendered/extracted evidence remain real artifacts under `/app/work`, linked where allowed rather than copied wholesale into every plan row. Every actual required passing/violating witness still belongs in the result in its appropriate compact form. Avoid embedding helper raw outputs or full length extraction logs when their referenced artifacts, source IDs and significant witnesses support verification more accurately with less text.

Use parent IDs rather than repeating the same case/version metadata in every child check unless the original contract requires that repetition. Seven axes are attributes plus a compact coverage summary—not a second duplicate of all 16 rubric evaluations. Keep observed, calculated and proposed changes separate and attributable. Aim to remove redundancy, not evidence, uncertainty or required scientific findings. Do not truncate all adverse checks into one generic problem or report `success` as experimental approval.

## Maintenance and package constraints

The intermediate formats are `finite-domain-review/v1` and `schedule-baseline/v1`; real case formats are discovered at runtime rather than replaced with these. Update related documentation when changing any interface. The helpers are deterministic given the same normalized inputs and options; re-run and compare semantic results rather than prose timestamps or runtime IDs. Do not add formal-case answers, precomputed case outputs, binary-only dependencies or symlinks to this Skill. Keep resources within the organizer's UTF-8 text/file-count/size limits.
