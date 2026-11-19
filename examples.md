# Minimum invocation example — not an official case

The following is a deliberately synthetic interface example. Its numbers, `demo` identifiers, sources and findings do not come from an official case or a real laboratory. Actual cases require genuine file hashes and citations, not these demo strings.

Input contract (`/input/case.json`, schema for this example only):

```json
{
  "case_id": "SYNTHETIC-DEMO-ONLY",
  "output_contract": {
    "case_id": "",
    "plan_reviews": [],
    "status": "",
    "sources": [],
    "uncertainties": [],
    "change_records": []
  },
  "plans": [
    {"plan_id": "demo-a", "x": "0.1", "hard_limit": "0.2"},
    {"plan_id": "demo-b", "x": "0.3", "hard_limit": "0.2"}
  ],
  "requirements": [
    {"id": "R1", "condition": "x <= hard_limit"}
  ],
  "note": "SYNTHETIC INTERFACE EXAMPLE ONLY. Not scientific evidence or an official case."
}
```

For a real case, call:

```text
Use the installed weekly-skill to review the actual /input/case.json and task.md against their supplied sources. Preserve the original output_contract fields and case_id. Compare all candidate versions independently, calculate declared finite-domain/schedule data, attach source locators, retain uncertainties and change records, and save /app/output/result.json with an honest run status.
```

The agent inspects the real files, extracts evidence, then runs the relevant helpers. For this finite-domain-only example, the semantic adapter is:

```json
{
  "schema_version": "finite-domain-review/v1",
  "case_id": "SYNTHETIC-DEMO-ONLY",
  "plans": [
    {
      "plan_id": "demo-a",
      "parameters": {
        "x": {"domain": ["0.1"], "source_id": "demo-source-a"}
      },
      "constraints": [
        {"id": "R1", "expression": "x <= 0.2", "hard": true, "source_id": "demo-requirement"}
      ]
    },
    {
      "plan_id": "demo-b",
      "parameters": {
        "x": {"domain": ["0.3"], "source_id": "demo-source-b"}
      },
      "constraints": [
        {"id": "R1", "expression": "x <= 0.2", "hard": true, "source_id": "demo-requirement"}
      ]
    }
  ]
}
```

Call and verify:

```bash
python3 /skills/weekly-skill/scripts/inspect_case.py \
  --case /input/case.json --task /input/task.md \
  --output /app/work/case_inspection.json
python3 /skills/weekly-skill/scripts/enumerate_constraints.py \
  /app/work/finite_domains.json --output /app/work/constraint_review.json \
  --audit /app/work/constraint_audit.jsonl
python3 /skills/weekly-skill/scripts/validate_result.py \
  --case /input/case.json --result /app/output/result.json \
  --inspection /app/work/case_inspection.json
```

Illustrative result (`/app/output/result.json`); only the arithmetic semantics are from this synthetic input. The source and uncertainty entries labelled “demo-shortened” are explanatory prose, not acceptable substitutes for real locators in an actual run:

```json
{
  "case_id": "SYNTHETIC-DEMO-ONLY",
  "plan_reviews": [
    {
      "plan_id": "demo-a",
      "parameter_scope": {"check_id": "R1", "judgment": "met"},
      "calculation": {"expression": "0.1 <= 0.2", "result": "true"},
      "evidence": "demo-shortened: use real case JSON Pointer and SHA-256 in production"
    },
    {
      "plan_id": "demo-b",
      "parameter_scope": {"check_id": "R1", "judgment": "unmet"},
      "calculation": {"expression": "0.3 <= 0.2", "result": "false"},
      "evidence": "demo-shortened: use real case JSON Pointer and SHA-256 in production"
    }
  ],
  "status": "success",
  "sources": ["demo-shortened: register actual source file and byte hash"],
  "uncertainties": [
    "This minimal example does not demonstrate coverage of all seven axes. A real review requires all seven axes and every actual public rubric for every plan."
  ],
  "change_records": [
    {"plan_id": "demo-b", "field": "x", "observed_relative_to_demo-a": "0.2", "constraint_id": "R1", "decision_change": "met_to_unmet"}
  ]
}
```

`status: success` here only describes completed processing within the example. It does not make demo-b feasible or prove a real experimental plan is scientifically valid. Prefer `partial` if any required material or axis remains unreviewed. Use [tool_interfaces.md](references/tool_interfaces.md) for constraints and full helper contracts.
