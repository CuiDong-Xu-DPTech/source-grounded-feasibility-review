---
name: weekly-skill
description: Audits source-grounded experimental plans for operational feasibility and version differences using actual case/PDF/SOP/resource/price/booking evidence. Use for 实验方案可行性评估, versioned_feasibility_review, three candidate plans, seven-axis checks (assumptions/variables, controls, equipment/materials, time/cost, parameters, risks/exceptions, ethics/safety), finite-domain arithmetic, evidence locators, uncertainty and change records; not for experiment execution or generic literature review.
---

# Versioned experimental-plan feasibility review

Produce a decision-ready, independently checkable review, not a generic proposal. Only case evidence can establish case facts. Read [review_protocol.md](references/review_protocol.md) before substantive judgments, [tool_interfaces.md](references/tool_interfaces.md) before using a helper, and [examples.md](examples.md) only for the interface pattern. No example is an official case answer.

## Runtime contract

1. Read `/input/case.json`, the actual `task.md` at its provided path, its real `output_contract`, all case-declared public rubrics/thresholds, and cited materials. Inspect `/input/environment/resources.yaml` or the actual resource manifest when present; use the named installed tools. Original documents take precedence over labels.
2. Write under `/app/work`; deliver under `/app/output/result.json`. Preserve the real `case_id` and every original output-contract field, name, level and type. Do not impose a template from this Skill on a different case schema. Include actual scientific results, sources, run status, uncertainties, and change records. Preserve honest partial output with its limits.
3. Locate the installed scripts at `/skills/weekly-skill/scripts` (or resolve them relative to this Skill file if installed elsewhere). Python 3.9+ standard library is sufficient for the helpers. No network, personal file, hidden answer, manuscript dataset, or undeclared dependency is required.
4. Maximum resources are 64 model requests, 900 seconds, and 16,384 tokens per response. Aim for 12–16 focused calls, not dozens of repeated full-document reads. Reserve the last 120 seconds for verification and saving. Never sacrifice required coverage or truthful status to an internal target.

## 1. Inventory and save a recovery point

Create `/app/work` and `/app/output`. Resolve the actual task path without overwriting any input, then inspect:

```bash
TASK=/input/task.md
[ -f "$TASK" ] || TASK=task.md
[ -f "$TASK" ] || TASK=/app/task.md
python3 /skills/weekly-skill/scripts/inspect_case.py \
  --case /input/case.json --task "$TASK" \
  --output /app/work/case_inspection.json
```

Always read the resolved task file. If none exists, report that limitation instead of assuming its contents.

Read the targeted inspection fields (including output-contract occurrences, canonical root `case_id`, candidate-list hints, source registry and missing references) with bounded JSON queries; do not dump the entire schema outline. Re-read the actual JSON at identified paths for candidate versions, all case-declared public rubrics/hard thresholds, finite parameter domains, resource/price/booking contracts and source files. An inferred structural role is not a scientific interpretation. Use the raw input to settle meaning.

Immediately write an **actual, clearly partial** `result.json` using the original contract, with the actual `case_id`, null/empty values of the expected types, accurate `partial` status, sources currently identified, pending axes/versions, and an empty or initial change record. Do not use fabricated identifiers or completed findings as placeholders. If a strict/closed schema cannot accommodate fields, keep supplemental notes in `/app/work` until they can be delivered through an allowed field or evidence map. If input cannot be parsed at all, report a real failure rather than purporting to preserve an unreadable contract.

Set a deadline buffer. Save each completed candidate atomically to the same result file while retaining its version; never let v2/v3 overwrite v1. Preserve copies of model-authored drafts, helper outputs, and validation reports under `/app/work`.

## 2. Extract only the evidence that exists

- Use `sha256:` source IDs from the inspection, which hashes original bytes. Register additional actual read files only with a true freshly computed hash.
- Read the actual PDFs/documents, including tables and finite-domain/rubric content. With the declared PDF text tool, retain page boundaries. For a scanned or failed page, follow the resource manifest's OCR route; record the real tool/version and pages covered or failed. Render/re-read critical numeric tables where extraction is uncertain.
- Record short exact quotes and physical PDF page numbers (starting at 1), section/table/row, or RFC 6901 JSON Pointers. Cite the original scientific source, not merely its filename or your summary. Never infer a missing page or fabricate page text from a label.
- Reuse extracted evidence by stable IDs instead of repeating entire papers. Keep file contents, derived calculations, reviewer proposals, and external methodological guidance separate. Do not require network access or manufacture an unavailable citation.

## 3. Build one independent evidence ledger per candidate

Read the same review protocol for all candidates and apply all seven axes plus every actual public rubric/hard requirement. For every check retain:

`case_id + plan_id/version + check_id + scope/applicability + requirement + observed facts + judgment + evidence locator(s) + calculation ID + uncertainty + actionable disposition`.

Explicitly cover assumptions/variables, controls, equipment/materials/samples, time/cost, parameter domain, risks/exceptions, ethics/safety. Use `missing` for absent necessary material, `undetermined` for inadequate evidence, `conflict` for unresolved contradictions, and `not_applicable` only with supporting facts. Positive evidence is needed for `met`; absence alone is not proof of either feasibility or physical impossibility.

Bind each statement to the correct candidate. Check technical capability, qualified unallocated inventory, capacity/calendar and booking separately. Split equipment occupancy, person-hours, elapsed waiting and assay turnaround. Record applicable approval scope/version/conditions rather than assuming a generic approval. Give a concrete missing item, trigger/next gate, alternative and recheck requirement—not a vague request to “confirm more”.

Do not impose animal-study guidance on materials work, a universal control design, arbitrary statistical power, risk scores, safety thresholds, default prices or expert approval durations. Use only supplied thresholds and appropriately scoped guidance.

## 4. Recompute explicit arithmetic and schedules

Where the input contains finite domains or explicit formulas, adapt **actual** sourced facts to the documented helper input. This is a semantic step: never let a script infer units, domains, ranking objectives or thresholds.

```bash
python3 /skills/weekly-skill/scripts/enumerate_constraints.py \
  /app/work/finite_domains.json --output /app/work/constraint_review.json \
  --audit /app/work/constraint_audit.jsonl --max-combinations 100000
```

Read both completeness and outcomes. A complete exhaustive result with no satisfying assignment is infeasible **only for the declared hard constraints**. Unknown constraints, missing domains, expression errors or partial enumeration cannot prove infeasibility. Unconstrained candidates and soft-constraint satisfaction are not overall scientific feasibility. Preserve constraint/source IDs and representative witness assignments. The helper exits 0 for a completed run, 3 for a recoverable partial result, 1 for a failed run, and 2 for argument errors; a nonzero exit must never make you discard an honest saved partial result or guess its missing conclusions.

For actual finish-to-start dependency data, run:

```bash
python3 /skills/weekly-skill/scripts/schedule_baseline.py \
  /app/work/schedule.json --output /app/work/schedule_result.json
```

Treat CPM makespan as a network baseline, not a promise of a bookable or resource-feasible plan. Check overload intervals, calendars, lead times, releases and booking constraints separately. Retain formulas, input values, unit conversion, rounding and output type. Never coerce missing data to zero or use approximate arithmetic silently.

## 5. Compare versions without inventing an optimum

For stable IDs, compare domain/unit/source changes, every axis's judgment, arithmetic, critical/overloaded steps, missing items, and witness assignments. Identify the specific changed constraint/source that explains a decision reversal. Report trade-offs and deltas, not just rankings.

Only filter by actual hard requirements and optimize by explicitly supplied objectives and tie-breaks. Do not invent weights or choose the longest/most favorable-looking version. Any proposed revision is labelled `observed → proposed`, with basis, affected version, validation/authorization required and recomputation. This is not an approval or a replacement observed fact.

## 6. Deliver and independently verify

Populate the real output contract with actual findings and actionable conditions. Put status, sources, uncertainty and change records in their actual fields. If the contract forbids extra fields, link supplementary `/app/output/evidence_map.json` through actual result JSON Pointers. Include editable artifacts only if requested; if Office/slide/diagram outputs are required, give real rendered PDF/PNG previews, not a claimed rendering.

Before finishing, re-read the saved result and run:

```bash
python3 /skills/weekly-skill/scripts/validate_result.py \
  --case /input/case.json --result /app/output/result.json \
  --inspection /app/work/case_inspection.json \
  > /app/work/validation-report.json
# Use --evidence /app/output/evidence_map.json instead of this default when a map was created.
python3 /skills/weekly-skill/scripts/package_check.py /skills/weekly-skill
```

Read the saved validator report. Repair actual errors, then rerun until the result is mechanically valid or an honest limitation is explicitly retained.

Fix reported contract, hash, pointer and citation errors against the actual evidence. A validator pass covers mechanics, not scientific completeness: manually confirm seven axes × every candidate, all public rubric/threshold items, complete arithmetic traces, unknowns/dispositions and version changes. Preserve reporting errors and unresolved gaps when relevant; do not erase them for a green status.

On a late or partial failure, retain the most complete verified result, affected source/pages/versions, failed tool/stage, uncovered checks, specific user action and truthful `partial`/`failed`/`stuck` status. Do not claim a measured improvement over the baseline, a fabricated review score, official case execution, or approval. Return a concise summary and the actual artifact paths; the final decision-ready content belongs in the files.
